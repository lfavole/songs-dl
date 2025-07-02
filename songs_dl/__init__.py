"""Songs downloader."""

import argparse
import logging
import re
import sys
import urllib.parse
from functools import partial
from pathlib import Path
from typing import cast

from rich import get_console
from rich.progress import Progress
from rich.traceback import Traceback
from rich.traceback import install as install_traceback
from yt_dlp.utils import sanitize_filename

from .deezer import download_deezer
from .display import Action, ActionsGroup
from .itunes import download_itunes
from .lrclib import download_lrclib
from .monkeypatch_requests import mp_requests
from .musicbrainz import download_musicbrainz
from .musixmatch import download_musixmatch
from .tags import add_tags
from .utils import Song, order_results
from .youtube import YoutubeSong, download_youtube
from .youtube_dl import download_youtube_dl
from .ytmusic import download_youtube_music

__version__ = "0.3.0"

logger = logging.getLogger(__name__)

# add a newline between each message on Termux
logging.basicConfig(format="[%(name)s] %(message)s" + ("\n" if hasattr(sys, "getandroidapilevel") else ""))


def parse_query(query: str) -> tuple[str, str | None, str | None]:
    """Parse a song query string. Return the song, artist and market."""
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

    return song, artist, market


def download_song(query: str, progress: Progress | None = None, parent: ActionsGroup | None = None) -> str | None:  # noqa: C901, PLR0912
    """Download a song with ID3 tags (title, artist, lyrics...). Return the path of the song or `None`."""
    install_traceback(show_locals=True)

    logger.info("Downloading '%s'", query)

    song, artist, market = parse_query(query)

    # Providers sorted by confidence
    metadata_actions: ActionsGroup[list[Song]] = ActionsGroup(
        "Fetching metadata...",
        [
            Action("iTunes", download_itunes),
            Action("YouTube Music", download_youtube_music),
            Action("MusicBrainz", download_musicbrainz),
            Action("Musixmatch", download_musixmatch),
            Action("LRCLIB", download_lrclib),
            Action("Deezer", download_deezer),
            Action("YouTube", download_youtube),
        ],
        expandable=True,
        no_task=True,
    )

    ytdl_action = ActionsGroup("Downloading...")
    add_tags_action = Action("Adding tags...")

    actions: ActionsGroup[list[Song]] = ActionsGroup(
        query,
        [
            metadata_actions,
            ytdl_action,
            add_tags_action,
        ],
        {metadata_actions: 3, ytdl_action: 2, add_tags_action: 1},
        progress=progress,
        expandable=True,
        calibrate=True,
    )
    actions.parent = parent
    metadata_actions(song, artist, market)

    # Display the results in order
    for action in metadata_actions:
        if action.error:
            print(f"Error when executing {action.description}:", file=sys.stderr)
            if logger.isEnabledFor(logging.INFO):
                get_console().print(
                    Traceback.from_exception(type(action.error), action.error, action.error.__traceback__)
                )
            else:
                print(f"{type(action.error).__name__}: {action.error}", file=sys.stderr)
        else:
            action.logs.handle_all()

    def get_best_songs(not_action: Action[list[Song]]) -> list[Song]:
        return [action.results[0] for action in metadata_actions if action != not_action and action and action.results]

    best_video = None

    # order the results
    for action in metadata_actions:
        action.results = order_results(action.description, get_best_songs(action), action.results)
        if action._description in {"YouTube", "YouTube Music"}:  # noqa: SLF001
            if action.results:
                best_video = best_video or cast("YoutubeSong", action.results[0])
        elif not action.results:
            action.results.append(Song.empty())

    if not best_video:
        logger.error("No videos available!")
        return None

    filename = download_youtube_dl(
        f"https://www.youtube.com/watch?v={urllib.parse.quote(best_video.youtube_video)}",
        ytdl_action,
    )

    title, artist, tags_list = add_tags(metadata_actions, filename)

    if artist and title:
        final_filename = sanitize_filename(f"{artist} - {title}.mp3")
        Path(filename).replace(final_filename)
    else:
        final_filename = filename
    logger.info("Final filename: %s", final_filename)

    if "USLT" in tags_list:
        Path(final_filename.rsplit(".", 1)[0] + ".lrc").write_text(tags_list["USLT"][0] + "\n", "utf-8")

    add_tags_action.completed = 1
    add_tags_action.total = 1

    logger.info("'%s' downloaded", query)

    return final_filename


def main() -> None:
    """Run the CLI."""
    parser = argparse.ArgumentParser(fromfile_prefix_chars="@")
    parser.add_argument("SONG", nargs="+", help="songs to download")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="number of songs to download in the same time",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="show more information")

    args = parser.parse_args()

    logging.root.setLevel(
        {
            0: logging.WARNING,
            1: logging.INFO,
            2: logging.DEBUG,
        }.get(args.verbose, logging.DEBUG)
    )

    mp_requests()

    if not args.SONG:
        return

    # If there is only one song, download it on the main thread
    with Progress(transient=True) as progress:
        if len(args.SONG) == 1:
            download_song(args.SONG[0], progress)
            return

        actions = ActionsGroup(
            "Downloading songs...",
            progress=progress,
            expandable=True,
            max_workers=args.max_workers,
        )
        for song in args.SONG:
            actions.add_action(Action(song, partial(download_song, song, parent=actions)))
        actions()


if __name__ == "__main__":
    main()
