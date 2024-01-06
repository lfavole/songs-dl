from pathlib import Path

from PyInstaller.__main__ import run
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
    *(extr._module for extr in gen_extractor_classes() if "youtube" not in extr._module),
]
exclusions_args = []
for excl in exclusions:
    exclusions_args.append("--exclude-module")
    exclusions_args.append(excl)

run(
    [
        "--onefile",
        "--name",
        "songs-dl",
        *exclusions_args,
        str(BASE_PATH / "songs_dl/__main__.py"),
    ]
)
