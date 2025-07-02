"""Create a standalone executable for the songs-dl CLI tool using PyInstaller."""

import sys
from pathlib import Path

from PyInstaller.__main__ import run  # noqa: PLC2701
from yt_dlp.extractor import gen_extractor_classes

BASE_PATH = Path(__file__).parent

exclusions = [
    "cffi",  # imported by Crypto
    "Crypto",  # imported by yt_dlp
    "Cryptodome",  # same thing
    "cryptography",  # same thing
    "matplotlib",  # imported by tqdm
    "numpy",  # same thing
    "pandas",  # same thing
    "statistics",  # imported by random
    *(extr._module for extr in gen_extractor_classes() if "youtube" not in extr._module),  # noqa: SLF001
]
exclusions_args = []
for excl in exclusions:
    exclusions_args.extend(("--exclude-module", excl))

system_suffix = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"

run([
    "--onefile",
    "--name",
    "songs-dl-" + system_suffix,
    *exclusions_args,
    str(BASE_PATH / "songs_dl/__main__.py"),
])
