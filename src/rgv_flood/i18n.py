"""Interface text. Every string the pages show lives in i18n/<lang>.json, so a
Spanish catalog can be added later without touching templates or code."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).parent / "i18n"


@lru_cache
def load_catalog(lang: str = "en") -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def t(key: str, lang: str = "en", **params) -> str:
    """The message for `key`, with `{name}` placeholders filled. An unknown key
    raises KeyError, so a missing string fails loudly in tests."""
    message = load_catalog(lang)[key]
    return message.format(**params) if params else message
