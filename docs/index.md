# Songs downloader

Download songs on [YouTube :simple-youtube:{ .youtube }](https://youtube.com){:target="_blank"}
and add metadata from
[Deezer :fontawesome-brands-deezer:{ .deezer }](https://deezer.com){:target="_blank"},
[iTunes ![iTunes icon](https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/ITunes_logo.svg/438px-ITunes_logo.svg.png){ .twemoji .itunes }](https://apple.com/itunes){:target="_blank"},
[Spotify :simple-spotify:{ .spotify }](https://spotify.com){:target="_blank"},
and [Musixmatch ![Musixmatch icon](https://upload.wikimedia.org/wikipedia/commons/e/e3/Musixmatch_logo_icon_only.svg){ .twemoji .musixmatch }](https://musixmatch.com){:target="_blank"}.

!!! warning "[This program respects copyright](disclaimer.md)"

## Installation

To install the latest release from PyPI ([see build](https://github.com/lfavole/songs-dl/releases/latest)):

	pip install songs-dl

To install the latest changes `{!.commit.md!}` ([see build](latest-build.md)):

	pip install git+https://github.com/lfavole/songs-dl.git

## Examples

	songs-dl "Song name"
	songs-dl "Song 1" "Song 2" "Song 3"
	songs-dl @songs_list.txt
