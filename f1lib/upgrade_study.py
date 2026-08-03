"""Did the upgrades work? A panel event study on declared car development.

The UPGRADES tab's board answers "what changed the round a package arrived",
by differencing a team's pace either side of it and subtracting a control
group. That is a good descriptive board and a weak causal design: the control
is whoever happened to sit a round out, the window is one or two events, and
a team that upgrades every round is compared against nobody.

This module runs the econometric version instead. The panel is one row per
(team, round); the outcome is pace vs the field median (negative = faster);
the treatment is declared FIA performance components. Two specifications,
both with TEAM and ROUND fixed effects:

  dose      y_it = a_i + g_t + b · cum_items_it + e_it

            `cum_items` counts performance components declared from round 2
            onward, so b is "pp of pace per component of in-season
            development". Round 1 is excluded from the count: those entries
            are the launch specification, and a launch car has no before.
            Team fixed effects absorb how good the car started; round fixed
            effects absorb anything that hit the whole field at once.

  event     y_it = a_i + g_t + SUM_k b_k · D^k_it + e_it

            D^k = 1 when the team introduced a MAJOR package (>= MAJOR_ITEMS
            components) k rounds ago, k running over EVENT_WINDOW with k = -1
            omitted as the reference. b_0 is the step on arrival, b_1..b_3
            whether it stuck, and the LEADS b_-2, b_-3 are the test that
            matters: they should be indistinguishable from zero. A team that
            was already improving before the package arrived would show up
            there, and would mean the design is reading a trend as an effect.

Inference
---------
Standard errors are clustered by team, because a team's weekends are not
independent draws. With only eleven clusters the asymptotic cluster-robust
formula over-rejects badly, so the p-values reported are WILD CLUSTER
BOOTSTRAP p-values (Rademacher weights, imposing the null), which is the
standard remedy at this cluster count. Both are returned so the difference is
visible rather than hidden.

What this design still cannot do
--------------------------------
It cannot separate development from CIRCUIT CHARACTER. A high-downforce car
gains at Hungary and loses at Spa without a single new part, and if a team
happens to bring its B-spec to a circuit that suits it, this reads the
circuit as the upgrade. Round fixed effects remove what moved the whole field
but not a team-specific circuit affinity. The leads are the honest guard: a
flat pre-trend means the confound is at least not systematically timed with
package arrivals. Treat a single row as suggestive; treat the pooled dose
coefficient and the flatness of the leads as the result.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from f1lib.config import apply_pace_legacy_columns
from f1lib.pace_features import canon

logger = logging.getLogger(__name__)

PACE_CSV = Path("data/team_pace_by_event.csv")
UPGRADES_CSV = Path("data/upgrades.csv")
STUDY_PATH = Path("data/upgrade_study.csv")

# Components in one event's declaration for it to count as a MAJOR package.
# The distribution is heavily skewed (31 single-item rounds, one 16-item
# B-spec), and 5 is where "a few parts" becomes "a development step": it
# keeps 17 of the 91 declared packages, spread across all eleven teams.
MAJOR_ITEMS = 5

# Event-time offsets estimated around a major package. k = -1 is the omitted
# reference (the round before it appeared); -2 and -3 are the pre-trend test;
# +3 is binned to absorb everything from three rounds on, so a late-season
# package does not silently drop out of the sample.
EVENT_WINDOW = (-3, -2, 0, 1, 2, 3)
REFERENCE_K = -1

# The launch specification is not in-season development, and round 1 has no
# before-period to difference against.
FIRST_DEV_ROUND = 2

OUTCOMES = {"onelap": "onelap_speed_pct", "longrun": "race_pace_pct"}


# ─────────────────────────────────────────────────────────────
# Panel construction
# ─────────────────────────────────────────────────────────────

def build_panel(season: int) -> pd.DataFrame:
    """One row per (team, round) for a season, carrying both outcomes, the
    cumulative in-season component count, and the event-time offset to the
    team's nearest major package."""
    pace = apply_pace_legacy_columns(pd.read_csv(PACE_CSV))
    pace = pace[pace["season"] == int(season)].copy()
    if pace.empty:
        return pd.DataFrame()
    pace["team"] = pace["team"].map(canon)

    up = pd.read_csv(UPGRADES_CSV, encoding="utf-8-sig")
    up = up[(up["season"] == int(season))
            & (up["category"] == "Performance")].copy()
    up["team"] = up["team"].map(canon)
    # events → round numbers, from the pace table (the calendar of record)
    rounds = (pace.drop_duplicates("event").set_index("event")["round"]
              .to_dict())
    up["round"] = up["event"].map(rounds)
    up = up.dropna(subset=["round"])
    up["round"] = up["round"].astype(int)

    items = (up.groupby(["team", "round"]).size()
             .rename("items").reset_index())
    panel = pace[["team", "round", "event", *OUTCOMES.values()]].copy()
    panel = panel.merge(items, on=["team", "round"], how="left")
    panel["items"] = panel["items"].fillna(0).astype(int)

    # in-season development only
    dev = panel["round"] >= FIRST_DEV_ROUND
    panel["dev_items"] = np.where(dev, panel["items"], 0)
    panel = panel.sort_values(["team", "round"])
    panel["cum_items"] = panel.groupby("team")["dev_items"].cumsum()

    # event time to the nearest major package (ties → the later one, which is
    # the more recent cause)
    panel["major"] = (panel["dev_items"] >= MAJOR_ITEMS)
    ktab = []
    for team, g in panel.groupby("team"):
        majors = g.loc[g["major"], "round"].tolist()
        for r in g["round"]:
            if majors:
                k = min((r - m for m in majors), key=lambda d: (abs(d), -d))
            else:
                k = np.nan
            ktab.append({"team": team, "round": r, "k": k})
    panel = panel.merge(pd.DataFrame(ktab), on=["team", "round"], how="left")
    return panel.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Fixed-effects OLS with cluster-robust and wild-bootstrap inference
# ─────────────────────────────────────────────────────────────

def _fe_design(panel: pd.DataFrame, regressors: pd.DataFrame
               ) -> tuple[np.ndarray, list[str]]:
    """[intercept | team dummies | round dummies | regressors], each set
    dropping one level so the design is full rank."""
    team = pd.get_dummies(panel["team"], prefix="tm", drop_first=True)
    rnd = pd.get_dummies(panel["round"], prefix="rd", drop_first=True)
    X = pd.concat([pd.Series(1.0, index=panel.index, name="const"),
                   team.astype(float), rnd.astype(float),
                   regressors.astype(float)], axis=1)
    return X.to_numpy(dtype=float), list(X.columns)


def _cluster_vcov(X: np.ndarray, resid: np.ndarray, groups: np.ndarray,
                  xtx_inv: np.ndarray) -> np.ndarray:
    """CR1 cluster-robust covariance."""
    n, k = X.shape
    G = len(np.unique(groups))
    meat = np.zeros((k, k))
    for g in np.unique(groups):
        m = groups == g
        u = X[m].T @ resid[m]
        meat += np.outer(u, u)
    c = (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    return c * (xtx_inv @ meat @ xtx_inv)


def _wild_bootstrap_p(X: np.ndarray, y: np.ndarray, groups: np.ndarray,
                      j: int, t_obs: float, reps: int = 999,
                      seed: int = 17) -> float:
    """Wild cluster bootstrap p-value for H0: beta_j = 0 (Rademacher weights,
    null imposed by refitting without column j). The right inference at this
    cluster count — the asymptotic formula over-rejects with 11 clusters."""
    rng = np.random.default_rng(seed)
    keep = [c for c in range(X.shape[1]) if c != j]
    Xr = X[:, keep]
    beta_r, *_ = np.linalg.lstsq(Xr, y, rcond=None)
    fit_r = Xr @ beta_r
    resid_r = y - fit_r
    uniq = np.unique(groups)
    count = 0
    for _ in range(reps):
        w = dict(zip(uniq, rng.choice([-1.0, 1.0], size=len(uniq))))
        wv = np.array([w[g] for g in groups])
        y_star = fit_r + resid_r * wv
        try:
            b_star, *_ = np.linalg.lstsq(X, y_star, rcond=None)
            r_star = y_star - X @ b_star
            xtx_inv = np.linalg.pinv(X.T @ X)
            V = _cluster_vcov(X, r_star, groups, xtx_inv)
            se = np.sqrt(max(V[j, j], 1e-18))
            if abs(b_star[j] / se) >= abs(t_obs):
                count += 1
        except np.linalg.LinAlgError:
            continue
    return (count + 1) / (reps + 1)


def _fit(panel: pd.DataFrame, y: np.ndarray, regressors: pd.DataFrame,
         boot: bool = True) -> pd.DataFrame:
    X, names = _fe_design(panel, regressors)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    xtx_inv = np.linalg.pinv(X.T @ X)
    groups = panel["team"].to_numpy()
    V = _cluster_vcov(X, resid, groups, xtx_inv)
    rows = []
    for name in regressors.columns:
        j = names.index(name)
        se = float(np.sqrt(max(V[j, j], 1e-18)))
        t = float(beta[j] / se) if se > 0 else 0.0
        rows.append({
            "term": name, "coef": float(beta[j]), "se_cluster": se, "t": t,
            "p_wild": _wild_bootstrap_p(X, y, groups, j, t) if boot else np.nan,
        })
    out = pd.DataFrame(rows)
    out.attrs["n"] = len(y)
    out.attrs["n_teams"] = len(np.unique(groups))
    out.attrs["r2"] = float(1 - resid.var() / y.var()) if y.var() > 0 else 0.0
    return out


# ─────────────────────────────────────────────────────────────
# Specifications
# ─────────────────────────────────────────────────────────────

def dose_response(panel: pd.DataFrame, kind: str, boot: bool = True
                  ) -> pd.DataFrame:
    """pp of pace per declared in-season component."""
    d = panel.dropna(subset=[OUTCOMES[kind]])
    reg = pd.DataFrame({"cum_items": d["cum_items"].to_numpy()}, index=d.index)
    return _fit(d, d[OUTCOMES[kind]].to_numpy(dtype=float), reg, boot=boot)


def event_study(panel: pd.DataFrame, kind: str, boot: bool = True
                ) -> pd.DataFrame:
    """Effect by rounds-since a major package, k = -1 omitted."""
    d = panel.dropna(subset=[OUTCOMES[kind], "k"]).copy()
    # Restrict to the window. Without this, every round far from any package
    # (k <= -4) falls into the omitted category too, so the "reference" is a
    # mix of "the round before the upgrade" and "nowhere near an upgrade" and
    # every coefficient is measured against a baseline that means nothing.
    lo, hi = min(EVENT_WINDOW), max(EVENT_WINDOW)
    d = d[(d["k"] >= lo) & (d["k"] <= hi)]
    if d.empty:
        return pd.DataFrame()
    k = d["k"].to_numpy()
    cols = {}
    for off in EVENT_WINDOW:
        if off == REFERENCE_K:
            continue
        # the last offset is binned: "this far after, or further"
        if off == hi:
            cols[f"k_{off}plus"] = (k >= off).astype(float)
        else:
            cols[f"k_{off}"] = (k == off).astype(float)
    reg = pd.DataFrame(cols, index=d.index)
    reg = reg.loc[:, reg.sum() > 0]           # drop offsets with no support
    if reg.empty:
        return pd.DataFrame()
    return _fit(d, d[OUTCOMES[kind]].to_numpy(dtype=float), reg, boot=boot)


def pretrend_ok(ev: pd.DataFrame, alpha: float = 0.05) -> bool | None:
    """True when no lead coefficient is significant — i.e. the design is not
    obviously reading a pre-existing trend as an upgrade effect."""
    leads = ev[ev["term"].str.startswith("k_-")]
    if leads.empty:
        return None
    return bool((leads["p_wild"] > alpha).all())


def study_df() -> pd.DataFrame:
    """The precomputed estimates (built by scripts/compute_upgrade_study.py);
    empty frame with columns when not built."""
    cols = ["season", "spec", "kind", "term", "coef", "se_cluster", "p_wild",
            "n", "n_teams", "pretrend_clean", "lo", "hi", "same_sign"]
    if not STUDY_PATH.exists():
        return pd.DataFrame(columns=cols)
    try:
        return pd.read_csv(STUDY_PATH)
    except Exception as exc:
        logger.warning("upgrade_study.csv unreadable: %s", exc)
        return pd.DataFrame(columns=cols)
