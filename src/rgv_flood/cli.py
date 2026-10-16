"""`uv run dev` and `uv run serve`: the same on Windows, macOS and Linux.

dev    fetch pinned front-end files if missing, rebuild the stylesheet whenever
       a template or script changes, and run the app with auto-reload.
serve  fetch, build the stylesheet once (minified), and run the app with
       several workers (RGV_WORKERS, default 4), as in production.
"""

from __future__ import annotations

import os
import subprocess

import uvicorn

from rgv_flood import assets, vendor

APP = "rgv_flood.app:create_app"


def dev() -> None:
    vendor.fetch_all()
    watcher = subprocess.Popen(assets.tailwind_command(minify=False, watch=True))
    try:
        uvicorn.run(APP, factory=True, reload=True, port=int(os.environ.get("PORT", "8000")))
    finally:
        watcher.terminate()


def serve() -> None:
    vendor.fetch_all()
    assets.build_css()
    uvicorn.run(
        APP, factory=True, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ.get("RGV_WORKERS", "4")), proxy_headers=True,
    )
