import logging
from pprint import pformat
from threading import Lock
from time import time
from typing import TypedDict

import requests

from .utils import Picture, PictureProvider, Song, format_query, get, locked

logger = logging.getLogger(__name__)
spotify_lock = Lock()


class SpotifyAccessToken(TypedDict):
    """
    Spotify access token (on Spotify).
    """

    accessToken: str
    accessTokenExpirationTimestampMs: int


class AccessToken(TypedDict):
    """
    Spotify access token for the `get_access_token` function
    """

    token: str
    expiration: int


class SpotifyArtist(TypedDict):
    name: str


class SpotifyImage(TypedDict):
    width: int
    height: int
    url: str


class SpotifyAlbum(TypedDict):
    name: str
    images: list[SpotifyImage]


class SpotifyTrack(TypedDict):
    name: str
    artists: list[SpotifyArtist]
    album: SpotifyAlbum
    duration_ms: int


class SpotifyTracks(TypedDict):
    items: list[SpotifyTrack]


class SpotifyData(TypedDict):
    tracks: SpotifyTracks


ACCESS_TOKEN = ""
ACCESS_TOKEN_EXPIRATION = 0


def get_access_token():
    """
    Get the Spofity access token
    """
    global ACCESS_TOKEN, ACCESS_TOKEN_EXPIRATION
    # we don't need "global" statement (we edit the keys)
    if not ACCESS_TOKEN_EXPIRATION or ACCESS_TOKEN_EXPIRATION < time():
        logger.info("Getting Spotify access token...")
        req = locked(spotify_lock)(requests.get)("https://open.spotify.com/get_access_token")

        try:
            result = req.json()
            logger.debug("JSON decoding OK")
        except requests.JSONDecodeError as err:
            logger.debug("JSON decoding error: %s", err)
            return ""

        if not result["accessToken"]:
            logger.error("Can't get the Spotify access token!")
            return ""

        ACCESS_TOKEN_EXPIRATION = get(result, "accessTokenExpirationTimestampMs", int) or int(
            time() + 30 * 60
        )  # 30 minutes

        ACCESS_TOKEN = result["accessToken"]

    return ACCESS_TOKEN


class SpotifyPictureProvider(PictureProvider):
    """
    Picture provider for Spotify.
    """

    def get_sure_pictures(self, result):
        pictures = get(result, ("album", "images"), list)
        return [
            Picture(
                get(picture, "url", str),
                get(picture, "width", int),
                get(picture, "height", int),
            )
            for picture in pictures
        ]

    def get_url_for_size(self, size):
        return None  # the Spotify URLs are hash-based


def download_spotify(song: str, artist: str | None = None, market: str | None = None):
    """
    Fetch the Spotify search results.
    """
    access_token = get_access_token()
    if not access_token:
        logger.error("No access token: stop Spotify search")
        return []

    logger.info("Searching %s on Spotify...", format_query(song, artist, market))
    params = {
        "q": f"{song} {artist}" if artist else song,
        "type": "track",
    }
    if market:
        params["market"] = market
    req = locked(spotify_lock)(requests.get)(
        "https://api.spotify.com/v1/search",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        result = req.json()
        logger.debug("JSON decoding OK")
    except requests.exceptions.JSONDecodeError as err:
        # we skip Spotify
        logger.debug("JSON decoding error: %s", err)
        return []

    # result = validate_schema(SpotifyData, result)

    ret: list[Song] = []
    for element in result.get("tracks", {}).get("items", []):
        ret.append(
            Song(
                title=get(element, "name", str),
                artists=[get(artist, "name", str) for artist in element.get("artists", {})],
                album=get(element.get("album", {}), "name", str),
                duration=get(element, "duration_ms", int) / 1000,
                isrc=get(element, ("external_ids", "isrc"), str),
                picture=SpotifyPictureProvider(element),
                # TODO add other elements?
            )
        )

    logger.debug("Results:\n%s", pformat(ret))

    return ret
