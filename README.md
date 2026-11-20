# ncaa-player-dashboard
Player Dashboard for NCAA D1, D2 &amp; D3 Players

### Player Ratings

The [Ratings folder](ratings/README.md) contains the daily BPM, RAPM, and EPM
pipeline, the player forecast exporter, and the Ratings page.

### Division I data and pages

- `data/raw/division_i/<season>/<retrieval>/` holds the original Torvik player
  CSV, shooting JSON, and retrieval time for each pull.
- `data/current/division-i-<season>.csv` is the validated snapshot consumed by
  Division I and Triton Zone. A failed build leaves the previous file in place.
- `data/historical/` holds the completed-season index and precomputed historical
  comparison tables.
- `pages/division_i/`, `pages/triton_zone/`, and `pages/historical_players/`
  contain their Shiny layouts, styles, and page-specific data or scoring code.
  Shared UI, navigation, and reactive wiring live in `app.py`.

#### Season preview

The Daily Division I preview snapshot workflow builds the 2026–27 CSV at
6:30 a.m. Pacific once the workflow is on the default branch. It uploads raw
inputs and the validated CSV as separate artifacts. Download the
`division-i-2027-preview` artifact to `data/current/`, or build it locally
from the repository root:

```sh
python scripts/build_division_i_snapshot.py --season 2027
D1_PREVIEW_SNAPSHOT=data/current/division-i-2027.csv shiny run app.py
```

For a reproducible rebuild, pass the two saved raw inputs with `--players`
and `--shooting`. Triton Zone scores the shared snapshot in memory as staff
adjust the thresholds. The preview uses Torvik player IDs and its own Watchlist
and Tracker storage keys. Historical Players includes 2025–26 in this mode.
Publishing to the public dashboard requires the production cutover.
