"""Adapt Hidalgo County's official Public Notice RSS feed into live signals."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from live_signals import IngestionResult, LiveSignal, LiveSignalStore, utc_timestamp

HIDALGO_PUBLIC_NOTICE_FEED = "https://www.hidalgocounty.us/RSSFeed.aspx?CID=Public-Notice-4&ModID=63"
HIDALGO_COUNTY_PUBLISHER = "Hidalgo County"


def ingest_hidalgo_public_notices(
    store: LiveSignalStore, feed_xml: str | bytes, *, retrieved_at: datetime
) -> IngestionResult:
    """Persist the current official Public Notice feed snapshot.

    The county's RSS feed is a county-jurisdiction source. Its entries are
    official notices, not mapped incidents: no location or closure status is
    inferred from their text.
    """
    return store.ingest(HIDALGO_PUBLIC_NOTICE_FEED, _signals_from_feed(feed_xml), retrieved_at=retrieved_at)


def _local_name(element: ElementTree.Element) -> str:
    """The tag without its XML namespace: '{http://www.georss.org/georss}point' -> 'point'."""
    return element.tag.rsplit("}", 1)[-1]


def _signals_from_feed(feed_xml: str | bytes) -> Iterable[LiveSignal]:
    root = ElementTree.fromstring(feed_xml)
    for item in root.findall(".//item"):
        values = {_local_name(child): (child.text or "").strip() for child in item}
        guid = values.get("guid", "")
        title = values.get("title", "")
        link = values.get("link", "")
        published_at = _rss_timestamp(values.get("pubDate"))
        if not all((guid, title, link, published_at)):
            continue
        geometry = _georss_geometry(item)
        yield LiveSignal(
            source=HIDALGO_PUBLIC_NOTICE_FEED,
            native_id=guid,
            provenance="official",
            source_url=link,
            source_publisher=HIDALGO_COUNTY_PUBLISHER,
            source_channel="rss",
            summary=title,
            source_attributes={
                "feed_url": HIDALGO_PUBLIC_NOTICE_FEED,
                "guid": guid,
                "title": title,
                "description": values.get("description", ""),
            },
            county_slugs=("hidalgo",),
            inclusion_basis="feed_jurisdiction",
            source_geometry=geometry,
            geometry_absence_reason=None if geometry is not None else "The RSS item supplies no geometry.",
            published_at=published_at,
        )


def _rss_timestamp(value: str | None) -> str | None:
    return utc_timestamp(parsedate_to_datetime(value)) if value else None


def _georss_geometry(item: ElementTree.Element) -> dict | None:
    """A GeoRSS point or polygon as GeoJSON. GeoRSS lists latitude first; GeoJSON, longitude."""
    for child in item:
        tag = _local_name(child)
        coordinates = _georss_coordinates(child.text)
        if tag == "point" and len(coordinates) == 2:
            latitude, longitude = coordinates
            return {"type": "Point", "coordinates": [longitude, latitude]}
        if tag == "polygon" and len(coordinates) >= 6 and len(coordinates) % 2 == 0:
            ring = [
                [longitude, latitude]
                for latitude, longitude in zip(coordinates[::2], coordinates[1::2], strict=True)
            ]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            return {"type": "Polygon", "coordinates": [ring]}
    return None


def _georss_coordinates(value: str | None) -> list[float]:
    try:
        return [float(coordinate) for coordinate in (value or "").split()]
    except ValueError:
        return []
