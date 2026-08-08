"""How much of each session the pace model can actually use.

Every actual the model is scored against is built from a SUBSET of the laps
run: `ValidLap & ~Dirty_Air & ~Perturbed_Lap`. Across 2026 that keeps roughly
half of a race. The post-race review kept running into this — a driver who
spent his afternoon in traffic is measured on a thin, unrepresentative slice of
it, and twice that turned out to explain more of a "miss" than anything about
the car (see data/model_review.csv, category `measurement_artifact`).

This script writes that retention out per session and per driver so it can be
looked at directly instead of rediscovered one weekend at a time.

    python scripts/compute_lap_retention.py            # every cached season
    python scripts/compute_lap_retention.py --season 2026

WHY IT MIGHT BE A FEATURE, NOT JUST A DIAGNOSTIC. Retention is not noise: a
weekend where a car keeps 80% of its laps is a weekend it ran clean air, hit
its marks and had a representative read. One at 35% is a weekend spent in
traffic, under flags, or nursing a problem. If clean weekends predict clean
races, retention belongs in the model rather than in a footnote about why it
missed. Nothing here acts on that — it just makes the quantity available.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

from f1lib.processing import (clean_and_enrich_laps, flag_dirty_air,
                              flag_perturbed_laps)

SESS = Path("data/sessions")
LITE = Path("data/sessions_lite")
OUT = Path("data/lap_retention.csv")

# Session ordering for anything that renders this.
SESSION_ORDER = ["Practice 1", "Practice 2", "Practice 3", "Sprint Qualifying",
                 "Sprint Shootout", "Sprint", "Qualifying", "Race"]


def _rounds() -> dict[tuple[int, str], int]:
    p = Path("data/season_calendar.csv")
    if not p.exists():
        return {}
    c = pd.read_csv(p)
    return {(int(r["season"]), str(r["event"])): int(r["round"])
            for _, r in c.iterrows()
            if pd.notna(r.get("round")) and pd.notna(r.get("event"))}


def retention_rows(season: int, event: str, session: str,
                   path: Path) -> list[dict]:
    """Per-driver kept-lap share for one session."""
    try:
        raw = pd.read_parquet(path)
    except Exception:
        return []
    if raw.empty:
        return []
    key = path.name.replace("__laps.parquet", "")
    rcm_p = path.parent / f"{key}__race_control.parquet"
    rcm = None
    if rcm_p.exists():
        try:
            rcm = pd.read_parquet(rcm_p)
        except Exception:
            rcm = None
    try:
        fl = flag_dirty_air(flag_perturbed_laps(clean_and_enrich_laps(raw),
                                                rcm=rcm))
    except Exception:
        return []
    if "Driver_Short" not in fl.columns:
        return []
    kept = fl[fl["ValidLap"] & ~fl.get("Dirty_Air", False)
              & ~fl.get("Perturbed_Lap", False)]
    tot = fl.groupby(["Team", "Driver_Short"]).size()
    n_k = kept.groupby(["Team", "Driver_Short"]).size()
    out = []
    for (team, drv), n in tot.items():
        if n < 3:                     # a 2-lap cameo is not a retention figure
            continue
        k = int(n_k.get((team, drv), 0))
        out.append({
            "season": season, "event": event, "session": session,
            "team": team, "driver": drv,
            "n_total": int(n), "n_kept": k, "keep": round(k / n, 4),
            "n_dirty": int(fl[(fl["Driver_Short"] == drv)]
                           .get("Dirty_Air", pd.Series(dtype=bool)).sum()),
            "n_perturbed": int(fl[(fl["Driver_Short"] == drv)]
                               .get("Perturbed_Lap", pd.Series(dtype=bool)).sum()),
            "n_invalid": int((~fl[fl["Driver_Short"] == drv]["ValidLap"]).sum()),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, help="limit to one season")
    args = ap.parse_args()

    seen: set[str] = set()
    paths = []
    for base in (SESS, LITE):        # full cache wins on collision
        if not base.exists():
            continue
        for p in sorted(base.glob("*__laps.parquet")):
            if p.name in seen:
                continue
            seen.add(p.name)
            paths.append(p)

    rnd = _rounds()
    rows = []
    for p in paths:
        key = p.name.replace("__laps.parquet", "")
        try:
            season_s, event_s, session_s = key.split("__", 2)
            season = int(season_s)
        except ValueError:
            continue
        if args.season and season != args.season:
            continue
        event = event_s.replace("_", " ")
        session = session_s.replace("_", " ")
        rows.extend(retention_rows(season, event, session, p))

    if not rows:
        print("no sessions found")
        return 1
    d = pd.DataFrame(rows)
    d["round"] = [rnd.get((int(s), str(e))) for s, e in
                  zip(d["season"], d["event"])]
    d = d[["season", "round", "event", "session", "team", "driver",
           "n_total", "n_kept", "keep", "n_dirty", "n_perturbed", "n_invalid"]]
    d = d.sort_values(["season", "round", "event", "session", "team", "driver"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False)

    print(f"Wrote {len(d)} driver-session rows -> {OUT}")
    per = (d.groupby(["season", "session"])["keep"].median().unstack()
           .reindex(columns=[s for s in SESSION_ORDER
                             if s in d["session"].unique()]))
    print("\nmedian kept share by season x session:")
    print((100 * per).round(0).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
