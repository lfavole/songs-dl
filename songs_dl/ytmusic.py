"""Functions to get metadata and songs from YouTube Music."""

import logging

import requests

from .utils import Picture, PictureProvider, format_query, get, locked
from .youtube import YoutubeSong, youtube_lock

logger = logging.getLogger(__name__)


class YoutubeMusicPictureProvider(PictureProvider):
    """A class to provide pictures from YouTube Music search results."""

    def get_sure_pictures(self) -> list[Picture]:
        """Get the pictures from the YouTube Music search result."""
        return [
            Picture(
                get(picture, "url", str),
                get(picture, "width", int),
                get(picture, "height", int),
                sure=True,
            )
            for picture in get(self.result, ("thumbnail", "musicThumbnailRenderer", "thumbnail", "thumbnails"), list)
        ]


def parse_duration(duration: str) -> int:
    """Parse a duration string in the format HH:MM:SS or MM:SS into seconds."""
    return sum(
        # 0 = 1 (seconds); 1 = 60 (minutes); 2 = 3600 (hours); ...
        int(value or 0) * (60**index)
        for index, value in enumerate(duration.split(":")[::-1])  # from the end
    )


def download_youtube_music(song: str, artist: str | None = None, _market: str | None = None) -> list[YoutubeSong]:
    """Get the YouTube Music search results."""
    logger.info("Searching %s on YouTube Music...", format_query(song, artist))
    query = f"{song} {artist}" if artist else song
    req = locked(youtube_lock)(requests.post)(
        "https://music.youtube.com/youtubei/v1/search?prettyPrint=false",
        headers={
            "Origin": "https://music.youtube.com",
            "X-Origin": "https://music.youtube.com",
        },
        json={
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20250204.03.00",
                },
            },
            "query": query,
            "params": "EgWKAQIIAWoKEAMQBBAJEAoQBQ%3D%3D",
        },
    )
    req.raise_for_status()

    logger.info("Results have been found")
    try:
        result = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        logger.critical("JSON decoding error: %s", err)  # same thing
        return []

    interessant_data = get(
        result,
        (
            "contents",
            "tabbedSearchResultsRenderer",
            "tabs",
            0,
            "tabRenderer",
            "content",
            "sectionListRenderer",
            "contents",
        ),
        list,
    )

    for item in interessant_data:
        result = None
        for key, value in item.items():
            if key == "musicShelfRenderer":
                result = value
                break
        if result is not None:
            interessant_data = result
            break

    interessant_data = get(interessant_data, "contents", list)

    ret = []

    for item in interessant_data:
        item = get(item, "musicResponsiveListItemRenderer", dict)  # noqa: PLW2901
        ret.append(
            YoutubeSong(
                title=get(
                    item,
                    ("flexColumns", 0, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", 0, "text"),
                    str,
                ),
                artists=[
                    get(
                        item,
                        ("flexColumns", 1, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", 0, "text"),
                        str,
                    )
                ],
                album=get(
                    item,
                    ("flexColumns", 1, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", 2, "text"),
                    str,
                ),
                duration=parse_duration(
                    get(
                        item,
                        ("flexColumns", 1, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", -1, "text"),
                        str,
                    )
                ),
                picture=YoutubeMusicPictureProvider(item),
                youtube_video=get(item, ("playlistItemData", "videoId"), str),
            )
        )

    return ret
