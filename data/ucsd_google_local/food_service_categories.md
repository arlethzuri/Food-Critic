# Food-service Google Local categories

Curated subset of `google_local_categories.txt` for filtering UCSD Google Local
businesses toward the same kinds of places as:

- `data/osm/slc/restaurants.csv` (OSM dining POIs)
- `data/processed/merged_food_inspections.csv` (SLCHD food establishments)

**List:** `food_service_categories.txt` (253 of 3042 categories)

## Include

Restaurants (all cuisine labels), cafes/coffee/boba, fast food, bars/pubs/
lounges, bakeries/pastry/dessert, ice cream/yogurt, juice/smoothie, delis/
sandwich shops, catering/mobile food, food courts, brewery/winery/distillery.

Aligned with OSM amenities (`restaurant`, `cafe`, `fast_food`, `bar`, `pub`,
`ice_cream`, `food_court`, …) and shops (`bakery`, `pastry`, `deli`, …), plus
inspection types like restaurants plated/non-plated, beverage service,
mobiles, caterers, concessions, commissary.

## Exclude

Grocery/retail food stores, suppliers/wholesalers/equipment, lodging,
schools/care, cosmetology and other non-food inspection types, and keyword
false positives (`Eyebrow bar`, `Kitchen remodeler`, `Grill store`, etc.).

## Notes

- No Google Local `Food truck` category; closest keep is `Mobile caterer`.
- `Shared-use commercial kitchen` kept as commissary-adjacent.
- If `google_local_categories.txt` changes, re-curate this list by the same
  include/exclude rules above.
