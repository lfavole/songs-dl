import datetime as dt
import logging

from yt_dlp.YoutubeDL import YoutubeDL

from .utils import Song, get, locked
from .youtube import youtube_lock

logger = logging.getLogger(__name__)


@locked(youtube_lock)
def download_youtube_dl(url: str):
    """
    Download a video with `yt_dlp`.
    """
    filename = ""
    info_dict = {}

    def progress_hook(data):
        nonlocal filename, info_dict
        if data["status"] == "finished":
            filename = data["filename"]
            info_dict = data["info_dict"]
            if youtube_lock.locked():
                youtube_lock.release()

    logger.info("Downloading YouTube video '%s'...", url)

    with YoutubeDL({
        "outtmpl": "%(title)s.%(ext)s",
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
    }) as ydl:
        ydl.download([url])

    return filename[: -len(filename.rsplit(".", maxsplit=1)[-1])] + "mp3", Song(
        title=get(info_dict, "title", str),
        artists=[get(info_dict, "uploader", "channel", "uploader_id", "channel_id", str)],
        duration=get(info_dict, "duration", float),
        release_date=get(info_dict, "upload_date", dt.date.fromisoformat),
    )
