"""Acquire complete DriveTexas road-condition snapshots without adding inference.

DriveTexas publishes current TxDOT-maintained road conditions as two public
FeatureServer layers.  Their source geometry, attributes, and snapshot-local
``OBJECTID`` are preserved verbatim enough to explain a map feature; no local
road coverage, status, severity, update time, or geometry is invented here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from live_signals import COUNTY_SLUGS, IngestionResult, LiveSignal, LiveSignalStore
from shapely.geometry import shape

DRIVE_TEXAS_PUBLISHER = "Texas Department of Transportation (TxDOT)"
DRIVE_TEXAS_SERVICE = "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/ArcGIS/rest/services"
DRIVE_TEXAS_COUNTY_CODES = {"cameron": 31, "hidalgo": 108, "starr": 214, "willacy": 245}
CONDITION_TYPES = {
    "A": "Accident", "C": "Construction", "D": "Damage", "F": "Flooding",
    "I": "Ice/snow", "O": "Other", "X": "Evacuation lane", "Y": "Contra flow", "Z": "Closed",
}


@dataclass(frozen=True)
class DriveTexasLayer:
    key: str
    endpoint: str
    page_size: int


DRIVE_TEXAS_LAYERS = (
    DriveTexasLayer("points", f"{DRIVE_TEXAS_SERVICE}/DriveTexas_Points/FeatureServer/0", 5000),
    DriveTexasLayer("lines", f"{DRIVE_TEXAS_SERVICE}/DriveTexas_Lines/FeatureServer/0", 2000),
)

PageFetcher = Callable[[DriveTexasLayer, int], Mapping[str, object]]


def drivetexas_county_where() -> str:
    """Return the sole approved server-side four-county scope filter."""
    return "TXDOT_COUNTY_NBR IN (" + ",".join(str(DRIVE_TEXAS_COUNTY_CODES[slug]) for slug in sorted(COUNTY_SLUGS)) + ")"


def ingest_drivetexas_snapshot(
    store: LiveSignalStore,
    county_boundaries: Mapping[str, Mapping[str, object]],
    *,
    fetch_page: PageFetcher,
    retrieved_at: datetime,
) -> IngestionResult:
    """Fetch both complete layers and reconcile each only after its full run.

    A request, payload, or pagination failure returns no changes for that layer,
    so partial upstream data can never close an existing live observation.
    """
    total = IngestionResult(0, 0, 0)
    for layer in DRIVE_TEXAS_LAYERS:
        try:
            features = list(_complete_snapshot(layer, fetch_page))
            signals = list(_signals(layer, features, county_boundaries))
        except (OSError, ValueError, KeyError, TypeError):
            store.ingest(f"drivetexas:{layer.key}", [], retrieved_at=retrieved_at, complete=False)
            continue
        result = store.ingest(
            f"drivetexas:{layer.key}", signals, retrieved_at=retrieved_at, reconcile=True
        )
        total = IngestionResult(
            total.inserted + result.inserted,
            total.updated + result.updated,
            total.terminalized + result.terminalized,
        )
    return total


def fetch_drivetexas_page(layer: DriveTexasLayer, offset: int) -> Mapping[str, object]:
    """Request one stable-OBJECTID GeoJSON page from the approved public layer."""
    query = urlencode(
        {
            "where": drivetexas_county_where(),
            "outFields": "*",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": layer.page_size,
            "orderByFields": "OBJECTID ASC",
            "returnGeometry": "true",
        }
    )
    request = Request(
        f"{layer.endpoint}/query?{query}",
        headers={"User-Agent": "RGV-Flood-Impact-Visualizer/1.0"},
    )
    with urlopen(request, timeout=30) as response:  # nosec B310 -- approved public source
        import json

        return json.load(response)


def _complete_snapshot(layer: DriveTexasLayer, fetch_page: PageFetcher) -> Iterable[Mapping[str, object]]:
    offset = 0
    while True:
        page = fetch_page(layer, offset)
        if "error" in page:
            raise OSError(f"DriveTexas {layer.key} returned an ArcGIS error")
        features = page.get("features")
        if not isinstance(features, list):
            raise TypeError("DriveTexas page has no feature list")
        yield from features
        exceeded = page.get("exceededTransferLimit", False)
        if not exceeded:
            return
        if not features:
            raise ValueError("DriveTexas page claims more results but is empty")
        offset += len(features)


def _signals(
    layer: DriveTexasLayer,
    features: Iterable[Mapping[str, object]],
    county_boundaries: Mapping[str, Mapping[str, object]],
) -> Iterable[LiveSignal]:
    boundaries = {slug: shape(geometry) for slug, geometry in county_boundaries.items()}
    for feature in features:
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise TypeError("DriveTexas feature lacks source geometry or attributes")
        object_id = properties.get("OBJECTID")
        if object_id is None:
            raise ValueError("DriveTexas feature lacks OBJECTID")
        try:
            source_geometry = shape(geometry)
        except (TypeError, ValueError):
            raise ValueError("DriveTexas feature has invalid source geometry") from None
        if source_geometry.is_empty or not source_geometry.is_valid:
            raise ValueError("DriveTexas feature has empty or invalid source geometry")
        counties = tuple(slug for slug, boundary in boundaries.items() if source_geometry.intersects(boundary))
        if not counties:
            continue
        condition_code = str(properties.get("CNSTRNT_TYPE_CD") or "")
        summary = str(properties.get("COND_DESC") or properties.get("COMMENTS") or condition_code or "Road condition")
        native_id = str(object_id)
        yield LiveSignal(
            source=f"drivetexas:{layer.key}",
            native_id=native_id,
            provenance="official",
            source_url=f"{layer.endpoint}/{native_id}",
            source_publisher=DRIVE_TEXAS_PUBLISHER,
            source_channel="public-feature-server",
            summary=summary,
            source_attributes={
                "layer": layer.key,
                "snapshot_identity": {"layer": layer.key, "OBJECTID": object_id},
                "condition_type_code": condition_code,
                "condition_type_label": CONDITION_TYPES.get(condition_code),
                "raw": properties,
            },
            county_slugs=counties,
            inclusion_basis="source_geometry_intersection",
            source_geometry=geometry,
            effective_at=_arcgis_timestamp(properties.get("COND_START_TS")),
            expires_at=_arcgis_timestamp(properties.get("COND_END_TS")),
        )


def _arcgis_timestamp(value: object) -> str | None:
    """Keep nullable ArcGIS epoch values as supplied scheduled/effective bounds."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None
