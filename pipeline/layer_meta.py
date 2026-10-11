"""Descriptive metadata for every map layer: title, plain-language description,
source, vintage, limitations, and links to the publisher's own visualizations.

`build_layers.py` stores these with each layer in the app database; the sidebar
and each layer's "source" card render straight from it. Keep the wording honest about what a
layer is not (see each `limitation`).
"""

_ARCGIS_ITEM = "https://www.arcgis.com/home/item.html?id="
_EXPERIENCE = "https://experience.arcgis.com/experience/"
_HCDD1_DASHBOARD = "https://hcdd1.maps.arcgis.com/apps/dashboards/"


def _link(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url}


# The publishers' own maps and dashboards, shown as "Original visualizations"
# links on each layer's source card.
HCDD1_FLOOD_WEB_MAP = _link("HCDD1 Flood Web Map", _ARCGIS_ITEM + "e98554156b5e4bcd84bbe0e2d10c2764")
HCDD1_FLOOD_ZONE_MAP = _link("HCDD1 Flood Zone Map", _EXPERIENCE + "bcb86ca21dc14729bb5c1a5814ca91ad")
HCDD1_STORM_EVENT_MAP = _link("HCDD1 Storm Event Map", _ARCGIS_ITEM + "bdfd390479054ca0943275bc4e0662ec")
HCDD1_SYSTEM_MAP = _link("HCDD1 System Map", _EXPERIENCE + "73feb7978e4c4a518787e6a9dc1f1d69")
HCDD1_MASTER_MAP = _link("HCDD1 Master Web Map", _ARCGIS_ITEM + "43d4be942e7e4e66b35f8220da82cb89")
FEMA_NFHL_VIEWER = _link(
    "FEMA National Flood Hazard Layer viewer",
    "https://hazards-fema.maps.arcgis.com/apps/webappviewer/index.html?id=8b0adb51996444d4879338b5529aa9cd",
)
OVERTURE_EXPLORER = _link("Overture Maps Explorer", "https://explore.overturemaps.org/")

LAYER_META: dict[str, dict] = {
    "county-boundaries": {
        "title": "County boundaries",
        "description": (
            "Just the outlines of the four counties. It sets the area the map "
            "covers and shows no flood risk of its own."
        ),
        "source": "US Census TIGER/Line 2023",
        "vintage": "2023",
        "hazard_type": "n/a — study-area reference",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": "Geographic reference only. Not flood evidence.",
        "source_url": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    },
    "fema-nfhl": {
        "title": "FEMA effective flood hazard (NFHL)",
        "description": (
            "The official government flood map used to set flood-insurance rates "
            "and building rules. Red areas flood most often, orange areas only in "
            "rarer big storms, and blue areas hardly ever. Not available for "
            "Hidalgo County."
        ),
        "source": "FEMA National Flood Hazard Layer",
        "vintage": "effective FIRM date varies by panel",
        "hazard_type": "effective regulatory flood hazard",
        "coverage": "Cameron, Starr, Willacy",
        "limitation": "No digital NFHL coverage for Hidalgo County. Clipped to county boundary; not a property-level determination.",
        "source_url": "https://msc.fema.gov/portal/home",
        "visualizations": [FEMA_NFHL_VIEWER],
    },
    "hidalgo-firm-1981": {
        "title": "Hidalgo County historic flood zones (1981 FIRM)",
        "description": (
            "Hidalgo County's only flood map, drawn back in 1981 — FEMA never "
            "made a modern one here. It's very out of date and leaves out most of "
            "today's neighborhoods, so treat it as a rough guide. Red areas flood "
            "most often, orange less often, blue rarely."
        ),
        "source": "Hidalgo County Drainage District No. 1 — digitized 1981 FIRM",
        "vintage": "1981 base map; some zones later revised by LOMR",
        "hazard_type": "historic local flood-zone reference",
        "coverage": "Hidalgo",
        "limitation": "44 years old; urban core largely undrawn. Legacy B/C zones shown as shaded-X / minimal by long-standing FEMA equivalence, but this is not current effective data.",
        "source_url": "https://www.hcdd1.org/page/floodplains",
        "visualizations": [HCDD1_FLOOD_ZONE_MAP, HCDD1_FLOOD_WEB_MAP],
    },
    "twdb-cursory-1in100": {
        "title": "TWDB modeled flood extent — 1% annual chance",
        "description": (
            "A state computer model's guess at which land would flood in a bad "
            "storm (about a 1-in-100-year flood), including flooding from heavy "
            "rain. One shaded area, not graded zones. It's an estimate for "
            "context, not an official flood map."
        ),
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
    "twdb-cursory-1in500": {
        "title": "TWDB modeled flood extent — 0.2% annual chance",
        "description": (
            "The same state model, but for a rarer, more extreme flood (about "
            "1-in-500-year) — a wider guess at what could go under water. For "
            "context only, not an official flood map."
        ),
        "source": "TWDB 2025 cursory floodplain (Fathom 3m)",
        "vintage": "2025",
        "hazard_type": "modeled pluvial/fluvial/coastal (contextual)",
        "coverage": "all four counties",
        "limitation": "Modeled estimate, not an effective FEMA map or regulatory determination.",
        "source_url": "https://www.twdb.texas.gov/flood/science/floodplain-dataset.asp",
    },
    "overture-bridges": {
        "title": "Bridges",
        "description": (
            "Bridges across the four counties — exactly what becomes impassable "
            "when a waterway floods. Not a hazard rating of its own."
        ),
        "source": "Overture Maps Foundation — infrastructure theme (OpenStreetMap)",
        "vintage": "current Overture release",
        "hazard_type": "n/a — infrastructure at risk, not a hazard zone",
        "coverage": "all four counties",
        "limitation": (
            "Crowd-sourced (OpenStreetMap); coverage and names vary by area. "
            "Not an official inventory of flood-prone crossings."
        ),
        "source_url": "https://overturemaps.org/",
        "visualizations": [OVERTURE_EXPLORER],
    },
    "overture-dams": {
        "title": "Dams",
        "description": (
            "Dams and levees — flood-control infrastructure, relevant to both "
            "flood risk and flood mitigation depending on the structure."
        ),
        "source": "Overture Maps Foundation — infrastructure theme (OpenStreetMap)",
        "vintage": "current Overture release",
        "hazard_type": "n/a — infrastructure, not a hazard zone",
        "coverage": "all four counties",
        "limitation": (
            "Crowd-sourced (OpenStreetMap); coverage and names vary by area. "
            "Not an official inventory."
        ),
        "source_url": "https://overturemaps.org/",
        "visualizations": [OVERTURE_EXPLORER],
    },
    "hcdd1-flood-extents": {
        "title": "Mapped flooding, 2008–2020 (Hidalgo)",
        "description": (
            "Areas the Hidalgo drainage district mapped as flooded after six past "
            "storms. This is recorded flooding, not a forecast — and it shows where "
            "the old 1981 map misses real flood problems."
        ),
        "source": "Hidalgo County Drainage District No. 1 — Historical Flooding layer",
        "vintage": "events in 2008, 2010, 2015, 2018, 2019, 2020",
        "hazard_type": "observed flooding (district-mapped)",
        "coverage": "Hidalgo, mostly the urban core",
        "limitation": (
            "Only the areas the district mapped, so absence of a shape does not mean "
            "no flooding. The inch range on each event is the district's own label; "
            "whether it is rainfall or flood depth is not stated."
        ),
        "source_url": "https://www.hcdd1.org/",
        "visualizations": [
            HCDD1_FLOOD_WEB_MAP,
            HCDD1_STORM_EVENT_MAP,
            _link("HCDD1 Flood Damages, June 2018", _ARCGIS_ITEM + "f9a644ef576943549ac75382d0ba56e2"),
        ],
    },
    "hcdd1-flood-photos": {
        "title": "Flood response photos (Hidalgo)",
        "description": (
            "Locations of field photos the drainage district took while responding "
            "to four floods. Each dot is a place where crews documented conditions."
        ),
        "source": "Hidalgo County Drainage District No. 1 — geotagged flood photos",
        "vintage": "June 2018, Sept 2018, June 2019, Hurricane Hanna 2020",
        "hazard_type": "observed flooding (field documentation)",
        "coverage": "Hidalgo",
        "limitation": (
            "Photos cluster where crews work along drainage assets, and a photo "
            "shows crews were there, not necessarily standing water. Photos are not "
            "reproduced here; GPS tags outside the valley are dropped."
        ),
        "source_url": "https://www.hcdd1.org/",
        "visualizations": [HCDD1_FLOOD_WEB_MAP, HCDD1_STORM_EVENT_MAP],
    },
    "hcdd1-drainage": {
        "title": "Drainage network (Hidalgo)",
        "description": (
            "The drainage district's channels, detention ponds, gates and pumps — "
            "the engineering that decides where stormwater goes."
        ),
        "source": "Hidalgo County Drainage District No. 1 — system, detention and gate/pump layers",
        "vintage": "district records as published",
        "hazard_type": "n/a — drainage infrastructure",
        "coverage": "Hidalgo County Drainage District No. 1 area",
        "limitation": "Reflects what the district publishes; other districts' systems may be missing.",
        "source_url": "https://www.hcdd1.org/",
        "visualizations": [
            HCDD1_SYSTEM_MAP,
            HCDD1_MASTER_MAP,
            _link("HCDD1 Working System Map", _ARCGIS_ITEM + "a3dd6fddb57846168ed9e1a9f13782b0"),
        ],
    },
    "hcdd1-bond-projects": {
        "title": "Drainage improvement projects (Hidalgo)",
        "description": (
            "Projects funded by the district's 2012, 2018 and 2023 bonds — new "
            "drainage built after the 1981 flood map, with each project's status."
        ),
        "source": "Hidalgo County Drainage District No. 1 — bond program layers",
        "vintage": "2012, 2018 and 2023 bond programs",
        "hazard_type": "n/a — infrastructure updates",
        "coverage": "Hidalgo",
        "limitation": "Status is as last published by the district; the 2012 program has no status field.",
        "source_url": "https://www.hcdd1.org/",
        "visualizations": [
            _link("2018 Bond dashboard", _HCDD1_DASHBOARD + "d3c9a895241a49e1a28a762674131994"),
            _link("2023 Bond dashboard", _HCDD1_DASHBOARD + "f7722aadbef74bf29d76d144d49390e8"),
            _link("2012 Bond dashboard", _ARCGIS_ITEM + "4bbb6b3959124f62bf7b30389a6dddce"),
            _link("HCDD1 District Projects", _ARCGIS_ITEM + "40da5a923154485cac2256bf3daec571"),
        ],
    },
    "nfip-claims-by-tract": {
        "title": "Flood insurance claims by tract",
        "description": (
            "How many federal flood-insurance claims were filed in each census tract "
            "since 1978 — a record of where flooding has actually cost people money."
        ),
        "source": "FEMA OpenFEMA — NFIP Redacted Claims v3",
        "vintage": "claims through 2026",
        "hazard_type": "observed flood losses",
        "coverage": "all four counties",
        "limitation": (
            "Counts only insured properties and is not adjusted for how many homes "
            "are insured, so tracts with more policies read higher."
        ),
        "source_url": "https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3",
    },
}
