# Songs downloader

Download songs on YouTube and add metadata from Deezer, iTunes and Spotify.

## Installation

To install the latest release from PyPI:

	pip install songs-dl

To install the latest changes:

	pip install git+https://github.com/lfavole/songs-dl.git

## Examples

	songs-dl "Song name"
	songs-dl "Song 1" "Song 2" "Song 3"
	songs-dl @songs_list.txt

<details>
<summary>Publishing the release on PyPI (only for the admin!)</summary>

## Building

	python -m install -e .[build]
	python -m build
	twine check dist/*
	twine upload dist/* [--repository testpypi]

## Bumping the version

	python -m install -e .[dev]
    bumpver update
</details>
