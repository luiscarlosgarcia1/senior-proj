"""The two pages: the map explorer ("/") and claims & rainfall by year ("/claims").

Templates hold structure only; every piece of data on a page comes from the
JSON API, fetched by the page's scripts. Pages are revalidated on every load
(`no-cache`); the assets they reference are versioned and cached for a year.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from rgv_flood import data_access
from rgv_flood.assets import asset_url
from rgv_flood.counties import COUNTIES, SHORT_NAMES
from rgv_flood.db import Db
from rgv_flood.i18n import load_catalog, t

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals.update(t=t, asset_url=asset_url, counties=COUNTIES, short_names=SHORT_NAMES)

# Runs before first paint so the page never flashes the wrong theme: the
# reader's saved choice, else their system setting. Its hash is allowed by the
# content-security policy (see app.py); no other inline script runs.
THEME_BOOTSTRAP = (
    "(function(){try{var t=localStorage.getItem('rgv-theme');"
    "if(t!=='light'&&t!=='dark')t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';"
    "document.documentElement.dataset.theme=t}catch(e){}})();"
)


def inline_script_hashes() -> list[str]:
    return ["sha256-" + base64.b64encode(hashlib.sha256(THEME_BOOTSTRAP.encode()).digest()).decode()]


def _built_label(db) -> str | None:
    stamp = data_access.built_at(db) if db.exists else None
    if not stamp:
        return None
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return t("footer.built", date=f"{when:%b} {when.day}, {when.year}")


def _render(request: Request, template: str, db, nav_active: str):
    response = templates.TemplateResponse(request, template, {
        "nav_active": nav_active,
        "theme_bootstrap": THEME_BOOTSTRAP,
        "catalog": load_catalog(),
        "built_label": _built_label(db),
        "data_ready": db.exists,
        "settings": request.app.state.settings,
    })
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/", include_in_schema=False)
def map_page(request: Request, db: Db):
    return _render(request, "site/map.html", db, "map")


@router.get("/claims", include_in_schema=False)
def claims_page(request: Request, db: Db):
    return _render(request, "site/claims.html", db, "claims")


@router.get("/analysis", include_in_schema=False)
def analysis_moved():
    return RedirectResponse("/claims", status_code=308)
