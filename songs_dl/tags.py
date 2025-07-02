"""Utility functions to add ID3 tags to a song."""

import logging
from io import BytesIO
from pprint import pformat
from typing import TYPE_CHECKING, TypedDict

import mutagen

from .utils import Picture, Song, merge_dicts

try:
    from PIL import Image
except ImportError:
    Image = None

if TYPE_CHECKING:
    from . import ActionsGroup

logger = logging.getLogger(__name__)


def get_image_mimetype(mimetype: str | None, url: str) -> str:
    """Get image MIME type with its `Content-Type` header or its file extension."""
    if mimetype and mimetype.removeprefix("image/"):
        return mimetype
    ext = url.rsplit(".", 1)[-1].replace("jpg", "jpeg")
    if ext not in {"jpeg", "png", "gif", "webp"}:
        ext = "jpeg"
    return "image/" + ext


class TagParams(TypedDict, total=False):
    """Dict with ID3 tags to be passed to `mutagen`."""

    encoding: int
    text: str
    lang: str

    type: int
    desc: str
    mime: str
    data: bytes


def _get_apic_tag(value: list[Picture]) -> TagParams:
    params = {}
    # we try all the pictures
    for picture in sorted(value, key=lambda e: e.size, reverse=True):
        data = picture.download()
        if data is False:
            continue
        params["type"] = 3
        params["desc"] = picture.url
        params["mime"] = get_image_mimetype(mimetype=picture.req.headers.get("Content-Type"), url=picture.url)
        params["data"] = data
        if Image is not None:
            try:
                img = Image.open(BytesIO(data))
                img.thumbnail((1200, 1200))
                output = BytesIO()
                img.save(output, format="jpeg")
                params["mime"] = "image/jpg"
                params["data"] = output.getvalue()
            except OSError:
                pass

    return params


def add_tags(actions: "ActionsGroup[list[Song]]", filename: str) -> tuple[str, str, dict[str, list[str]]]:
    """Add ID3 tags to a song."""
    # we don't need to load the file's tags (we replace them)
    # so there is no filename here
    tags = mutagen.id3.ID3()

    # tags (itunes -> musixmatch -> deezer -> youtube)
    tags_list = merge_dicts(
        *({key: value for key, value in action.results[0].to_id3().items() if value} for action in actions)
    )

    logger.debug("ID3 tags:\n%s", "\n".join([f"{a}: {pformat(b)}" for a, b in tags_list.items()]))

    title = ""
    artist = ""
    for tag_name, value in tags_list.items():
        params: TagParams = {"encoding": 3}

        if tag_name == "APIC":
            params.update(_get_apic_tag(value))
        elif tag_name == "COMM":
            params["text"] = "\n\n".join(value)  # join all the comments
        elif tag_name == "SYLT":
            params["text"] = value[0]  # use SYLT as is (list of tuples), will be handled correctly by Mutagen
        else:
            params["text"] = str(value[0])  # stringify anything else

        if tag_name == "TIT2":
            title = params["text"]
        elif tag_name == "TPE1":
            artist = params["text"]
        elif tag_name == "COMM":
            params["lang"] = "eng"
        elif tag_name == "USLT":
            params["lang"] = [*tags_list.get("TLAN", []), ""][0] or "eng"

        tags[tag_name] = getattr(mutagen.id3, tag_name)(**params)

    tags.save(filename, v2_version=3)

    return title, artist, tags_list
