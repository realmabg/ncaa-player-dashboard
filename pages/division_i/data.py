"""Load the shared Division I dataset for the dashboard."""

from data_engine import load_d1_data


def load_division_i(root, *, snapshot, season):
    return load_d1_data(
        snapshot or str(root / "mbb_with_pca_all_players_2026_with_pbp.csv"),
        transfer_path=str(root / "transfer_portal_cache.csv"),
        recruiting_path=str(root / "recruiting_rankings_cache.csv"),
        snapshot_season=season if snapshot else None,
    )
