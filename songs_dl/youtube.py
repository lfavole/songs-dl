import json
import logging
import re
import sys
from pprint import pformat
from threading import Lock
from typing import Any, TypedDict

import requests

from .utils import Song, format_query, get, locked

youtube_lock = Lock()
logger = logging.getLogger(__name__)


class YoutubeVideo(TypedDict):
    id: str
    thumbnail: str
    title: str
    channel: str
    length: int
    views: int
    badges: list[str]
    match_value: int | None


class Thumbnail(TypedDict):
    width: int
    size: int
    url: str


class YtThumbnailObject(TypedDict):
    thumbnails: list[Thumbnail]


class YtText(TypedDict):
    text: str


class YtRunsText(TypedDict):
    runs: list[YtText]


class YtSimpleText(TypedDict):
    simpleText: str


class YtBadge(TypedDict):
    style: str


class YtBadgeObject(TypedDict):
    metadataBadgeRenderer: YtBadge


class YtInitialData(TypedDict):
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
    def __init__(self, *args, youtube_video: YoutubeVideo, **kwargs):
        self.youtube_video = youtube_video
        super().__init__(*args, **kwargs)


def download_youtube(song: str, artist: str | None = None, _market: str | None = None):
    """
    Get the YouTube search results.
    """
    logger.info("Searching %s on YouTube...", format_query(song, artist))
    if artist:
        query = song + " " + artist
    else:
        query = song
    song = f"allintitle:{song}"
    req = locked(youtube_lock)(requests.get)("https://www.youtube.com/results", params={"search_query": query})
    logger.debug("Page size: %d", len(req.text))
    if not (match := re.search(r"var ytInitialData = (.*?);</script>", req.text)):
        # no YouTube video = no song => stop
        logger.error("Search failed: can't get the results in the YouTube page!")
        sys.exit()

    logger.info("Results have been found")
    try:
        result = json.loads(match.group(1))
        logger.debug("JSON decoding OK")
    except json.decoder.JSONDecodeError as err:
        logger.critical("JSON decoding error: %s", err)  # same thing
        sys.exit()

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
        for video in contents:
            # there is other information like
            # promotedSparklesTextSearchRenderer...
            # but it's not useful
            if "videoRenderer" in video:
                videos_list.append(video)

    if len(videos_list) == 0:
        logger.critical("No results!")  # same thing
        sys.exit()

    logger.debug("%d videos", len(videos_list))

    def map_video(video_data: dict[str, Any]):
        video = get(video_data, "videoRenderer", dict[str, Any])
        length = sum(
            # 0 = 1 (seconds); 1 = 60 (minutes); 2 = 3600 (hours); ...
            int(value or 0) * (60**index)
            for index, value in enumerate(
                get(video, ("lengthText", "simpleText"), str).split(":")[::-1]
            )  # from the end
        )
        thumbnail: str = ""
        size = 0
        for f in get(video, ("thumbnail", "thumbnails"), list[dict[str, Any]]):
            if get(f, "width", int) >= size:
                size = get(f, "width", int)
                thumbnail = get(f, "url", str)

        def get_int(value: str):
            """
            Helper function for view count.

            >>> get_int("12 345 views")s
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

        artists = []

        if " - " in ret["title"]:
            parts = ret["title"].split(" - ", 1)
            title = parts[1].strip().strip("-").strip()
            artists.append(parts[0].strip().strip("-").strip())
        else:
            title = ret["title"]

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

        return YoutubeSong(title=title, artists=artists, duration=ret["length"], youtube_video=ret)

    ret = [map_video(v) for v in videos_list]

    logger.debug("Results:\n%s", pformat(ret))

    return ret
