"""Functions to get metadata from Deezer."""

import datetime as dt
import json
import logging
import re
from pprint import pformat
from threading import Lock
from typing import Any

import requests

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
deezer_lock = Lock()


class DeezerPictureProvider(PictureProvider):
    """Deezer picture provider."""

    def get_sure_pictures(self) -> list[Picture]:  # noqa: D102
        # TODO: add debug information
        pictures: list[Picture] = []

        def get_size_from_url(url: str) -> int | None:
            _, basename = url.rsplit("/", 1)
            size_str, other = basename.split("x", 1)
            try:
                size = int(size_str)
            except ValueError:
                return None
            if not other.startswith(str(size)):
                return None
            return size

        for key, value in get(self.result, "album", dict[str, str]).items():
            if key.startswith("cover_"):
                size = get_size_from_url(value)
                if size is None:
                    size = {
                        "small": 56,
                        "medium": 250,
                        "big": 500,
                        "xl": 1000,
                    }.get(key.removeprefix("cover_"))
                if size is None:
                    continue
                pictures.append(Picture(value, size))

        return pictures


class DeezerLazySong(Song):
    """Deezer song with lazy request to the Deezer song page (with lyrics...) when needed."""

    def __init__(self, result: dict[str, Any], *args, **kwargs) -> None:
        """Create a `DeezerLazySong`."""
        self.result = result

        self._app_state: dict[str, Any] | None = None

        self.picture = DeezerPictureProvider(result)
        super().__init__(*args, **kwargs)

    @property
    def fetched(self) -> bool:
        """Return `True` if the Deezer song page has been fetched, `False` otherwise."""
        return self._app_state is not None

    @property
    def app_state(self) -> dict[str, Any]:
        """Data in the Deezer song page."""
        if self._app_state is not None:
            return self._app_state
        self._app_state = {}
        logger.info("Downloading song page (%s)...", self.result["link"])
        req = locked(deezer_lock)(requests.get)(self.result["link"])  # song page
        match = re.search(r"<script>window.__DZR_APP_STATE__ ?= ?(.*?);?</script>", req.text)
        if not match:
            logger.debug("JSON data not found in the song page")
            return {}
        try:
            self._app_state = json.loads(match.group(1))
            logger.debug("JSON decoding OK")
        except json.decoder.JSONDecodeError:
            logger.debug("JSON decoding error")
        return self._app_state

    @property
    def data(self) -> dict[str, Any]:
        """Data (shortcut for self.APP_STATE["DATA"])."""
        return get(self.app_state, "DATA", dict[str, Any])

    @property
    def title(self) -> str:
        """Title of the song."""
        return get(self.data, "SNG_TITLE", str) if self.fetched else self.result["title"]

    @title.setter
    def title(self, _value: str) -> None:
        pass

    @property
    def artists(self) -> list[str]:
        """Artists of the song."""
        return (
            [get(e, "ART_NAME", str) for e in get(self.data, "ARTISTS", list[dict[str, str]])]
            or [get(self.data, ("SNG_CONTRIBUTORS", "main_artist"), str)]
            if self.fetched
            else [get(self.result, ("artist", "name"), str)]
        )

    @artists.setter
    def artists(self, _value: list[str]) -> None:
        pass

    @property
    def album(self) -> str:
        """Album of the song."""
        return get(self.data, "ALB_TITLE", str) if self.fetched else get(self.result, ("album", "title"), str)

    @album.setter
    def album(self, _value: str) -> None:
        pass

    @property
    def duration(self) -> float:
        """Duration of the song."""
        return get(self.data, "DURATION", float) if self.fetched else get(self.result, "duration", float)

    @duration.setter
    def duration(self, _value: float) -> None:
        pass

    @property
    def composers(self) -> list[str]:
        """Composers of the song."""
        return get(self.data, ("SNG_CONTRIBUTORS", "composer"), list[str])

    @composers.setter
    def composers(self, _value: list[str]) -> None:
        pass

    @property
    def release_date(self) -> dt.date:
        """Release date of the song."""
        return get(self.data, "PHYSICAL_RELEASE_DATE", dt.date)

    @release_date.setter
    def release_date(self, _value: str | dt.date | None) -> None:
        pass

    @property
    def isrc(self) -> str:
        """ISRC of the song."""
        return get(self.data, "ISRC", str)

    @isrc.setter
    def isrc(self, _value: str) -> None:
        pass

    @property
    def track_number(self) -> int:
        """Track number of the song."""
        return get(self.data, "TRACK_NUMBER", int)

    @track_number.setter
    def track_number(self, _value: int) -> None:
        pass

    @property
    def copyright(self) -> str:
        """Copyright of the song."""
        return get(self.data, "COPYRIGHT", str).strip("©").strip()

    @copyright.setter
    def copyright(self, _value: str) -> None:
        pass

    @property
    def lyrics(self) -> list[tuple[str, float]]:
        """Lyrics of the song."""
        try:
            return [
                (get(line, "line", str), get(line, "milliseconds", int) / 1000)
                for line in get(
                    self.app_state,
                    ("LYRICS", "LYRICS_SYNC_JSON"),
                    list[dict[str, int | str]],
                )
            ]
        except (IndexError, ValueError):
            return []

    @lyrics.setter
    def lyrics(self, _value: list[tuple[str, float]]) -> None:
        pass


def download_deezer(song: str, artist: str | None = None, _market: str | None = None) -> list[Song]:
    """Fetch the Deezer search results."""
    logger.info("Searching %s on Deezer...", format_query(song, artist))
    query = f"{song} {artist}" if artist else song
    req = locked(deezer_lock)(requests.get)("https://api.deezer.com/search/track", params={"q": query})
    try:
        # decode the JSON data
        search = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError:
        # we skip Deezer
        logger.debug("JSON decoding error")
        return []

    results = search["data"]
    if len(results) == 0:
        logger.debug("No 'data' index")
        return []  # same thing

    ret = [DeezerLazySong(result) for result in results]

    logger.debug("Results:\n%s", pformat(ret))

    return ret
