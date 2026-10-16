"""Front-end assets: vendored third-party files, versioned URLs, the Tailwind build."""

import hashlib
import json
import mimetypes

import pytest

from rgv_flood import assets, vendor


def _lock(tmp_path, content: bytes, *, sha256: str | None = None):
    source = tmp_path / "upstream" / "lib.js"
    source.parent.mkdir()
    source.write_bytes(content)
    lock = tmp_path / "vendor.lock.json"
    lock.write_text(json.dumps({"files": [{
        "name": "lib", "url": source.as_uri(), "path": "vendor/lib/lib.js",
        "sha256": sha256 or hashlib.sha256(content).hexdigest(),
    }]}))
    return lock, source


def test_vendor_downloads_and_verifies(tmp_path):
    lock, _ = _lock(tmp_path, b"console.log(1)")

    (written,) = vendor.fetch_all(lock, tmp_path / "static")

    assert written == tmp_path / "static" / "vendor" / "lib" / "lib.js"
    assert written.read_bytes() == b"console.log(1)"


def test_vendor_rejects_hash_mismatch(tmp_path):
    lock, _ = _lock(tmp_path, b"tampered", sha256="0" * 64)

    with pytest.raises(vendor.HashMismatch, match="lib"):
        vendor.fetch_all(lock, tmp_path / "static")

    assert not (tmp_path / "static" / "vendor" / "lib" / "lib.js").exists()


def test_vendor_skips_matching_file(tmp_path):
    lock, source = _lock(tmp_path, b"console.log(1)")
    vendor.fetch_all(lock, tmp_path / "static")
    source.unlink()  # a second run must not need the network

    vendor.fetch_all(lock, tmp_path / "static")


def test_the_real_lock_file_pins_exact_versions():
    entries = json.loads(vendor.LOCK_FILE.read_text())["files"]

    assert {e["name"] for e in entries} >= {"maplibre-gl", "maplibre-gl-worker",
                                            "maplibre-gl-css", "alpine-csp", "plotly-basic"}
    for entry in entries:
        assert "@" in entry["url"] and "latest" not in entry["url"] and ".x" not in entry["url"], entry["name"]
        assert len(entry["sha256"]) == 64, entry["name"]


def test_asset_url_versions_by_content(tmp_path, monkeypatch):
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "app.css").write_text("body{}")
    monkeypatch.setattr(assets, "STATIC_ROOT", tmp_path)
    assets.asset_url.cache_clear()

    url = assets.asset_url("css/app.css")

    assert url == f"/static/css/app.css?v={hashlib.sha256(b'body{}').hexdigest()[:10]}"


def test_versioned_static_is_immutable(api_client):
    versioned = api_client.get("/static/basemap/offline.json?v=abc")
    plain = api_client.get("/static/basemap/offline.json")

    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert plain.headers["cache-control"] == "no-cache"


def test_javascript_modules_have_a_javascript_type():
    import rgv_flood.app  # noqa: F401  registers the types

    assert mimetypes.guess_type("x.mjs")[0] == "text/javascript"
    assert mimetypes.guess_type("x.js")[0] == "text/javascript"


def test_offline_style_is_valid_json():
    style = json.loads((assets.STATIC_ROOT / "basemap" / "offline.json").read_text())

    assert style["version"] == 8
    assert [layer["type"] for layer in style["layers"]] == ["background"]


def test_tailwind_build_contains_tokens(tmp_path):
    output = tmp_path / "app.css"

    assets.build_css(output, minify=False)

    css = output.read_text()
    assert "--brand" in css
    assert ".cb" in css
    assert "@font-face" in css


def test_build_output_does_not_overwrite_a_tracked_file():
    assert assets.CSS_OUTPUT.name == "site.css"


def test_fonts_are_public_sans():
    css = (assets.STATIC_ROOT / "css" / "input.css").read_text(encoding="utf-8")
    entries = json.loads(vendor.LOCK_FILE.read_text())["files"]

    assert '"Public Sans"' in css
    assert "IBM Plex" not in css
    assert {e["name"] for e in entries if "font" in e["path"]} == {"public-sans-400", "public-sans-500", "public-sans-600"}
