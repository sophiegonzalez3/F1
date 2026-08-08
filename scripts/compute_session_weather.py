"""Per-session weather summary — every session of every event, not just races.

`data/race_stats.csv` carries one weather row per RACE, and its `rain` column
is `Rainfall.any()`: a single wet sample anywhere in the session marks the
whole race wet. Measured against tyres, 7 of the 13 races that flag trips on
(2023-2026) never ran an intermediate — Austria 2024 is flagged wet at a track
temperature of 46 C. Anything built on that flag inherits the error.

Nothing recorded practice or qualifying weather at all, which is what made a
dry Monaco 2026 look like a wet weekend during the model review.

This writes one row per session with three independent pieces of evidence:

    rain_share      fraction of weather samples reporting rain
    inter_share     fraction of laps on INTERMEDIATE
    wet_share       fraction of laps on WET

and classifies from the TYRES first, because that is what the teams actually
decided. INTERMEDIATE matters far more than WET: across the archive it is used
about ten times as often, and full wets appear in a handful of sessions.

    dry        nobody left slicks and no rain was recorded
    drizzle    rain recorded, but the field stayed on slicks throughout
    rain       intermediates or wets were run

    python scripts/compute_session_weather.py
    python scripts/compute_session_weather.py --season 2026
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

SESS = Path("data/sessions")
LITE = Path("data/sessions_lite")
OUT = Path("data/session_weather.csv")

# A lap counts as wet-shod on these. Anything else (including MISSING/NONE) is
# ignored rather than assumed dry, so a session with broken compound data
# reports NaN instead of a confident "dry".
WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
DRY_COMPOUNDS = {"SOFT", "MEDIUM", "HARD", "SUPERSOFT", "ULTRASOFT",
                 "HYPERSOFT"}

WET_TYRE_MIN = 0.01      # >= 1% of laps on inters/wets = a genuinely wet session

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


def classify(rain_share: float, wet_tyre: float) -> str:
    if pd.notna(wet_tyre) and wet_tyre >= WET_TYRE_MIN:
        return "rain"
    if pd.notna(rain_share) and rain_share > 0:
        return "drizzle"
    return "dry"


def summarise(path: Path) -> dict | None:
    key = path.name.replace("__weather.parquet", "")
    try:
        season_s, event_s, session_s = key.split("__", 2)
        season = int(season_s)
    except ValueError:
        return None
    try:
        w = pd.read_parquet(path)
    except Exception:
        return None
    if w.empty or "TrackTemp" not in w.columns:
        return None

    rain_share = (float(w["Rainfall"].astype(bool).mean())
                  if "Rainfall" in w.columns else float("nan"))

    inter = wet = n_laps = float("nan")
    lp = path.parent / f"{key}__laps.parquet"
    if lp.exists():
        try:
            c = pd.read_parquet(lp, columns=["Compound"])["Compound"]
            c = c.astype(str).str.upper()
            c = c[c.isin(WET_COMPOUNDS | DRY_COMPOUNDS)]
            if len(c):
                n_laps = int(len(c))
                inter = float(c.eq("INTERMEDIATE").mean())
                wet = float(c.eq("WET").mean())
        except Exception:
            pass

    wet_tyre = (inter + wet) if pd.notna(inter) and pd.notna(wet) else float("nan")
    return {
        "season": season,
        "event": event_s.replace("_", " "),
        "session": session_s.replace("_", " "),
        "n_samples": int(len(w)),
        "rain_share": round(rain_share, 4) if pd.notna(rain_share) else None,
        "air_c": round(float(w["AirTemp"].mean()), 1),
        "track_c": round(float(w["TrackTemp"].mean()), 1),
        "track_min": round(float(w["TrackTemp"].min()), 1),
        "track_max": round(float(w["TrackTemp"].max()), 1),
        "n_laps": n_laps if pd.notna(n_laps) else None,
        "inter_share": round(inter, 4) if pd.notna(inter) else None,
        "wet_share": round(wet, 4) if pd.notna(wet) else None,
        "condition": classify(rain_share, wet_tyre),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    args = ap.parse_args()

    seen: set[str] = set()
    rows = []
    for base in (SESS, LITE):          # full cache wins on collision
        if not base.exists():
            continue
        for p in sorted(base.glob("*__weather.parquet")):
            if p.name in seen:
                continue
            seen.add(p.name)
            r = summarise(p)
            if r and (not args.season or r["season"] == args.season):
                rows.append(r)

    if not rows:
        print("no weather files found")
        return 1
    d = pd.DataFrame(rows)
    rnd = _rounds()
    d["round"] = [rnd.get((int(s), str(e))) for s, e in
                  zip(d["season"], d["event"])]
    d["_o"] = d["session"].apply(
        lambda s: SESSION_ORDER.index(s) if s in SESSION_ORDER else 99)
    d = d.sort_values(["season", "round", "_o"]).drop(columns="_o")
    d = d[["season", "round", "event", "session", "condition",
           "rain_share", "inter_share", "wet_share",
           "air_c", "track_c", "track_min", "track_max",
           "n_samples", "n_laps"]]

    # MERGE, never replace. `--season 2026` re-derives 55 rows; writing those
    # straight out would delete the other 510 and silently shrink the archive
    # to one year — the same way a --seasons subset has clobbered consolidated
    # files here before. Rows for the requested season are refreshed, every
    # other season is carried through untouched.
    if args.season and OUT.exists():
        try:
            old = pd.read_csv(OUT)
            keep = old[old["season"] != args.season]
            before = len(old)
            d = pd.concat([keep, d], ignore_index=True)
            d = d.sort_values(["season", "round", "event", "session"])
            print(f"merged: kept {len(keep)} row(s) from other seasons "
                  f"(file had {before})")
        except Exception as exc:
            print(f"!! could not merge with existing {OUT} ({exc}); "
                  f"refusing to overwrite")
            return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False)

    print(f"Wrote {len(d)} sessions -> {OUT}")
    print("\ncondition by season:")
    print(pd.crosstab(d["season"], d["condition"]).to_string())
    wet = d[d["condition"] == "rain"]
    if len(wet):
        print(f"\ngenuinely wet sessions ({len(wet)}):")
        print(wet[["season", "event", "session", "rain_share", "inter_share",
                   "wet_share", "track_c"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
