import json
import logging
import re
from threading import Lock
from typing import Any
from urllib.parse import quote

import requests
from yt_dlp.utils.networking import random_user_agent

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
musixmatch_lock = Lock()


class MusixmatchPictureProvider(PictureProvider):
    def get_sure_pictures(self, result: dict[str, Any]):
        # TODO add debug information
        pictures: list[Picture] = []

        for key, value in result.items():
            if key.startswith("albumCoverart"):
                try:
                    pictures.append(Picture(value, int(key.removeprefix("albumCoverart").split("x")[0])))
                except ValueError:  # invalid number
                    pass

        return pictures


def download_musixmatch(song: str, artist: str | None = None, market: str | None = None):
    """
    Fetch the Musixmatch search results.
    """
    logger.info("Searching %s on Musixmatch...", format_query(song, artist, market))
    if artist:
        query = song + " " + artist
    else:
        query = song

    req = locked(musixmatch_lock)(requests.get)(
        f"https://www.musixmatch.com/search/{quote(query)}/tracks",
        headers={
            "User-Agent": random_user_agent(),
        },
    )

    match = re.search(r"(?s)<script>(var __mxmProps.*?)</script>", req.text)
    if not match:
        logger.debug("Can't find mxmProps in search page")
        return []  # we skip Musixmatch

    match2 = re.search(
        r"""(?sx)
    "tracks":
    \{"0":
    (
        \{.*?\}
    )
    (?:
        ,"1":|
        \],"length":1
    )
    """,
        match.group(1),
    )

    if not match2:
        logger.debug("Can't find tracks list in mxmProps")
        return []  # same thing

    match3 = re.search(
        r"""(?sx)
    "attributes":
    ({.*?})
    ,"id":
    """,
        match2.group(1),
    )

    if not match3:
        logger.debug("Can't find attributes in tracks list")
        return []  # same thing

    try:
        # decode the JSON data
        data = json.loads(match3.group(1))
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip Musixmatch
        logger.debug("JSON decoding error: %s", err)
        return []

    req2 = locked(musixmatch_lock)(requests.get)(
        "https://www.musixmatch.com/lyrics/" + data["commontrack_vanity_id"],
        headers={
            "User-Agent": random_user_agent(),
        },
    )

    match4 = re.search(r"(?s)<script>.*?var __mxmState\s*=\s*({.*?});?</script>", req2.text)
    if not match4:
        logger.debug("Can't find mxmState in song page")
        return []  # same thing

    try:
        # decode the JSON data
        data2 = json.loads(match4.group(1))
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip Musixmatch
        logger.debug("JSON decoding error: %s", err)
        return []

    result = get(data2, ("page", "track"), dict[str, Any])

    return [
        Song(
            title=get(result, "name", str),
            artists=[get(result, "artistName", str)],
            album=get(result, "albumName", str),
            duration=get(result, "length", int),
            language=get(data2, ("page", "lyrics", "lyrics", "language"), str),
            genre=get(result, ("primaryGenres", 0, "name"), str),
            release_date=get(result, "firstReleaseDate", str),
            lyrics=get(data2, ("page", "lyrics", "lyrics", "body"), str),
            picture=MusixmatchPictureProvider(result),
        )
    ]
