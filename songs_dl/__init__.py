"""
Songs downloader.
"""

import argparse
import concurrent.futures
import logging
import os
import re
import sys
import traceback
import urllib.parse
from io import BytesIO
from pprint import pformat
from typing import Callable, TypedDict

import mutagen.id3
from yt_dlp.utils import sanitize_filename

from .deezer import download_deezer
from .itunes import download_itunes
from .monkeypatch_requests import mp_requests
from .musixmatch import download_musixmatch
from .spotify import download_spotify
from .utils import Song, merge_dicts, order_results
from .youtube import YoutubeSong, download_youtube
from .youtube_dl import download_youtube_dl

__version__ = "0.2.2"

logger = logging.getLogger(__name__)

# add a newline between each message on Termux
logging.basicConfig(format="[%(name)s] %(message)s" + ("\n" if hasattr(sys, "getandroidapilevel") else ""))


def download_song(query: str) -> str | None:
    """
    Download a song with ID3 tags (title, artist, lyrics...).
    Return the path of the song or None.
    """

    logger.info("Downloading '%s'", query)

    match = re.match(r"\bmarket:([\w-]+)", query)
    if match:
        market = match.group(1)
        query = query[: match.start()] + query[match.end() :]
    else:
        market = None

    if "--" in query:
        parts = [part.strip() for part in query.split("--", 2)]
        song, artist = parts
    else:
        song = query
        artist = None

    logger.debug("Parsed query: song = %r, artist = %r, market = %r", song, artist, market)

    results: dict[str, list[Song]] = {
        "spotify": [],
        "itunes": [],
        "musixmatch": [],
        "deezer": [],
        "youtube": [],
    }
    actions: dict[str, Callable[[str], list[Song]]] = {
        "spotify": download_spotify,
        "itunes": download_itunes,
        "musixmatch": download_musixmatch,
        "deezer": download_deezer,
        "youtube": download_youtube,
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_action = {executor.submit(func, song, artist, market): action for action, func in actions.items()}
        for future in concurrent.futures.as_completed(future_to_action):
            provider = future_to_action[future]
            try:
                results[provider] = future.result()
            except:  # noqa
                print(f"Error when executing {provider}:", file=sys.stderr)
                traceback.print_exc()
            if provider == "youtube" and len(results[provider]) == 0:
                logger.error("No videos available!")
                for future in future_to_action:
                    future.cancel()
                return None

    # be sure there is at least one song in every list
    for provider, songs in results.items():
        if len(songs) == 0:
            songs.append(Song.empty())

    # Providers sorted by confidence
    best_providers = ["spotify", "itunes", "musixmatch", "deezer", "youtube"]

    def get_best_songs(not_provider):
        return [
            item[1]
            for item in sorted(
                [(action, songs[0]) for action, songs in results.items() if action != not_provider],
                key=lambda item: best_providers.index(item[0]),
            )
        ]

    # order the results
    for provider, songs in results.items():
        if provider != "spotify":
            results[provider] = order_results(provider, get_best_songs(provider), results)
        if len(results[provider]) == 0:
            if provider == "youtube":
                logger.error("No videos available!")
                return None
            results[provider].append(Song.empty())

    best_video: YoutubeSong = results["youtube"][0]  # type: ignore

    filename, youtube_song = download_youtube_dl(
        f"https://www.youtube.com/watch?v={urllib.parse.quote(best_video.youtube_video['id'])}"
    )
    # add the metadata from the YouTube page
    results["youtube_dl"] = [youtube_song]

    # we don't need to load the file's tags (we replace them)
    # so there is no filename here
    tags = mutagen.id3.ID3()

    # tags (spotify -> itunes -> musixmatch -> deezer -> youtube)
    tags_list = merge_dicts(
        results["spotify"][0].to_id3(),
        results["itunes"][0].to_id3(),
        results["musixmatch"][0].to_id3(),
        results["deezer"][0].to_id3(),
        results["youtube_dl"][0].to_id3(),
        results["youtube"][0].to_id3(),
    )
    tags_list = {key: [value for value in values if value] for key, values in tags_list.items()}

    def get_image_mimetype(mimetype: str | None, url: str):
        """
        Get image MIME type with its `Content-Type` header or its file extension.
        """
        if mimetype and mimetype.startswith("image/") and len(mimetype) > 6:  # image/...
            return mimetype
        ext = url.rsplit(".", 1)[-1].replace("jpg", "jpeg")
        if ext not in ["jpeg", "png", "gif", "webp"]:
            ext = "jpeg"
        return "image/" + ext

    logger.debug("ID3 tags:\n%s", "\n".join([f"{a}: {pformat(b)}" for a, b in tags_list.items()]))

    class TagParams(TypedDict, total=False):
        """
        Dict with ID3 tags to be passed to `mutagen`.
        """

        encoding: int
        text: str
        lang: str

        type: int
        desc: str
        mime: str
        data: bytes

    title = ""
    artist = ""
    for tag_name, value in tags_list.items():
        params: TagParams = {"encoding": 3}
        if tag_name == "APIC":
            # we try all the pictures
            for picture in sorted(value, key=lambda e: e.size, reverse=True):
                data = picture.download()
                if data is False:
                    continue
                params["type"] = 3
                params["desc"] = picture.url
                try:
                    from PIL import Image

                    img = Image.open(BytesIO(data))
                    img.thumbnail((1200, 1200))
                    output = BytesIO()
                    img.save(output, format="jpeg")
                    params["mime"] = "image/jpg"
                    params["data"] = output.getvalue()
                except (ImportError, OSError):
                    params["mime"] = get_image_mimetype(
                        mimetype=picture.req.headers.get("Content-Type"), url=picture.url
                    )
                    params["data"] = data
                break
        else:
            if tag_name == "COMM":
                value = "\n\n".join(value)  # join all the comments
            elif tag_name == "SYLT":
                value = value[0]  # use SYLT as is (list of tuples), will be handled correctly by Mutagen
            else:
                value = str(value[0])  # stringify anything else
            params["text"] = value
        if tag_name == "TIT2":
            title = params["text"]  # type: ignore
        elif tag_name == "TPE1":
            artist = params["text"]  # type: ignore
        elif tag_name == "COMM":
            params["lang"] = "eng"
        elif tag_name == "USLT":
            params["lang"] = (tags_list.get("TLAN", []) + [""])[0] or "eng"
        tags[tag_name] = getattr(mutagen.id3, tag_name)(**params)

    tags.save(filename, v2_version=3)

    if artist and title:
        final_filename = sanitize_filename(f"{artist} - {title}.mp3")
        os.replace(filename, final_filename)
    else:
        final_filename = filename
    logger.info("Final filename: %s", final_filename)

    if "USLT" in tags_list:
        with open(final_filename.rsplit(".", 1)[0] + ".lrc", "w", encoding="utf-8") as f:
            f.write(tags_list["USLT"][0] + "\n")

    return final_filename


def main():
    """
    Main entry point for CLI.
    """
    parser = argparse.ArgumentParser(fromfile_prefix_chars="@")
    parser.add_argument("SONG", nargs="+", help="songs to download")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="number of songs to download in the same time",
    )
    parser.add_argument("-v", "--verbose", action="count", help="show more information")

    args = parser.parse_args()

    logging.root.setLevel(
        {
            0: logging.WARNING,
            1: logging.INFO,
            2: logging.DEBUG,
        }.get(args.verbose, logging.DEBUG)
    )

    mp_requests()

    ret = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_song = {executor.submit(download_song, song): song for song in args.SONG}
        for future in concurrent.futures.as_completed(future_to_song):
            song = future_to_song[future]
            try:
                ret.append(future.result())
            except:  # noqa
                print(f"Error when downloading '{song}':", file=sys.stderr)
                traceback.print_exc()
    return ret


if __name__ == "__main__":
    main()
