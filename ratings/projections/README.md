# Player stat projections

This folder owns the dashboard export and published snapshot. The trained models
and their per-stat code live in the forecasting workspace. The dashboard shows
season-to-date actuals and rest-of-season projections for 18 stats. Actuals pool
eligible events and opportunities through the cutoff. Percentiles compare
actual values across the full Ratings snapshot before the page's filters,
with lower turnovers and fouls ranking higher.

Players without an eligible prior Division I profile and verified players on
current Division I teams outside the fitted model's school registry get a
Ratings estimate starting from the mean of the eligible preseason forecasts.
The estimate uses the same production exposure scales and recency weights to incorporate
their season-to-date games. The table labels these estimates **Est.** and
labels player-specific forecasts **Proj.** A shooting percentage without
attempts shows a dash for the actual and still displays the forecast.

Run from the dashboard repository root using the forecasting workspace's
Python environment and a fresh audit directory:

```sh
"$PROJECTION_WORKSPACE/.venv-pymc/bin/python" -m ratings.projections.export_player_projections \
  --workspace "$PROJECTION_WORKSPACE" \
  --rosters "$ROSTER_GZ" --teams "$TEAM_CSV" --games "$GAMES_GZ" \
  --date "$FORECAST_DATE" --audit-dir "$NEW_AUDIT_DIRECTORY"
```

Supply the same season for all three inputs. The current exporter targets
2026–27:

- `--rosters` uses `ncaa_mbb_team_rosters_2027.csv.gz` from the
  [SportsDataverse NCAA team roster release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/ncaa_mbb_team_rosters).
- `--teams` uses the school and conference columns in
  [Torvik's team results](https://barttorvik.com/2027_team_results.csv).
- `--games` uses the full [Torvik advanced box-score archive](https://barttorvik.com/2027_all_advgames.json.gz)
  so the exporter can reconstruct stat opportunities.

The wrapper calls `scripts/live_player_skills.py` in the forecasting workspace
with `outputs/live_player_skills_v2/settings.json`. Games on or after the
forecast date are excluded. Inspect `roster_matches.csv` and `player_skills.csv`
in the audit directory. The default website output is
`ratings/projections/player_projections.json`. Use `--output` to write a review
copy elsewhere. Publish the refreshed snapshot with the regular GitHub Pages
build.

The exporter also writes `ucsd_wcc_forecast.json` beside the main snapshot.
It reruns the UC San Diego roster with WCC as the destination conference, using
the same season and games as the Ratings forecast. The lineup builder compares
these scenarios when both snapshots have the same cutoff.
