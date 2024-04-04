import os
import re
from pathlib import Path

url = os.getenv("READTHEDOCS_CANONICAL_URL")
mkdocs_yml = Path("mkdocs.yml")
data = mkdocs_yml.read_text("utf-8")

print(f"Replacing site_url by {url}")
data = re.sub(r"(?m)^site_url: .*$", f"site_url: {url}", data)

mkdocs_yml.write_text(data, "utf-8")
