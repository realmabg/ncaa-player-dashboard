-- Run after provisioning an approved PostgreSQL LOGIN named ratings_writer.
-- The connection string belongs in the Actions secret RATINGS_DATABASE_URL.
grant usage on schema ratings to ratings_writer;
grant select, insert on all tables in schema ratings to ratings_writer;
grant update on ratings.games, ratings.game_sources, ratings.game_metric_status,
  ratings.review_issues, ratings.snapshots to ratings_writer;
grant delete on ratings.player_ratings to ratings_writer;

do $$
declare relation text;
begin
  for relation in select tablename from pg_catalog.pg_tables where schemaname = 'ratings' loop
    execute format('create policy ratings_writer_access on ratings.%I to ratings_writer using (true) with check (true)', relation);
  end loop;
end $$;
