"""Functions to fetch metadata and lyrics from Musixmatch."""

import datetime
import logging
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from pprint import pformat
from threading import Lock
from typing import Any

import requests

from .tokens import ProviderToken, Token
from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
musixmatch_lock = Lock()


class MusixmatchPictureProvider(PictureProvider):
    """A picture provider for Musixmatch."""

    def get_sure_pictures(self) -> list[Picture]:
        """Return a list of all the sure pictures for Musixmatch."""
        # TODO: add debug information
        pictures: list[Picture] = []

        for key, value in self.result.items():
            if key.startswith("album_coverart_"):
                try:
                    picture = Picture(value, int(key.removeprefix("album_coverart_").split("x")[0]))
                except ValueError:  # invalid number
                    pass
                else:
                    pictures.append(picture)

        return pictures


class MusixmatchToken(ProviderToken):
    """A token provider for Musixmatch."""

    name = "musixmatch"
    cooldown_period = 5

    @classmethod
    def real_get(cls) -> Token | None:
        """Get the Musixmatch access token."""
        logger.info("Getting Musixmatch access token...")
        req = locked(musixmatch_lock)(requests.get)(
            "https://apic-desktop.musixmatch.com/ws/1.1/token.get",
            {"app_id": "web-desktop-app-v1.0", "user_language": "en"},
        )
        req.raise_for_status()

        try:
            result = req.json()
            logger.debug("JSON decoding OK")
        except requests.JSONDecodeError as err:
            logger.debug("JSON decoding error: %s", err)
            return None

        status_code = get(result, ("message", "header", "status_code"), int)
        if status_code and status_code != HTTPStatus.OK:
            logger.warning("Musixmatch API error when getting API token")
            return None

        token = get(result, ("message", "body", "user_token"), str)

        if not token:
            logger.error("Can't get the Musixmatch access token!")
            return None

        return Token(token)


def get_api(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    *args,
    **kwargs,
) -> dict[str, Any]:
    """Make a call to the Musixmatch API."""
    resp = locked(musixmatch_lock)(requests.get)(
        "https://apic-desktop.musixmatch.com/ws/1.1/" + url,
        {
            **(params or {}),
            "app_id": "web-desktop-app-v1.0",
            "usertoken": MusixmatchToken.get(),
        },
        *args,
        headers={
            **(headers or {}),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36"
            ),
        },
        **kwargs,
    )
    resp.raise_for_status()
    data = resp.json()
    status_code = get(data, ("message", "header", "status_code"), int)
    if status_code and status_code != HTTPStatus.OK:
        logger.error("Musixmatch API error")
        return {}
    return data


def format_time(time_in_seconds: float) -> str:
    """Return a [mm:ss.xx] formatted string from the given time in seconds."""
    time = datetime.timedelta(seconds=time_in_seconds)
    minutes, seconds = divmod(time.seconds, 60)
    return f"{minutes:02}:{seconds:02}.{time.microseconds // 10000:02}"


def get_lyrics(track_id: int) -> str:
    """Return the lyrics of the song with the given `track_id`."""
    # Currently, the word-by-word lyrics are disabled
    # (see https://github.com/lfavole/songs-dl/tree/867e31b/songs_dl/musixmatch.py#L109 for the commented code)
    # so we get the normal lyrics
    data = get_api("track.subtitle.get", {"track_id": track_id, "subtitle_format": "lrc"})
    return get(data, ("message", "body", "subtitle", "subtitle_body"), str)


def lazy_string(func: Callable[[], str]) -> str:
    """Return an object that looks like a string and will call the passed function when needed."""

    class LazyString:
        def __init__(self) -> None:
            self._data: str | None = None

        @property
        def data(self) -> str:
            if self._data is None:
                self._data = func()
            return self._data

        def __str__(self) -> str:
            return str(self.data)

        def __repr__(self) -> str:
            return str(self.data)

        def __eq__(self, other: object) -> bool:
            return str(self) == other

        def __hash__(self) -> int:
            return hash(str(self))

        def __len__(self) -> int:
            return len(str(self))

        def __add__(self, other: str) -> str:
            return str(self) + other

    return LazyString()  # type: ignore[return-value]


def download_musixmatch(song: str, artist: str | None = None, market: str | None = None) -> list[Song]:
    """Fetch the Musixmatch search results."""
    logger.info("Searching %s on Musixmatch...", format_query(song, artist, market))
    query = f"{song} {artist}" if artist else song

    try:
        data = get_api("track.search", {"q": query, "limit": 20})
    except ValueError:
        return []
    tracks = get(data, ("message", "body", "track_list"), list)

    ret: list[Song] = []
    for track_obj in tracks:
        track = get(track_obj, "track", dict)
        if track:
            ret.append(
                Song(
                    title=get(track, "track_name", str),
                    artists=[get(track, "artist_name", str)],
                    album=get(track, "album_name", str),
                    duration=get(track, "track_length", int),
                    genre=get(track, ("primary_genres", "music_genre_list", 0, "music_genre", "music_genre_name"), str),
                    release_date=get(track, "first_release_date", str),
                    lyrics=lazy_string(partial(get_lyrics, get(track, "track_id", int))),
                    picture=MusixmatchPictureProvider(track),
                )
            )

    logger.debug("Results:\n%s", pformat(ret))

    return ret
