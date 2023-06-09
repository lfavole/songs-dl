# Songs downloader

Download songs on YouTube and add metadata from Deezer, iTunes and Spotify.

## Examples

	songs-dl "Song name"
	songs-dl "Song 1" "Song 2" "Song 3"
	songs-dl @songs_list.txt

## Building

	python -m install -e .[build]
	python -m build
	twine check dist/*
	twine upload dist/* [--repository testpypi]

## Bumping the version

	python -m install -e .[dev]
    bumpver update
