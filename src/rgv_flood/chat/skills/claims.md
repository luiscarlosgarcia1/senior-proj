---
name: claims
use_when: Flood-insurance (NFIP) claims or dollars paid for a county, town or years, including claims per policy.
tools: [find_place, claims_summary, query_database]
tables: [nfip_claims, nfip_policies_by_year, places, place_tracts]
---
## How to answer
1. If the question names a town, call find_place first. If it matches several places, pick the one the question most likely means, say which, and use its exact name.
2. Call claims_summary with the county or the place, and the years asked about. With no years given, leave them out: the tool uses the last ten full years, and you say so.
3. Use query_database only for what claims_summary does not give (for example claims by flood event name or by cause of damage), and keep the same rules.

## Traps
- Claims carry a county and a census tract, never a city. For a town, the numbers are claims in the census tracts that make up most of it. Say "in the tracts that make up most of Edinburg", never "in Edinburg".
- Claims per 1,000 policies exists only for whole counties, and only for years with a policy count (2009 on). Never divide town claims by county policies.
- Dollars paid are building plus contents plus increased cost of compliance. They are what FEMA paid, not the damage.
- Few claims does not mean little flooding: most homes in the Valley have no flood insurance.
- If the tool says the years are outside the data, tell the reader the range it gave.

## Good answer
Hidalgo County had 412 flood-insurance claims from 2015 to 2024, with $9.8 million paid.
I read this as the last ten full years; ask again for other years.
- Most claims came in 2020 (Hurricane Hanna): 190 claims, $5.1 million.
- Claims per 1,000 policies peaked at 21 in 2020.
From: nfip_claims, nfip_policies_by_year; Hidalgo County; 2015-2024
Limits: counts only insured buildings, so it understates flooding where few people carry flood insurance.

(The figures above only show the shape. Every real figure must come from a tool result.)
