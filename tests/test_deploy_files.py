"""Deployment files: Docker image, Compose with Caddy, GitHub Actions."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_compose_is_valid_yaml():
    compose = _yaml("deploy/compose.yaml")

    assert set(compose["services"]) == {"app", "caddy"}
    assert compose["services"]["caddy"]["ports"][:2] == ["80:80", "443:443"]
    assert compose["services"]["app"]["restart"] == "unless-stopped"


def test_caddy_proxies_to_the_app():
    caddyfile = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")

    assert "{$RGV_DOMAIN}" in caddyfile
    assert "reverse_proxy app:8000" in caddyfile
    assert "encode zstd gzip" in caddyfile


def test_workflows_parse_and_schedule_monthly():
    ci = _yaml(".github/workflows/ci.yml")
    release = _yaml(".github/workflows/release.yml")
    # PyYAML reads the key `on` as True
    release_triggers = release.get("on", release.get(True))

    assert "test" in ci["jobs"]
    assert release_triggers["schedule"] == [{"cron": "0 9 1 * *"}]
    assert "workflow_dispatch" in release_triggers


def test_dockerfile_runs_as_non_root_and_has_healthcheck():
    dockerfile = (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "rgv_flood.app:create_app" in dockerfile
    for module in ("run_nws.py", "run_drivetexas.py", "run_hidalgo_rss.py", "live_signals.py", "database.py"):
        assert module in dockerfile, module


def test_dockerignore_keeps_secrets_and_caches_out():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()

    assert {".git", ".venv", "tmp", "data/ml", ".superpowers"} <= set(ignored)
