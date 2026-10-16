"""The map page's first-load weight, before any layer is turned on.

Counts everything the browser downloads for the page itself: the HTML, every
stylesheet and script it references, every module those scripts import,
MapLibre's worker and the web fonts, each compressed as served. The basemap
is someone else's (OpenFreeMap) and not counted.
"""

import gzip
import re

from rgv_flood.assets import STATIC_ROOT

BUDGET_BYTES = 600_000
IMPORT = re.compile(r"""(?:import|from)\s*["']([^"']+\.m?js)["']""")


def _static_path(url: str):
    return STATIC_ROOT / url.split("?")[0].removeprefix("/static/")


def _modules(entry, seen):
    """A module and everything it statically imports, transitively."""
    if entry in seen or not entry.is_file():
        return
    seen.add(entry)
    for target in IMPORT.findall(entry.read_text(encoding="utf-8", errors="replace")):
        _modules((entry.parent / target).resolve(), seen)


def test_map_page_first_load_budget(api_client):
    html = api_client.get("/").text
    files = set()
    for url in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        path = _static_path(url)
        if path.suffix in (".js", ".mjs"):
            _modules(path.resolve(), files)
        else:
            files.add(path.resolve())
    files.add((STATIC_ROOT / "vendor/maplibre/maplibre-gl-worker.mjs").resolve())
    files |= {path.resolve() for path in (STATIC_ROOT / "fonts").glob("*.woff2")}

    # level 9: what the app's GZipMiddleware (and Caddy) serve
    sizes = {path.name: len(gzip.compress(path.read_bytes(), 9)) for path in files}
    total = len(gzip.compress(html.encode(), 9)) + sum(sizes.values())

    assert not [name for name in sizes if "plotly" in name]
    assert total <= BUDGET_BYTES, sorted(sizes.items(), key=lambda item: -item[1])[:5]
