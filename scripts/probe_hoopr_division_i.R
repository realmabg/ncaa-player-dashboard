# Validate the two BartTorvik feeds from the runner before considering a switch.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 1L)
output <- args[[1L]]
dir.create(output, recursive = TRUE, showWarnings = FALSE)

attempt <- function(name, fetch) {
  tryCatch(fetch(), error = function(error) {
    message(name, ": ", conditionMessage(error))
    FALSE
  })
}

players_ok <- attempt("hoopR BartTorvik player table", function() {
  players <- hoopR::torvik_player_stats(year = 2027)
  required <- c(
    "player_name", "team", "conf", "games", "usage", "e_fg", "ts_pct",
    "orb_pct", "drb_pct", "ast_pct", "to_pct", "two_pa", "two_p_pct",
    "three_pa", "three_p_pct", "height", "bpm", "minutes", "year",
    "player_id", "rim_made", "mid_made", "role"
  )
  stopifnot(nrow(players) > 0L, ncol(players) >= 67L,
            all(required %in% names(players)),
            identical(as.integer(unique(players$year)), 2027L),
            !anyDuplicated(players$player_id))
  # hoopR preserves the original field order. Drop its added header for the
  # existing positional snapshot importer.
  write.table(players, file.path(output, "players.csv"), sep = ",",
              col.names = FALSE, row.names = FALSE, qmethod = "double", na = "")
  message("hoopR returned ", nrow(players), " BartTorvik player rows.")
  TRUE
})

shooting_ok <- attempt("BartTorvik shooting JSON", function() {
  response <- httr2::request("https://barttorvik.com/2027_pbp_playerstat_array.json") |>
    httr2::req_user_agent("Mozilla/5.0 (hoopR; +https://hoopR.sportsdataverse.org)") |>
    httr2::req_timeout(45) |>
    httr2::req_perform()
  payload <- httr2::resp_body_string(response)
  shots <- jsonlite::fromJSON(payload, simplifyVector = FALSE)
  stopifnot(length(shots) > 0L, all(lengths(shots) == 15L))
  writeLines(payload, file.path(output, "shooting.json"), useBytes = TRUE)
  message("BartTorvik returned ", length(shots), " shooting rows.")
  TRUE
})

if (!players_ok || !shooting_ok) quit(status = 1L)
