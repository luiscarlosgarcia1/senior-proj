"""Third-party front-end files (MapLibre, Alpine, Plotly, fonts), pinned.

The app serves its own copies so every page loads from one origin under a
strict content-security policy, and a CDN outage can't break it. Each file is
listed in vendor.lock.json with an exact version in its URL and its SHA-256;
a download that doesn't match is deleted and the run fails.

    uv run python scripts/vendor.py            fetch whatever is missing
    uv run python scripts/vendor.py --update   re-hash after changing versions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

PACKAGE = Path(__file__).parent
LOCK_FILE = PACKAGE / "vendor.lock.json"
STATIC_ROOT = PACKAGE / "static"
USER_AGENT = {"User-Agent": "RGV-Flood-Impact-Visualizer/1.0 (vendor script)"}


class HashMismatch(Exception):
    """A downloaded file isn't the one the lock file pinned."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        dest.write_bytes(response.read())


def fetch_all(lock: Path = LOCK_FILE, static_root: Path = STATIC_ROOT, *, force: bool = False) -> list[Path]:
    """Make every locked file present and verified under `static_root`."""
    written = []
    for entry in json.loads(Path(lock).read_text(encoding="utf-8"))["files"]:
        dest = Path(static_root) / entry["path"]
        if not force and dest.is_file() and _sha256(dest) == entry["sha256"]:
            written.append(dest)
            continue
        _download(entry["url"], dest)
        if _sha256(dest) != entry["sha256"]:
            dest.unlink()
            raise HashMismatch(f"{entry['name']}: {entry['url']} does not match its pinned SHA-256")
        written.append(dest)
    return written


def update_hashes(lock: Path = LOCK_FILE, static_root: Path = STATIC_ROOT) -> None:
    """Download every file again and write its hash into the lock file."""
    data = json.loads(Path(lock).read_text(encoding="utf-8"))
    for entry in data["files"]:
        dest = Path(static_root) / entry["path"]
        _download(entry["url"], dest)
        entry["sha256"] = _sha256(dest)
    Path(lock).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="re-download and re-hash every file")
    args = parser.parse_args(argv)
    if args.update:
        update_hashes()
    for path in fetch_all():
        print("ok", path.relative_to(STATIC_ROOT))
