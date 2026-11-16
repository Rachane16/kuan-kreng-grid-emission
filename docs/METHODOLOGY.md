# Current model: full_grid_1km_v1

See the repository README for the complete current method and assumptions.

1. Fixed 1 km UTM zone 47N grid, origin (0,0), clipped to supplied study boundary.
2. FIRMS point center must lie inside the supplied boundary. Point assignment is unique; shared internal grid lines assign east/north.
3. Activate one clipped cell once per Thai day and selected source set. All satellites uses the unique union of active cells.
4. Use all of the activated cell's clipped area as a user-approved full-grid burning scenario.
5. Form groups using positive-length shared clipped edges. No diagonal grouping, gap filling, hulls or inactive connecting cells.
6. Intersect each cell with each fuel layer independently, preserve intended overlaps, and calculate area × ρ × η × EF in kg.
7. Add the separate Melaleuca surface and leaves+bark pools. Peat 0–10 cm is independently toggleable.
8. Start each day independently. Never deduct previous-day fuel or count a cell twice within the same day's selected sources.
9. Export grid/group IDs and all six fuel rows for reproducibility. Use full prepared geometry for calculations; simplified geometry is display-only.
10. Do not interpret full-grid scenario area as satellite-confirmed burned area. Missing source coverage is distinct from zero observations.

The fixed grid has 1,052 cells and exactly covers the supplied boundary within floating-point tolerance. See outputs/tables/grid_model_audit.json.
