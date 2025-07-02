"""Utilitary functions."""

import datetime as dt
import difflib
import functools
import inspect
import logging
import math
import operator
import re
from collections.abc import Callable, Iterable, Sequence
from io import BytesIO
from threading import Lock
from typing import (
    Any,
    Literal,
    Required,
    Self,
    TypedDict,
    TypeVar,
    get_origin,
    overload,
)

import mutagen.id3
import requests
from unidecode import unidecode as unidecode_py

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger(__name__)

AnyDictKey = TypeVar("AnyDictKey")
AnyT = TypeVar("AnyT")


def merge_dicts(*args: dict[AnyDictKey, AnyT], merge_lists: bool | None = False) -> dict[AnyDictKey, list[AnyT]]:
    """
    Merge many dicts and return a dict with arrays containing all values.

    `merge_lists` is used to determine how to merge the lists:
    - `True` -> all the elements must be lists (list/tuple) and are concatenated
    - `False` -> all the elements are added as is
    - `None` -> `True` for the element that are lists and `False` for the other elements

    >>> merge_dicts({"a": "b"}, {"x": "y"}, {"a": "c"}, {"x": ["z", "Z"]}, merge_lists = None)
    {"a": ["b", "c"], "x": ["y", "z", "Z"]}

    Raises:
        ValueError: if `merge_lists` is `True` and a value is not a list/tuple.

    """
    ret = {}
    for arg in args:
        for key, value in arg.items():
            if not value:
                continue
            if ret.get(key) is None:
                ret[key] = []
            if merge_lists is None:
                if not isinstance(value, list) and not isinstance(value, tuple):
                    ret[key].append(value)
            elif merge_lists is False:
                ret[key].append(value)
            elif not isinstance(value, list) and not isinstance(value, tuple):
                msg = f"The value {key!r}: {value!r} is not a list"
                raise ValueError(msg)
            else:
                ret[key].append(*value)
    return ret


ExpectedT = TypeVar("ExpectedT")


def get_base_type(candidate: type) -> type:
    """
    Return the base type of a type.

    >>> get_base_type(list)
    <class 'list'>
    >>> get_base_type(list[str])
    <class 'list'>
    """
    origin = get_origin(candidate)
    if origin:
        return origin
    return candidate


@overload
def get(obj: Any, paths: Any, expected: Callable[[Any], ExpectedT]) -> ExpectedT: ...  # noqa: ANN401


@overload
def get(obj: Any, paths: Any, expected: type[ExpectedT]) -> ExpectedT: ...  # noqa: ANN401


@overload
def get(obj: Any, paths: Any, expected: ExpectedT) -> ExpectedT: ...  # noqa: ANN401


@overload
def get(
    obj: dict[str, Any] | Sequence[Any],
    *paths: Any,  # noqa: ANN401
    expected: Callable[[Any], ExpectedT],
) -> ExpectedT: ...


@overload
def get(obj: dict[str, Any] | Sequence[Any], *paths: Any, expected: type[ExpectedT]) -> ExpectedT: ...  # noqa: ANN401


@overload
def get(obj: dict[str, Any] | Sequence[Any], *paths: Any, expected: ExpectedT) -> ExpectedT: ...  # noqa: ANN401


@overload
def get(obj: Any, *paths: Any, expected: None = ...) -> Any: ...  # noqa: ANN401


def get(data, *paths, default_type=None):  # noqa: C901
    """Safely traverse nested `dict`s and `Sequence`s."""
    if not default_type and (get_base_type(paths[-1]) or callable(paths[-1])):
        default_type = paths[-1]
        paths = paths[:-1]

    # Navigate through the nested dictionary using the keys
    for keys in paths:
        if isinstance(keys, str):
            keys = [keys]  # noqa: PLW2901
        try:
            for key in keys:
                if (isinstance(data, dict) and key in data) or isinstance(data, list):
                    data = data[key]
                else:
                    # If the key is not found, return the default value
                    if default_type is not None:
                        break
                    return None  # or raise an exception if preferred
        except Exception:  # noqa: BLE001, S112
            continue

        if default_type and callable(default_type):
            try:
                return default_type(data)
            except Exception:  # noqa: BLE001, S110
                pass
        elif default_type is None or isinstance(data, get_base_type(default_type)):
            # If a default type is specified and the value is not of that type, continue
            return data

    return instantiate(default_type)


def instantiate(target_type: type[ExpectedT] | Callable[[Any], ExpectedT]) -> ExpectedT | None:
    """Return an empty instance of the given type/function or `None` if it's not possible."""
    if target_type is dt.date:
        target_type = dt.date.fromisoformat

    target_type = get_base_type(target_type)

    for args in [
        (),
        (""),
        (0),
    ]:
        try:
            return target_type(*args)
        except:  # noqa: E722, PERF203, S110
            pass

    return None


F = TypeVar("F", bound=Callable)


def ratio(string1: str, string2: str, minimum: float = 0) -> float:
    """Return the ratio of similarity between two strings."""
    ret = difflib.SequenceMatcher(None, string1, string2).ratio()
    if ret < minimum:
        return 0
    return ret


def partial_ratio(string1: str, string2: str, minimum: float = 0) -> float:
    """Return the ratio of similarity between two strings, based on the longest match."""
    # Find the longest match
    seq_matcher = difflib.SequenceMatcher(None, string1, string2)
    match = seq_matcher.find_longest_match(0, len(string1), 0, len(string2))

    # Calculate the length of the matching subsequence
    match_length = match.size
    if match_length == 0:
        return 0.0

    # Calculate the ratio based on the longest match
    matched_string1 = string1[match.a : match.a + match_length]
    matched_string2 = string2[match.b : match.b + match_length]

    ret = difflib.SequenceMatcher(None, matched_string1, matched_string2).ratio()
    if ret < minimum:
        return 0
    return ret


class Picture:
    """A picture (album art) on a website."""

    CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        url: str = "",
        width: int = 0,
        height: int = 0,
        sure: bool = True,
        data: Literal[False] | bytes | None = None,
    ) -> None:
        """Create a new `Picture`."""
        self.url = url
        self.width = width
        self.height = height or width
        self.data: Literal[False] | bytes | None = data
        self.sure = sure
        self.req: requests.Response | None = None
        self._pillow = None
        self._load_metadata()

    def _load_metadata(self) -> None:
        if self.data:
            self.sure = True
            if Image is not None:
                try:
                    img = Image.open(BytesIO(self.data))
                    self._pillow = img
                    self.width, self.height = img.size
                except OSError:
                    pass

    @property
    def pillow(self) -> Image.Image | None:  # noqa: D102
        if self._pillow is not None:
            return self._pillow

        if not isinstance(self.data, bytes) or Image is None:
            return None

        self._pillow = Image.open(BytesIO(self.data))
        return self._pillow

    @property
    def size(self) -> float:
        """Size of the image (smallest dimension)."""
        return min(self.width, self.height)

    def check(self) -> bool:
        """Check if the picture exists (without downloading it, if possible)."""
        if self.sure:
            return True
        logger.debug("Checking picture '%s'...", self.url)
        # don't download the picture, just the headers
        req = requests.head(self.url, stream=True)  # noqa: S113
        try:
            req.raise_for_status()
            self.sure = True
        except requests.exceptions.HTTPError as err:
            logger.debug("HTTP error: %s...", err)
            self.sure = False
        return self.sure

    def download(self) -> Literal[False] | bytes:
        """Download the picture."""
        if self.data is not None:
            return self.data

        # download the picture
        logger.debug("Downloading picture '%s'...", self.url)

        self.data = b""

        try:
            # don't download the page if there is an error
            self.req = requests.get(self.url, stream=True)  # noqa: S113
            self.req.raise_for_status()
            self.data = self.req.content or b""
        except requests.exceptions.HTTPError as err:
            logger.debug("HTTP error: %s...", err)
            self.data = False

        logger.debug("Picture downloaded")
        return self.data

    def __repr__(self) -> str:
        """Return the debug representation of the picture."""
        return f"<Picture {self.size}x{self.size} {'sure' if self.sure else 'not sure'} at {self.url}>"


class PictureProvider:
    """Class for listing and downloading the images of a website."""

    def __init__(self, result: dict[str, Any]) -> None:
        """Create a new `PictureProvider`."""
        self.result = result

        self.pictures = self.get_sure_pictures()

        self.provider_urls = {pic.size: pic for pic in self.pictures}

        if self.pictures:
            sizes_to_try = [1200, 1000, 800, 500, 300]

            for size in sizes_to_try:
                if not any(pic.size == size for pic in self.pictures):
                    url = self.get_url_for_size(size)
                    if url:
                        self.pictures.append(Picture(url, size, sure=False))

            self.pictures.sort(key=lambda pic: pic.size, reverse=True)

    def get_sure_pictures(self) -> list[Picture]:
        """Return a list of all the sure pictures."""
        raise NotImplementedError

    def get_url_for_size(self, size: int) -> str | None:
        """
        Return a (probably) valid URL for the given size, if possible.

        The default implementation tries to replace the size of a picture with the asked size for all the pictures.
        If the URLs do not contain the size, this method should be overridden and return `None`.
        """
        for picture in self.pictures:
            picture_size = picture.size
            picture_url = picture.url

            url_parts = picture_url.split("/")
            if str(picture_size) in url_parts[-1]:
                url_parts[-1] = url_parts[-1].replace(str(picture_size), str(size))
                return "/".join(url_parts)

        return None

    @property
    def best_picture(self) -> Picture:
        """The best picture."""
        return self.pictures[0]

    @property
    def pillow(self) -> "Image.Image | None":
        """The best picture, opened with Pillow if it is available."""
        return self.best_picture.pillow


class TagsList(TypedDict, total=False):
    """A list of ID3 tags."""

    TIT2: Required[str]
    TPE1: Required[str]
    TALB: str
    TLEN: str
    TCOM: str
    TYER: str
    TDAT: str
    TIME: str
    COMM: str
    TSRC: str
    TRCK: str
    TCOP: str
    TLAN: str
    TCON: str
    USLT: str
    SYLT: list[tuple[str, int]]
    APIC: Picture | None


class Artists:
    """An artists list from MusicBrainz."""

    def __init__(self, mb_data: list[dict[str, Any]]) -> None:
        """Create a new `Artists` object from MusicBrainz data."""
        self.mb_data = mb_data

    def __bool__(self) -> bool:
        """Return `True` if the artists list is not empty, `False` otherwise."""
        return len(self.mb_data) > 0

    def __str__(self) -> str:
        """Return the string representation of the artists list."""
        ret = ""
        previous = None
        for artist in self.mb_data:
            if previous is not None:
                ret += previous.get("joinphrase", ", ")
            ret += artist["name"]
            previous = ret
        return ret


class Song:
    """A song."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        title: str = "",
        artists: list[str] | tuple[str, ...] | Artists = (),
        album: str | None = None,
        duration: float = 0,
        language: str | None = None,
        genre: str | None = None,
        composers: list[str] | None = None,
        release_date: str | dt.date | None = None,
        isrc: str | None = None,
        track_number: int | tuple[int, int | None] | None = None,
        copyright: str | None = None,  # noqa: A002
        lyrics: str | list[tuple[str, float]] | None = None,
        picture: Picture | PictureProvider | None = None,
        comments: str | None = None,
    ) -> None:
        """Create a new `Song`."""
        self.title = title
        self.artists = artists
        self.album = album
        self.duration = duration
        self.language = language
        self.genre = genre
        self.composers = composers
        if isinstance(release_date, str):
            try:
                self.release_date = dt.datetime.fromisoformat(release_date)
            except ValueError:
                self.release_date = None
        else:
            self.release_date = release_date
        self.isrc = isrc
        self.track_number = (track_number, None) if isinstance(track_number, int) else track_number
        self.copyright = copyright
        self.lyrics = lyrics.rstrip() if isinstance(lyrics, str) else lyrics
        self.picture = picture
        self.comments = comments

    @classmethod
    def empty(cls) -> Self:
        """Return an empty song for placeholder purposes."""
        return cls()

    def __bool__(self) -> bool:
        """Return `True` if the song is not empty, `False` otherwise."""
        return bool(self.title or self.artists)

    def to_id3(self) -> TagsList:
        """Return the ID3 tags for a song."""
        if not self:
            return {"TIT2": "", "TPE1": ""}
        r_date = self.release_date
        if not r_date:
            year = date = time = ""
        else:

            def test_value(value: str) -> str:
                """Return `""` if the int representation of a value is 0, otherwise return the original value."""
                return "" if not int(value) else value  # avoid "0000" for example...

            year = test_value(f"{r_date:%Y}")  # YYYY
            date = test_value(f"{r_date:%d%m}")  # DDMM
            time = test_value(f"{r_date:%H%M}")  # HHMM

        def format_lrc_timestamp(timestamp: float) -> str:
            """Format a LRC timestamp."""
            return f"[{int(timestamp // 60):02d}:{timestamp % 60:05.2f}]"

        ret: TagsList = {
            "TIT2": self.title,
            "TPE1": str(self.artists) if isinstance(self.artists, Artists) else ", ".join(self.artists),
            "TALB": self.album or "",
            "TLEN": str(int(self.duration * 1000)) if self.duration is not None else "",
            "TCOM": ", ".join(self.composers) if self.composers else "",
            "TYER": year,
            "TDAT": date,
            "TIME": time,
            "TSRC": self.isrc or "",
            "TRCK": (
                (
                    "/".join(str(n) for n in self.track_number)
                    if isinstance(self.track_number, tuple)
                    else str(self.track_number)
                )
                if self.track_number
                else ""
            ),
            "TCOP": self.copyright or "",
            "TLAN": self.language or "",
            "TCON": self.genre or "",
            "USLT": (
                "\n".join((format_lrc_timestamp(ts) + line if line else "") for line, ts in self.lyrics)
                if isinstance(self.lyrics, list)
                else (self.lyrics or "")
            ),
            "SYLT": [(line[0], int(line[1] * 1000)) for line in self.lyrics] if isinstance(self.lyrics, list) else [],
            "APIC": self.picture.best_picture if isinstance(self.picture, PictureProvider) else self.picture,
            "COMM": self.comments or "",
        }
        return ret

    @staticmethod
    def _parse_track_number(tag: str) -> tuple[int, int] | int | None:
        """Parse a `TRCK` ID3 tag. Return `(track, total_tracks)`, `track` or `None`."""
        track_n = tag.split("/")
        if len(track_n) < 2:  # noqa: PLR2004
            track_n.append("")

        if track_n[1]:
            return int(track_n[0]), int(track_n[1])
        if track_n[0]:
            return int(track_n[0])
        return None

    @classmethod
    def from_id3(cls, file: str) -> Self:
        """Create a `Song` from ID3 metadata present in a given file."""
        id3 = mutagen.id3.ID3(file)

        @overload
        def get_tag(tag: str, integer: Literal[False] = False) -> str: ...

        @overload
        def get_tag(tag: str, integer: Literal[True]) -> int: ...

        def get_tag(tag, integer=False):
            item = id3.getall(tag)
            if not item:
                return ""

            text = item[0].text
            if not text:
                return ""
            if isinstance(text, list):
                text = text[0]

            if integer:
                try:
                    return int(text)
                except ValueError:
                    return 0
            return text

        try:
            date = get_tag("TDAT")
            year = get_tag("TYER", True)
            release_date = dt.date(year, int(date[2:4]), int(date[0:2]))
        except (ValueError, IndexError):
            release_date = None

        track_n = cls._parse_track_number(get_tag("TRCK"))

        pictures = id3.getall("APIC")

        return cls(
            title=get_tag("TIT2"),
            artists=[get_tag("TPE1")],
            album=get_tag("TALB"),
            duration=get_tag("TLEN", True),
            language=get_tag("TLAN"),
            genre=get_tag("TCON"),
            composers=[get_tag("TCOM")],
            release_date=release_date,
            isrc=get_tag("TSRC"),
            track_number=track_n,
            copyright=get_tag("TCOP"),
            lyrics=get_tag("USLT"),
            picture=Picture(data=pictures[0].data, url=pictures[0].desc) if pictures else None,
            comments=get_tag("COMM"),
        )

    @classmethod
    def merge(cls: type[Self], songs: list[Self]) -> Self:
        """Merge two songs, taking the first available information in all the songs. Return the new song."""
        T = TypeVar("T")
        T2 = TypeVar("T2")

        def get_first(list_: Iterable[T], default: T2 = None) -> T | T2:
            try:
                iterator = iter(list_)
                while True:
                    item = next(iterator)
                    if item:
                        return item
            except StopIteration:
                return default

        kwargs = {}
        for arg, def_value in (inspect.getfullargspec(cls.__init__).kwonlydefaults or {}).items():
            kwargs[arg] = get_first((getattr(song, arg) for song in songs), def_value)

        return cls(**kwargs)

    def __repr__(self) -> str:
        """Return the debug representation of the song."""
        return f"<Song '{self.title}' by {', '.join(self.artists)} album {self.album} {self.duration} s>"


def _get_sentence_words(string: str) -> str:
    """Get all the words in a sentence."""
    return re.findall(r"\w+", unidecode(string.lower()))


def _normalize_sentence(string: str) -> str:
    """Return a sentence without punctuation, without brackets and lowercased."""
    return " ".join(_get_sentence_words(re.sub(r"(?i)\(.*?\)|-\s+.*|feat", "", string)))


DISCARD_RE = re.compile(
    r"""(?xi)
    \d+ h(?:our)?s?\b
    |\bloops?\b
    |\bbest\W*of\b
    |\bfull\b
    |\bcompl[eè]t
    |\bnon\W*stop\b
    |\b8d audio\b
    |\bspee?d up\b
    |\baco?usti
    |\bpiano
    |\blive\b
    |\bdire[ct]ta?\b
    |\bremix
    |\bversion
    |\brecord
    |\d+[./-]\d+[./-]\d+
    """,
)


def order_results(provider: str, best_items: list[Song], results: list[Song] | None) -> list[Song]:  # noqa: PLR0914
    """Order the results: choose the result that is the most similar to the Spotify / Deezer song."""
    if not results:
        return []

    best_item = Song.merge(best_items)

    ret: list[tuple[Song, float, list[float]]] = []

    def normalize_title(title: str) -> str:
        title = re.sub(r"\.\s*(?=\w\W|\w$|$)", "", title)
        title = re.sub(r"\bst(e?s?)(\s+|$)", r"saint\1\2", title)
        title = re.sub(r"(?<=\w)\W+(ve|d|ll|s|m|re)", r"\1", title)
        title = re.sub(r"(?<=\wn)\W+t", r"t", title)
        return title  # noqa: RET504

    for result in results:
        # check for common word
        song_title = normalize_title(result.title)
        best_title = normalize_title(best_item.title)

        if not any(word in _get_sentence_words(song_title) for word in _get_sentence_words(best_title)):
            # if there are no common words, skip result
            continue

        # Find artist match
        # match = (no of artist names in result) / (no of artist names on spotify) * 100
        all_r_artists = _normalize_sentence(" ".join(result.artists))

        artist_match_number = sum(
            1 if partial_ratio(_normalize_sentence(sp_artist), all_r_artists, 0.85) else 0
            for sp_artist in best_item.artists
        )

        artist_match = (artist_match_number / len(best_item.artists)) * 100

        # Skip if there are no artists in common
        if artist_match_number == 0:
            continue

        name_match = ratio(
            str(unidecode(best_title.lower())),
            str(unidecode(song_title.lower())),
            0.6,
        )

        official_match = (
            len(
                re.findall(
                    r"(?i)(\b[ou]ffi[cz]i[ae]l|_off\b|\btopic\b|\blyric|\bparole|audio(?=.*\b[ou]ffi[cz]i[ae]l))",
                    song_title + " " + all_r_artists,
                )
            )
            * 100
        )
        if not official_match and hasattr(result, "artist_badge"):
            official_match += 100 if result.artist_badge else 0
        if official_match:
            official_match += len(re.findall(r"(?i)\baudio\b", song_title)) * 100

        if best_item.copyright:
            copyright_match = 80 + (_normalize_sentence(best_item.copyright) in all_r_artists) * 20
        else:
            copyright_match = 100

        delta = max(abs(result.duration - best_item.duration) - 4, 0)
        non_match_value = delta**2 / best_item.duration * 100

        time_match = max(100 - non_match_value, 0)

        views_match = math.log10(result.views) / 10 * 100 if getattr(result, "views", 0) else 50

        discard_match = (len(DISCARD_RE.findall(song_title)) + len(DISCARD_RE.findall(all_r_artists))) * -100

        # the average match is rounded for debugging
        average_match = round(
            (
                artist_match
                + name_match
                + official_match * 2
                + copyright_match * 2
                + time_match * 3
                + views_match * 0.5
                + discard_match * 2
            )
            / 11.5,
            ndigits=3,
        )

        # the results along with the average match
        ret.append((
            result,
            average_match,
            [artist_match, name_match, official_match, copyright_match, time_match, views_match, discard_match],
        ))

    ret = sorted(ret, key=operator.itemgetter(1), reverse=True)
    logger.debug(
        "%s sorted results:\n%s",
        provider,
        "\n".join([f"{el[1]} ({' '.join(str(round(e, 3)) for e in el[2])}): {el[0]}" for el in ret]),
    )
    return [el[0] for el in ret]


# for type checking
def unidecode(string: str) -> str:
    """Transliterate an Unicode object into an ASCII string."""
    return unidecode_py(string)


AnyFunction = TypeVar("AnyFunction", bound=Callable)


def locked(lock: Lock) -> Callable[[AnyFunction], AnyFunction]:
    """
    Acquire a lock before executing the function and release it after.

    If the lock has already been released, don't do anything.
    """

    def decorator(f: AnyFunction) -> AnyFunction:
        @functools.wraps(f)
        def wrapper(*args, **kwargs) -> Any:  # noqa: ANN401
            lock.acquire()
            try:
                return f(*args, **kwargs)
            finally:
                if lock.locked():
                    lock.release()

        return wrapper

    return decorator


def format_query(song: str, artist: str | None = None, market: str | None = None) -> str:
    """Return a formatted version of `song`, `artist` and `market` (for logging)."""
    return f"'{song}'" + (f" - '{artist}'" if artist else "") + (f" on '{market}' market" if market else "")


# https://stackoverflow.com/a/17246726
def get_all_subclasses(cls: type) -> list[type]:
    """Return all the subclasses of a given class."""
    all_subclasses = []

    for subclass in cls.__subclasses__():
        all_subclasses.append(subclass)
        all_subclasses.extend(get_all_subclasses(subclass))

    # https://stackoverflow.com/a/7961390
    return [*dict.fromkeys(all_subclasses)]
