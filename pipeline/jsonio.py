"""The few ways this pipeline reads and writes JSON."""

from __future__ import annotations

import json
from pathlib import Path


def canonical_json(value: object) -> str:
    """Compact JSON with sorted keys, so the same value always gives the same bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_ndjson(path: Path) -> list[dict]:
    """One object per non-blank line; an absent file reads as no records."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}
