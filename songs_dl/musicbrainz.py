"""Functions to get metadata from MusicBrainz."""

import logging
from collections import UserList
from collections.abc import Callable, Iterator
from pprint import pformat
from threading import Lock
from typing import Generic, ParamSpec, TypeVar

import requests

from .utils import Artists, Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
musicbrainz_lock = Lock()

P = ParamSpec("P")
T = TypeVar("T")


class LazyList(UserList, Generic[T]):
    """A list that is lazily evaluated."""

    def __init__(self, func: Callable[P, list[T]], *args, **kwargs) -> None:
        """Create a `LazyList`."""
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def _evaluate(self) -> None:
        """Evaluate the lazy list."""
        if self._func:
            self.extend(self._func(*self._args, **self._kwargs))
            self._func = None

    def __getitem__(self, index: int | slice) -> T | list[T]:
        """Get an item from the lazy list."""
        self._evaluate()
        return super().__getitem__(index)

    def __iter__(self) -> Iterator[T]:
        """Iterate over the lazy list."""
        self._evaluate()
        return super().__iter__()


class MusicBrainzPictureProvider(PictureProvider):
    """Picture provider for MusicBrainz."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the MusicBrainz picture provider."""
        super().__init__(*args, **kwargs)
        self._data = None

    @property
    def data(self) -> dict:
        """The data from MusicBrainz cover art archive."""
        if self._data is not None:
            return self._data
        self._data = {}
        logger.info("Downloading MusicBrainz cover art for %s...", get(self.result, "name", str))
        req = locked(musicbrainz_lock)(requests.get)(
            "https://coverartarchive.org/release/" + get(self.result, "id", str)
        )
        try:
            self._data = req.json()
            logger.debug("JSON decoding OK")
        except requests.exceptions.JSONDecodeError:
            logger.debug("JSON decoding error")
        return self._data

    def get_sure_pictures(self) -> LazyList[Picture]:
        """Get the pictures from MusicBrainz cover art archive."""

        def real_get_pictures() -> list[Picture]:
            front_cover = None
            for cover in get(self.data, "images", list):
                if get(cover, "front", bool):
                    front_cover = cover
                    break
            else:
                return []
            return [Picture(url, int(size), int(size)) for size, url in get(front_cover, "thumbnails", dict).items()]

        return LazyList(real_get_pictures)


def download_musicbrainz(song: str, artist: str | None = None, market: str | None = None) -> list[Song]:
    """Fetch the MusicBrainz search results."""
    logger.info("Searching %s on MusicBrainz...", format_query(song, artist, market))

    def escape_quotes(text: str) -> str:
        """Escape quotes in the text."""
        return text.replace('"', '\\"')

    params = {
        "query": f'recording:"{escape_quotes(song)}"' + (f' artist:"{escape_quotes(artist)}"' if artist else ""),
        "fmt": "json",
    }
    if market:
        params["market"] = market
    req = locked(musicbrainz_lock)(requests.get)(
        "https://musicbrainz.org/ws/2/recording",
        params=params,
    )

    try:
        result = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip MusicBrainz
        logger.debug("JSON decoding error: %s", err)
        return []

    def get_best_album(albums: list) -> dict | None:
        """Get the best album from the list of albums."""

        def is_va(artist: dict) -> bool:
            """Check if the artist is a VA (various artists)."""
            return (
                get(artist, ("artist", "id"), str) == "89ad4ac3-39f7-470e-963a-56509c546377"
                or get(artist, "name", str) == "various artists"
                or "add compilations" in get(artist, ("artist", "disambiguation"), str)
            )

        first = None
        for album in albums:
            if first is None:
                first = album
            if any(is_va(artist) for artist in get(album, "artist-credit", list)):
                continue
            return album

        return first

    ret: list[Song] = []
    for element in result.get("recordings", []):
        album = get_best_album(get(element, "releases", list))
        ret.append(
            Song(
                title=get(element, "title", str),
                artists=Artists(element.get("artist-credit", [])),
                album=get(album, "title", ""),
                duration=get(element, "length", int) / 1000,
                picture=MusicBrainzPictureProvider(album),
                release_date=get(element, "first-release-date"),
                isrc=get(element, ("isrcs", 0), str),
                # TODO: add other elements?
            )
        )

    logger.debug("Results:\n%s", pformat(ret))

    return ret
