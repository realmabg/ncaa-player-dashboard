"""Shiny layout for the Division I tab."""

from shiny import ui


def make_division_i_tab(sidebar, content):
    return ui.div(
        {"id": "d1-tab", "class": "tab-panel active"},
        ui.div({"class": "body-grid"}, sidebar, content),
    )


def snapshot_note(retrieved_at):
    local_time = retrieved_at.tz_convert("America/Los_Angeles")
    return ui.div(
        "Torvik data pulled ",
        ui.tags.time(local_time.strftime("%b %d, %I:%M %p PT"), datetime=local_time.isoformat()),
        class_="sb-snapshot-note",
    )
