"""The canonical county-collection context shared by import stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CountyImport:
    """One county collection and the source artifacts registered from it."""

    directory: Path
    slug: str
    source_artifacts: dict[str, str]
    repository_root: Path
