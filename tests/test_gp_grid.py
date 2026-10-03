"""Regression tests for f1lib.state.gp_grid — the Grand Prix starting grid.

The bug this pins: on a SPRINT weekend the Sprint session carries its own
`GridPosition` (a different grid), so a forecast that read grid positions off
the loaded results indiscriminately started everyone in their sprint slot.
Zandvoort 2026 was the worked example — Leclerc lined up 3rd for the sprint but
qualified 6th for the Grand Prix, and the pre-race forecast put him on the
podium ~53% of the time off the wrong P3.

gp_grid must always prefer the real GP grid (Race GridPosition once the race is
loaded, else the main Qualifying classification) and never the sprint grid.
"""
import pandas as pd
import pytest

import f1lib.state as state


_ORDER = ["NOR", "RUS", "ANT", "PIA", "HAM", "LEC", "VER", "LAW"]


def _quali(order=_ORDER):
    """Qualifying rows: classification `Position`, no GridPosition."""
    return [("Qualifying", a, i, None) for i, a in enumerate(order, 1)]


def _grid(session, order):
    """A grid-bearing session (Sprint/Race): `GridPosition`, no Position."""
    return [(session, a, None, i) for i, a in enumerate(order, 1)]


def _frame(rows):
    return pd.DataFrame(
        rows, columns=["session", "Abbreviation", "Position", "GridPosition"])


# LEC qualifies 6th for the GP but started the sprint 3rd.
_QUALI = _quali()                                                      # LEC = 6
_SPRINT = _grid("Sprint", ["RUS", "NOR", "LEC", "PIA", "ANT",
                           "VER", "HAM", "LAW"])                       # LEC = 3
_RACE = _grid("Race", _ORDER)                                         # LEC = 6


@pytest.fixture(autouse=True)
def _restore_results_raw():
    saved = state.results_raw
    yield
    state.results_raw = saved


def test_sprint_weekend_prerace_uses_quali_not_the_sprint_grid():
    state.results_raw = _frame(_QUALI + _SPRINT)
    g = state.gp_grid(min_drivers=3)
    assert g["LEC"] == 6, "must be the GP grid (quali P6), never the sprint P3"
    assert g["ANT"] == 3


def test_race_grid_supersedes_the_sprint_grid_after_the_race():
    state.results_raw = _frame(_QUALI + _SPRINT + _RACE)
    g = state.gp_grid(min_drivers=3)
    assert g["LEC"] == 6                       # Race GridPosition, not sprint


def test_conventional_prerace_uses_the_quali_classification():
    state.results_raw = _frame(_QUALI)
    assert state.gp_grid(min_drivers=3)["LEC"] == 6


def test_prequali_has_no_grid_and_falls_back_to_none():
    state.results_raw = _frame([("Practice 1", a, None, None)
                                for a in _ORDER])
    assert state.gp_grid(min_drivers=3) is None


def test_min_drivers_gate_returns_none_on_a_thin_book():
    state.results_raw = _frame(_quali(["NOR", "RUS"]))     # only 2 drivers
    assert state.gp_grid(min_drivers=8) is None


def test_no_results_is_none_not_an_exception():
    state.results_raw = None
    assert state.gp_grid() is None
    state.results_raw = pd.DataFrame()
    assert state.gp_grid() is None
