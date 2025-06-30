import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from time import sleep, time

from .paths import get_app_data_path

logger = logging.getLogger(__name__)


@dataclass
class Token:
    """A single token sent by a provider."""
    token: str
    expiration: int = 0

    def __bool__(self):
        return self.token != ""

    @classmethod
    def from_json(cls, data):
        token = data["token"]
        try:
            expiration = int(data["expiration"])
        except ValueError:
            expiration = 0
        return cls(token, expiration)

    def to_json(self):
        return {
            "token": self.token,
            "expiration": self.expiration,
        }


Token.empty = Token("", 0)  # type: ignore

_locks = defaultdict(threading.RLock)


class _MetaAccessToken(type):
    @property
    def path(cls):
        path = get_app_data_path() / f"songs-dl/.{cls.name}_access_token"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def lock(cls):
        return _locks[cls]


class ProviderToken(metaclass=_MetaAccessToken):
    """A getter for a token of a provider."""
    name: str
    token = Token.empty
    cooldown_period = 5
    default_expiration = 600  # 10 minutes
    loaded = False

    @classmethod
    def real_get(cls) -> Token | None:
        """
        Try to get the token by making a single request.

        Return a `Token` or `None` if no token was provided by the server.
        """
        raise NotImplementedError

    @classmethod
    def get(cls, tries=3) -> str:
        """Return the access token."""
        # TODO lock
        if not cls.loaded:
            cls.load()

        while True:
            if cls.token.expiration and time() >= cls.token.expiration:
                cls.token = cls.real_get()
                cls.token.expiration = cls.token.expiration or time() + cls.default_expiration
                cls.save()

            if cls.token:
                return cls.token.token

            tries -= 1
            if tries <= 0:
                raise ValueError(f"Unable to get {cls.name} token")
            logger.info("Waiting %d seconds...", cls.cooldown_period)
            sleep(cls.cooldown_period)

    @classmethod
    def save(cls):
        """Save the token to its JSON file."""
        with cls.path.open("w") as f:
            json.dump(cls.token, f)

    @classmethod
    def load(cls):
        """Load the token from its JSON file."""
        if not cls.path.exists():
            return
        try:
            with cls.path.open() as f:
                cls.token = Token.from_json(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
