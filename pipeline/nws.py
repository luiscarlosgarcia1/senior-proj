"""Ingest active National Weather Service alerts without inventing geography.

NWS alert geocodes make the county claim used to include an alert explicit.
The GeoJSON geometry remains the only map geometry: alerts that omit it are
stored as attributed official notices, never converted to local pins or areas.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from urllib.request import Request, urlopen

from live_signals import IngestionResult, LiveSignal, LiveSignalStore

NWS_ACTIVE_ALERTS_URL = "https://api.weather.gov/alerts/active?area=TX"
NWS_COUNTY_CODES = {
    "cameron": {"TXC061", "048061"},
    "hidalgo": {"TXC215", "048215"},
    "starr": {"TXC427", "048427"},
    "willacy": {"TXC489", "048489"},
}
NWS_PUBLISHER = "National Weather Service"

AlertFetcher = Callable[[], Mapping[str, object]]


def fetch_nws_active_alerts() -> Mapping[str, object]:
    """Retrieve NWS's active Texas-alert GeoJSON collection."""
    request = Request(
        NWS_ACTIVE_ALERTS_URL,
        headers={
            "Accept": "application/geo+json",
            "User-Agent": "RGV-Flood-Impact-Visualizer/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:  # nosec B310 -- public NWS API
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise TypeError("NWS returned a non-object alert collection")
    return payload


def ingest_nws_active_alerts(
    store: LiveSignalStore,
    payload: Mapping[str, object],
    *,
    retrieved_at: datetime,
) -> IngestionResult:
    """Persist a complete, source-scoped active-alert snapshot.

    Invalid responses are recorded as incomplete so they cannot terminalize a
    prior alert. Identity remains NWS's CAP alert identifier and lifecycle
    reconciliation stays isolated to the NWS source.
    """
    try:
        features = payload["features"]
        if not isinstance(features, list):
            raise TypeError("NWS alert collection has no feature list")
        signals = []
        for feature in features:
            if not isinstance(feature, dict):
                raise TypeError("NWS alert feature is not an object")
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("NWS alert lacks properties")
            # Texas-wide responses contain many out-of-region alerts.  Their
            # own county codes are the sole scope decision; they are not an
            # error and must not make the RGV snapshot incomplete.
            if not _claimed_counties(properties):
                continue
            signals.append(_signal(feature))
    except (KeyError, TypeError, ValueError):
        return store.ingest(
            NWS_ACTIVE_ALERTS_URL, [], retrieved_at=retrieved_at, complete=False
        )
    return store.ingest(NWS_ACTIVE_ALERTS_URL, signals, retrieved_at=retrieved_at)


def run_nws_active_alert_ingestion(
    store: LiveSignalStore,
    *,
    fetch_alerts: AlertFetcher = fetch_nws_active_alerts,
    retrieved_at: datetime,
) -> IngestionResult:
    """Fetch and persist one snapshot, preserving safety on network failure."""
    try:
        return ingest_nws_active_alerts(store, fetch_alerts(), retrieved_at=retrieved_at)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return store.ingest(
            NWS_ACTIVE_ALERTS_URL, [], retrieved_at=retrieved_at, complete=False
        )


def _signal(feature: object) -> LiveSignal:
    if not isinstance(feature, dict):
        raise TypeError("NWS alert feature is not an object")
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise TypeError("NWS alert lacks properties")
    counties = _claimed_counties(properties)
    if not counties:
        raise ValueError("NWS alert lacks an RGV county claim")
    native_id = properties.get("id") or feature.get("id")
    if not isinstance(native_id, str) or not native_id:
        raise ValueError("NWS alert lacks its source identity")
    source_url = properties.get("@id") or feature.get("id")
    if not isinstance(source_url, str) or not source_url:
        raise ValueError("NWS alert lacks a source URL")
    geometry = feature.get("geometry")
    if geometry is not None and not isinstance(geometry, dict):
        raise TypeError("NWS alert geometry is not GeoJSON")
    event = properties.get("event")
    headline = properties.get("headline")
    summary = headline if isinstance(headline, str) and headline else event
    if not isinstance(summary, str) or not summary:
        raise ValueError("NWS alert lacks a source summary")
    publisher = properties.get("senderName")
    return LiveSignal(
        source=NWS_ACTIVE_ALERTS_URL,
        native_id=native_id,
        provenance="official",
        source_url=source_url,
        source_publisher=publisher if isinstance(publisher, str) and publisher else NWS_PUBLISHER,
        source_channel="api",
        summary=summary,
        source_attributes={"raw": properties, "nws_feature_id": feature.get("id")},
        county_slugs=counties,
        inclusion_basis="source_county_claim",
        source_geometry=geometry,
        geometry_absence_reason=("The NWS alert supplies no geometry." if geometry is None else None),
        published_at=_text(properties.get("sent")),
        effective_at=_text(properties.get("effective")) or _text(properties.get("onset")),
        updated_at=_text(properties.get("updated")),
        expires_at=_text(properties.get("ends")) or _text(properties.get("expires")),
    )


def _claimed_counties(properties: Mapping[str, object]) -> tuple[str, ...]:
    geocode = properties.get("geocode")
    if not isinstance(geocode, dict):
        return ()
    codes = {
        str(code).upper()
        for key in ("UGC", "SAME")
        for code in (geocode.get(key) if isinstance(geocode.get(key), list) else [])
    }
    return tuple(slug for slug, known_codes in NWS_COUNTY_CODES.items() if codes & known_codes)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
