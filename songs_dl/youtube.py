"""Functions to get metadata and songs from YouTube."""

import json
import logging
import re
from pprint import pformat
from threading import Lock
from typing import Any, TypedDict
from urllib.parse import urlencode

import requests

from .utils import Song, format_query, get, locked

youtube_lock = Lock()
logger = logging.getLogger(__name__)


class YoutubeVideo(TypedDict):
    """A YouTube video."""

    id: str
    thumbnail: str
    title: str
    channel: str
    length: int
    views: int
    badges: list[str]
    match_value: int | None


class Thumbnail(TypedDict):
    """A YouTube thumbnail."""

    width: int
    size: int
    url: str


class YtThumbnailObject(TypedDict):
    """A YouTube thumbnail list."""

    thumbnails: list[Thumbnail]


class YtText(TypedDict):
    """A text on YouTube."""

    text: str


class YtRunsText(TypedDict):
    """A YouTube container for list of texts."""

    runs: list[YtText]


class YtSimpleText(TypedDict):
    """A YouTube text container."""

    simpleText: str


class YtBadge(TypedDict):
    """A YouTube badge."""

    style: str


class YtBadgeObject(TypedDict):
    """A YouTube badge container."""

    metadataBadgeRenderer: YtBadge


class YtInitialData(TypedDict):
    """Data provided by YouTube."""

    videoId: str
    thumbnail: YtThumbnailObject
    title: YtRunsText
    longBylineText: YtRunsText
    publishedTimeText: YtSimpleText
    lengthText: YtSimpleText
    viewCountText: YtSimpleText
    ownerBadges: list[YtBadgeObject]
    ownerText: YtRunsText
    shortBylineText: YtRunsText
    shortViewCountText: YtSimpleText
    isWatched: bool


class YoutubeSong(Song):
    """A `Song` that is available as a YouTube video."""

    def __init__(
        self,
        *args,
        youtube_video: str | None = None,
        views: int | None = None,
        artist_badge: bool | None = None,
        **kwargs,
    ) -> None:
        """Create a new `YoutubeSong`."""
        self.youtube_video = youtube_video
        self.views = views
        self.artist_badge = artist_badge
        super().__init__(*args, **kwargs)


def download_youtube(  # noqa: C901, PLR0915
    song: str, artist: str | None = None, _market: str | None = None, music: bool = False
) -> list[YoutubeSong]:
    """Get the YouTube search results."""
    logger.info("Searching %s on YouTube...", format_query(song, artist))
    query = f"{song} {artist}" if artist else song
    song = f"allintitle:{song}"
    if music:
        endpoint = "https://music.youtube.com/search"
        param = "q"
    else:
        endpoint = "https://www.youtube.com/results"
        param = "search_query"
    with requests.Session() as session:
        session.headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:139.0) Gecko/20100101 Firefox/139.0"}
        url = endpoint + "?" + urlencode({param: query})
        req = locked(youtube_lock)(session.get)(url)
        if req.url.startswith("https://consent.youtube.com/"):
            match = re.search(r"<input type=\"hidden\" name=\"bl\" value=\"([^\"]*)\"", req.text)
            if match:
                req = session.post(
                    "https://consent.youtube.com/save",
                    data={
                        "gl": "FR",
                        "m": "0",
                        "app": "0",
                        "pc": "ytm",
                        "continue": url,
                        "x": "6",
                        "bl": match.group(1),
                        "hl": "fr",
                        "src": "1",
                        "cm": "2",
                        "set_eom": "true",
                    },
                )
    logger.debug("Page size: %d", len(req.text))
    re_match = r"path: '\/search', .*?, data: '(.*?)'" if music else r"var ytInitialData = (.*?);</script>"
    if not (match := re.search(re_match, req.text)):
        # no YouTube video = no song => stop
        logger.error("Search failed: can't get the results in the YouTube page!")
        return []

    logger.info("Results have been found")
    try:
        content = match.group(1)
        if music:
            content = re.sub(r"\\x([0-9a-f]{2})", lambda match: chr(int(match[1], 16)), content)
            content = content.replace("\\\\", "\\")
        result = json.loads(content)
        logger.debug("JSON decoding OK")
    except json.decoder.JSONDecodeError as err:
        logger.critical("JSON decoding error: %s", err)  # same thing
        return []

    main_contents = get(
        result,
        (
            "contents",
            "twoColumnSearchResultsRenderer",
            "primaryContents",
            "sectionListRenderer",
            "contents",
        ),
        list,
    )

    videos_list = []
    for content in main_contents:
        contents = get(content, ("itemSectionRenderer", "contents"), list)
        videos_list.extend(
            video
            for video in contents
            # there is other information like
            # promotedSparklesTextSearchRenderer...
            # but it's not useful
            if "videoRenderer" in video
        )

    logger.debug("%d videos", len(videos_list))

    def map_video(video_data: dict[str, Any]) -> YoutubeSong:
        video = get(video_data, "videoRenderer", dict[str, Any])
        length = sum(
            # 0 = 1 (seconds); 1 = 60 (minutes); 2 = 3600 (hours); ...
            int(value or 0) * (60**index)
            for index, value in enumerate(
                get(video, ("lengthText", "simpleText"), str).split(":")[::-1]
            )  # from the end
        )
        thumbnail = get(
            max(
                [*get(video, ("thumbnail", "thumbnails"), list[dict[str, Any]]), {"url": "", "width": 0}],
                key=lambda obj: get(obj, "width", int),
            ),
            "url",
            str,
        )

        def get_int(value: str) -> int:
            """
            Return the view count from a view count string.

            >>> get_int("12 345 views")
            12345
            """
            value = "".join(c for c in value if c.isnumeric())
            try:
                return int(value)
            except ValueError:
                return 0

        ret: YoutubeVideo = {
            "id": get(video, "videoId", str),
            "thumbnail": thumbnail,
            "title": get(video, ("title", "runs", 0, "text"), str),
            "channel": get(video, ("ownerText", "runs", 0, "text"), str),
            "length": length,
            "views": get(video, ("viewCountText", "simpleText"), get_int),
            "badges": [
                get(badge, ("metadataBadgeRenderer", "style"), str)
                for badge in get(video, "ownerBadges", list[dict[str, Any]])
            ],
            "match_value": None,
        }

        title = ret["title"]
        artists = []

        if " - " in ret["title"]:
            parts = ret["title"].split(" - ", 1)
            title = parts[1].strip().strip("-").strip()
            artists.append(parts[0].strip().strip("-").strip())

        match = re.search(
            r"""(?x)
        ^ (?P<title_first>.*) # first part of title
        [(\[]? \b f(?:ea)?t \b \.? (?P<artist>.*?) [)\]]? # feat. / ft. with parens or brackets
        (?P<title_second> [(\[] .*)? [)\]]? $ # second part of title (begins with paren), remove trailing ")"
        """,
            title,
        )
        if match:
            title = (match.group("title_first").strip() + " " + (match.group("title_second") or "")[1:].strip()).strip()
            artists.append(match.group("artist").strip())

        artists.append(ret["channel"])

        return YoutubeSong(
            title=title,
            artists=artists,
            duration=ret["length"],
            youtube_video=ret["id"],
            views=ret["views"],
            artist_badge="BADGE_STYLE_TYPE_VERIFIED_ARTIST" in ret["badges"],
        )

    ret = [map_video(v) for v in videos_list]

    logger.debug("Results:\n%s", pformat(ret))

    return ret
