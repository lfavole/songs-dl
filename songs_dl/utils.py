"""
Utilitary functions.
"""

import datetime as dt
import functools
import inspect
import logging
import re
from io import BytesIO
from threading import Lock
from typing import (
    Any,
    Callable,
    Iterable,
    Literal,
    Required,
    Sequence,
    Type,
    TypedDict,
    TypeVar,
    Union,
    get_origin,
    overload,
)

import mutagen.id3
import requests
from rapidfuzz import fuzz
from unidecode import unidecode as unidecode_py
from yt_dlp.utils import traverse_obj

Self = TypeVar("Self")

logger = logging.getLogger(__name__)

AnyDictKey = TypeVar("AnyDictKey")
AnyT = TypeVar("AnyT")


def merge_dicts(
    *args: Union[dict[AnyDictKey, AnyT], TypedDict], merge_lists: bool | None = False
) -> dict[AnyDictKey, list[AnyT]]:
    """
    Merge many dicts and return a dict with arrays containing all values.

    `merge_lists` is used to determine how to merge the lists:
    - `True` -> all the elements must be lists (list/tuple) and are concatenated
    - `False` -> all the elements are added as is
    - `None` -> `True` for the element that are lists and `False` for the other elements

    >>> merge_dicts({"a": "b"}, {"x": "y"}, {"a": "c"}, {"x": ["z", "Z"]}, merge_lists = None)
    {"a": ["b", "c"], "x": ["y", "z", "Z"]}
    """
    ret = {}
    for arg in args:
        for key, value in arg.items():
            if value:
                if ret.get(key) is None:
                    ret[key] = []
                if merge_lists is None:
                    if not isinstance(value, list) and not isinstance(value, tuple):
                        value = [value]
                elif merge_lists is False:
                    value = [value]
                else:
                    if not isinstance(value, list) and not isinstance(value, tuple):
                        raise ValueError(f"The value {key!r}: {value!r} is not a list")
                ret[key].append(*value)
    return ret


ExpectedT = TypeVar("ExpectedT")


def get_base_type(candidate):
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
    if not isinstance(candidate, type):
        return type(candidate)
    return candidate


@overload
def get(obj: Any, paths: Any, expected: Callable[[Any], ExpectedT]) -> ExpectedT: ...


@overload
def get(obj: Any, paths: Any, expected: Type[ExpectedT]) -> ExpectedT: ...


@overload
def get(obj: Any, paths: Any, expected: ExpectedT) -> ExpectedT: ...


@overload
def get(
    obj: dict[str, Any] | Sequence[Any],
    *paths: Any,
    expected: Callable[[Any], ExpectedT],
) -> ExpectedT: ...


@overload
def get(obj: dict[str, Any] | Sequence[Any], *paths: Any, expected: Type[ExpectedT]) -> ExpectedT: ...


@overload
def get(obj: dict[str, Any] | Sequence[Any], *paths: Any, expected: ExpectedT) -> ExpectedT: ...


@overload
def get(obj: Any, *paths: Any, expected: None = ...) -> Any: ...


def get(obj, *paths, expected=None, **kwargs):
    """
    Safely traverse nested `dict`s and `Sequence`s.

    Work around to force the return value to have the correct type.

    See `yt_dlp.utils.traverse_obj` docstring for more information.
    """
    expected_type = kwargs.pop("expected_type", None)
    expected = expected or expected_type
    if not expected and (get_base_type(paths[-1]) or callable(paths[:-1])):
        expected = paths[-1]
        paths = paths[:-1]
    if expected:
        expected = get_base_type(expected)
    ret = traverse_obj(
        obj,
        *paths,
        expected_type=expected,
        **kwargs,
    )
    if ret is None and expected:
        return instantiate(expected)
    return ret


def instantiate(target_type: Type[ExpectedT] | Callable[[Any], ExpectedT]) -> ExpectedT | None:
    """
    Return an empty instance of the given type/function or `None` if it's not possible.
    """
    if target_type is dt.date:
        target_type = dt.date.fromisoformat  # type: ignore

    target_type = get_base_type(target_type)

    for args in [
        (),
        (""),
        (0),
    ]:
        try:
            return target_type(*args)  # type: ignore
        except:  # noqa
            pass

    return None


def fuzz_wrapper(func):
    """
    Decorator for `rapidfuzz` functions: work around emojis that cause bugs.
    """

    @functools.wraps(func)
    def wrapper(str1: str, str2: str, score_cutoff: float = 0):
        try:
            return func(str1, str2, score_cutoff)
        except:  # noqa
            # we build new strings that contain only alphanumerical characters and spaces
            # and return the partial_ratio of that
            new_str1 = "".join(each_letter for each_letter in str1 if each_letter.isalnum() or each_letter.isspace())
            new_str2 = "".join(each_letter for each_letter in str2 if each_letter.isalnum() or each_letter.isspace())
            return func(new_str1, new_str2, score_cutoff=score_cutoff)

    return wrapper


_ratio = fuzz_wrapper(fuzz.ratio)
_partial_ratio = fuzz_wrapper(fuzz.partial_ratio)


class Picture:
    """
    A picture (album art) on a website.
    """

    CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        url: str = "",
        width: int = 0,
        height: int = 0,
        sure=True,
        data: Literal[False] | bytes | None = None,
    ):
        self.url = url
        self.width = width
        self.height = height or width
        self.data: Literal[False] | bytes | None = data
        self.sure = sure
        self.req: requests.Response | None = None
        self._pillow = None
        self._load_metadata()

    def _load_metadata(self):
        if self.data:
            self.sure = True
            try:
                from PIL import Image

                img = Image.open(BytesIO(self.data))
                self._pillow = img
                self.width, self.height = img.size
            except (ImportError, OSError):
                pass

    @property
    def pillow(self):
        if self._pillow is not None:
            return self._pillow

        if not isinstance(self.data, bytes):
            return None

        from PIL import Image

        self._pillow = Image.open(BytesIO(self.data))
        return self._pillow

    @property
    def size(self):
        """
        Size of the image (smallest dimension).
        """
        return min(self.width, self.height)

    def check(self):
        """
        Check if the picture exists (without downloading it, if possible).
        """
        if self.sure:
            return True
        logger.debug("Checking picture '%s'...", self.url)
        # don't download the picture, just the headers
        req = requests.head(self.url, stream=True)
        try:
            req.raise_for_status()
            self.sure = True
        except requests.exceptions.HTTPError as err:
            logger.debug("HTTP error: %s...", err)
            self.sure = False
        return self.sure

    def download(self) -> Literal[False] | bytes:
        """
        Download the picture.
        """
        if self.data is not None:
            return self.data

        # download the picture
        logger.debug("Downloading picture '%s'...", self.url)

        self.data = b""

        try:
            # don't download the page if there is an error
            self.req = requests.get(self.url, stream=True)
            self.req.raise_for_status()
            self.data = self.req.content
        except requests.exceptions.HTTPError as err:
            logger.debug("HTTP error: %s...", err)
            self.data = False

        logger.debug("Picture downloaded")
        return self.data

    def __repr__(self):
        return f"<Picture {self.size}x{self.size} {'sure' if self.sure else 'not sure'} at {self.url}>"


class PictureProvider:
    """
    Class for listing and downloading the images of a website.
    """

    pictures: list[Picture]

    def __init__(self, result: dict[str, Any]):
        self.provider_urls = {pic.size: pic for pic in self.get_sure_pictures(result)}

        self.pictures = self.get_sure_pictures(result)

        if not self.pictures:
            return

        sizes_to_try = [1200, 1000, 800, 500, 300]

        for size in sizes_to_try:
            if not any(pic.size == size for pic in self.pictures):
                url = self.get_url_for_size(size)
                if url:
                    self.pictures.append(Picture(url, size, sure=False))

        self.pictures.sort(key=lambda pic: pic.size, reverse=True)

    def get_sure_pictures(self, result: dict[str, Any]) -> list[Picture]:
        """
        Return a list of all the sure pictures.
        """
        raise NotImplementedError

    def get_url_for_size(self, size: int) -> str | None:
        """
        Return a probably valid URL for the given size.
        """
        for picture in self.pictures:
            picture_size = picture.size
            picture_url = picture.url

            url_parts = picture_url.split("/")
            if str(picture_size) in url_parts[-1]:
                url_parts[-1] = url_parts[-1].replace(str(picture_size), str(size))
                return "/".join(url_parts)

    def get_pictures(self):
        return self.pictures

    def get_best_picture(self):
        return self.pictures[0]

    @property
    def pillow(self):
        return self.get_best_picture().pillow


class TagsList(TypedDict, total=False):
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


class Song:
    """
    A song.
    """

    def __init__(
        self,
        *,
        title: str = "",
        artists: list[str] | tuple[str, ...] = (),
        album: str | None = None,
        duration: float = 0,
        language: str | None = None,
        genre: str | None = None,
        composers: list[str] | None = None,
        release_date: str | dt.date | None = None,
        isrc: str | None = None,
        track_number: int | tuple[int, int | None] | None = None,
        copyright: str | None = None,  # pylint: disable=W0622
        lyrics: str | list[tuple[str, float]] | None = None,
        picture: Picture | PictureProvider | None = None,
        comments: str | None = None,
    ):
        self.title = title
        self.artists = list(artists)
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
    def empty(cls):
        """
        Return an empty song for placeholder purposes.
        """
        return cls()

    def __not__(self):
        return not self.title and not self.artists

    def to_id3(self) -> TagsList:
        """
        Return the ID3 tags for a song.
        """
        if not self:
            return {"TIT2": "", "TPE1": ""}
        r_date = self.release_date
        if not r_date:
            year = date = time = ""
        else:

            def test_value(value: str):
                return "" if not int(value) else value  # avoid "0000" for example...

            year = test_value(f"{r_date:%Y}")  # YYYY
            date = test_value(f"{r_date:%d%m}")  # DDMM
            time = test_value(f"{r_date:%H%M}")  # HHMM

        def format_lrc_timestamp(timestamp: float):
            return f"[{int(timestamp // 60):02d}:{timestamp % 60:05.2f}]"

        ret: TagsList = {
            "TIT2": self.title,
            "TPE1": ", ".join(self.artists),
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
            "APIC": self.picture.get_best_picture() if isinstance(self.picture, PictureProvider) else self.picture,
            "COMM": self.comments or "",
        }
        return ret

    @classmethod
    def from_id3(cls, file):
        id3 = mutagen.id3.ID3(file)

        @overload
        def get_tag(tag: str, integer: Literal[False] = False) -> str: ...

        @overload
        def get_tag(tag: str, integer: Literal[True] = True) -> int: ...

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
                    return int(float(text))
                except ValueError:
                    return 0
            return text

        try:
            date = get_tag("TDAT")
            year = get_tag("TYER", True)
            release_date = dt.date(year, int(date[2:4]), int(date[0:2]))
        except (ValueError, IndexError):
            release_date = None

        track_n = get_tag("TRCK").split("/")
        if len(track_n) < 2:
            track_n.append("")
        track_n = (int(track_n[0]), int(track_n[1])) if track_n[1] else int(track_n[0]) if track_n[0] else None

        pictures = id3.getall("APIC")

        return Song(
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
    def merge(cls: Type[Self], songs: list[Self]) -> Self:
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

        return cls(**kwargs)  # type: ignore

    def __repr__(self):
        return f"<Song '{self.title}' by {', '.join(self.artists)} album {self.album} {self.duration} s>"


def _get_sentence_words(string: str):
    """
    Get all the words in a sentence.
    """
    return re.findall(r"\w+", unidecode(string.lower()))


def _normalize_sentence(string: str):
    """
    Return a sentence without punctuation, without brackets and lowercased.
    """
    return " ".join(_get_sentence_words(re.sub(r"(?i)\(.*?\)|-\s+.*|feat", "", string)))


def get_provider_name(provider: str):
    """
    Return the human name of a provider.
    """
    return {"itunes": "iTunes", "youtube": "YouTube"}.get(provider, provider.title())


def order_results(provider: str, best_items: list[Song], results: dict[str, list[Song]] | None):
    """
    Order the results: choose the result that is the most similar to the Spotify / Deezer song.
    """
    if not results:
        return best_items

    best_item = Song.merge(best_items)

    ret: list[tuple[Song, float, list[float]]] = []

    def normalize_title(title: str):
        title = re.sub(r"\.\s*(?=\w\W|\w$|$)", "", title)
        title = re.sub(r"\bst(e?s?)(\s+|$)", r"saint\1\2", title)
        return title

    for result in results[provider]:
        # check for common word
        song_title = normalize_title(result.title)
        best_title = normalize_title(best_item.title)
        best_title_words = _get_sentence_words(best_title)

        if not any(word in _get_sentence_words(song_title) for word in best_title_words):
            # if there are no common words, skip result
            continue

        # Find artist match
        # match = (no of artist names in result) / (no of artist names on spotify) * 100
        artist_match_number = 0

        all_r_artists = _normalize_sentence(" ".join(result.artists))

        artist_match_number = sum(
            1 if _partial_ratio(_normalize_sentence(sp_artist), all_r_artists, 85) else 0
            for sp_artist in best_item.artists
        )

        artist_match = (artist_match_number / len(best_item.artists)) * 100

        # Skip if there are no artists in common
        if artist_match_number == 0:
            continue

        name_match = _ratio(
            str(unidecode(best_title.lower())),
            str(unidecode(song_title.lower())),
            60,
        )

        official_match = (
            len(
                re.findall(
                    r"(?i)(\b[ou]ffi[cz]i[ae]l|_off\b|\btopic\b|audio(?=.*\b[ou]ffi[cz]i[ae]l))",
                    song_title + " " + all_r_artists,
                )
            )
            * 100
        )
        if not official_match and hasattr(result, "youtube_video"):
            official_match += (
                100 if "BADGE_STYLE_TYPE_VERIFIED_ARTIST" in result.youtube_video["badges"] else 0  # type: ignore
            )
        if official_match:
            official_match += len(re.findall(r"(?i)\baudio\b", song_title)) * 100

        if best_item.copyright:
            copyright_match = 80 + (_normalize_sentence(best_item.copyright) in all_r_artists) * 20
        else:
            copyright_match = 100

        delta = max(abs(result.duration - best_item.duration) - 4, 0)
        non_match_value = delta**2 / best_item.duration * 100

        time_match = max(100 - non_match_value, 0)

        discard_match = (
            len(
                re.findall(
                    r"""(?xi)
                    \d+ h(?:our)\b
                    |\b8d audio\b
                    |\bspee?d up\b
                    |\baco?usti
                    |\blive\b
                    |\bdire[ct]ta?\b
                    |\bremix
                    |\bversion
                    |\brecord
                    |\d+[./-]\d+[./-]\d+
                    """,
                    song_title,
                )
            )
            * -100
        )

        # the average match is rounded for debugging
        average_match = round(
            (artist_match + name_match + official_match * 2 + copyright_match * 2 + time_match * 3 + discard_match * 2)
            / 11,
            ndigits=3,
        )

        # the results along with the average match
        ret.append((
            result,
            average_match,
            [artist_match, name_match, official_match, copyright_match, time_match, discard_match],
        ))

    ret = sorted(ret, key=lambda el: el[1], reverse=True)
    logger.debug(
        "%s sorted results:\n%s",
        get_provider_name(provider),
        "\n".join([f"{el[1]} ({' '.join(str(round(e, 3)) for e in el[2])}): {el[0]}" for el in ret]),
    )
    return [el[0] for el in ret]


# for type checking
def unidecode(string: str) -> str:
    """
    Transliterate an Unicode object into an ASCII string.
    """
    return unidecode_py(string)  # type: ignore


AnyFunction = TypeVar("AnyFunction", bound=Callable)


def locked(lock: Lock):
    """
    Acquire a lock before executing the function and release it after
    (if the lock has already been released, don't do anything).
    """

    def decorator(f: AnyFunction) -> AnyFunction:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            lock.acquire()
            try:
                return f(*args, **kwargs)
            finally:
                if lock.locked():
                    lock.release()

        return wrapper  # type: ignore

    return decorator


def format_query(song: str, artist: str | None = None, market: str | None = None):
    """
    Return a formatted version of `song`, `artist` and `market` (for logging).
    """
    return f"'{song}'" + (f" - '{artist}'" if artist else "") + (f" on '{market}' market" if market else "")
