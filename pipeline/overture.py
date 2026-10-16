"""Bridges and dams from Overture Maps for the four counties.

Overture Maps Foundation publishes open, versioned map data as GeoParquet on
S3; the `overturemaps` package reads it anonymously (no credentials or API
key). Only two classes of its `infrastructure` theme are kept: bridges
(impassable in a flood, this app's core theme) and dams (flood-control
relevant). The rest of the theme (power grid, barriers, parking, street
furniture, ...) is not flood-specific and would only clutter the map.

The query is a bounding box, which also covers a strip of Mexico: the border
follows the Rio Grande, so no rectangle can avoid it. The layers built from it
keep a feature only where it really touches a county.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapely
from net import already_have
from overturemaps import record_batch_reader
from paths import DOWNLOAD_CACHE

from rgv_flood.counties import RGV_BBOX

KEPT_CLASSES = ("bridge", "dam")
CACHE_FILE = DOWNLOAD_CACHE / "overture" / "bridges-and-dams.parquet"


def _download(dest: Path) -> None:
    """Stream the `infrastructure` theme for the RGV bounding box into `dest`,
    keeping only the bridge and dam rows."""
    reader = record_batch_reader("infrastructure", bbox=RGV_BBOX, stac=True)
    if reader is None:
        raise OSError("Overture returned no data for the RGV bounding box")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    kept = pa.array(KEPT_CLASSES)
    with pq.ParquetWriter(part, reader.schema) as writer:
        for batch in reader:
            writer.write_batch(batch.filter(pc.is_in(batch.column("class"), value_set=kept)))
    part.replace(dest)
    print(f"  [ok]   {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)


def bridges_and_dams(cache_file: Path = CACHE_FILE) -> Iterator[tuple[shapely.Geometry, dict]]:
    """Each bridge or dam in the bounding box as (geometry, Overture attributes)."""
    if not already_have(cache_file):
        _download(cache_file)
    table = pq.read_table(cache_file)
    geometries = shapely.from_wkb(table.column("geometry").to_pylist())
    attributes = table.drop_columns(["geometry", "bbox"]).to_pylist()
    yield from zip(geometries, attributes, strict=True)
