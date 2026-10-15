#!/usr/bin/env python3
"""Write data/seed/nfip-policies-by-year.csv: NFIP policies in force per county
and year, from FEMA's "FIMA NFIP Redacted Policies v2" export.

FEMA retired that dataset on 2026-10-15, and the newer v3 cannot be filtered by
county, so the counts are kept as a seed file rather than downloaded on each
build. Run this only to regenerate them from a saved copy of the export (one
JSON policy per line, as `fetch_ml_inputs.py --only nfip_policies` saved it).

A row of the export is one policy term, usually a year long, with the number of
policies it covers. Policies in force in a year are counted as the policies
whose term began that year.

Run:  uv run python pipeline/seed_nfip_policies.py [path/to/nfip_policies_v2.ndjson]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

from paths import ML_RAW, SEED_DIR

from rgv_flood.counties import FIPS_TO_SLUG

SEED_FILE = SEED_DIR / "nfip-policies-by-year.csv"


def policies_by_year(export: Path) -> Counter:
    counts: Counter = Counter()
    with export.open(encoding="utf-8") as lines:
        for line in lines:
            if not line.strip():
                continue
            policy = json.loads(line)
            county = FIPS_TO_SLUG.get(policy.get("countyCode"))
            began = (policy.get("policyEffectiveDate") or "")[:4]
            if county and began.isdigit():
                counts[county, int(began)] += policy.get("policyCount") or 1
    return counts


def main() -> None:
    export = Path(sys.argv[1]) if len(sys.argv) > 1 else ML_RAW / "nfip" / "nfip_policies_v2.ndjson"
    counts = policies_by_year(export)
    with SEED_FILE.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["county", "year", "policies"])
        writer.writerows((county, year, n) for (county, year), n in sorted(counts.items()))
    print(f"wrote {len(counts)} county-years to {SEED_FILE}")


if __name__ == "__main__":
    main()
