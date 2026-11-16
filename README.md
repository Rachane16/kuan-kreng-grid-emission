# Kuan Kreng · 1 km Grid Fire & Emission

Daily PM₂.₅ **full-grid burning scenarios** for the supplied Kuan Kreng peat swamp boundary. This independent project uses FIRMS hotspot **points**, not satellite pixel footprints as burned polygons.

- Website: https://rachane16.github.io/kuan-kreng-grid-emission/
- Repository: https://github.com/Rachane16/kuan-kreng-grid-emission
- Local project: D:\LAB Emission
- Model: full_grid_1km_v1

## Calculation

A fixed 1,000 × 1,000 m grid uses EPSG:32647 with origin (0,0). There are 1,052 positive-area cells covering 93,105.272906 ha after clipping to the supplied boundary. One or more point centers inside a cell and inside the boundary activate that cell for the selected Thai calendar day (UTC+7). Count each cell once, even across multiple satellites or overpasses. Nominal cells are 100 ha; boundary cells use their clipped area.

Adjacent active cells form a group only when they share an edge of positive length inside the study boundary (4-neighbor connectivity). Diagonal contact does not join groups. Gaps and holes are not filled. Group totals equal the sum of their unique cells.

Intersect each activated cell with each fuel layer independently. Intentional overlaps between fuel layers are retained. For each fuel pool:

**PM₂.₅ (kg) = intersected area (ha) × ρ (dry t/ha) × η × EF (g/kg dry fuel)**

The tonne-to-kilogram and gram-to-kilogram factors cancel. Melaleuca surface fuel and leaves + bark are separate pools on the same extent and their emissions are added. Peat is an optional **0–10 cm soil burning scenario**. The six user-approved numerical parameter sets and references are retained in config/emission_parameters.json.

Activation assumes **100% of the clipped cell area** is exposed to burning; η still specifies the fraction of its starting dry fuel consumed. These are different assumptions. Full-grid areas and emissions are scenarios, not confirmed burned area or measured emissions.

Each Thai day starts independently with the same fuel parameters. A cell active on different days is recalculated for each day. Multi-day graph sums must not be interpreted as unique burned area, independent fire events, or a fuel-depletion inventory.

## Data and automation

The project includes 96 recalculated Thai days (2026-08-13–2026-11-16) from the previous project's saved FIRMS observations. Historical product availability and per-source coverage states are preserved; absent/incomplete data are not equivalent to confirmed absence of fire.

GitHub Actions checks for new observations at minute 7 and 37 each hour. FIRMS latency and GitHub scheduling delays apply. Four source families are retained: MODIS Terra/Aqua, VIIRS S-NPP, NOAA-20, NOAA-21. Source availability is checked before fetching. The existing S-NPP product may have no newer observations.

FIRMS_MAP_KEY is stored only as a repository Actions Secret. Browser code contains no key. Settings → Pages must use GitHub Actions.

The authoritative full precision boundary and fuel geometry is bundled as gzip GeoJSON under data/processed/spatial. Raw source shapefiles are not copied into this project; their original path metadata is provenance only. Display fuel geometry is simplified and is not used for calculations.

## Run and validate

Python 3.12:

~~~powershell
cd "D:\LAB Emission"
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node tests/chart-data.test.cjs
python scripts/rebuild_grid_history.py
python -m http.server 8766 --bind 127.0.0.1 --directory web
~~~

Set FIRMS_MAP_KEY only in the process environment to run python scripts/fire_pipeline.py collect --days 3. Never add the key to source or URLs in logs.

The dashboard offers daily satellite filters, individual cells or contiguous groups, original hotspot points, grid/cluster fuel breakdown popups, CSV exports, a monthly comparison graph, peat toggle, fuel overlays, and three basemaps.

Audit: outputs/tables/grid_model_audit.json. Calculation tests cover clipping, repeated points, grid-edge assignment, adjacency, gaps, daily independence, and real point output. Historical API/date preservation and chart data checks also run in CI.

## Provenance

Imported from Rachane16/khuan-khreng-emission as a separate repository, then replaced the pixel model and recalculated all saved dates. Existing template-era reports under docs and outputs describe the original project's spatial preparation or previous implementation. This README, docs/METHODOLOGY.md and the grid audit define the current grid model.
