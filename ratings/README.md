# Player Ratings

| Folder | What lives there |
| --- | --- |
| [daily/](daily/) | Daily BPM and RAPM calculations, game validation and repairs, Supabase SQL, and CSV export and publishing. |
| [projections/](projections/) | The 18-stat forecast export, player matching, and the snapshot used by the site. |
| [page/](page/) | The Ratings table, filters, conference list, and styles. |

**BPM and RAPM refresh daily.** At 7:30 a.m. Pacific, the
[GitHub Actions workflow](../.github/workflows/daily-rapm.yml) validates new
games and retries missing inputs. It recalculates the ratings, publishes the
snapshot in Supabase, then exports both ratings to one `player-ratings.csv`
on the `ratings-data` branch. The page fetches that CSV when the dashboard
session starts. Daily ratings updates do not require rebuilding the website.

**Actual stats and rest-of-season projections use a separate snapshot.**
The [projection exporter](projections/README.md) writes the model result to
`player_skills.csv` for audit and packages the 18 actual and projected stats
into `projections/player_projections.json` for the page. The exporter is
currently run manually in the forecasting workspace. The website needs a
Pages rebuild to pick up a newer bundled forecast. The two dates can differ,
and the page displays each data cutoff.
