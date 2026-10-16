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
STATE_FLOOD_PLAN_VIEWER = _link("Interactive State Flood Plan Viewer", "https://texasstatefloodplan.org/")
STATE_FLOOD_PLAN = "https://www.twdb.texas.gov/flood/planning/sfp/2024/index.asp"

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
        "title": "Flood photos and photo locations (Hidalgo)",
        "description": (
            "Places where drainage district crews photographed conditions while "
            "responding to four floods. Magenta dots are flood photos: click one "
            "to see the picture, which the district has published for September "
            "2018 and June 2019. Grey dots are photo locations: where and when a "
            "photo was taken during June 2018 or Hurricane Hanna, without the "
            "picture."
        ),
        "source": "Hidalgo County Drainage District No. 1 — geotagged flood photos",
        "vintage": "June 2018, Sept 2018, June 2019, Hurricane Hanna 2020",
        "hazard_type": "observed flooding (field documentation)",
        "coverage": "Hidalgo",
        "limitation": (
            "Photos cluster where crews work along drainage assets, and a photo "
            "shows crews were there, not necessarily standing water. Images load "
            "from the district's own server and are not copied here; GPS tags "
            "outside the valley are dropped."
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
    "waterways": {
        "title": "Drains, canals and creeks",
        "description": (
            "The water lines that carry runoff across the valley: drainage "
            "ditches and floodways, irrigation canals, resacas, and the creeks "
            "and arroyos of Starr County. Kinds come from each line's own name "
            "(a \"Drn\" is a drain, a \"Cnl\" a canal). Where the Hidalgo "
            "drainage district, Harlingen or Brownsville map a ditch, their line "
            "is shown in their own layer instead."
        ),
        "source": "U.S. Census Bureau — TIGER/Line 2023 linear water",
        "vintage": "2023",
        "hazard_type": "n/a — drainage paths",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": (
            "Census lines are drawn for map labeling, not engineering; small "
            "private ditches and storm sewers are missing, and an unnamed canal "
            "or ditch can't be told apart."
        ),
        "source_url": "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    },
    "fema-flood-photos": {
        "title": "Flood photos (FEMA)",
        "description": (
            "FEMA's own photographs of flooding in the valley: Hurricane Dolly "
            "in 2008 (Brownsville, La Feria, Raymondville, Weslaco), the Roma "
            "flood of August 2008, and Hurricane Alex in 2010 (Roma, La Grulla, "
            "Mission). Click a town to see its photos."
        ),
        "source": "FEMA photo library, as kept on Wikimedia Commons (public domain)",
        "vintage": "2008–2010",
        "hazard_type": "observed — photographs of flooding",
        "coverage": "Cameron, Hidalgo, Starr, Willacy (towns FEMA photographed)",
        "limitation": (
            "Each photo is placed at the town its caption names (the Census "
            "point for that town), not where it was taken. Only the storms FEMA "
            "photographed and Commons keeps are here."
        ),
        "source_url": "https://commons.wikimedia.org/wiki/Category:Effects_of_Hurricane_Dolly_(2008)_in_Texas",
    },
    "flood-infrastructure": {
        "title": "Flood infrastructure (state flood plan)",
        "description": (
            "Dams, levees, sea walls, storm drain systems, low-water crossings "
            "and coastal works (dunes, jetties, beach nourishment) the regional "
            "flood planning group inventoried for the 2024 State Flood Plan, "
            "plus named dams the plan lacks that OpenStreetMap has."
        ),
        "source": (
            "Texas Water Development Board — 2024 State Flood Plan, existing flood "
            "infrastructure; extra dams from Overture Maps Foundation (OpenStreetMap)"
        ),
        "vintage": "2024 State Flood Plan (Region 15 inventory, 2023)",
        "hazard_type": "n/a — flood infrastructure",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": (
            "Only what local entities reported to the planning group; most "
            "items have no condition or level-of-service rating. The plan also "
            "lists wetlands, lakes (as ponds) and parks; those are left out here."
        ),
        "source_url": STATE_FLOOD_PLAN,
        "visualizations": [STATE_FLOOD_PLAN_VIEWER],
    },
    "city-drainage": {
        "title": "City storm drainage (Harlingen, Brownsville)",
        "description": (
            "The storm sewers, drainage ditches and detention ponds Harlingen "
            "publishes, and the drainage ditches Brownsville publishes, with "
            "the district or owner of each ditch."
        ),
        "source": "City of Harlingen (storm drain system); City of Brownsville Engineering (drainage ownership)",
        "vintage": "as last published by each city",
        "hazard_type": "n/a — drainage infrastructure",
        "coverage": "Harlingen and Brownsville (Cameron County)",
        "limitation": (
            "Only these two cities publish their drainage. Pipe sizes are as "
            "recorded by the city and many records are incomplete."
        ),
        "source_url": "https://www.harlingentx.gov/",
    },
    "flood-projects": {
        "title": "Flood projects (state flood plan)",
        "description": (
            "Drainage and flood-control projects in the 2024 State Flood Plan: "
            "ongoing ones that cities, counties and districts reported, and "
            "new ones the regional planning group recommended, with cost and "
            "how many buildings each would take out of the 100-year floodplain."
        ),
        "source": "Texas Water Development Board — 2024 State Flood Plan",
        "vintage": "2024 State Flood Plan (Region 15, 2023)",
        "hazard_type": "n/a — planned and ongoing projects",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": (
            "Status and costs are as reported for the plan in 2023. A "
            "recommended project is a candidate for state funding, not a "
            "commitment to build it."
        ),
        "source_url": STATE_FLOOD_PLAN,
        "visualizations": [STATE_FLOOD_PLAN_VIEWER],
    },
    "nws-flood-reports": {
        "title": "Reported flooding (National Weather Service)",
        "description": (
            "Flooding people reported to the National Weather Service in "
            "Brownsville since 2005: flooded streets and homes, flash floods, "
            "heavy rain totals. Each dot is one report, with who made it and "
            "what they saw."
        ),
        "source": "NWS Brownsville Local Storm Reports (archive: Iowa Environmental Mesonet)",
        "vintage": "2005 to present",
        "hazard_type": "observed flooding (reports)",
        "coverage": "Cameron, Hidalgo, Starr, Willacy",
        "limitation": (
            "Reports are not a complete record: they come from whoever "
            "contacted the NWS, and a location is often a town or road, not "
            "the exact flooded spot."
        ),
        "source_url": "https://mesonet.agron.iastate.edu/lsr/",
        "visualizations": [_link("IEM Local Storm Report app", "https://mesonet.agron.iastate.edu/lsr/")],
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
