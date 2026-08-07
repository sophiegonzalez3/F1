"""Smoke tests: every BRIEF figure must actually BUILD with plausible data.

These exist because of a real outage. The predicted-order charts were changed
from bars to dots with a shaded range, and the range was softened with
`error_x=dict(..., opacity=0.55)`. Plotly's ErrorX has no `opacity` property,
so constructing the trace raised — which took down the whole WEEKEND BRIEF tab
render. Dash caught the exception, the callback returned nothing, and the UI
silently stayed on the previously-selected tab. Nothing in the suite noticed,
because no test had ever built these figures with data.

An invalid Plotly property is not a subtle bug, but it is invisible to
anything that only imports the module. Each test here constructs one figure
from a small synthetic frame shaped like the real one; that is enough to catch
bad property paths, bad column references and shape mismatches.

Kept deliberately cheap — no session cache, no model fit — so the whole file
runs in well under a second and nobody is tempted to skip it.
"""
import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go

from tabs import brief

TEAMS = ["Ferrari", "Mercedes", "McLaren", "Red Bull Racing", "Williams",
         "Alpine", "Haas F1 Team"]
DRIVERS = ["LEC", "HAM", "RUS", "ANT", "NOR", "PIA", "VER", "HAD"]


def _stage(kind="onelap"):
    rng = np.random.default_rng(0)
    rows = []
    for k in ("onelap", "longrun"):
        for i, t in enumerate(TEAMS):
            rows.append({"team": t, "kind": k, "mean": -1.2 + 0.4 * i,
                         "var": 0.09, "sd": 0.3 + 0.02 * i})
    return pd.DataFrame(rows)


def _dpred():
    return pd.DataFrame({
        "driver": DRIVERS,
        "team": [TEAMS[i // 2] for i in range(len(DRIVERS))],
        "kind": "longrun",
        "mean": np.linspace(-1.1, 1.3, len(DRIVERS)),
        "effect": np.linspace(-0.25, 0.2, len(DRIVERS)),
        "car_var": 0.08, "drv_var": 0.01,
        "sd": np.linspace(0.25, 0.4, len(DRIVERS)),
    })


def _actual(index):
    rng = np.random.default_rng(7)
    return pd.Series(np.linspace(-1.0, 1.2, len(index))
                     + rng.normal(0, 0.15, len(index)), index=list(index))


# ─────────────────────────────────────────────────────────────

def test_order_fig_builds():
    for kind in ("onelap", "longrun"):
        fig = brief._order_fig(_stage(), kind)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1


def test_driver_order_fig_builds():
    fig = brief._driver_order_fig(_dpred())
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_progression_fig_builds():
    stages = {"prior": _stage(), "after FP1": _stage(), "after FP3": _stage()}
    fig = brief._progression_fig(stages, "onelap")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(TEAMS)


def test_team_ledger_fig_builds():
    st = _stage()
    act = _actual(TEAMS)
    fig = brief._ledger_fig(st, act, "onelap")
    assert isinstance(fig, go.Figure)
    # one connector per team, plus the predicted and actual marker traces
    assert len(fig.data) == len(TEAMS) + 2


def test_driver_ledger_fig_builds():
    fig = brief._driver_ledger_fig(_dpred(), _actual(DRIVERS))
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(DRIVERS) + 2


def test_ledgers_survive_an_empty_frame():
    """A weekend with no outcome yet must render an empty chart, not raise."""
    empty = pd.Series(dtype=float)
    assert isinstance(brief._ledger_fig(_stage(), empty, "onelap"), go.Figure)
    assert isinstance(brief._driver_ledger_fig(_dpred(), empty), go.Figure)


def test_walkthrough_fig_builds():
    fig = brief._walkthrough_fig()
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1


def test_track_record_fig_builds_with_and_without_calibration():
    base = pd.DataFrame({
        "season": 2026, "era": "2026-regs",
        "event": ["A", "B", "C", "D"] * 2, "round": [1, 2, 3, 4] * 2,
        "kind": ["onelap"] * 4 + ["longrun"] * 4,
        "stage": ["prior", "after FP1", "after FP3", "raw-FP"] * 2,
        "mae": 0.3, "rho": 0.8, "n_teams": 10,
    })
    assert isinstance(brief._track_record_fig(base), go.Figure)
    withcov = base.assign(cov68=0.7, cov95=0.94, crps=0.2, nll=0.5,
                          mean_z2=1.1, tau=0.6, rmse=0.4)
    fig = brief._track_record_fig(withcov)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 2          # a line per kind per panel


def test_per_event_fig_scores_the_sharpest_stage_each_weekend():
    """The recap must plot the LAST pre-outcome read each weekend reached —
    that is the number that was on screen before qualifying — not an average
    over stages, and not the prior."""
    b = pd.DataFrame({
        "season": 2026, "era": "2026-regs",
        "event": ["A", "A", "B", "B"], "round": [1, 1, 2, 2],
        "kind": "onelap",
        "stage": ["prior", "after FP3", "prior", "after FP1"],
        "mae": [0.9, 0.2, 0.8, 0.5], "rho": 0.8, "tau": 0.6, "n_teams": 10,
    })
    fig = brief._per_event_fig(b)
    assert isinstance(fig, go.Figure) and len(fig.data) == 1
    # one point per event, taking the sharpest stage (FP3 for A, FP1 for B)
    assert list(fig.data[0].y) == [0.2, 0.5]
    assert list(fig.data[0].x) == ["R1", "R2"]


def test_per_event_fig_survives_no_usable_stages():
    b = pd.DataFrame({"season": 2026, "era": "2026-regs", "event": ["A"],
                      "round": [1], "kind": ["onelap"], "stage": ["raw-FP"],
                      "mae": [0.5], "rho": [0.5], "tau": [0.4],
                      "n_teams": [10]})
    assert isinstance(brief._per_event_fig(b), go.Figure)


def test_calibration_strip_builds_and_degrades():
    """The strip is the only chart that says whether the ± can be trusted, so
    it must render when coverage exists and stay silent (not raise) when it
    does not — old backtest CSVs predate the calibration columns."""
    base = pd.DataFrame({
        "season": 2026, "era": "2026-regs", "event": ["A", "B"] * 2,
        "round": [1, 2] * 2, "kind": ["onelap"] * 2 + ["longrun"] * 2,
        "stage": ["prior", "after FP3"] * 2, "mae": 0.3, "rho": 0.8,
        "n_teams": 10,
    })
    empty = brief._calibration_strip_fig(base)
    assert isinstance(empty, go.Figure) and len(empty.data) == 0
    fig = brief._calibration_strip_fig(base.assign(cov68=0.72))
    assert isinstance(fig, go.Figure) and len(fig.data) == 1


# ─────────────────────────────────────────────────────────────
# The plain-language readings must be strings, never crash, and
# degrade to None rather than half a sentence when data is thin.
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn,args", [
    ("_order_plain", lambda: (_stage(), "onelap", "over one lap")),
    ("_driver_order_plain", lambda: (_dpred(),)),
    ("_progression_plain", lambda: ({"prior": _stage(),
                                     "after FP3": _stage()}, "onelap")),
])
def test_plain_readings_return_text(fn, args):
    out = getattr(brief, fn)(*args())
    assert out is None or (isinstance(out, str) and len(out) > 40)


def test_ledger_plain_reports_coverage():
    st = _stage()
    parts = brief._ledger_parts(st, _actual(TEAMS), "onelap")
    assert parts is not None
    txt = brief._ledger_plain(parts[0], parts[1], parts[2],
                              lambda k: str(k), "the car")
    assert isinstance(txt, str)
    assert "error bar" in txt


def test_review_card_renders_blank_cells_as_unreviewed(tmp_path, monkeypatch):
    """An empty CSV cell arrives as NaN, and float('nan') is TRUTHY — so the
    natural `x.get("note") or ""` renders the literal string "nan" and every
    unreviewed row looks like somebody wrote "nan" in it. Shipped exactly that
    once; pinned here."""
    p = tmp_path / "model_review.csv"
    pd.DataFrame([
        {"season": 2026, "round": 11, "event": "Hungarian Grand Prix",
         "driver": "ALO", "team": "Aston Martin", "kind": "longrun",
         "predicted": 2.16, "actual": 0.66, "miss": -1.5, "sd": 0.78,
         "category": "", "note": ""},
        {"season": 2026, "round": 11, "event": "Hungarian Grand Prix",
         "driver": "NOR", "team": "McLaren", "kind": "onelap",
         "predicted": -0.9, "actual": -1.8, "miss": -0.9, "sd": 0.4,
         "category": "strategy", "note": "Pitted under the safety car."},
    ]).to_csv(p, index=False)
    monkeypatch.setattr(brief, "_REVIEW_PATH", p)
    c = brief._model_review_card(2026, "Hungarian Grand Prix")
    assert c is not None
    txt = str(c)
    assert "nan" not in txt.lower().replace("hungarian", "")
    assert "unreviewed" in txt
    assert "Pitted under the safety car." in txt


def test_review_card_is_none_for_an_unreviewed_event(tmp_path, monkeypatch):
    p = tmp_path / "model_review.csv"
    pd.DataFrame(columns=["season", "round", "event", "driver", "team",
                          "kind", "predicted", "actual", "miss", "sd",
                          "category", "note"]).to_csv(p, index=False)
    monkeypatch.setattr(brief, "_REVIEW_PATH", p)
    assert brief._model_review_card(2026, "Nowhere Grand Prix") is None


def test_plain_readings_are_none_on_thin_data():
    thin = pd.DataFrame({"team": ["A", "B"], "kind": "onelap",
                         "mean": [0.0, 1.0], "sd": [0.2, 0.2]})
    assert brief._order_plain(thin, "onelap", "x") is None
    assert brief._driver_order_plain(_dpred().head(2)) is None
