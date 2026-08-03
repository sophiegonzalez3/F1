"""Tests for the session-normalised one-lap pace estimator.

The SEASON tab's momentum charts stand on `_session_normalised_pace`, so the
properties that make it worth having are pinned here: it must remove the
Q1→Q3 track-evolution offset, stay indifferent to which team is quickest, and
refuse to answer rather than guess when the fit is not identified.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

# compute_team_pace.py is a script, not a package module — load it by path
_spec = importlib.util.spec_from_file_location(
    "compute_team_pace", ROOT / "scripts" / "compute_team_pace.py")
ctp = importlib.util.module_from_spec(_spec)
sys.modules["compute_team_pace"] = ctp
_spec.loader.exec_module(ctp)

norm = ctp._session_normalised_pace


def _round(rows):
    """rows: {team: {"Q1": t, "Q2": t, "Q3": t}} -> a quali-results frame."""
    return pd.DataFrame([
        {"team": team, **{s: times.get(s, np.nan) for s in ("Q1", "Q2", "Q3")}}
        for team, times in rows.items()
    ])


def test_removes_session_offset():
    """Two teams of identical pace, one of which only ran Q1, must come out
    level — the raw best-of-Q gap would put the Q1 team ~1% behind purely
    because the track was slower then."""
    g = _round({
        # every team is 90.0 s in Q1 terms; Q2 is 0.9 s quicker (track evolution)
        "A": {"Q1": 90.0, "Q2": 89.1},
        "B": {"Q1": 90.0, "Q2": 89.1},
        "C": {"Q1": 90.0},              # knocked out in Q1
    })
    out = norm(g)
    assert out, "estimator should have produced a fit"
    assert out["C"] == pytest.approx(out["A"], abs=0.02)
    assert out["C"] == pytest.approx(out["B"], abs=0.02)

    # the raw measure, for contrast, penalises C by ~1%
    best = g[["Q1", "Q2", "Q3"]].min(axis=1)
    raw = (best / best.min() - 1) * 100
    assert raw.iloc[2] > 0.9


def test_recovers_known_pace_differences():
    """A team genuinely 1% slower should read ~1% slower, whichever session
    its lap came from."""
    g = _round({
        "fast": {"Q1": 90.0, "Q2": 89.1, "Q3": 89.0},
        "mid": {"Q1": 90.45, "Q2": 89.55},          # +0.5%
        "slow": {"Q1": 90.9},                        # +1.0%, Q1 exit
    })
    out = norm(g)
    # expressed vs the field median (= "mid" here)
    assert out["mid"] == pytest.approx(0.0, abs=0.05)
    assert out["fast"] == pytest.approx(-0.5, abs=0.10)
    assert out["slow"] == pytest.approx(+0.5, abs=0.10)


def test_median_baseline_absorbs_a_bad_day_at_the_front():
    """The reference is the median car, not whoever was quickest.

    This is the fix for the moving-baseline problem: in 2026 Mercedes was the
    pole reference for rounds 1-10, so every other team's line was really a
    Mercedes-relative line and a Mercedes off-weekend read as the whole field
    improving. Here the quickest team loses a second; as long as it stays on
    the same side of the median, nobody else's number may move — while a
    pole-anchored baseline shifts everyone.
    """
    base = {"A": 90.0, "B": 90.4, "C": 90.8, "D": 91.2,   # D is the median
            "E": 91.6, "F": 92.0, "G": 92.4}
    hurt = dict(base, A=91.0)                # A has a scruffy lap, still 2nd

    out1 = norm(_round({t: {"Q1": v} for t, v in base.items()}))
    out2 = norm(_round({t: {"Q1": v} for t, v in hurt.items()}))
    for team in ("C", "D", "E", "F", "G"):
        assert out2[team] == pytest.approx(out1[team], abs=0.02), (
            f"{team} moved when an unrelated team had a bad session")

    # the pole-anchored measure, for contrast, drags the whole field with it
    pole1 = pd.Series(base).min()
    pole2 = pd.Series(hurt).min()
    gap1 = (base["G"] / pole1 - 1) * 100
    gap2 = (hurt["G"] / pole2 - 1) * 100
    assert abs(gap2 - gap1) > 0.4, (
        "expected the pole baseline to move the backmarker's gap materially")


def test_rejects_unidentified_fit():
    """A single team, or a lone team in its own session, cannot be separated
    from the session effect — the estimator must return nothing so the caller
    falls back rather than plotting a fabricated number."""
    assert norm(_round({"A": {"Q1": 90.0}})) == {}


def test_rejects_implausible_output():
    """A wild fit (red-flagged session, one-lap sample) is discarded rather
    than drawn: nothing in a dry F1 field is 15% off the median."""
    g = _round({"A": {"Q1": 90.0, "Q2": 89.0},
                "B": {"Q1": 90.2, "Q2": 89.2},
                "C": {"Q1": 400.0}})        # aborted / in-lap garbage
    assert norm(g) == {}


def test_model_and_backtest_read_the_same_pace_columns():
    """The pace model's prior and the backtest's target must agree, and both
    must be the session-normalised columns.

    They used to disagree: the model learned from and was scored against
    gap-to-pole, which carries the Q1→Q3 track evolution the SEASON tab now
    corrects for. That artifact correlates +0.84 with a team's true pace, so it
    inflated the model's apparent rank skill while adding error it could never
    have predicted. If these drift apart again, the scorecard silently starts
    measuring something other than prediction quality.
    """
    import importlib.util as _ilu
    from f1lib.pace_model import PaceModel

    spec = _ilu.spec_from_file_location(
        "backtest_pace_model", ROOT / "scripts" / "backtest_pace_model.py")
    bt = _ilu.module_from_spec(spec)
    sys.modules["backtest_pace_model"] = bt
    spec.loader.exec_module(bt)

    assert bt.TARGET == {"onelap": "onelap_speed_pct",
                         "longrun": "race_pace_pct"}
    if not (ROOT / "data" / "team_pace_by_event.csv").exists():
        pytest.skip("pace table not built")
    m = PaceModel()
    assert m.col_onelap == bt.TARGET["onelap"], (
        f"model prior reads {m.col_onelap} but the backtest scores "
        f"{bt.TARGET['onelap']}")
    assert m.col_longrun == bt.TARGET["longrun"], (
        f"model prior reads {m.col_longrun} but the backtest scores "
        f"{bt.TARGET['longrun']}")


def test_real_table_has_both_measure_families():
    """The shipped table must carry the RESULT measures AND the speed/pace
    measures — the SEASON charts read the latter, and conflating them is the
    whole bug this estimator exists to fix.

    Read through the legacy-column map, exactly as every consumer does, so a
    table written before the speed/pace rename still passes rather than
    failing the suite on a naming change it is not about.
    """
    from f1lib.config import apply_pace_legacy_columns

    path = ROOT / "data" / "team_pace_by_event.csv"
    if not path.exists():
        pytest.skip("team_pace_by_event.csv not built")
    d = apply_pace_legacy_columns(pd.read_csv(path))
    for col in ("quali_result_gap_pct", "onelap_speed_pct",
                "race_pace_gap_pct", "race_pace_pct", "race_pace_missing"):
        assert col in d.columns, f"missing column {col}"

    latest = d[d["season"] == d["season"].max()]
    # gap-to-pole is non-negative by construction; speed-vs-median straddles 0
    assert (latest["quali_result_gap_pct"] >= -1e-9).all()
    assert latest["onelap_speed_pct"].min() < 0 < latest["onelap_speed_pct"].max()
    # and the median car should sit near zero
    assert abs(latest.groupby("round")["onelap_speed_pct"].median().mean()) < 0.35


# ── legacy column compatibility ──────────────────────────────

def test_legacy_columns_are_renamed_on_load():
    """A table written before the speed/pace rename must still load. The map
    is what lets the CSV schema move without a flag day."""
    from f1lib.config import apply_pace_legacy_columns

    legacy = pd.DataFrame({
        "season": [2026], "round": [1], "event": ["X"], "team": ["Ferrari"],
        "quali_gap_pct": [0.5], "quali_pace_pct": [-0.2],
        "race_pace_pct": [-0.1],
    })
    out = apply_pace_legacy_columns(legacy)
    assert "onelap_speed_pct" in out.columns
    assert "quali_result_gap_pct" in out.columns
    assert out["onelap_speed_pct"].iloc[0] == -0.2
    assert out["quali_result_gap_pct"].iloc[0] == 0.5
    # untouched columns stay put
    assert out["race_pace_pct"].iloc[0] == -0.1


def test_legacy_map_never_clobbers_a_current_column():
    """A hand-edited table carrying BOTH names must keep the current one —
    silently overwriting it with stale values would be the worst outcome."""
    from f1lib.config import apply_pace_legacy_columns

    both = pd.DataFrame({"quali_pace_pct": [99.0], "onelap_speed_pct": [-0.2]})
    out = apply_pace_legacy_columns(both)
    assert out["onelap_speed_pct"].iloc[0] == -0.2


def test_current_table_needs_no_renaming():
    """The shim must be a no-op on a freshly built table — if it fires, the
    writer and the readers have drifted apart."""
    from f1lib.config import apply_pace_legacy_columns, PACE_LEGACY_COLUMNS

    path = ROOT / "data" / "team_pace_by_event.csv"
    if not path.exists():
        pytest.skip("team_pace_by_event.csv not built")
    d = pd.read_csv(path, nrows=1)
    stale = [c for c in PACE_LEGACY_COLUMNS if c in d.columns]
    assert not stale, (
        f"data/team_pace_by_event.csv still uses {stale} — "
        "re-run scripts/compute_team_pace.py")
    assert list(apply_pace_legacy_columns(d).columns) == list(d.columns)
