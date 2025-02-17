# Songs downloader

Download songs on YouTube and add metadata from Deezer, iTunes and Spotify.

## Installation

To install the latest release from PyPI:

    # with pip
	pip install songs-dl

    # with uv
    uv tool install songs-dl

To install the latest changes:

	# with pip
    pip install git+https://github.com/lfavole/songs-dl.git

    # with uv
    uv tool install git+https://github.com/lfavole/songs-dl.git

## Examples

	songs-dl "Song name"
	songs-dl "Song 1" "Song 2" "Song 3"
	songs-dl @songs_list.txt

<details>
<summary>Publishing the release on PyPI (only for the admin!)</summary>

## Building (no more needed, done by GitHub Actions)

	uv sync --extra build
	uv build
	uv publish [--index testpypi]

## Bumping the version

	uv sync --extra dev
    uv run bump-my-version bump major | minor | patch
</details>
