"""Tests for the upgrade panel event study (f1lib/upgrade_study.py).

The estimator has to survive two things to be worth showing: it must recover
an effect that is really there, and it must NOT find one that is not. Both
are pinned on synthetic panels where the truth is set by construction. The
event-study reference group gets its own test, because contaminating it is
silent — every coefficient stays plausible while meaning nothing.
"""
import numpy as np
import pandas as pd
import pytest

from f1lib import upgrade_study as us

ROOT_KIND = "longrun"


def _panel(effect_per_item: float, n_teams: int = 11, n_rounds: int = 11,
           noise: float = 0.25, seed: int = 0) -> pd.DataFrame:
    """A synthetic season where each declared part is worth exactly
    `effect_per_item` pp, on top of team levels and round shocks."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    level = dict(zip(teams, rng.normal(0, 1.2, n_teams)))
    shock = dict(zip(range(1, n_rounds + 1), rng.normal(0, 0.4, n_rounds)))
    rows = []
    for t in teams:
        cum = 0
        for r in range(1, n_rounds + 1):
            items = int(rng.poisson(1.5)) if r >= us.FIRST_DEV_ROUND else 3
            if r >= us.FIRST_DEV_ROUND:
                cum += items
            rows.append({
                "team": t, "round": r, "event": f"E{r}",
                "items": items, "dev_items": items if r >= us.FIRST_DEV_ROUND else 0,
                "cum_items": cum,
                "onelap_speed_pct": np.nan,
                "race_pace_pct": (level[t] + shock[r]
                                  + effect_per_item * cum
                                  + rng.normal(0, noise)),
            })
    p = pd.DataFrame(rows)
    p["major"] = p["dev_items"] >= us.MAJOR_ITEMS
    ktab = []
    for team, g in p.groupby("team"):
        majors = g.loc[g["major"], "round"].tolist()
        for r in g["round"]:
            k = (min((r - m for m in majors), key=lambda d: (abs(d), -d))
                 if majors else np.nan)
            ktab.append({"team": team, "round": r, "k": k})
    return p.merge(pd.DataFrame(ktab), on=["team", "round"])


def test_recovers_a_planted_effect():
    """Plant −0.08 pp per part and the dose spec must find it back."""
    out = us.dose_response(_panel(-0.08), ROOT_KIND, boot=False)
    assert out.iloc[0]["coef"] == pytest.approx(-0.08, abs=0.02)


def test_finds_nothing_when_upgrades_do_nothing():
    """The more important direction: a season where parts are worthless must
    not produce a confident effect, or every future result is suspect."""
    out = us.dose_response(_panel(0.0, seed=4), ROOT_KIND, boot=True)
    r = out.iloc[0]
    assert abs(r["coef"]) < 0.03
    assert r["p_wild"] > 0.10


def test_event_study_reference_is_not_contaminated():
    """Only rounds inside the window may enter the fit. Without the
    restriction every round far from a package joins the omitted category,
    so coefficients are measured against 'the round before an upgrade' AND
    'nowhere near an upgrade' at once — plausible-looking and meaningless."""
    p = _panel(-0.08)
    ev = us.event_study(p, ROOT_KIND, boot=False)
    assert not ev.empty
    in_window = p.dropna(subset=["k"])
    in_window = in_window[(in_window["k"] >= min(us.EVENT_WINDOW))
                          & (in_window["k"] <= max(us.EVENT_WINDOW))]
    assert ev.attrs["n"] == len(in_window)
    assert ev.attrs["n"] < len(p.dropna(subset=["k"]))


def test_event_study_omits_exactly_the_reference_round():
    ev = us.event_study(_panel(-0.08), ROOT_KIND, boot=False)
    terms = set(ev["term"])
    assert f"k_{us.REFERENCE_K}" not in terms
    assert "k_0" in terms


def test_outcome_noise_does_not_manufacture_significance():
    """Pure noise panels must not clear the bar more often than chance —
    a smoke test against the wild bootstrap being miscalibrated."""
    hits = 0
    for seed in range(8):
        out = us.dose_response(_panel(0.0, noise=0.8, seed=100 + seed),
                               ROOT_KIND, boot=True)
        hits += int(out.iloc[0]["p_wild"] < 0.05)
    assert hits <= 2, f"{hits}/8 pure-noise panels came out significant"


def test_shipped_estimates_carry_their_robustness_checks():
    """A shipped dose estimate must always be accompanied by its placebo and
    leave-one-out rows — the card reads them, and a bare coefficient is
    exactly the thing this module exists to avoid."""
    d = us.study_df()
    if d.empty:
        pytest.skip("upgrade_study.csv not built")
    for (season, kind), g in d[d["spec"] == "dose"].groupby(["season", "kind"]):
        same = d[(d["season"] == season) & (d["kind"] == kind)]
        assert not same[same["spec"] == "placebo"].empty, (
            f"{season} {kind}: dose estimate with no placebo null")
        assert not same[same["spec"] == "loo_summary"].empty, (
            f"{season} {kind}: dose estimate with no leave-one-out check")
