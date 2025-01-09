import logging
from threading import Lock
from typing import Any

import requests

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
itunes_lock = Lock()


class ItunesPictureProvider(PictureProvider):
    def get_sure_pictures(self, result: dict[str, Any]):
        # TODO add debug information
        pictures: list[Picture] = []

        for key, value in result.items():
            if key.startswith("artworkUrl"):
                try:
                    pictures.append(Picture(value, int(key.removeprefix("artworkUrl"))))
                except ValueError:  # invalid number
                    pass

        return pictures


def download_itunes(song: str, artist: str | None = None, market: str | None = None):
    """
    Fetch the iTunes search results.
    """
    logger.info("Searching %s on iTunes...", format_query(song, artist, market))
    if artist:
        query = f"{song} {artist}"
    else:
        query = song
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

    ret: list[Song] = []

    for result in results:
        ret.append(
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
                # picture = Picture(image, taille) if image and taille else None,
                picture=ItunesPictureProvider(result),
            )
        )

    return ret
