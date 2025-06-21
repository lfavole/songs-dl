"""Copy the latest built files in the `dist` directory into the docs."""

import shutil
import subprocess as sp  # noqa: S404
from pathlib import Path

import songs_dl

SIZE_SCALE = 1024.0


# https://stackoverflow.com/a/1094933
def sizeof_fmt(num: float, suffix: str = "B") -> str:
    """Return a human formatted file size with the given suffix."""
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < SIZE_SCALE:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


current_build = sp.check_output(["git", "rev-parse", "--short", "HEAD"], text=True)  # noqa: S603, S607
print(f"Current build: {current_build}")

docs = Path(__file__).parent / "docs"

(docs / ".commit.md").write_text(current_build, encoding="utf-8")

latest_build_folder = docs / "latest-build"
latest_build_folder.mkdir(exist_ok=True)
print(f"Latest build folder: {latest_build_folder}")

latest_build_text = """\
File | Size
---- | ----
"""

version = songs_dl.__version__

for old_file in (Path(__file__).parent / "dist").iterdir():
    print(f"Copying {old_file.name} to latest-build")
    file = Path(shutil.copy(old_file, latest_build_folder))
    if f"-{version}" in file.name:
        file = file.rename(file.parent / file.name.replace(f"-{version}", ""))
    fname = file.name
    size_formatted = sizeof_fmt(file.stat().st_size)
    latest_build_text += f"[{fname}](latest-build/{fname}) | {size_formatted}\n"

print("Writing .latest-build.md")
(docs / ".latest-build.md").write_text(latest_build_text, encoding="utf-8")
