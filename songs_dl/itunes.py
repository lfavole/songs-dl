"""Functions to get metadata from iTunes."""

import logging
from threading import Lock
from typing import Any

import requests

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
itunes_lock = Lock()


class ItunesPictureProvider(PictureProvider):
    """A picture provider for iTunes."""

    def get_sure_pictures(self) -> list[Picture]:  # noqa: D102
        # TODO: add debug information
        pictures: list[Picture] = []

        for key, value in self.result.items():
            if key.startswith("artworkUrl"):
                try:
                    size = int(key.removeprefix("artworkUrl"))
                except ValueError:  # invalid number
                    pass
                else:
                    pictures.append(Picture(value, size))

        return pictures


def download_itunes(song: str, artist: str | None = None, market: str | None = None) -> list[Song]:
    """Fetch the iTunes search results."""
    logger.info("Searching %s on iTunes...", format_query(song, artist, market))
    query = f"{song} {artist}" if artist else song
    params = {"term": query, "entity": "song"}
    if market:
        params["country"] = market
    req = locked(itunes_lock)(requests.get)("https://itunes.apple.com/search", params=params)
    try:
        # decode the JSON data
        search = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip iTunes
        logger.debug("JSON decoding error: %s", err)
        return []

    results = get(search, "results", list[dict[str, Any]])
    if len(results) == 0:
        logger.debug("No 'results' index")
        return []  # same thing

    ret: list[Song] = [
        Song(
            title=get(result, "trackName", str),
            artists=[get(result, "artistName", str)],
            album=get(result, "collectionName", str),
            duration=get(result, "trackTimeMillis", int) / 1000,
            language=get(result, "country", str).lower(),
            genre=get(result, "primaryGenreName", str),
            track_number=(
                get(result, "trackNumber", int),
                get(result, "trackCount", int),
            ),
            release_date=get(result, "releaseDate", str),
            picture=ItunesPictureProvider(result),
        )
        for result in results
    ]

    return ret
