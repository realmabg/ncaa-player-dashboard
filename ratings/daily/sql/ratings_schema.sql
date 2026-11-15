create schema ratings;
revoke all on schema ratings from public, anon, authenticated;

create table ratings.games (
  season integer not null,
  game_key text not null,
  game_date date not null,
  home_team_id text not null,
  away_team_id text not null check (away_team_id <> home_team_id),
  home_score integer not null check (home_score >= 0),
  away_score integer not null check (away_score >= 0),
  primary key (season, game_key)
);
create index ratings_games_date on ratings.games (season, game_date);

create table ratings.game_sources (
  season integer not null,
  game_key text not null,
  provider text not null,
  provider_game_id text not null,
  url text not null,
  fetched_at timestamptz not null default now(),
  primary key (season, provider, provider_game_id),
  foreign key (season, game_key) references ratings.games
);
create index ratings_game_sources_game on ratings.game_sources (season, game_key);

-- Each version is an immutable batch of one player's box row per game
-- or one accepted lineup row per possession, stored together per game.
create table ratings.game_inputs (
  season integer not null,
  game_key text not null,
  metric text not null check (metric in ('bpm', 'rapm')),
  revision text not null,
  game_date date not null,
  rows jsonb not null check (jsonb_typeof(rows) = 'array' and jsonb_array_length(rows) > 0),
  evidence jsonb not null,
  accepted_at timestamptz not null default now(),
  primary key (season, game_key, metric, revision),
  foreign key (season, game_key) references ratings.games
);

create table ratings.game_metric_status (
  season integer not null,
  game_key text not null,
  metric text not null check (metric in ('bpm', 'rapm')),
  status text not null check (status in ('accepted', 'accepted_with_exclusions', 'retry', 'needs_review')),
  accepted_revision text,
  accepted_rows integer not null default 0 check (accepted_rows >= 0),
  excluded_rows integer not null default 0 check (excluded_rows >= 0),
  last_attempt_at timestamptz not null default now(),
  next_retry_at timestamptz,
  reason text,
  primary key (season, game_key, metric),
  foreign key (season, game_key) references ratings.games,
  foreign key (season, game_key, metric, accepted_revision) references ratings.game_inputs
);
create index ratings_retry_due on ratings.game_metric_status (season, next_retry_at)
  where next_retry_at is not null;

create table ratings.validation_attempts (
  season integer not null,
  game_key text not null,
  metric text not null,
  run_id text not null,
  attempted_at timestamptz not null default now(),
  decision text not null,
  evidence jsonb not null,
  primary key (season, game_key, metric, run_id),
  foreign key (season, game_key, metric) references ratings.game_metric_status
);

create table ratings.review_issues (
  season integer not null,
  game_key text not null,
  metric text not null,
  issue_key text not null,
  evidence jsonb not null,
  opened_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolution text,
  primary key (season, game_key, metric, issue_key),
  foreign key (season, game_key, metric) references ratings.game_metric_status
);
create index ratings_open_review on ratings.review_issues (season, updated_at)
  where resolved_at is null;

create table ratings.snapshots (
  season integer not null,
  through_date date not null,
  published_at timestamptz not null default now(),
  model_version text not null,
  coverage jsonb not null,
  input_manifest jsonb not null,
  primary key (season, through_date)
);
create table ratings.player_ratings (
  season integer not null,
  through_date date not null,
  player_key text not null,
  player_name text not null,
  team text not null,
  bpm double precision,
  rapm double precision,
  details jsonb not null,
  primary key (season, through_date, player_key),
  foreign key (season, through_date) references ratings.snapshots on delete cascade
);

do $$
declare relation text;
begin
  for relation in select tablename from pg_catalog.pg_tables where schemaname = 'ratings' loop
    execute format('alter table ratings.%I enable row level security', relation);
  end loop;
end $$;
revoke all on all tables in schema ratings from public, anon, authenticated;

create view ratings.open_review_queue with (security_invoker = true) as
select i.*, g.game_date, g.home_team_id, g.away_team_id
from ratings.review_issues i join ratings.games g using (season, game_key)
where i.resolved_at is null;

create view ratings.accepted_inputs with (security_invoker = true) as
select i.*
from ratings.game_inputs i join ratings.game_metric_status s
  on (i.season,i.game_key,i.metric,i.revision)=(s.season,s.game_key,s.metric,s.accepted_revision);

revoke all on ratings.open_review_queue, ratings.accepted_inputs from public, anon, authenticated;
