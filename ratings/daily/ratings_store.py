"""Read and write validated ratings data through a private Postgres connection."""
import base64
import json
import os
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit


def query(sql):
    uri = urlsplit(os.environ["RATINGS_DATABASE_URL"])
    if uri.scheme not in {"postgres", "postgresql"} or not uri.username:
        raise ValueError("RATINGS_DATABASE_URL must be a PostgreSQL connection URI")
    options = parse_qs(uri.query)
    env = dict(os.environ, PGHOST=options.get("host", [uri.hostname or ""])[0],
               PGPORT=options.get("port", [str(uri.port or 5432)])[0],
               PGDATABASE=unquote(uri.path.lstrip("/")) or "postgres",
               PGUSER=unquote(uri.username), PGPASSWORD=unquote(uri.password or ""),
               PGSSLMODE=options.get("sslmode", ["require"])[0], PGCONNECT_TIMEOUT="15")
    result = subprocess.run(["psql", "-XqAtw", "-v", "ON_ERROR_STOP=1"], input=sql,
                            stdout=subprocess.PIPE, text=True, check=True, env=env)
    return result.stdout


def payload(value):
    encoded = base64.b64encode(json.dumps(value, allow_nan=False, separators=(",", ":")).encode()).decode()
    return f"convert_from(decode('{encoded}','base64'),'UTF8')::jsonb"


def records(table, values, conflict=""):
    return f"""insert into ratings.{table}
        select row.* from jsonb_populate_recordset(null::ratings.{table}, {payload(values)}) row
        {conflict};"""


def game_batch(game, sources, metrics, run_id, stamp):
    season, game_key = game["season"], game["game_key"]
    sql = [
        "begin;",
        f"select pg_advisory_xact_lock({season}, hashtext({payload(game_key)} #>> '{{}}'));",
        records("games", [game], """on conflict (season,game_key) do update set
          game_date=excluded.game_date, home_score=excluded.home_score, away_score=excluded.away_score"""),
        records("game_sources", [dict(source, season=season, game_key=game_key, fetched_at=stamp)
                                  for source in sources],
                """on conflict (season,provider,provider_game_id) do update set
                   fetched_at=excluded.fetched_at, url=excluded.url
                   where ratings.game_sources.game_key=excluded.game_key"""),
    ]
    for metric, attempt in metrics.items():
        base = dict(season=season, game_key=game_key, metric=metric)
        rows, evidence = attempt["rows"], attempt["evidence"]
        if rows:
            sql.append(records("game_inputs", [dict(base, revision=attempt["revision"], rows=rows,
                evidence=evidence, game_date=game["game_date"], accepted_at=stamp)], "on conflict do nothing"))
        status = dict(base, status=attempt["status"], accepted_revision=attempt["revision"],
                      accepted_rows=len(rows), excluded_rows=attempt["excluded"], last_attempt_at=stamp,
                      next_retry_at=attempt["retry_at"], reason=attempt["reason"])
        sql.append(records("game_metric_status", [status], """on conflict (season,game_key,metric) do update set
            status=excluded.status, last_attempt_at=excluded.last_attempt_at,
            next_retry_at=excluded.next_retry_at, reason=excluded.reason,
            accepted_revision=coalesce(excluded.accepted_revision,ratings.game_metric_status.accepted_revision),
            accepted_rows=case when excluded.accepted_revision is null then ratings.game_metric_status.accepted_rows else excluded.accepted_rows end,
            excluded_rows=case when excluded.accepted_revision is null then ratings.game_metric_status.excluded_rows else excluded.excluded_rows end
            where ratings.game_metric_status.last_attempt_at <= excluded.last_attempt_at"""))
        sql.append(records("validation_attempts", [dict(base, run_id=run_id, attempted_at=stamp,
            decision=attempt["status"], evidence=evidence)], "on conflict do nothing"))
        predicate = (f"season={season} and game_key=({payload(game_key)} #>> '{{}}') "
                     f"and metric='{metric}' and issue_key='validation' and updated_at<='{stamp}'")
        if attempt["status"] in ("needs_review", "accepted_with_exclusions"):
            sql.append(records("review_issues", [dict(base, issue_key="validation", evidence=evidence,
                opened_at=stamp, updated_at=stamp)], """on conflict (season,game_key,metric,issue_key) do update set
                  evidence=excluded.evidence, updated_at=excluded.updated_at,
                  resolved_at=null, resolution=null where ratings.review_issues.updated_at <= excluded.updated_at
                    and (ratings.review_issues.resolved_at is null or ratings.review_issues.evidence <> excluded.evidence)"""))
        elif attempt["status"] == "accepted":
            sql.append(f"""update ratings.review_issues set resolved_at='{stamp}', updated_at='{stamp}',
                resolution='Passed automated revalidation' where {predicate} and resolved_at is null;""")
    sql.append("commit;")
    return "\n".join(sql)


def load_season(season, cutoff):
    games = json.loads(query(f"""select coalesce(jsonb_agg(to_jsonb(g) order by g.game_date,g.game_key),'[]')
        from ratings.games g where season={season} and game_date<='{cutoff}';"""))
    # One JSON row per accepted game and metric avoids a large aggregate in Postgres.
    lines = query(f"""select jsonb_build_object('game_key',s.game_key,'metric',s.metric,
        'revision',s.accepted_revision,'status',s.status,'reason',s.reason,
        'excluded_rows',s.excluded_rows,'rows',i.rows,
        'evidence',jsonb_build_object('minutes_disputes',coalesce(i.evidence->'minutes_disputes','[]'::jsonb),
                                    'sportsdataverse_review',i.evidence->'sportsdataverse_review'))
        from ratings.game_metric_status s join ratings.games g using (season,game_key)
        left join ratings.game_inputs i on (s.season,s.game_key,s.metric,s.accepted_revision)=
          (i.season,i.game_key,i.metric,i.revision)
        where s.season={season} and g.game_date<='{cutoff}' order by g.game_date,g.game_key,s.metric;""")
    return games, [json.loads(line) for line in lines.splitlines()]


def publish(snapshot, players):
    season, cutoff = snapshot["season"], snapshot["through_date"]
    sql = [
        "begin;", f"select pg_advisory_xact_lock(827513,{season});",
        f"""do $$ begin
        if exists (select 1 from ratings.snapshots where season={season}
                   and through_date='{cutoff}' and published_at>'{snapshot["published_at"]}')
        then raise exception 'A newer run already published this cutoff'; end if;
        if exists (
            select old.entry->>0, old.entry->>1
            from (
                select input_manifest from ratings.snapshots where season={season}
                  and through_date<='{cutoff}' order by through_date desc limit 1
            ) previous
            cross join lateral jsonb_array_elements(previous.input_manifest) old(entry)
            except
            select proposed.entry->>0, proposed.entry->>1
            from jsonb_array_elements({payload(snapshot["input_manifest"])}) proposed(entry)
        ) then raise exception 'Ratings coverage regressed: a previously published game is missing'; end if;
        end $$;""",
        records("snapshots", [snapshot], """on conflict (season,through_date) do update set
          published_at=excluded.published_at, model_version=excluded.model_version,
          coverage=excluded.coverage, input_manifest=excluded.input_manifest
          where ratings.snapshots.published_at<=excluded.published_at"""),
        f"""delete from ratings.player_ratings p using ratings.snapshots s
             where (p.season,p.through_date)=(s.season,s.through_date) and p.season={season}
             and p.through_date='{cutoff}' and s.published_at='{snapshot["published_at"]}';""",
        records("player_ratings", players, "on conflict do nothing"),
        "commit;",
    ]
    query("\n".join(sql))


def load_queue(season, cutoff, stamp):
    data = query(f"""select jsonb_build_object(
      'games', coalesce((select jsonb_agg(to_jsonb(g)) from ratings.games g
                         where g.season={season} and g.game_date<='{cutoff}'), '[]'),
      'last_cutoff', (select max(through_date) from ratings.snapshots where season={season} and through_date<='{cutoff}'),
      'last_version', (select model_version from ratings.snapshots
                       where season={season} and through_date<='{cutoff}'
                       order by through_date desc limit 1),
      'due', coalesce((select jsonb_agg(distinct g.game_date) from ratings.games g
                       join ratings.game_metric_status s using (season,game_key)
                       where g.season={season} and g.game_date<='{cutoff}'
                         and s.next_retry_at<='{stamp}'), '[]'));""")
    result = json.loads(data)
    return result["games"], result["due"], result["last_cutoff"], result["last_version"]


def load_source_review_inputs(season, dates):
    """Read prior source decisions and the accepted rows that still need comparison."""
    lines = query(f"""select jsonb_build_object('game_key', i.game_key, 'metric', i.metric,
          'rows', case when i.evidence->>'sportsdataverse_review'='pending' then i.rows end,
          'revision', i.revision, 'evidence', i.evidence)
        from ratings.game_metric_status s join ratings.games g using (season,game_key)
        join ratings.game_inputs i on (s.season,s.game_key,s.metric,s.accepted_revision)=
          (i.season,i.game_key,i.metric,i.revision)
        where i.season={season}
          and g.game_date in (select value::date from jsonb_array_elements_text({payload(sorted(d.isoformat() for d in dates))}))
          and (i.evidence->>'sportsdataverse_review'='pending'
               or i.evidence->>'selected' in ('ncaa','NCAA'));""")
    return {(row["game_key"], row["metric"]): row for row in map(json.loads, lines.splitlines())}
