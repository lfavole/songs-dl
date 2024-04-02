"""
Monkeypatch of the requests library to add a progress bar to each request.
"""

from requests.models import Response
from tqdm import tqdm


def mp_requests():
    if hasattr(Response.iter_content, "monkeypatched"):
        return

    def iter_content(self, *args, **kwargs):
        pb = tqdm(unit_scale=True, unit="B")
        if "Content-Length" in self.headers:
            pb.total = int(self.headers["Content-Length"])
        for e in Response._old_iter_content(self, *args, **kwargs):  # type: ignore
            pb.update(len(e))
            yield e
        pb.close()

    iter_content.monkeypatched = True

    Response._old_iter_content = Response.iter_content  # type: ignore
    Response.iter_content = iter_content
