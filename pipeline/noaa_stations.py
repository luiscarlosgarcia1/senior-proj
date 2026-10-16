"""GHCN-Daily stations used for each county's rainfall record.

Only official NOAA COOP ("USC00...") and WBAN airport ("USW00...") stations, no
CoCoRaHS/volunteer ("US1...") stations, to match the longer, more consistent
2000-2025 record the Hidalgo set was originally chosen for. Selected by checking
NOAA's ghcnd-stations.txt against each county's TIGER boundary (plus ~5 km
buffer), then dropping any station already claimed by another county.
"""

from __future__ import annotations


def _station(name: str, latitude: float, longitude: float, elevation_m: float | None) -> dict:
    return {"name": name, "latitude": latitude, "longitude": longitude, "elevation_m": elevation_m}


STATIONS_BY_COUNTY: dict[str, dict[str, dict]] = {
    "hidalgo": {
        "USW00012959": _station("McAllen Miller International Airport", 26.1792, -98.2444, 30.2),
        "USW00012987": _station("Edinburg 17 NNE", 26.5258, -98.0633, 19.5),
        "USC00412758": _station("Edinburg", 26.2981, -98.1575, 29.3),
        "USC00414139": _station("Hidalgo", 26.1, -98.2667, 31.1),
        "USC00415701": _station("McAllen", 26.1922, -98.2503, 33.5),
        "USC00415836": _station("Mercedes 6 SSE", 26.0619, -97.8997, 22.9),
        "USC00415972": _station("Mission 4 W", 26.2167, -98.4, 40.5),
        "USC00415973": _station("Mission Pumping Station", 26.2, -98.3167, 39.9),
        "USC00419588": _station("Weslaco", 26.1781, -97.9708, 22.9),
    },
    "cameron": {
        "USW00012919": _station("Brownsville", 25.9161, -97.4189, 26.8),
        "USW00012904": _station("Harlingen Rio Grande Valley Intl", 26.2303, -97.6556, 9.4),
        "USW00012957": _station("Port Isabel Cameron Co AP", 26.1597, -97.3378, 5.2),
        "USC00411133": _station("Brownsville", 25.9008, -97.5039, 5.5),
        "USC00413943": _station("Harlingen", 26.2028, -97.6728, 11.6),
        "USC00417952": _station("San Benito", 26.1333, -97.6333, 11.9),
        "USC00410576": _station("Bayview", 26.1167, -97.4, 6.1),
        "USC00418060": _station("Santa Rosa", 26.25, -97.8333, 14.9),
    },
    "starr": {
        "USC00417622": _station("Rio Grande City", 26.3769, -98.8117, 52.4),
        "USC00411349": _station("Cameron Rch", 26.55, -98.5833, 139.9),
        "USC00412879": _station("El Sauz", 26.5747, -98.8708, 62.2),
        "USC00413060": _station("Falcon Dam", 26.5581, -99.1372, 97.5),
        "USC00413444": _station("Garciasville 2 ESE", 26.3231, -98.6778, 53.3),
    },
    "willacy": {
        "USC00417458": _station("Raymondville", 26.4644, -97.7847, 9.4),
        "USC00415444": _station("Lyford", 26.4, -97.8, None),
        "USC00416017": _station("Monte Alto", 26.55, -97.9667, 11.9),
        "USC00417184": _station("Port Mansfield", 26.5533, -97.4278, 1.8),
        "USC00417990": _station("San Perlita", 26.5, -97.6, 6.1),
    },
}
