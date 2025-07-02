"""Utility functions to download a song video with `yt_dlp`."""

import datetime as dt
import logging
from typing import Any

from yt_dlp.postprocessor import (
    FFmpegExtractAudioPP,
    FFmpegMergerPP,
    FFmpegPostProcessor,
    MoveFilesAfterDownloadPP,
    PostProcessor,
)
from yt_dlp.YoutubeDL import YoutubeDL

from .display import Action, ActionsGroup
from .utils import Song, get, get_all_subclasses, locked
from .youtube import youtube_lock

logger = logging.getLogger(__name__)


def ponderate(action: Action[list]) -> float:
    """Return the ponderation for a given action based on its type."""
    pp_key = action.description

    if pp_key == "downloading":
        return 90

    pp = None
    for pp_to_try in get_all_subclasses(PostProcessor):
        if pp_to_try.pp_key() == pp_key:
            pp = pp_to_try

    if pp:
        if issubclass(pp, FFmpegMergerPP):
            return 6
        if issubclass(pp, FFmpegExtractAudioPP):
            return 3
        if issubclass(pp, FFmpegPostProcessor):
            return 2
        if issubclass(pp, MoveFilesAfterDownloadPP):
            return 0.5
    return 1


@locked(youtube_lock)
def download_youtube_dl(url: str, ytdl_action: ActionsGroup[list]) -> str:
    """Download a video with `yt_dlp`."""
    filename = ""
    info_dict = {}
    ytdl_action.description = "Downloading..."
    ytdl_action.ponderations = ponderate

    last_data = {}

    def fix_description() -> None:
        status = "Downloaded"
        for action in ytdl_action.actions:
            if action.completed != action.total:
                status = action._description + "..."  # noqa: SLF001
                break

        ytdl_action.description = status

    def get_action(name: str) -> Action[list]:
        for action in ytdl_action.actions:
            if action.description == name:
                return action

        # Create a new Action if not found
        action = Action(name, list)
        ytdl_action.add_action(action)
        return action

    def progress_hook(data: dict[str, Any]) -> None:
        nonlocal last_data
        last_data = {**data, "progress_action": ytdl_action}

        dl_action = get_action("Downloading")
        dl_action.completed = data.get("downloaded_bytes") or 0
        dl_action.total = data.get("total_bytes") or data.get("total_bytes_estimate") or 1
        fix_description()

        if data["status"] == "finished" and youtube_lock.locked():
            youtube_lock.release()

    def postprocessor_hook(data: dict[str, Any]) -> None:
        nonlocal filename, info_dict, ytdl_action
        info_dict = data["info_dict"]
        filename = info_dict.get("filepath") or filename

        pp_action = get_action(data["postprocessor"])
        pp_action.description = data["postprocessor"]
        pp_action.completed = 1 if data["status"] == "finished" else 0
        pp_action.total = 1
        fix_description()

    logger.info("Downloading YouTube video '%s'...", url)

    with YoutubeDL({
        "outtmpl": "%(id)s.%(ext)s",
        "format": "bestaudio",
        "retries": float("inf"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "logger": logger,
    }) as ydl:
        ydl.download([url])

    # add the metadata from the YouTube page
    song = Song(
        title=get(info_dict, "title", str),
        artists=[get(info_dict, "uploader", "channel", "uploader_id", "channel_id", str)],
        duration=get(info_dict, "duration", float),
        release_date=get(info_dict, "upload_date", dt.date.fromisoformat),
    )
    ytdl_action.actions[-1].results = [song]

    return filename
