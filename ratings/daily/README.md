# Daily BPM and RAPM

The data job runs at 7:30 a.m. Pacific on the default branch. A pull request
runs a calculation without a database connection. Production runs require
the Actions secret `RATINGS_DATABASE_URL`, a TLS-enabled Supabase session
pooler URI for an approved `ratings_writer` login. Provision its privileges
with [ratings_writer_grants.sql](sql/ratings_writer_grants.sql) after the
[schema migration](sql/ratings_schema.sql) is applied. The grants script
assumes the login already exists.

The first run discovers completed Division I games from the NCAA schedule
and ESPN scoreboards. Subsequent runs check the latest three game dates,
any missed calendar days since the last published run, and dates with due
retries. The recent window also discovers games posted late by both sources. The job
validates SportsDataverse and ESPN box scores separately, compares the
fields BPM uses, and logs disagreements for review. ESPN roster aliases
must match uniquely by team, jersey, surname, and first initial when a
full-name match fails. BPM and the RAPM replay use the same guarded roster match.
Previously verified name variants also require the
audited ESPN and NCAA jerseys. When reported minutes conflict or a box
fails validation, the job can use playing time reconstructed from ESPN
substitutions after checking every period, lineup, and player point total.
If both boxes provide counting stats, those stats must agree for the
replay to resolve the game. When an audited school box provides a
third value for every disputed field, the job uses the value supported
by two sources, validates the resulting box, and records the votes.
When two complete boxes pass validation and the available evidence does
not settle the disagreement, the job includes the NCAA box in BPM. The
audit records the default and disputed fields and keeps the game open
for review and retry. Games still need a validated box and resolved final
score to count. RAPM can fall back
to replaying ESPN starters and substitutions when the NCAA lineup feed
has no valid game. The replay keeps an and-one free throw with its basket
when ESPN places them at different clock times. Historical verified
corrections ship with the code.

`bpm_school_boxes_2027.csv` contains audited official box scores for
the November 11 backfill. The job checks team scores, player IDs,
playing time, and counting stats before accepting a school box. When
both feeds agree on counting stats, verified school minutes can resolve
a timing dispute while preserving those counts. Rows with an appearance
rounded to zero in the school box include a play-by-play source for
the measured seconds.
Increment `INPUT_RULES_VERSION` when changing validation or source
selection rules or shipping historical corrections. The first daily run
after a version change revalidates previously processed games, including
accepted games and open reviews. The workflow's **Revalidate previously
processed games** option can also force a replay.

`ratings.game_sources` identifies the evidence attached to each game.
`ratings.game_metric_status` tracks each metric, its next retry, and its last
accepted input revision. A failed retry preserves that revision.
`ratings.open_review_queue` lists open issues with evidence, source URLs,
and affected player or possession details when available. A reviewer can
record a resolution and timestamp in `ratings.review_issues`. To reprocess a
reviewed game, set its metric's `next_retry_at` to `now()`. The pipeline can
close an issue automatically after a successful recheck.

Each run downloads the season roster and matches listed positions to the
validated BPM boxes by team and NCAA player ID. BPM blends the position
estimated from box scores with 50 minutes at the listed default: 1.5 for
guards, 3.5 for forwards, and 5 for centers. Missing or unsupported labels
use position 3. The offensive-role default is 4. The snapshot and Actions
summary report how many BPM players used a roster position or the fallback.

RAPM uses the ten players on the floor and a 90-day half-life for game
weights. It fits observed scoring with ridge regularization centered at
zero. The output reports actual possession counts.

The model reads accepted revisions from Supabase and publishes the snapshot
and player rows together in one transaction. The snapshot includes the
input revisions, coverage counts, model version, and each metric's cutoff.
Publication fails if a game previously included in the latest snapshot for
that cutoff or earlier would disappear from either metric. Revision updates
and newly validated games can still publish. The Actions summary lists
coverage and each missing game with its reason. The workflow warns about
gaps even when it can publish the validated data.

```sql
select game_date, game_key, metric, evidence
from ratings.open_review_queue
order by game_date desc, game_key, metric;

select through_date, coverage
from ratings.snapshots
order by through_date desc
limit 1;
```

## Dashboard CSV

After publishing the Supabase snapshot, the daily workflow exports
`player-ratings.csv` to the `ratings-data` branch. The GitHub Pages Ratings
tab loads the CSV in the background, so daily ratings updates do not require a site rebuild.
The CSV contains the player ratings, their sample sizes, and snapshot coverage.
Missing ratings are blank. The CSV is accessible from the public GitHub repository.
