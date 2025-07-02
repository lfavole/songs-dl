"""Monkey-patch of the requests library to add a progress bar to each request."""

from collections.abc import Generator
from typing import Any

from requests.models import Response
from tqdm import tqdm


def mp_requests() -> None:
    """Monkey-patch the `Response.iter_content` method."""
    if hasattr(Response.iter_content, "monkeypatched") or True:
        return

    def iter_content(self: Response, *args, **kwargs) -> Generator[Any, None, None]:
        pb = tqdm(unit_scale=True, unit="B")
        if "Content-Length" in self.headers:
            pb.total = int(self.headers["Content-Length"])
        for e in old_iter_content(self, *args, **kwargs):
            pb.update(len(e))
            yield e
        pb.close()

    iter_content.monkeypatched = True

    old_iter_content = Response.iter_content
    Response.iter_content = iter_content
