# Food inspection data

## `processed/merged_food_inspections.csv`

The combined dataset: two independently scraped sources merged into one
flat table, **one row per violation**. An inspection with no violations,
or an establishment with no inspections on record, still gets exactly one
row with the missing fields left empty — rows are never dropped for
lacking detail.

Regenerate with `python3 scripts/merge_food_inspections.py` (reads
`processed/slc/*.csv` and `../food_inspections.csv`, both described below).

### Columns

| Column | Description |
|---|---|
| `establishment_name` | Business/facility name as listed on the inspection site. |
| `establishment_type` | Category, e.g. `Restaurants: plated`, `Mobiles: Food Carts`, `Child Care Centers: Licensed`. |
| `address` | Street address. |
| `city_state_zip` | City, state, and ZIP as one string, e.g. `SANDY, UT 84070`. |
| `contact_info` | Phone number, formatting varies by source (see Caveats). |
| `rank` | Site's own establishment rank/score field, where available. |
| `inspection_date` | Date of the inspection, `M/D/YYYY`. |
| `inspection_type` | e.g. `01 - Routine`, `02 - Followup`, `07 - Critical Item`. |
| `inspection_score` | Numeric inspection score. |
| `count_critical_violations` | Critical violation count reported for that inspection. |
| `count_noncritical_violations` | Non-critical violation count reported for that inspection. |
| `violation_code` | Code for this specific violation, e.g. `4.5.18*`. Empty if the inspection had no violations, or if the source didn't capture violation-level detail (see Caveats). |
| `violation_description` | Free-text description of the observed violation. |
| `violation_critical` | `True`/`False` — whether this violation was marked critical. |
| `violation_occurrences` | Number of occurrences of this violation noted in the inspection. |
| `violation_cos` | Whether the violation was corrected on site (`True`/`False`). |
| `violation_phr` | Public health risk category / rule reference for the violation. |
| `source` | Which raw source this row came from: `friend_slc` or `own_scrape` (see below). |
| `scraped_at` | Timestamp the underlying record was scraped, where available. |

### Row granularity

One row = one violation. All establishment/inspection fields (name,
address, score, violation counts, etc.) repeat on every violation row
belonging to that inspection. To get establishment- or inspection-level
tables, group by `establishment_name`+`address` or by
`establishment_name`+`inspection_date` and drop the violation columns.

### Sources merged

- **`friend_slc`** (32,738 rows) — from `processed/slc/establishments.csv`,
  `inspections.csv`, and `violations.csv`, joined on `establishment_key`
  (and `inspection_date` for violations). Has full violation-level detail.
- **`own_scrape`** (431 rows) — from `../food_inspections.csv`
  (`data-scrapping/scrapper.py` output, pages 76-118 of the results list).
  Only captured establishment info and inspection-history summaries, not
  individual violation line items, so `violation_code`,
  `violation_description`, and the other `violation_*` columns are always
  empty for these rows.

### Caveats

- No establishment-name overlap was found between the two sources, so no
  deduplication was needed or attempted.
- `contact_info` formatting differs by source (`friend_slc`: digits only,
  e.g. `8017272740`; `own_scrape`: `(801) 727-8188`) — left as scraped
  rather than normalized.
- 24 establishments in `friend_slc` have two inspections logged on the
  same date. The raw `violations.csv` only keys violations by
  (establishment, date), not a unique inspection id, so in those 24 cases
  the same violation list is attached to both same-day inspections rather
  than guessed apart.

## `processed/slc/*.csv`

Relational export (one dataset, three normalized tables) underlying the
`friend_slc` rows above:

- **`establishments.csv`** — one row per establishment. Key column
  `establishment_key` is `name|address|city`.
- **`inspections.csv`** — one row per inspection, keyed by
  `establishment_key` + `inspection_date`.
- **`violations.csv`** — one row per violation, keyed by
  `establishment_key` + `inspection_date`.

Use these directly if you want the relational form instead of the flat
merged CSV.
