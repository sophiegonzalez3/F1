"""Derive a circuit-normalised straight-line-speed index per team (and, by
extension, per power-unit manufacturer) from the cached session archive.

Why this exists
---------------
Manufacturers never publish power-unit horsepower or ERS-deployment figures, so
there is no ground-truth engine number to chart. The one thing we *can* measure
is how fast each car goes in a straight line: FastF1's per-lap ``Speed_ST`` is
the speed recorded at the circuit's speed trap (the end of the longest straight),
where the 2026 power unit — roughly half combustion, half electric — is deployed
flat out. It is the standard public proxy for "how much go has this engine got",
with the well-known caveat that it also reflects the car's drag level (wing), not
just the PU. Treat the output as a tentative power+deployment proxy, not a dyno
figure.

Method
------
For every cached Qualifying-type and Race-type session of the season:
  * per driver, take a robust top speed = median of their three fastest
    ``Speed_ST`` laps (kills a one-off slipstream tow);
  * per team, average its two drivers → the team's top speed that session;
  * centre on the session field: ``idx = team_top − field_mean`` (km/h vs the
    average car that weekend). Centring per session removes the circuit effect
    (Monza vs Monaco) so the season average compares like with like.

Qualifying sessions (max deployment, low fuel) drive the headline index; race
sessions are aggregated too for context. ``retention`` = mean race-trap /
quali-trap ratio per event — kept for reference but note it is inflated by
race-day slipstreaming, so it is NOT a clean deployment-efficiency measure.

Output
------
  data/pu_topspeed.csv   one row per (season, team):
      season, team, pu_maker, quali_idx, race_idx, quali_raw, race_raw,
      retention, n_quali, n_race, n_events

The SEASON tab's "Engine Championship" card rolls these up per manufacturer.

Usage
-----
    python scripts/compute_pu_topspeed.py            # every cached season
    python scripts/compute_pu_topspeed.py --season 2026
    python scripts/compute_pu_topspeed.py --verbose
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import glob
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.config import SESSIONS_DIR

VERBOSE = "--verbose" in sys.argv
_SEASON_ARG = None
if "--season" in sys.argv:
    try:
        _SEASON_ARG = int(sys.argv[sys.argv.index("--season") + 1])
    except (IndexError, ValueError):
        _SEASON_ARG = None

SESSIONS = Path(SESSIONS_DIR)
OUT = Path("data/pu_topspeed.csv")
FACILITIES = Path("data/facilities.csv")

# Session-name slugs (spaces → underscores, as written in the cache filenames).
_QUALI = {"Qualifying", "Sprint_Qualifying", "Sprint_Shootout"}
_RACE = {"Race", "Sprint"}


def _pu_short(name) -> str:
    """Collapse a facilities.csv pu_maker string to the short supplier label
    used across the app (matches data/pu_penalties.csv's pu_supplier)."""
    n = str(name)
    for k in ("Ford", "Mercedes", "Ferrari", "Honda", "Audi"):
        if k in n:
            return k
    if "Red Bull Powertrains" in n:      # belt-and-braces if the (Ford) tag drops
        return "Ford"
    return n.strip()


def _parts(fn: str) -> tuple[str, str, str]:
    """(season, meeting_slug, session_slug) from a *__laps.parquet filename."""
    base = os.path.basename(fn).replace("__laps.parquet", "")
    p = base.split("__")
    return p[0], p[1], p[2]


def _team_tops(fn: str) -> pd.Series | None:
    """Each team's robust top speed for one session, or None if unusable."""
    try:
        laps = pd.read_parquet(fn, columns=["Driver", "Team", "Speed_ST"])
    except Exception as exc:                      # pragma: no cover
        if VERBOSE:
            print(f"    skip {os.path.basename(fn)} ({exc})")
        return None
    laps["st"] = pd.to_numeric(laps["Speed_ST"], errors="coerce")
    laps = laps.dropna(subset=["st"])
    laps = laps[(laps["Team"].astype(str) != "") & (laps["st"] > 0)]
    if laps.empty:
        return None
    # per driver: median of the three fastest trap speeds (tow-robust)
    dtop = (laps.groupby(["Team", "Driver"])["st"]
            .apply(lambda s: s.nlargest(3).median()))
    return dtop.groupby("Team").mean()


def _season_rows(season: str) -> list[dict]:
    files = sorted(glob.glob(str(SESSIONS / f"{season}__*__laps.parquet")))
    per_session = []                              # (meeting, cat, team, top, idx)
    for fn in files:
        _, mslug, sslug = _parts(fn)
        if sslug in _QUALI:
            cat = "quali"
        elif sslug in _RACE:
            cat = "race"
        else:
            continue
        ttop = _team_tops(fn)
        if ttop is None or ttop.empty:
            continue
        field_mean = float(ttop.mean())
        for team, val in ttop.items():
            per_session.append((mslug, cat, str(team), float(val),
                                float(val) - field_mean))
        if VERBOSE:
            print(f"    {mslug:<28} {sslug:<18} field mean={field_mean:6.1f} "
                  f"({len(ttop)} teams)")
    if not per_session:
        return []

    d = pd.DataFrame(per_session, columns=["meeting", "cat", "team", "top", "idx"])
    fac = pd.read_csv(FACILITIES) if FACILITIES.exists() else pd.DataFrame()
    team2maker = ({r.team: _pu_short(r.pu_maker) for r in fac.itertuples()}
                  if not fac.empty and "pu_maker" in fac.columns else {})

    rows = []
    for team, g in d.groupby("team"):
        q = g[g["cat"] == "quali"]
        r = g[g["cat"] == "race"]
        piv = g.pivot_table(index="meeting", columns="cat", values="top",
                            aggfunc="mean")
        retention = (float((piv["race"] / piv["quali"]).mean())
                     if {"race", "quali"} <= set(piv.columns) else np.nan)
        n_events = int(g["meeting"].nunique())
        rows.append({
            "season": int(season),
            "team": team,
            "pu_maker": team2maker.get(team, ""),
            "quali_idx": round(float(q["idx"].mean()), 3) if len(q) else np.nan,
            "race_idx": round(float(r["idx"].mean()), 3) if len(r) else np.nan,
            "quali_raw": round(float(q["top"].mean()), 2) if len(q) else np.nan,
            "race_raw": round(float(r["top"].mean()), 2) if len(r) else np.nan,
            "retention": round(retention, 4) if retention == retention else np.nan,
            "n_quali": int(len(q)),
            "n_race": int(len(r)),
            "n_events": n_events,
        })
    return rows


def main() -> None:
    if not SESSIONS.exists():
        print(f"No sessions cache at {SESSIONS} — nothing to do.")
        return
    metas = glob.glob(str(SESSIONS / "*__laps.parquet"))
    seasons = sorted({os.path.basename(f).split("__")[0] for f in metas})
    if _SEASON_ARG is not None:
        seasons = [s for s in seasons if s == str(_SEASON_ARG)]

    all_rows: list[dict] = []
    for season in seasons:
        print(f"Season {season}:")
        rows = _season_rows(season)
        print(f"  -> {len(rows)} teams with straight-line data")
        all_rows.extend(rows)

    if not all_rows:
        print("No straight-line data computed — is the session cache populated?")
        return

    out = pd.DataFrame(all_rows).sort_values(["season", "quali_idx"],
                                             ascending=[True, False])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\nWrote {OUT} ({len(out)} rows).")
    if VERBOSE:
        print(out.to_string(index=False))


if __name__ == "__main__":
    main()
