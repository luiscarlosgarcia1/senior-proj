"""Validation helpers for canonical county record sets."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from jsonschema import Draft202012Validator

from .errors import BuildError


def iter_ndjson(path: Path, repository_root: Path) -> Iterator[tuple[int, dict]]:
    """Yield object records from an NDJSON artifact with useful input context."""
    shown_path = path.relative_to(repository_root)
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise BuildError(f"{shown_path}:{line_number}: invalid JSON") from error
        if not isinstance(value, dict):
            raise BuildError(f"{shown_path}:{line_number}: record must be an object")
        yield line_number, value


def record_validator(schema: dict) -> Draft202012Validator:
    """Build a record set's validator once; it is reused for every record in the set."""
    return Draft202012Validator(schema)


def validate_record(record: dict, validator: Draft202012Validator, context: str) -> None:
    """Raise the first JSON Schema violation using the record's source context."""
    errors = sorted(validator.iter_errors(record), key=str)
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "record"
        raise BuildError(f"{context}: {location}: {error.message}")
