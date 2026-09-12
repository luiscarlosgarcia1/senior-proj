"""Validation helpers for canonical county record sets."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from jsonschema import Draft202012Validator

from .errors import BuildError


def iter_ndjson(path: Path, repository_root: Path) -> Iterator[tuple[int, dict]]:
    """Yield object records from an NDJSON artifact with useful input context."""
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise BuildError(
                f"{path.relative_to(repository_root)}:{line_number}: invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise BuildError(
                f"{path.relative_to(repository_root)}:{line_number}: record must be an object"
            )
        yield line_number, value


def validate_record(record: dict, schema: dict, context: str) -> None:
    """Raise the first JSON Schema violation using the record's source context."""
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=str)
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "record"
        raise BuildError(f"{context}: {location}: {error.message}")
