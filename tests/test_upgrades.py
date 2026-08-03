"""Upgrade Impact board: the control group has to exist.

The board reports what an upgrade was worth by subtracting a "field control" —
the median move of teams that brought NOTHING that round — from the upgrading
team's move. The idea is sound and the implementation was not: on a busy round
almost nobody sits out.

Measured on the 2026 season, 58 of 83 rows had fewer than three control teams.
Round 11 had one (Alpine). Round 6 (Monaco) had ZERO, and the old code then
quietly used `control = 0.0`, i.e. no adjustment at all, and drew that row
identically to a properly controlled one.

Two properties pinned here:

1. below MIN_CONTROL teams the control falls back to the whole field's median
   rather than one arbitrary team — or worse, nothing;
2. rows resting on that fallback, or on an incomplete "after" window, are
   marked so they cannot be read with the confidence of a settled row.
"""
import numpy as np
import pandas as pd
import pytest

import tabs.upgrades as U


def test_min_control_is_more_than_a_single_team():
    assert U.MIN_CONTROL >= 3


@pytest.fixture(scope="module")
def eff():
    e = U._effect_rows(2026)
    if e.empty:
        pytest.skip("no 2026 upgrade rows")
    return e


def test_board_reports_its_control_size_and_window(eff):
    for col in ("n_control", "control_basis", "n_after"):
        assert col in eff.columns, f"board must expose {col}"


def test_thin_control_falls_back_to_the_field(eff):
    thin = eff[eff["n_control"] < U.MIN_CONTROL]
    if thin.empty:
        pytest.skip("every round had a full control group")
    assert (thin["control_basis"] == "field").all(), (
        "a control group below MIN_CONTROL must not be used as-is")


def test_healthy_control_is_left_alone(eff):
    ok = eff[eff["n_control"] >= U.MIN_CONTROL]
    assert not ok.empty
    assert (ok["control_basis"] == "clean").all()


def test_zero_control_teams_no_longer_means_zero_correction(eff):
    """Monaco 2026: every team upgraded. The old code read that as 'the field
    did not move', which is not the same statement at all."""
    none = eff[eff["n_control"] == 0]
    if none.empty:
        pytest.skip("no round had a completely empty control group")
    assert (none["control"] != 0).any(), (
        "an empty control group still produced a zero correction")


def test_latest_round_is_flagged_as_provisional(eff):
    """Nothing has been raced since the newest package, so its 'after' window
    is one event against a two-event baseline."""
    last = int(eff["round"].max())
    newest = eff[eff["round"] == last]
    assert not newest.empty
    assert (newest["n_after"] < U._WINDOW).all(), (
        "the most recent upgrade round should have an incomplete after-window")


def test_settled_rows_have_a_full_after_window(eff):
    settled = eff[eff["round"] <= int(eff["round"].max()) - U._WINDOW]
    if settled.empty:
        pytest.skip("season too short")
    assert (settled["n_after"] >= U._WINDOW).all()


def test_figure_marks_provisional_rows(eff):
    """The distinction has to reach the chart, not just the frame."""
    fig = U._effect_board_fig(eff, 2026)
    bar = fig.data[0]
    shapes = list(bar.marker.pattern.shape or [])
    assert shapes, "no pattern applied — provisional rows are indistinguishable"
    prov = ((eff["n_after"] < U._WINDOW)
            | (eff["control_basis"] != "clean")).to_numpy()
    assert sum(1 for s in shapes if s) == int(prov.sum())


def test_hover_exposes_the_sample_sizes(eff):
    fig = U._effect_board_fig(eff, 2026)
    ht = fig.data[0].hovertemplate
    assert "round(s)" in ht and "team(s)" in ht, (
        "the hover must say how much data each row rests on")
