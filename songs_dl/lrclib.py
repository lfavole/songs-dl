"""Functions to get metadata from LRCLIB."""

import logging
from pprint import pformat
from threading import Lock

import requests

from .utils import Song, format_query, get, locked

logger = logging.getLogger(__name__)
lrclib_lock = Lock()


def download_lrclib(song: str, artist: str | None = None, market: str | None = None) -> list[Song]:
    """Fetch the LRCLIB search results."""
    logger.info("Searching %s on LRCLIB...", format_query(song, artist, market))
    req = locked(lrclib_lock)(requests.get)(
        "https://lrclib.net/api/search",
        params={
            "track_name": song,
            "artist_name": artist,
        },
    )

    try:
        result = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip LRCLIB
        logger.debug("JSON decoding error: %s", err)
        return []

    ret: list[Song] = [
        Song(
            title=get(element, "trackName", str),
            artists=[get(element, "artistName", str)],
            album=get(element, "albumName", ""),
            duration=get(element, "duration", float),
            lyrics=get(element, "syncedLyrics", str),
        )
        for element in result
    ]

    logger.debug("Results:\n%s", pformat(ret))

    return ret
