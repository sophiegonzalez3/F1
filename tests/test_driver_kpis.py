"""Per-event KPI window + the pieces of the TEAM & TEAMATE tab that decide
who 'wins' a metric."""
import numpy as np
import pandas as pd

from f1lib.driver_kpis import overtake_pairs, window_rounds
from tabs.teammates import _winner


def _lap(drv, lap, pos, pit=False, status="1"):
    return {"Driver": drv, "LapNo": lap, "Position": pos,
            "PitIn": 1.0 if pit else np.nan, "PitOut": np.nan,
            "TrackStatus": status}


def test_pass_counted_only_on_track():
    laps = pd.DataFrame([
        _lap("A", 1, 1), _lap("B", 1, 2), _lap("C", 1, 3),
        # lap 2: B passes A on track; C gains nothing
        _lap("A", 2, 2), _lap("B", 2, 1), _lap("C", 2, 3),
        # lap 3: A pits, C moves ahead of A -> NOT a pass
        _lap("A", 3, 3, pit=True), _lap("B", 3, 1), _lap("C", 3, 2),
    ])
    assert overtake_pairs(laps) == [(2, "B", "A")]


def test_no_pass_under_safety_car():
    laps = pd.DataFrame([_lap("A", 1, 1), _lap("B", 1, 2),
                         _lap("A", 2, 2, status="4"), _lap("B", 2, 1, status="4")])
    assert overtake_pairs(laps) == []


def test_window_stops_at_round_one():
    k = pd.DataFrame({"season": [2025] * 3 + [2026] * 3,
                      "round": [22, 23, 24, 1, 2, 3]})
    assert window_rounds(k, 2026, 2, 5) == [1, 2]       # never reaches 2025
    assert window_rounds(k, 2026, 3, 2) == [2, 3]
    assert window_rounds(k, 2026, 3, 0) == [1, 2, 3]    # 0 = whole season


def test_winner_draw_band_and_ties():
    assert _winner(-0.50, -0.52, True, 0.05) == "draw"
    assert _winner(-0.50, -0.60, True, 0.05) == "b"
    assert _winner(3, 3, False, 0) == "draw"            # a tie no longer goes to B
    assert _winner(np.nan, 1.0, True, 0) is None


def test_split_half_detects_a_stable_trait():
    from f1lib.driver_kpis import split_half
    rng = np.random.default_rng(0)
    rows = []
    for season in (2023, 2024):
        for t in range(8):
            for d in range(2):
                skill = t * 0.3 + d * (0.05 + 0.1 * t)   # stable, pair-specific gap
                for rnd in range(1, 21):
                    rows.append({"season": season, "round": rnd,
                                 "team": f"T{t}", "driver": f"D{t}{d}",
                                 "race_gap_pct": skill + rng.normal(0, 0.05),
                                 "best_lap_pct": rng.normal(0, 1.0)})   # pure noise
    k = pd.DataFrame(rows)
    for c in ("laps_fp", "laps_q", "laps_sprint", "laps_race", "race_gained",
              "spr_gained", "race_points", "spr_points", "purple_quali",
              "purple_race"):
        k[c] = 0.0
    r = split_half(k)
    assert r["race"]["driver"] > 0.9 and r["race"]["teammate"] > 0.6
    assert r["best"]["driver"] < 0.6
