"""HTTP helpers shared by the data-fetching steps."""

from __future__ import annotations

import http.client
import json
import shutil
import time
import urllib.request
from pathlib import Path

USER_AGENT = {"User-Agent": "RGV-Flood-Impact-Visualizer/1.0 (student research)"}
# URLError, HTTPError and TimeoutError are all OSError subclasses.
NETWORK_ERRORS = (OSError, http.client.HTTPException)


def already_have(path: Path, *, force: bool = False) -> bool:
    """True (and says so) if `path` is a non-empty file that needn't be refetched."""
    present = path.exists() and path.stat().st_size > 0 and not force
    if present:
        print(f"  [skip] {path.name} already present", flush=True)
    return present


def get_text(url: str, *, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def get_json(
    url: str, *, body: dict | None = None, timeout: int = 90, attempts: int = 1
) -> dict | list:
    """GET JSON (POST when `body` is given), backing off and retrying on network errors.

    Some public APIs (OpenFEMA especially) answer 503 under load; retrying beats
    losing a long paged download.
    """
    headers = dict(USER_AGENT)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (*NETWORK_ERRORS, json.JSONDecodeError) as error:
            if attempt == attempts:
                raise
            wait = min(10 * 2 ** (attempt - 1), 120)
            print(f"    retry {attempt}/{attempts} after {error!r}; waiting {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def download(
    url: str, dest: Path, *, required: bool = True, force: bool = False, attempts: int = 1
) -> bool:
    """Stream `url` to `dest` via a .part file, so an interrupted run never leaves
    a truncated file that later looks finished. Retries with backoff on network
    errors; returns False (instead of raising) when `required` is False."""
    if already_have(dest, force=force):
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers=USER_AGENT)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=300) as response, part.open("wb") as out:
                shutil.copyfileobj(response, out)
            break
        except NETWORK_ERRORS as error:
            part.unlink(missing_ok=True)
            if attempt < attempts:
                wait = min(10 * 2 ** (attempt - 1), 120)
                print(f"    retry {attempt}/{attempts} after {error!r}; waiting {wait}s", flush=True)
                time.sleep(wait)
            elif required:
                raise
            else:
                print(f"  [fail] {dest.name}: {error}", flush=True)
                return False
    part.replace(dest)
    print(f"  [ok]   {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return True
