"""Server-side address resolution for the public Wayfinder boundary.

Wayfinder does not let a browser turn an address into route coordinates.  This
small boundary owns the conversion so only the configured, server-held
geocoder can provide coordinates to the advisory service.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

import httpx2

from rgv_flood.api.models import Place
from rgv_flood.wayfinder import Coordinate


class AddressGeocoder(Protocol):
    """The deliberately small server-held address-search capability."""

    def search(self, query: str) -> list[Place]: ...


@dataclass(frozen=True)
class AddressResolution:
    coordinate: Coordinate | None
    reason: str | None = None


def resolve_public_address(geocoder: AddressGeocoder | None, address: str, role: str) -> AddressResolution:
    """Resolve exactly one address or return a public, fail-closed explanation."""
    if len(address) < 3:
        return AddressResolution(None, f"{role} address is not a usable street address.")
    if geocoder is None:
        return AddressResolution(None, "Wayfinder address resolution is not currently configured for public use.")
    try:
        places = geocoder.search(address)
    except (httpx2.HTTPError, KeyError, TypeError, ValueError):
        return AddressResolution(None, f"{role} address could not be resolved from the server-held address service.")
    if not places:
        return AddressResolution(None, f"{role} address could not be resolved. Use a complete street address in the Rio Grande Valley.")
    if len(places) != 1:
        return AddressResolution(None, f"{role} address is ambiguous. Use a more specific street address.")
    place = places[0]
    if not isfinite(place.lat) or not isfinite(place.lon):
        return AddressResolution(None, f"{role} address could not be resolved from the server-held address service.")
    return AddressResolution(Coordinate(place.lat, place.lon))
