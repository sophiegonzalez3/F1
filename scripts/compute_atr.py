"""Derive the ATR (Aerodynamic Testing Restrictions) sliding scale per team.

F1's handicap system: wind-tunnel runs and CFD allowances scale with
championship position — the leader gets 70% of the baseline, each place down
adds 5%, last place gets 115%, and a new entrant gets the maximum. The scale
resets twice a year:

  H1 (1 Jan – 30 Jun)  based on the previous season's final standings
  H2 (1 Jul – 31 Dec)  based on the standings as of 30 June

Both bases are in the local standings archive, so this is derived, not
curated. Race dates come from the cached laps (LapStartDate), which the June
cutoff needs. Teams that rebrand between seasons are mapped (Kick Sauber →
Audi); teams with no predecessor (Cadillac 2026) get the new-entrant 115%.

Output: data/atr_allowance.csv
        season, period, period_label, team, basis_position, basis, atr_pct

Usage:  python scripts/compute_atr.py
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import re
from pathlib import Path

import pandas as pd

from f1lib.config import SESSIONS_DIR

STANDINGS = Path("data/historical_results/constructor_standings_all.parquet")
OUT = Path("data/atr_allowance.csv")

# position → % of the baseline aero-testing allowance (2023+ sporting regs)
SCALE = {1: 70, 2: 75, 3: 80, 4: 85, 5: 90,
         6: 95, 7: 100, 8: 105, 9: 110, 10: 115}
NEW_ENTRANT_PCT = 115

# rebrands: name in season N-1 → name in season N
RENAMES = {"Kick Sauber": "Audi", "AlphaTauri": "Racing Bulls",
           "Alfa Romeo": "Kick Sauber"}


def _slugify(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _race_dates(season: int) -> dict[str, pd.Timestamp]:
    """slug(meeting) → race date, from the cached race laps."""
    out = {}
    for lp in Path(SESSIONS_DIR).glob(f"{season}__*__Race__laps.parquet"):
        try:
            df = pd.read_parquet(lp, columns=["meeting", "LapStartDate"])
        except Exception:
            continue
        d = pd.to_datetime(df["LapStartDate"], errors="coerce").dropna()
        if len(d):
            out[_slugify(df["meeting"].iloc[0])] = d.iloc[0].normalize()
    return out


def _standings_at(st: pd.DataFrame, season: int, upto_round=None) -> dict[str, int]:
    s = st[st["season"] == season]
    if upto_round is not None:
        s = s[s["round_number"] <= upto_round]
    if s.empty:
        return {}
    last = s[s["round_number"] == s["round_number"].max()]
    return {str(r.TeamName): int(r.position) for r in last.itertuples()}


def _teams_of(st: pd.DataFrame, season: int) -> list[str]:
    return sorted(st[st["season"] == season]["TeamName"].unique())


def main() -> None:
    st = pd.read_parquet(STANDINGS)
    seasons = sorted(st["season"].unique())
    rows = []

    for season in seasons:
        teams = _teams_of(st, int(season))
        season = int(season)

        # ── H1: previous season's final standings ─────────────
        if season - 1 in seasons:
            prev = _standings_at(st, season - 1)
            prev = {RENAMES.get(t, t): p for t, p in prev.items()}
            for team in teams:
                pos = prev.get(team)
                rows.append({
                    "season": season, "period": "H1",
                    "period_label": f"Jan–Jun {season}",
                    "team": team,
                    "basis_position": pos if pos else None,
                    "basis": (f"P{pos} in {season - 1} final standings"
                              if pos else "new entrant"),
                    "atr_pct": SCALE.get(pos, NEW_ENTRANT_PCT)
                               if pos else NEW_ENTRANT_PCT,
                })

        # ── H2: standings as of 30 June ───────────────────────
        dates = _race_dates(season)
        cutoff = pd.Timestamp(f"{season}-06-30")
        sr = st[st["season"] == season].drop_duplicates(
            ["round_number", "event_name"])
        done = [int(r.round_number) for r in sr.itertuples()
                if dates.get(_slugify(r.event_name), pd.Timestamp.max) <= cutoff]
        if not done:
            continue
        upto = max(done)
        # only emit H2 once the season has actually reached July
        latest_date = max(dates.values()) if dates else None
        if latest_date is None or latest_date <= cutoff:
            continue
        mid = _standings_at(st, season, upto_round=upto)
        for team in teams:
            pos = mid.get(team)
            rows.append({
                "season": season, "period": "H2",
                "period_label": f"Jul–Dec {season}",
                "team": team,
                "basis_position": pos if pos else None,
                "basis": (f"P{pos} after round {upto} (30 Jun cutoff)"
                          if pos else "new entrant"),
                "atr_pct": SCALE.get(pos, NEW_ENTRANT_PCT)
                           if pos else NEW_ENTRANT_PCT,
            })

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    print(f"Wrote {OUT} ({len(df)} rows, seasons "
          f"{sorted(df['season'].unique()) if len(df) else '—'})")


if __name__ == "__main__":
    main()
