# Player Ratings

| Folder | What lives there |
| --- | --- |
| [daily/](daily/) | Daily BPM, RAPM, and EPM calculations, game validation and repairs, Supabase SQL, and CSV export and publishing. |
| [projections/](projections/) | The 18-stat forecast export, player matching, and the snapshot used by the site. |
| [page/](page/) | The Ratings table, filters, conference list, and styles. |

**BPM, RAPM, and EPM refresh daily.** At 7:30 a.m. Pacific, the
[GitHub Actions workflow](../.github/workflows/daily-rapm.yml) validates new
games and retries missing inputs. It recalculates the ratings, publishes the
snapshot in Supabase, then exports the ratings to one `player-ratings.csv`
on the `ratings-data` branch. The page fetches that CSV when the dashboard
session starts. Daily ratings updates do not require rebuilding the website.

**Estimated Plus-Minus (EPM)** uses the dashboard's BPM as the starting point
for its lineup regression. It measures net points per 100 possessions and
requires both box-score and lineup data for the player. Click the EPM column
header to rank by it. The percentile is based on all players in that snapshot
with an EPM value.

The **UCSD Lineup Predictor** reads that same CSV on page load and shows the
cutoff for each metric. The season slider blends 2025–26 and 2026–27 within
each metric and defaults to 25% current season. The metric slider then
combines BPM and RAPM into the lineup score and defaults to 100% BPM.
Both choices are saved in the browser. Starter scores are sums, and
rotation scores are minutes-weighted five-player equivalents. For each of
2021–22 through 2025–26, the tier model blends final rotation BPM and RAPM
at the selected metric weight. It ranks teams by their recorded regular
season conference winning percentage, with ties sharing a rank. The WCC
reference excludes Gonzaga from each season and reranks the other teams
using their recorded winning percentages. In each season, the cutoff
is the midpoint between the nearest rated finish on either side of the
boundary, such as third and fourth for Top 3. Tied teams' scores are averaged
at their shared rank. If no rated team finished below a boundary, use the
score at the nearest rated finish above it. Crossed cutoffs are averaged
together within a season to keep the tier order; then the five seasons'
cutoffs are averaged with equal weight.

Title and Elite use the champion boundary. Top 3 and Top 4 use third and
fourth, respectively. Mid-Pack and Top Half use the top half, including
the middle place in an odd-sized league. Lower Half and Mid-Tier use the
boundary above the bottom quarter (rounded up). Scores below that final
boundary are Rebuild or Rebuilding. The reference uses the same team-seasons
for every metric weight, with RAPM available for at least 90% of rotation
minutes. Missing ratings do not change a team's place or the league size.
The season weight applies to the lineup score only. The conference
selector switches the standings benchmarks and the stat projection
scenario. The lineup score uses BPM and RAPM directly, with no additional
conference adjustment.
The 5-Man tab tiers the rotation when minutes are assigned and uses the
starting five score when no minutes are assigned. The 9-Man tab tiers
the minutes-weighted score as minutes are assigned. When the selected mix
uses RAPM and coverage is incomplete, the breakdown shows the rated minutes.

The predictor's 2025–26 roster values come from a historical run of
`ratings/daily/player_ratings.py --season 2026 --inputs <cached provider files>`
through April 6, 2026, with the same 90-day RAPM weights used in 2026–27.
The rows in `PRIOR_IMPACT` match each player's name and 2025–26 school.
If one season is missing for a metric, the available season gets full weight.
Manual BPM in Season Update takes precedence over the current-season feed.

**Actual stats and rest-of-season projections use a separate snapshot.**
The [projection exporter](projections/README.md) writes the model result to
`player_skills.csv` for audit and packages the 18 actual and projected stats
into `projections/player_projections.json` for the page. The exporter is
currently run manually in the forecasting workspace. The website needs a
Pages rebuild to pick up a newer bundled forecast. The two dates can differ,
and the page displays each data cutoff.

**Watchlist only** uses the dashboard's shared Watchlist. Stars on player
profiles update the same list used by the Watchlist page and Ratings. The
site saves that list in this browser's local storage.
