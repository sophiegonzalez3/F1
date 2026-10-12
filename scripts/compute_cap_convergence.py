"""Did the cost cap close the field? Season metrics 2011→now for the CONTEXT
tab's "Did the Cap Level the Field?" card.

Prompted by The Race's "top four points dominance" graphic (Oct 2026): the
fixed big four (McLaren, Mercedes, Red Bull, Ferrari) took 77.4% of points in
2011-2020 and 83.5% in 2021-2025, read as "the cap hasn't let small teams catch
up". This script reproduces that number (77.0 / 83.4 here) and puts it next to
the measures that actually answer the question:

  top4_share     points share of THAT season's real top four constructors.
                 The fixed big four is a hindsight definition — McLaren
                 2015-18 was a backmarker while Lotus / Williams / Force India
                 were genuine top-four teams — and the gap between the two
                 lines is exactly that bias.
  big4_share     The Race's measure (fixed big four), for reference.
  spread_pct     one-lap gap fastest → slowest team, session-normalised via
                 f1lib/quali_norm (NEVER min(Q1,Q2,Q3): the green-track Q1
                 penalty lands on the slowest teams and inflates the spread).
                 Median over the season's rounds.
  mid_gap_pct    median gap of the non-big-four teams to the fastest team.
  big4_dnf_pct / other_dnf_pct
                 retirement rate (classified finish = Finished / +N Lap(s) /
                 Lapped — both archive vocabularies).
  merit_beat_pct of all (big-four finisher, other finisher) pairs in a race,
                 the share where the other car finished ahead — order
                 stability with retirements removed.
  mid_share_race non-big-four share of race points.

Also writes the split-half reliability of each per-season axis (odd vs even
rounds, Spearman-Brown) and the reliability counterfactual: the 2021-25
midfield race-points share re-weighted to the pre-cap distribution of big-four
retirements per race.

Data: 2019+ from the local results archive; 2011-2018 from Jolpica, fetched
once into data/historical_results/pre2019_{race,quali}.parquet (pass
--refetch to redo it). Fastest-lap and sprint points are included as scored.

Output: data/cap_convergence.csv, data/cap_convergence_meta.json
Usage:  python scripts/compute_cap_convergence.py [--refetch]
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from f1lib.quali_norm import normalised_gap_pct

HIST = Path("data/historical_results")
PRE_RACE = HIST / "pre2019_race.parquet"
PRE_QUALI = HIST / "pre2019_quali.parquet"
OUT = Path("data/cap_convergence.csv")
META = Path("data/cap_convergence_meta.json")

JOLPICA = "https://api.jolpi.ca/ergast/f1"
FIRST_SEASON = 2011           # The Race's 10-season pre-cap baseline starts here
ARCHIVE_FIRST = 2019          # local archive coverage
CAP_START = 2021
BIG4 = ("mclaren", "mercedes", "red_bull", "ferrari")
FINISHED = r"^(Finished|\+\d+ Laps?|Lapped)$"


# ── Jolpica backfill ────────────────────────────────────────

def _get(path: str) -> dict:
    for i in range(5):
        r = requests.get(f"{JOLPICA}/{path}", timeout=30)
        if r.status_code == 200:
            return r.json()["MRData"]
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"Jolpica: {path} failed")


def _races(kind: str, season: int) -> list[dict]:
    out, off = [], 0
    while True:
        d = _get(f"{season}/{kind}.json?limit=100&offset={off}")
        out += d["RaceTable"]["Races"]
        off += 100
        time.sleep(0.4)
        if off >= int(d["total"]):
            return out


def _laptime(s) -> float | None:
    try:
        m, sec = str(s).split(":")
        return int(m) * 60 + float(sec)
    except (ValueError, TypeError):
        return None


def fetch_pre_archive() -> None:
    rows, qrows = [], []
    for y in range(FIRST_SEASON, ARCHIVE_FIRST):
        for rc in _races("results", y):
            for x in rc["Results"]:
                rows.append(dict(
                    season=y, round_number=int(rc["round"]),
                    TeamId=x["Constructor"]["constructorId"],
                    TeamName=x["Constructor"]["name"],
                    Position=int(x["position"]), Points=float(x["points"]),
                    Status=x["status"]))
        for rc in _races("qualifying", y):
            for x in rc["QualifyingResults"]:
                qrows.append(dict(
                    season=y, round_number=int(rc["round"]),
                    TeamId=x["Constructor"]["constructorId"],
                    Q1=_laptime(x.get("Q1")), Q2=_laptime(x.get("Q2")),
                    Q3=_laptime(x.get("Q3"))))
        print(f"  {y}: {len(rows)} race rows, {len(qrows)} quali rows")
    pd.DataFrame(rows).to_parquet(PRE_RACE)
    pd.DataFrame(qrows).to_parquet(PRE_QUALI)


# ── metrics ─────────────────────────────────────────────────

def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cols = ["season", "round_number", "TeamId", "Position", "Points", "Status"]
    race = pd.concat([pd.read_parquet(PRE_RACE)[cols],
                      pd.read_parquet(HIST / "race_results_all.parquet")[cols]],
                     ignore_index=True)
    sprint = pd.read_parquet(HIST / "sprint_results_all.parquet")[cols]
    qcols = ["season", "round_number", "TeamId", "Q1", "Q2", "Q3"]
    quali = pd.concat([pd.read_parquet(PRE_QUALI)[qcols],
                       pd.read_parquet(HIST / "quali_results_all.parquet")[qcols]],
                      ignore_index=True)
    for d in (race, sprint, quali):
        d["big4"] = d["TeamId"].astype(str).str.lower().isin(BIG4)
    race["fin"] = race["Status"].astype(str).str.match(FINISHED)
    return race, sprint, quali


def _event_rows(race: pd.DataFrame, quali: pd.DataFrame) -> pd.DataFrame:
    """One row per race: the per-event inputs every season metric averages."""
    qg = {k: g for k, g in quali.groupby(["season", "round_number"])}
    out = []
    for (y, rd), e in race.groupby(["season", "round_number"]):
        f = e[e["fin"]]
        a = f.loc[f["big4"], "Position"].to_numpy()
        o = f.loc[~f["big4"], "Position"].to_numpy()
        beat = (o[:, None] < a[None, :]).mean() if len(a) and len(o) else np.nan
        tot = e["Points"].sum()
        spread = mid_gap = np.nan
        q = qg.get((y, rd))
        if q is not None:
            gaps = normalised_gap_pct(q.assign(team=q["TeamId"]), "team")
            if len(gaps) >= 8:
                v = pd.Series(gaps).sort_values()
                v = v - v.iloc[0]
                spread = v.iloc[-1]
                mid_gap = v[[t for t in v.index if t not in BIG4]].median()
        out.append(dict(
            season=y, round_number=rd,
            big4_out=int((~e.loc[e["big4"], "fin"]).sum()),
            big4_dnf=1 - e.loc[e["big4"], "fin"].mean(),
            other_dnf=1 - e.loc[~e["big4"], "fin"].mean(),
            merit_beat=beat, spread=spread, mid_gap=mid_gap,
            mid_share=e.loc[~e["big4"], "Points"].sum() / tot * 100 if tot else np.nan))
    return pd.DataFrame(out)


def _split_half(ev: pd.DataFrame, col: str, agg: str) -> float:
    odd = ev[ev["round_number"] % 2 == 1].groupby("season")[col].agg(agg)
    even = ev[ev["round_number"] % 2 == 0].groupby("season")[col].agg(agg)
    r = odd.corr(even)
    return round(float(2 * r / (1 + r)), 2)


def compute() -> tuple[pd.DataFrame, dict]:
    race, sprint, quali = _load()
    ev = _event_rows(race, quali)
    pts = pd.concat([race[["season", "TeamId", "big4", "Points"]],
                     sprint[["season", "TeamId", "big4", "Points"]]])
    rows = []
    for y, g in pts.groupby("season"):
        tot = g["Points"].sum()
        team = g.groupby("TeamId")["Points"].sum().sort_values(ascending=False)
        e = ev[ev["season"] == y]
        rows.append(dict(
            season=int(y), rounds=len(e),
            top4_share=team.head(4).sum() / tot * 100,
            big4_share=g.loc[g["big4"], "Points"].sum() / tot * 100,
            top4_teams=",".join(team.head(4).index),
            spread_pct=e["spread"].median(), mid_gap_pct=e["mid_gap"].median(),
            quali_rounds=int(e["spread"].notna().sum()),
            big4_dnf_pct=e["big4_dnf"].mean() * 100,
            other_dnf_pct=e["other_dnf"].mean() * 100,
            merit_beat_pct=e["merit_beat"].mean() * 100,
            mid_share_race=e["mid_share"].mean()))
    df = pd.DataFrame(rows).round(2)

    # Reliability counterfactual: cap-era midfield share at pre-cap big-four
    # retirement frequency (0 / 1 / 2+ big-four cars out per race).
    ev["k"] = ev["big4_out"].clip(upper=2)
    pre = ev[ev["season"] < CAP_START]
    cap = ev[(ev["season"] >= CAP_START) & (ev["season"] < CAP_START + 5)]
    w = pre["k"].value_counts(normalize=True)
    m = cap.groupby("k")["mid_share"].mean()
    meta = dict(
        split_half=dict(
            spread_pct=_split_half(ev, "spread", "median"),
            mid_gap_pct=_split_half(ev, "mid_gap", "median"),
            big4_dnf_pct=_split_half(ev, "big4_dnf", "mean"),
            merit_beat_pct=_split_half(ev, "merit_beat", "mean"),
            mid_share_race=_split_half(ev, "mid_share", "mean")),
        mid_share_by_big4_out={
            era: {int(k): round(float(v), 1) for k, v in
                  d.groupby("k")["mid_share"].mean().items()}
            for era, d in (("pre_cap", pre), ("cap_2021_25", cap))},
        cap_mid_share_actual=round(float(cap["mid_share"].mean()), 1),
        cap_mid_share_pre_cap_reliability=round(float((m * w).sum()), 1),
        big4_out_per_race=dict(pre_cap=round(float(pre["big4_out"].mean()), 2),
                               cap_2021_25=round(float(cap["big4_out"].mean()), 2)),
    )
    return df, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true",
                    help="re-download 2011-2018 from Jolpica")
    args = ap.parse_args()
    if args.refetch or not (PRE_RACE.exists() and PRE_QUALI.exists()):
        print("Fetching 2011-2018 results from Jolpica ...")
        fetch_pre_archive()
    df, meta = compute()
    expected = set(range(FIRST_SEASON, int(df["season"].max()) + 1))
    missing = sorted(expected - set(df["season"]))
    df.to_csv(OUT, index=False)
    META.write_text(json.dumps(meta, indent=2))
    print(f"Cap convergence: {len(df)} seasons "
          f"({df['season'].min()}-{df['season'].max()}), "
          f"{int(df['rounds'].sum())} races -> {OUT}"
          + (f"  WARNING: MISSING {missing}" if missing else ""))
    print(f"  split-half: {meta['split_half']}")


if __name__ == "__main__":
    main()
