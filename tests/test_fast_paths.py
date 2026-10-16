"""Speed rewrites that must stay numerically identical to the original code.

1. driver_ratings._fit solves the car+driver fixed-effects system through the
   Schur complement of its diagonal car block and gets rank(X) from the graph's
   connected components. Pinned against the original dense solve
   (inv(XᵀWX + Λ), np.linalg.matrix_rank) on a synthetic pace table with two
   disconnected driver groups.
2. season_ops._phase_arrays / _phase_residuals_w replace a pandas groupby per
   resample with weighted sums over a precomputed (round, team, section)
   tensor. Pinned against the original groupby formula, including a bootstrap
   weighting (a round drawn twice).
3. RaceForecaster.simulate's shared retirement draws no longer depend on
   set() order (which follows per-process string hashing) — the seeded
   forecast used to change on every app restart.
"""
import numpy as np
import pandas as pd

import f1lib.driver_ratings as dr


def _pace_table(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    # two driver pools that never share a car → 2 graph components
    pools = [["AAA", "BBB", "CCC", "DDD"], ["EEE", "FFF", "GGG"]]
    for rnd in range(1, 13):
        for gi, pool in enumerate(pools):
            for team_i in range(2):
                pair = rng.choice(pool, 2, replace=False)
                for drv in pair:
                    rows.append({"season": 2025, "round": rnd, "event": f"E{rnd}",
                                 "team": f"T{gi}{team_i}", "driver": drv,
                                 "kind": "race",
                                 "gap_pct": rng.normal(0, 0.3)})
    p = tmp_path / "pace.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _dense_fit(sub, as_of_idx):
    """The original estimator, step for step (after the same row filters)."""
    w = 0.5 ** ((as_of_idx - sub["event_idx"]).clip(lower=0) / dr.HALF_LIFE_EVENTS)
    car = pd.get_dummies(sub["season"].astype(str) + "|" + sub["event"].astype(str)
                         + "|" + sub["team"].astype(str), prefix="car")
    drv = pd.get_dummies(sub["driver"], prefix="d")
    X = pd.concat([car, drv], axis=1).astype(float)
    cols = list(X.columns); Xv = X.values; y = sub["gap_pct"].values
    lam = np.array([dr.RIDGE if c.startswith("d_") else 0.0 for c in cols])

    def solve(W):
        inv = np.linalg.inv(Xv.T @ (W[:, None] * Xv) + np.diag(lam))
        return inv @ (Xv.T @ (W * y)), inv

    W = w.values
    beta, inv = solve(W)
    resid = y - Xv @ beta
    mad = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    if mad > 1e-6:
        r = np.abs(resid) / (dr._HUBER_K * mad)
        W = W * np.where(r <= 1, 1.0, 1.0 / r)
        beta, inv = solve(W)
        resid = y - Xv @ beta
    dof = max(len(y) - np.linalg.matrix_rank(Xv), 1.0)
    s2 = float((W * resid**2).sum() / (W.mean() * dof))
    var = np.clip(np.diag(inv) * s2, 0.0, None)
    d_idx = [i for i, c in enumerate(cols) if c.startswith("d_")]
    eff = pd.DataFrame({"driver": [cols[i][2:] for i in d_idx],
                        "effect": [beta[i] for i in d_idx],
                        "se": [np.sqrt(var[i]) for i in d_idx]})
    eff["effect"] -= np.average(eff["effect"])
    return eff.sort_values("effect").reset_index(drop=True)


def test_schur_fit_matches_dense_solve(tmp_path, monkeypatch):
    ratings = dr.DriverRatings(_pace_table(tmp_path))
    # disable the teammate-deviation clip so both paths see identical rows
    monkeypatch.setitem(dr.MAX_TEAMMATE_DEV, "race", 1e9)
    sub = ratings.pace[ratings.pace["kind"] == "race"]
    fast = ratings._fit(sub, ratings._max_idx, kind="race")
    ref = _dense_fit(sub.dropna(subset=["gap_pct"]), ratings._max_idx)
    assert fast["driver"].tolist() == ref["driver"].tolist()
    np.testing.assert_allclose(fast["effect"], ref["effect"], atol=1e-12)
    np.testing.assert_allclose(fast["se"], ref["se"], atol=1e-12)


def test_effects_memo_returns_independent_copies(tmp_path):
    ratings = dr.DriverRatings(_pace_table(tmp_path))
    a = ratings.effects("race")
    a.loc[:, "effect"] = 99.0
    assert (ratings.effects("race")["effect"] != 99.0).all()


def _phase_groupby(d):
    """The original pandas formula behind the Car Character residuals."""
    g = d.groupby(["team", "section"])[["team_s", "median_s"]].sum()
    raw = ((g["team_s"] / g["median_s"] - 1) * 100).unstack()
    lap = d.groupby("team")[["team_s", "median_s"]].sum()
    lap = (lap["team_s"] / lap["median_s"] - 1) * 100
    res = pd.DataFrame(index=raw.index)
    for k in raw.columns:
        ok = raw[k].notna() & lap.reindex(raw.index).notna()
        if ok.sum() < 6:
            continue
        b = np.polyfit(lap[raw.index[ok]], raw[k][ok], 1)
        res[k] = raw[k] - np.polyval(b, lap.reindex(raw.index))
    return res, lap, raw


def test_phase_tensor_matches_groupby():
    import tabs.season_ops as so
    rng = np.random.default_rng(5)
    rows = []
    for rnd in range(1, 9):
        for t in "ABCDEFGH":
            if rnd == 3 and t == "H":
                continue                        # a team missing a round
            for sec in ("low_speed", "traction", "top_speed"):
                m = rng.uniform(5, 10)
                rows.append({"round": rnd, "team": t, "section": sec,
                             "median_s": m, "team_s": m * rng.normal(1.0, 0.01)})
    d = pd.DataFrame(rows)
    tens = so._phase_tensor(d)
    for picks in ([1, 2, 3, 4, 5, 6, 7, 8], [1, 3, 5, 7], [2, 2, 3, 6, 6, 6, 8, 1]):
        w = np.bincount(np.searchsorted(tens["rounds"], picks),
                        minlength=len(tens["rounds"]))
        res, lap, raw = so._phase_residuals_w(tens, w)
        ref = _phase_groupby(pd.concat([d[d["round"] == r] for r in picks]))
        for got, want in zip((res, lap, raw), ref):
            np.testing.assert_allclose(got.to_numpy(float), want.to_numpy(float),
                                       atol=1e-10)
            assert list(got.index) == list(want.index)


_SIM_SNIPPET = """
import numpy as np, pandas as pd
from f1lib.race_forecast import RaceForecaster
rf = RaceForecaster(); rf.p["n_sims"] = 300; rf.p["dnf_corr"] = 0.5
teams = ["Zeta", "Alpha", "Mid", "Beta", "Kappa", "Omega"]
pred = pd.DataFrame({"driver": [f"D{i}" for i in range(12)],
                     "team": [t for t in teams for _ in range(2)],
                     "mean": np.linspace(-1, 1, 12), "car_var": 0.04, "drv_var": 0.01})
sim = rf.simulate(pred, event="Italian Grand Prix", rng=np.random.default_rng(1))
print(int(sim["dnf"].sum()), int((sim["finish"] * np.arange(1, 13)).sum()))
"""


def test_simulate_independent_of_hash_seed():
    """Same seed, different PYTHONHASHSEED → same simulation (set order of
    team names used to decide the order of the shared retirement draws)."""
    import os, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    outs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run([sys.executable, "-c", _SIM_SNIPPET], cwd=root, env=env,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-2000:]
        outs.append(r.stdout.strip().splitlines()[-1])
    assert outs[0] == outs[1]
