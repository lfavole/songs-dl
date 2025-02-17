import datetime
from functools import partial
import json
import logging
from pprint import pformat
from threading import Lock
from time import sleep, time
from typing import Any

import requests

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
musixmatch_lock = Lock()


class MusixmatchPictureProvider(PictureProvider):
    def get_sure_pictures(self, result: dict[str, Any]):
        # TODO add debug information
        pictures: list[Picture] = []

        for key, value in result.items():
            if key.startswith("album_coverart_"):
                try:
                    pictures.append(Picture(value, int(key.removeprefix("album_coverart_").split("x")[0])))
                except ValueError:  # invalid number
                    pass

        return pictures


ACCESS_TOKEN = ""
ACCESS_TOKEN_EXPIRATION = 0


def get_access_token(tries: int = 3):
    """Gets the Musixmatch access token."""
    global ACCESS_TOKEN, ACCESS_TOKEN_EXPIRATION

    if not ACCESS_TOKEN_EXPIRATION or ACCESS_TOKEN_EXPIRATION < time():
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
            return ""

        status_code = get(result, ("message", "header", "status_code"), int)
        if status_code and status_code != 200:
            logger.warning("Musixmatch API error when getting API token, waiting...")
            sleep(5)
            return get_access_token(tries - 1) if tries > 0 else ""

        token = get(result, ("message", "body", "user_token"), str)

        if not token:
            logger.error("Can't get the Musixmatch access token!")
            return ""

        ACCESS_TOKEN = token
        ACCESS_TOKEN_EXPIRATION = int(time() + 10 * 60)  # 10 minutes

    return ACCESS_TOKEN


def get_api(url, params=None, headers=None, *args, **kwargs):
    resp = locked(musixmatch_lock)(requests.get)(
        "https://apic-desktop.musixmatch.com/ws/1.1/" + url,
        {
            **(params or {}),
            "app_id": "web-desktop-app-v1.0",
            "usertoken": get_access_token(),
        },
        headers={
            **(headers or {}),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36",
        },
        *args,
        **kwargs,
    )
    resp.raise_for_status()
    data = resp.json()
    status_code = get(data, ("message", "header", "status_code"), int)
    if status_code and status_code != 200:
        logger.error("Musixmatch API error")
        return {}
    return data


def format_time(time_in_seconds: float):
    """Returns a [mm:ss.xx] formatted string from the given time in seconds."""
    time = datetime.timedelta(seconds=time_in_seconds)
    minutes, seconds = divmod(time.seconds, 60)
    return f"{minutes:02}:{seconds:02}.{time.microseconds // 10000:02}"


def get_lyrics(track_id: int):
    # try to get the word-by-word lyrics first
    # currently disabled (doesn't work on every music player)

    # data = get_api("track.richsync.get", {"track_id": track_id, "subtitle_format": "lrc"})
    # lyrics = get(data, ("message", "body", "richsync", "richsync_body"), str)
    # if lyrics:
    #     lrc_raw = json.loads(lyrics)
    #     lrc_str = ""
    #     for i in lrc_raw:
    #         lrc_str += f"[{format_time(i['ts'])}] "
    #         for l in i["l"]:
    #             t = format_time(float(i["ts"]) + float(l["o"]))
    #             lrc_str += f"<{t}> {l['c']} "
    #         lrc_str += "\n"
    #     return lrc_str

    # otherwise, get the normal lyrics
    data = get_api("track.subtitle.get", {"track_id": track_id, "subtitle_format": "lrc"})
    return get(data, ("message", "body", "subtitle", "subtitle_body"), str)


def lazy_string(func):
    class LazyString:
        def __init__(self) -> None:
            self._data = None

        @property
        def data(self):
            if self._data is None:
                self._data = func()
            return self._data

        def __str__(self):
            return str(self.data)

        def __repr__(self):
            return str(self.data)

        def __eq__(self, other):
            return str(self) == other

        def __hash__(self):
            return hash(str(self))

        def __len__(self):
            return len(str(self))

        def __add__(self, other):
            return str(self) + other

    return LazyString()


def download_musixmatch(song: str, artist: str | None = None, market: str | None = None):
    """
    Fetch the Musixmatch search results.
    """
    logger.info("Searching %s on Musixmatch...", format_query(song, artist, market))
    if artist:
        query = song + " " + artist
    else:
        query = song

    data = get_api("track.search", {"q": query, "limit": 20})
    tracks = get(data, ("message", "body", "track_list"), list)

    ret: list[Song] = []
    for track in tracks:
        track = get(track, "track", dict)
        if track:
            ret.append(
                Song(
                    title=get(track, "track_name", str),
                    artists=[get(track, "artist_name", str)],
                    album=get(track, "album_name", str),
                    duration=get(track, "track_length", int),
                    genre=get(track, ("primary_genres", "music_genre_list", 0, "music_genre", "music_genre_name"), str),
                    release_date=get(track, "first_release_date", str),
                    lyrics=lazy_string(partial(get_lyrics, get(track, "track_id", int))),  # type: ignore
                    picture=MusixmatchPictureProvider(track),
                )
            )

    logger.debug("Results:\n%s", pformat(ret))

    return ret
