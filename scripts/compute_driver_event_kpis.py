"""Build the per-event driver KPI table -> data/driver_event_kpis.csv.

One row per (season, round, driver) of every race weekend in the results
archive. It feeds the TEAM & TEAMATE tab's "last N events" window — see
f1lib/driver_kpis.py for the window-validity rules the columns follow.

Columns
-------
  season, round, event, team, driver
  race_grid, race_pos, race_classified, race_gained, race_points, race_status
  spr_grid,  spr_pos,  spr_classified,  spr_gained,  spr_points
                      results archive. *_gained = grid - finish, drivers who
                      took the flag only (status Finished / Lapped / +N Laps):
                      every DNF — even one classified on distance — and every
                      DSQ is left out, the DNF columns count those. A pit-lane
                      start (grid 0) counts as the back of the grid. Sprint
                      columns NaN off sprint weekends.
  quali_pos           classified qualifying position.
  quali_gap_pct, quali_nsess
                      session-normalised one-lap speed, % vs field median
                      (driver_pace_by_event 'quali': the Q1->Q3 evolution is
                      removed, so a Q2 exit and a Q3 runner are comparable).
  race_gap_pct, race_se_pct, race_n_clean
                      clean-air, fuel- and evolution-corrected median race lap,
                      % vs field median (driver_pace_by_event 'race', GP only).
  best_lap_pct        best lap of the weekend (any session, deleted and pit
                      laps excluded) as % gap to the weekend's fastest lap.
  laps_fp, laps_q, laps_sprint, laps_race
                      valid laps per session type (lap_retention: n_total -
                      n_invalid, i.e. the old tab's ValidLap count).
  pit_n, pit_lane_delta_sum, pit_slow_n, pit_stat_sum, pit_stat_n
                      pit_league stops. Pit-lane time is circuit-dependent, so
                      each stop is stored as its delta to that event's median
                      stop; slow = more than SLOW_STOP_S above it. Stationary
                      time is circuit-independent and kept raw (sparse feed).
  passes_made, passes_lost, passes_sessions
                      green-flag non-pit on-track passes, race + sprint
                      (f1lib.driver_kpis.overtake_pairs).
  cons_pct, cons_n    in-stint lap spread, % of lap time (GP race).
  deleted_quali, deleted_race
                      laps deleted by race control (mostly track limits) in
                      quali-type / race-type sessions — kept apart, see scan.
  bw_flags            black-and-white flags shown to the driver in race and
                      sprint (race-control messages, 2023+; any reason —
                      ~70% are track limits).
  purple_quali, purple_race
                      progressive purple sectors (beat the session best so
                      far) in quali-type and race-type sessions.
  race_fl_rank        rank of the driver's fastest GP-race lap (1 = fastest lap).
  ideal_gap_pct       GP quali: best lap vs sum of best sectors, % — time left
                      on the table. FAILED the split-half bar (r < 0: which
                      run each best sector came from is luck of tyres and
                      track evolution, not execution) — kept for the record,
                      NOT shown on the tab.
  mk_n, mk_laps, mk_time_lost, mk_n_p, mk_laps_p, mk_n_f, mk_laps_f
                      micro-mistakes (compute_mistakes.py), competitive
                      sessions; *_p / *_f = with / without a car close ahead.
  dnf_n, dnf_car, dnf_driver, dnf_collision, dnf_dsq, dnf_unknown
                      race retirements and their family (dnf_causes.csv).
  inc_n, pen_n        incidents (contact / off-track) and penalties received.
  lap1_gain           places gained grid -> end of lap 1 (pit-lane starts out).

Usage
-----
    python scripts/compute_driver_event_kpis.py              # every season
    python scripts/compute_driver_event_kpis.py --season 2026
A --season run REPLACES that season's rows and keeps every other season's
rows from the existing file — a subset run never clobbers the table.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import f1lib.data_loader as dl
from f1lib.config import SESSIONS_LITE_DIR
from f1lib.driver_kpis import (
    KPI_CSV, SESSION_BUCKET, LAP_BUCKETS, SLOW_STOP_S,
    overtake_pairs, driver_abbr, stint_consistency,
    split_half, RELIABILITY_JSON,
)
from f1lib.processing import clean_and_enrich_laps, flag_perturbed_laps

HIST = Path("data/historical_results")
BASES = (Path(dl.SESSIONS_DIR), Path(SESSIONS_LITE_DIR))   # full cache wins
RED_FLAG_PITLANE_S = 120.0   # longer = sat in the pit lane under a red flag
MAX_STOP_DELTA_S = 15.0      # |delta to event median| beyond = repair / not a stop


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _event_stem(season: int, event: str) -> str:
    return dl._session_key(str(season), event, "X").rsplit("__", 1)[0]


def _session_paths(season: int, event: str) -> dict[str, Path]:
    """session label ('Race', 'Practice_1', ...) -> laps parquet."""
    stem = _event_stem(season, event)
    out: dict[str, Path] = {}
    for base in BASES:
        for p in base.glob(f"{stem}__*__laps.parquet"):
            sess = p.name[len(stem) + 2:-len("__laps.parquet")]
            out.setdefault(sess, p)
    return out


def _results_block(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    d = df.copy()
    n_start = d.groupby(["season", "round_number"])["Abbreviation"].transform("size")
    grid = _num(d["GridPosition"])
    grid = grid.where(grid > 0, n_start)                 # pit-lane start = back
    fin = _num(d["ClassifiedPosition"])
    # took the flag: a retirement classified on distance (>90%) or a DSQ
    # keeps a ClassifiedPosition, but is a DNF the DNF columns already count
    st = d["Status"].astype(str)
    flagged = st.isin(["Finished", "Lapped"]) | st.str.startswith("+")
    out = pd.DataFrame({
        "season": d["season"].astype(int),
        "round": d["round_number"].astype(int),
        "driver": d["Abbreviation"],
        f"{prefix}_grid": grid,
        f"{prefix}_pos": _num(d["Position"]),
        f"{prefix}_classified": fin.notna(),
        f"{prefix}_gained": (grid - fin).where(flagged),
        f"{prefix}_points": _num(d["Points"]).fillna(0.0),
    })
    if prefix == "race":
        out["event"] = d["event_name"].values
        out["team"] = d["TeamName"].values
        out["race_status"] = d["Status"].values
    return out


_SECS = ("Sector1", "Sector2", "Sector3")
_SCAN_COLS = ["Driver", "LapTime", "PitIn", "PitOut", "IsDeleted",
              *[f"{k}Time" for k in _SECS], *[f"{k}SessionTime" for k in _SECS]]
QUALI_SESS = ("Qualifying", "Sprint_Qualifying", "Sprint_Shootout")
RACE_SESS = ("Race", "Sprint")


def _secs(s: pd.Series) -> pd.Series:
    if pd.api.types.is_timedelta64_dtype(s):
        s = s.dt.total_seconds()
    return _num(s)


def _purples(l: pd.DataFrame) -> dict[str, int]:
    """Progressive purple sectors: each time a lap beats the session's best
    time in a sector SO FAR (ordered by when the sector was completed), as
    the timing screen paints it. The session's first time in each sector is
    not counted — it is purple by default."""
    out: dict[str, int] = {}
    for k in _SECS:
        t, at = f"{k}Time", f"{k}SessionTime"
        if t not in l.columns or at not in l.columns:
            continue
        d = l[["Driver", t, at]].dropna().sort_values(at)
        best = np.inf
        for drv, v in zip(d["Driver"], d[t]):
            if v < best:
                if np.isfinite(best):
                    a = driver_abbr(drv)
                    out[a] = out.get(a, 0) + 1
                best = v
    return out


def _session_scan(paths: dict[str, Path]) -> pd.DataFrame:
    """One read per session file -> per-driver lap-file KPIs:
    best_lap_pct, deleted_quali / deleted_race, purple_quali,
    purple_race, race_fl_rank (GP race fastest-lap rank), ideal_gap_pct
    (GP quali: best lap vs sum of best sectors, % of the best lap)."""
    best: dict[str, float] = {}
    rec: dict[str, dict] = {}

    def put(d, k, v, add=True):
        r = rec.setdefault(d, {})
        r[k] = r.get(k, 0) + v if add else v

    for sess, p in paths.items():
        try:
            l = pd.read_parquet(p, columns=_SCAN_COLS)
        except Exception:
            try:
                l = pd.read_parquet(p, columns=["Driver", "LapTime", "PitIn", "PitOut"])
            except Exception:
                continue
        for c in l.columns:
            if c.endswith("Time") and c != "LapStartTime":
                l[c] = _secs(l[c])
        deleted = (l["IsDeleted"].fillna(False).astype(bool) if "IsDeleted" in l.columns
                   else pd.Series(False, index=l.index))
        ok = l["LapTime"].notna() & l["PitIn"].isna() & l["PitOut"].isna() & ~deleted
        bests = l[ok].groupby("Driver")["LapTime"].min()
        for drv, v in bests.items():
            a = driver_abbr(drv)
            best[a] = min(best.get(a, np.inf), float(v))
        if sess in QUALI_SESS + RACE_SESS:
            # Kept apart on purpose: a deleted QUALI lap is a push-the-limit
            # attempt that costs a grid slot, a deleted RACE lap is a
            # track-limits strike on the way to a black-and-white flag and a
            # penalty. Summed, a driver's race habit was diluted by his
            # teammate's quali deletions (ANT 28 vs RUS 4 in 2026 races read
            # as 36 vs 17).
            dkey = "deleted_quali" if sess in QUALI_SESS else "deleted_race"
            for drv, n in l[deleted].groupby("Driver").size().items():
                put(driver_abbr(drv), dkey, int(n))
            for drv in l["Driver"].dropna().unique():
                put(driver_abbr(drv), dkey, 0)
            key = "purple_quali" if sess in QUALI_SESS else "purple_race"
            pur = _purples(l[~deleted])
            for drv in l["Driver"].dropna().unique():
                a = driver_abbr(drv)
                put(a, key, pur.get(a, 0))
        if sess == "Race" and not bests.empty:
            for drv, rk in bests.rank(method="min").items():
                put(driver_abbr(drv), "race_fl_rank", int(rk), add=False)
        if sess == "Qualifying" and all(f"{k}Time" in l.columns for k in _SECS):
            ql = l[~deleted]
            ideal = ql.groupby("Driver")[[f"{k}Time" for k in _SECS]].min().sum(
                axis=1, min_count=3)
            for drv, v in ideal.dropna().items():
                b = bests.get(drv)
                if b is not None and np.isfinite(b) and v <= b:
                    put(driver_abbr(drv), "ideal_gap_pct",
                        round((b - v) / b * 100, 4), add=False)
    if best:
        ref = min(best.values())
        for d, v in best.items():
            put(d, "best_lap_pct", round((v / ref - 1) * 100, 4), add=False)
    if not rec:
        return pd.DataFrame(columns=["driver"])
    return pd.DataFrame.from_dict(rec, orient="index").rename_axis("driver").reset_index()


_BW = re.compile(r"BLACK AND WHITE FLAG FOR CAR \d+ \((\w{3})\)")


def _bw_flags(paths: dict[str, Path]) -> dict[str, int] | None:
    """Black-and-white flags per driver in race + sprint. None when neither
    session has race-control messages cached (unknown, not zero)."""
    out: dict[str, int] = {}
    seen = False
    for sess in RACE_SESS:
        p = paths.get(sess)
        if p is None:
            continue
        rp = p.parent / p.name.replace("__laps.parquet", "__race_control.parquet")
        if not rp.exists():
            continue
        try:
            msg = pd.read_parquet(rp, columns=["Message"])["Message"].astype(str)
        except Exception:
            continue
        seen = True
        for m in msg:
            hit = _BW.search(m)
            if hit:
                out[hit.group(1)] = out.get(hit.group(1), 0) + 1
    return out if seen else None


def _race_lap_block(paths: dict[str, Path]) -> pd.DataFrame:
    made: dict[str, int] = {}
    lost: dict[str, int] = {}
    sess_n: dict[str, int] = {}
    cons = pd.DataFrame(columns=["driver", "cons_pct", "cons_n"])
    for sess in ("Race", "Sprint"):
        p = paths.get(sess)
        if p is None:
            continue
        try:
            raw = pd.read_parquet(p)
        except Exception:
            continue
        if "Position" in raw.columns and raw["Position"].notna().any():
            for drv in {driver_abbr(x) for x in raw["Driver"].dropna().unique()}:
                sess_n[drv] = sess_n.get(drv, 0) + 1
            for _, a, b in overtake_pairs(raw):
                a, b = driver_abbr(a), driver_abbr(b)
                made[a] = made.get(a, 0) + 1
                lost[b] = lost.get(b, 0) + 1
        if sess == "Race":
            rcm = None
            rp = p.parent / p.name.replace("__laps.parquet", "__race_control.parquet")
            if rp.exists():
                try:
                    rcm = pd.read_parquet(rp)
                except Exception:
                    rcm = None
            try:
                fl = flag_perturbed_laps(clean_and_enrich_laps(raw), rcm=rcm)
                cons = stint_consistency(fl)
            except Exception as exc:
                print(f"    consistency failed: {exc}")
    drivers = set(sess_n) | set(cons["driver"])
    out = pd.DataFrame({"driver": sorted(drivers)})
    out["passes_made"] = out["driver"].map(lambda d: made.get(d, 0) if d in sess_n else np.nan)
    out["passes_lost"] = out["driver"].map(lambda d: lost.get(d, 0) if d in sess_n else np.nan)
    out["passes_sessions"] = out["driver"].map(lambda d: sess_n.get(d, np.nan))
    return out.merge(cons, on="driver", how="left")


def _laps_block(seasons: set[int]) -> pd.DataFrame:
    lr = pd.read_csv("data/lap_retention.csv")
    lr = lr[lr["season"].isin(seasons) & lr["round"].notna()].copy()
    lr["bucket"] = lr["session"].map(SESSION_BUCKET)
    lr["valid"] = lr["n_total"] - lr["n_invalid"]
    w = (lr.dropna(subset=["bucket"])
           .pivot_table(index=["season", "round", "driver"], columns="bucket",
                        values="valid", aggfunc="sum"))
    w = w.reindex(columns=list(LAP_BUCKETS)).add_prefix("laps_").reset_index()
    w["season"] = w["season"].astype(int)
    w["round"] = w["round"].astype(int)
    return w


def _pit_block(rounds: pd.DataFrame) -> pd.DataFrame:
    p = pd.read_csv("data/pit_league.csv")
    p = p.merge(rounds, left_on=["season", "meeting"],
                right_on=["season", "event"], how="inner")
    # Red-flag periods put cars in the pit lane for 20-40 MINUTES and land in
    # the feed as "stops" — not a pit stop, drop before taking the median.
    p = p[p["pitlane_s"] <= RED_FLAG_PITLANE_S]
    p["delta"] = p["pitlane_s"] - p.groupby(["season", "round"])["pitlane_s"].transform("median")
    # Beyond this it is a repair / long penalty, not crew performance. A
    # botched wheel change (5-12 s lost) stays IN — that is what this KPI is for.
    p = p[p["delta"].between(-MAX_STOP_DELTA_S, MAX_STOP_DELTA_S)]
    p["slow"] = p["delta"] > SLOW_STOP_S
    g = p.groupby(["season", "round", "driver"])
    return pd.DataFrame({
        "pit_n": g["delta"].count(),
        "pit_lane_delta_sum": g["delta"].sum(),
        "pit_slow_n": g["slow"].sum(),
        "pit_stat_sum": g["stationary_s"].sum(min_count=1),
        "pit_stat_n": g["stationary_s"].count(),
    }).reset_index()


# micro-mistakes: competitive sessions only (practice is where drivers try
# things on purpose); same per-100-clean-laps definition as the DUEL tab
MISTAKE_SESS = ("Qualifying", "Sprint Qualifying", "Sprint", "Race")
DNF_FAMILY_COL = {"car imputable": "dnf_car", "driver imputable": "dnf_driver",
                  "collision": "dnf_collision", "disqualified": "dnf_dsq"}


def _by_meeting(df, rounds, meeting_col="meeting"):
    return df.merge(rounds, left_on=["season", meeting_col],
                    right_on=["season", "event"], how="inner")


def _mistakes_block(rounds: pd.DataFrame) -> pd.DataFrame:
    m = pd.read_parquet("data/mistakes_all.parquet")
    m = _by_meeting(m[m["session"].isin(MISTAKE_SESS)], rounds)
    if m.empty:
        return pd.DataFrame(columns=["season", "round", "driver"])
    # a corner row per lap pass: laps of the session = the max over corners
    ps = (m.groupby(["season", "round", "session", "Driver_Short"])
            .agg(mk_n=("n_mistakes", "sum"), mk_laps=("n_laps", "max"),
                 mk_time_lost=("time_lost_s", "sum")).reset_index())
    out = (ps.groupby(["season", "round", "Driver_Short"])
             [["mk_n", "mk_laps", "mk_time_lost"]].sum().reset_index())
    pr = _by_meeting(pd.read_parquet("data/mistakes_pressure_all.parquet"), rounds)
    pr = (pr.groupby(["season", "round", "Driver_Short"])
            .agg(mk_laps_p=("laps_p", "sum"), mk_n_p=("events_p", "sum"),
                 mk_laps_f=("laps_f", "sum"), mk_n_f=("events_f", "sum"))
            .reset_index())
    out = out.merge(pr, on=["season", "round", "Driver_Short"], how="outer")
    return out.rename(columns={"Driver_Short": "driver"})


def _dnf_block(seasons: set[int]) -> pd.DataFrame:
    from f1lib.incidents import session_of
    d = pd.read_csv("data/dnf_causes.csv")
    # race retirements only: the file holds every session since 2026-10-12
    d = d[d["season"].isin(seasons) & d["round"].notna()
          & session_of(d).eq("Race")].copy()
    d["col"] = d["cause_family"].map(DNF_FAMILY_COL).fillna("dnf_unknown")
    w = d.pivot_table(index=["season", "round", "driver"], columns="col",
                      values="event", aggfunc="count").reset_index()
    w["round"] = w["round"].astype(int)
    return w


def _incident_block(seasons: set[int]) -> pd.DataFrame:
    from f1lib.incidents import session_of
    i = pd.read_csv("data/incidents.csv")
    i = i[i["season"].isin(seasons) & i["round"].notna()
          & session_of(i).eq("Race")].copy()
    i["is_inc"] = i["kind"].isin(["contact", "off-track"])
    i["is_pen"] = i["outcome"].astype(str).str.startswith("penalty")
    g = (i.groupby(["season", "round", "driver"])
           .agg(inc_n=("is_inc", "sum"), pen_n=("is_pen", "sum")).reset_index())
    g["round"] = g["round"].astype(int)
    return g


def _lap1_block(rounds: pd.DataFrame) -> pd.DataFrame:
    l = _by_meeting(pd.read_csv("data/lap1_league.csv"), rounds)
    return (l.groupby(["season", "round", "driver"])["gain"].sum()
             .rename("lap1_gain").reset_index())


def build(seasons: set[int]) -> pd.DataFrame:
    race = pd.read_parquet(HIST / "race_results_all.parquet")
    race = race[race["season"].isin(seasons)]
    spr = pd.read_parquet(HIST / "sprint_results_all.parquet")
    spr = spr[spr["season"].isin(seasons)]
    q = pd.read_parquet(HIST / "quali_results_all.parquet")
    q = q[q["season"].isin(seasons)]

    base = _results_block(race, "race")
    base = base.merge(_results_block(spr, "spr"), on=["season", "round", "driver"],
                      how="left")
    qp = pd.DataFrame({"season": q["season"].astype(int),
                       "round": q["round_number"].astype(int),
                       "driver": q["Abbreviation"],
                       "quali_pos": _num(q["Position"])})
    base = base.merge(qp, on=["season", "round", "driver"], how="left")

    pace = pd.read_csv("data/driver_pace_by_event.csv")
    pace = pace[pace["season"].isin(seasons) & pace["round"].notna()]
    pace["round"] = pace["round"].astype(int)
    pq = (pace[pace["kind"] == "quali"]
          .rename(columns={"gap_pct": "quali_gap_pct", "n_sessions": "quali_nsess"})
          [["season", "round", "driver", "quali_gap_pct", "quali_nsess"]])
    pr = (pace[pace["kind"] == "race"]
          .rename(columns={"gap_pct": "race_gap_pct", "se_pct": "race_se_pct",
                           "n_clean": "race_n_clean"})
          [["season", "round", "driver", "race_gap_pct", "race_se_pct", "race_n_clean"]])
    base = (base.merge(pq.drop_duplicates(["season", "round", "driver"]),
                       on=["season", "round", "driver"], how="left")
                .merge(pr.drop_duplicates(["season", "round", "driver"]),
                       on=["season", "round", "driver"], how="left"))

    base = base.merge(_laps_block(seasons), on=["season", "round", "driver"], how="left")
    rounds = base[["season", "round", "event"]].drop_duplicates()
    base = base.merge(_pit_block(rounds), on=["season", "round", "driver"], how="left")
    base["pit_n"] = base["pit_n"].fillna(0).astype(int)
    key = ["season", "round", "driver"]
    base = (base.merge(_mistakes_block(rounds), on=key, how="left")
                .merge(_dnf_block(seasons), on=key, how="left")
                .merge(_incident_block(seasons), on=key, how="left")
                .merge(_lap1_block(rounds), on=key, how="left"))
    # Seasons the DNF register / incident log cover: a missing row there is
    # a zero, not unknown. Outside them it stays NaN (no data).
    for cols, src in ((list(DNF_FAMILY_COL.values()) + ["dnf_unknown"], "data/dnf_causes.csv"),
                      (["inc_n", "pen_n"], "data/incidents.csv")):
        covered = set(pd.read_csv(src, usecols=["season"])["season"].unique())
        for c in cols:
            if c not in base.columns:
                base[c] = np.nan
            m = base["season"].isin(covered)
            base.loc[m, c] = base.loc[m, c].fillna(0)
    base["dnf_n"] = (~base["race_classified"].astype(bool)).astype(int)

    per_event = []
    for r in rounds.sort_values(["season", "round"]).itertuples(index=False):
        paths = _session_paths(r.season, r.event)
        blk = _race_lap_block(paths).merge(_session_scan(paths), on="driver",
                                           how="outer")
        bw = _bw_flags(paths)
        blk["bw_flags"] = (blk["driver"].map(lambda d: bw.get(d, 0))
                           if bw is not None else np.nan)
        blk["season"], blk["round"] = r.season, r.round
        per_event.append(blk)
        print(f"  {r.season} R{r.round:>2} {r.event}: {len(paths)} sessions, "
              f"{int(blk['passes_made'].sum(min_count=1) or 0)} passes, "
              f"{blk['cons_pct'].notna().sum()} consistency", flush=True)
    if per_event:
        base = base.merge(pd.concat(per_event, ignore_index=True),
                          on=["season", "round", "driver"], how="left")

    lead = ["season", "round", "event", "team", "driver"]
    base = base[lead + [c for c in base.columns if c not in lead]]
    return base.sort_values(["season", "round", "team", "driver"]).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, help="rebuild one season only")
    args = ap.parse_args()
    race = pd.read_parquet(HIST / "race_results_all.parquet", columns=["season"])
    all_seasons = set(int(s) for s in race["season"].unique())
    seasons = {args.season} if args.season else all_seasons
    new = build(seasons)
    if args.season and KPI_CSV.exists():
        old = pd.read_csv(KPI_CSV)
        new = pd.concat([old[old["season"] != args.season], new], ignore_index=True)
        new = new.sort_values(["season", "round", "team", "driver"])
    new.to_csv(KPI_CSV, index=False)
    # the reliability every card shows next to its title (validation bar)
    import json
    rel = split_half(new)
    RELIABILITY_JSON.write_text(json.dumps(rel, indent=1))
    print("split-half (Spearman-Brown, 2023+): "
          + ", ".join(f"{k} {v['driver']}/{v['teammate']}" for k, v in rel.items()))
    print(f"\nWrote {len(new)} rows -> {KPI_CSV} "
          f"(seasons {sorted(new['season'].unique())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
