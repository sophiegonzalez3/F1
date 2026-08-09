"""Derive per-race operational stats from the cached race archive.

Everything here is measured — no hand-curated ratings. For every cached Race
session in data/sessions it computes:

  safety cars    – SC / VSC deployments (track_status transitions) and how many
                   of the leader's laps ran under each; red-flag count
  overtakes      – green-flag, non-pit on-track passes, counted as pairwise
                   order inversions between consecutive lap charts (standard
                   lap-chart method: excludes lap 1, any driver in a pit cycle,
                   and laps not run entirely under green)
  lap-1 chaos    – mean |position change| on lap 1 vs the grid (pit-lane
                   starters excluded), plus a per-driver lap-1 gain table
  weather        – mean air / track temp and whether rain fell during the race
  track limits   – laps deleted (race-control messages), with a per-corner
                   hotspot table parsed from the "AT TURN n" text
  pit loss       – median green-flag cost of a stop: (in-lap + out-lap)
                   − 2 × the driver's median clean lap; plus the median
                   stationary time from data/pitstops when available
  strategy       – the winner's stint structure ("M14 → H38"), the field's
                   modal stop count and the one-stop share among finishers

Outputs
-------
  data/race_stats.csv    one row per race (the TRACK weekend guide and the
                         SEASON chaos/ops cards read this)
  data/track_limits.csv  season, meeting, circuit_key, turn, deleted
  data/lap1_league.csv   season, meeting, driver, team, grid, lap1_pos, gain
  data/pit_league.csv    one row per pit stop with the team attached (from the
                         race results), for the SEASON pit-stop league

Usage
-----
    python scripts/compute_race_stats.py             # all cached races
    python scripts/compute_race_stats.py --verbose   # per-race detail
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.config import (HIST_CIRCUIT_KEY_MAP, SESSIONS_DIR,
                         SESSIONS_LITE_DIR)

VERBOSE = "--verbose" in sys.argv

SESSIONS = Path(SESSIONS_DIR)
SESSIONS_LITE = Path(SESSIONS_LITE_DIR)
PITSTOPS_DIR = Path("data/pitstops")
STANDINGS_PATH = Path("data/historical_results/constructor_standings_all.parquet")

OUT_STATS = Path("data/race_stats.csv")
OUT_LIMITS = Path("data/track_limits.csv")
OUT_LAP1 = Path("data/lap1_league.csv")
OUT_PITS = Path("data/pit_league.csv")


def _slugify(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


# slug(event name) → circuit_key, slugifying both sides so accents ("São
# Paulo") normalise the same way the archive filenames do.
_EVENT_TO_CIRCUIT = {
    _slugify(hist): fr
    for fr, hists in HIST_CIRCUIT_KEY_MAP.items() for hist in hists
}


_ARCHIVE: pd.DataFrame | None = None


def _archive_results(season: int, meeting: str) -> pd.DataFrame:
    """Stand-in for a missing `__results.parquet`, built from the archive.

    The laps-only backfill store carries no side files at all, so every
    results-derived figure (lap-1 swing, pit league, strategy) was blank for
    2019-2022 — 82 races reported as missing data rather than measured. The
    results archive holds the same fields for every race in it, so the gap is
    one lookup wide.

    Returns an empty frame if the archive cannot supply the race, which the
    callers already treat as "no results".
    """
    global _ARCHIVE
    if _ARCHIVE is None:
        p = Path("data/historical_results/race_results_all.parquet")
        try:
            _ARCHIVE = pd.read_parquet(p)
        except Exception:
            _ARCHIVE = pd.DataFrame()
    if _ARCHIVE.empty:
        return pd.DataFrame()
    a = _ARCHIVE[(_ARCHIVE["season"] == season)
                 & (_ARCHIVE["event_name"] == meeting)]
    return a.copy() if not a.empty else pd.DataFrame()


def _round_map() -> dict[tuple[int, str], int]:
    """(season, slug(event)) → round number, from the standings archive."""
    if not STANDINGS_PATH.exists():
        return {}
    s = pd.read_parquet(STANDINGS_PATH,
                        columns=["season", "event_name", "round_number"])
    s = s.drop_duplicates(["season", "event_name"])
    return {(int(r.season), _slugify(r.event_name)): int(r.round_number)
            for r in s.itertuples()}


# ─────────────────────────────────────────────────────────────
# Safety cars / red flags (track_status)
# ─────────────────────────────────────────────────────────────

def _safety_stats(ts: pd.DataFrame, leader_laps: pd.DataFrame) -> dict:
    out = {"sc_count": 0, "vsc_count": 0, "red_flags": 0,
           "sc_laps": 0, "vsc_laps": 0}
    if not ts.empty and "Status" in ts.columns:
        codes = ts.sort_values("Time")["Status"].astype(str).tolist()
        prev = None
        for c in codes:
            if c == "4" and prev != "4":
                out["sc_count"] += 1
            elif c == "6" and prev not in ("6", "7"):
                out["vsc_count"] += 1
            elif c == "5" and prev != "5":
                out["red_flags"] += 1
            prev = c
    # laps run under SC / VSC, measured on the leader's lap chart
    if not leader_laps.empty and "TrackStatus" in leader_laps.columns:
        st = leader_laps["TrackStatus"].astype(str)
        out["sc_laps"] = int(st.str.contains("4").sum())
        out["vsc_laps"] = int(st.str.contains("6").sum())

        # DEPLOYMENT COUNTS FROM THE LAP CHART when there is no track_status
        # side file. The laps-only backfill store (2019-2022) has none, and
        # without this every one of those 82 races reports sc_count = 0 — not
        # "unknown" but a confident zero, which silently halved the measured
        # safety-car rate (0.54 -> 0.28) and destroyed the comparison it fed.
        #
        # Safe because it agrees exactly with the side file wherever both
        # exist: any_sc by season came out 0.583/0.375/0.542/0.545 either way
        # across 2023-2026. Resolution is per-lap rather than per-message, so
        # two deployments inside one lap read as one — acceptable for a
        # deployment COUNT, and the share-of-races figure is unaffected.
        if ts.empty or "Status" not in ts.columns:
            seq = leader_laps.sort_values(
                "LapNo" if "LapNo" in leader_laps.columns
                else leader_laps.columns[0])["TrackStatus"].astype(str)
            for code, field in (("4", "sc_count"), ("6", "vsc_count"),
                                ("5", "red_flags")):
                inside = seq.str.contains(code)
                out[field] = int((inside & ~inside.shift(1, fill_value=False)).sum())
    return out


# ─────────────────────────────────────────────────────────────
# Overtakes (lap-chart inversion count)
# ─────────────────────────────────────────────────────────────

def _overtakes(laps: pd.DataFrame) -> int | None:
    need = {"Driver", "LapNo", "Position", "PitIn", "PitOut", "TrackStatus"}
    if not need.issubset(laps.columns):
        return None
    d = laps.dropna(subset=["LapNo", "Position"]).copy()
    d["LapNo"] = d["LapNo"].astype(int)
    d["green"] = d["TrackStatus"].astype(str) == "1"
    d["pit"] = d["PitIn"].notna() | d["PitOut"].notna()

    by_lap: dict[int, dict[str, tuple[float, bool, bool]]] = {}
    for r in d.itertuples():
        by_lap.setdefault(r.LapNo, {})[r.Driver] = (r.Position, r.pit, r.green)

    total = 0
    for n in sorted(by_lap):
        if n <= 1 or (n - 1) not in by_lap:
            continue
        prev, cur = by_lap[n - 1], by_lap[n]
        # drivers present on both laps, green both laps, no pit activity either lap
        drs = [a for a in cur
               if a in prev and cur[a][2] and prev[a][2]
               and not cur[a][1] and not prev[a][1]]
        if len(drs) < 2:
            continue
        order_prev = sorted(drs, key=lambda a: prev[a][0])
        pos_cur = {a: cur[a][0] for a in drs}
        # pairwise inversions between the two orderings = passes
        for i in range(len(order_prev)):
            for j in range(i + 1, len(order_prev)):
                if pos_cur[order_prev[j]] < pos_cur[order_prev[i]]:
                    total += 1
    return total


# ─────────────────────────────────────────────────────────────
# Lap 1 (grid → end of lap 1)
# ─────────────────────────────────────────────────────────────

def _lap1(laps: pd.DataFrame, results: pd.DataFrame):
    """(mean |swing|, per-driver rows). Pit-lane starters excluded."""
    if results.empty or "GridPosition" not in results.columns:
        return None, []
    l1 = laps[laps["LapNo"] == 1].dropna(subset=["Position"])
    if l1.empty:
        return None, []
    grid = {}
    team = {}
    abbr = {}
    for r in results.itertuples():
        dno = str(r.DriverNumber).strip()
        g = float(r.GridPosition) if pd.notna(r.GridPosition) else 0.0
        grid[dno] = g
        team[dno] = str(r.TeamName)
        abbr[dno] = str(r.Abbreviation)
    rows, swings = [], []
    for r in l1.itertuples():
        dno = str(r.DriverNo).strip()
        g = grid.get(dno)
        if not g:                      # 0 / NaN = pit-lane start
            continue
        gain = g - float(r.Position)
        swings.append(abs(gain))
        rows.append({"driver": abbr.get(dno, dno), "team": team.get(dno, ""),
                     "grid": int(g), "lap1_pos": int(r.Position),
                     "gain": int(gain)})
    return (round(float(np.mean(swings)), 2) if swings else None), rows


# ─────────────────────────────────────────────────────────────
# Race control: deleted laps / track limits
# ─────────────────────────────────────────────────────────────

_TURN_RE = re.compile(r"TURN\s+(\d+)")


def _deleted_laps(rcm: pd.DataFrame):
    if rcm.empty or "Message" not in rcm.columns:
        return 0, {}
    msg = rcm["Message"].astype(str).str.upper()
    deleted = msg[msg.str.contains("DELETED") & ~msg.str.contains("REINSTATED")]
    per_turn: dict[int, int] = {}
    for m in deleted:
        t = _TURN_RE.search(m)
        if t:
            per_turn[int(t.group(1))] = per_turn.get(int(t.group(1)), 0) + 1
    return int(len(deleted)), per_turn


# ─────────────────────────────────────────────────────────────
# Pit loss + strategy (laps)
# ─────────────────────────────────────────────────────────────

def _pit_and_strategy(laps: pd.DataFrame, results: pd.DataFrame) -> dict:
    out = {"pit_loss_s": None, "winner": "", "winner_strategy": "",
           "stops_mode": None, "one_stop_pct": None}
    d = laps.dropna(subset=["LapNo"]).copy()
    d["LapNo"] = d["LapNo"].astype(int)
    lt = pd.to_numeric(d["LapTime"], errors="coerce")
    green = d["TrackStatus"].astype(str) == "1"
    clean = lt.notna() & green & d["PitIn"].isna() & d["PitOut"].isna()

    # median green-flag time lost per stop, vs the driver's own clean pace
    losses = []
    for drv, g in d.groupby("Driver"):
        g = g.sort_values("LapNo")
        base = pd.to_numeric(g.loc[clean.reindex(g.index, fill_value=False),
                                   "LapTime"], errors="coerce").median()
        if pd.isna(base):
            continue
        for r in g[g["PitIn"].notna()].itertuples():
            nxt = g[g["LapNo"] == r.LapNo + 1]
            if nxt.empty or pd.isna(r.LapTime):
                continue
            nxt = nxt.iloc[0]
            if pd.isna(nxt["LapTime"]) or pd.isna(nxt["PitOut"]):
                continue
            # green-flag stops only — SC stops distort the cost
            if str(r.TrackStatus) != "1" or str(nxt["TrackStatus"]) != "1":
                continue
            losses.append(float(r.LapTime) + float(nxt["LapTime"]) - 2 * base)
    if losses:
        out["pit_loss_s"] = round(float(np.median(losses)), 1)

    # stint structure per classified finisher → stops; winner's strategy string
    if results.empty:
        return out
    res = results.copy()
    res["Position"] = pd.to_numeric(res["Position"], errors="coerce")
    finishers = res[res["Status"].astype(str).str.startswith(("Finished", "+"))]
    stops = []
    for r in finishers.itertuples():
        dno = str(r.DriverNumber).strip()
        g = d[d["DriverNo"].astype(str).str.strip() == dno]
        if g.empty or "Stint" not in g.columns:
            continue
        n_stints = g["Stint"].dropna().nunique()
        if n_stints:
            stops.append(n_stints - 1)
        if r.Position == 1:
            out["winner"] = str(r.Abbreviation)
            stints = (g.dropna(subset=["Stint"]).groupby("Stint")
                      .agg(compound=("Compound", "first"), n=("LapNo", "count"))
                      .sort_index())
            out["winner_strategy"] = " → ".join(
                f"{str(c)[:1]}{int(n)}" for c, n in
                zip(stints["compound"], stints["n"]))
    if stops:
        vals, counts = np.unique(stops, return_counts=True)
        out["stops_mode"] = int(vals[np.argmax(counts)])
        out["one_stop_pct"] = round(100.0 * (np.array(stops) == 1).mean(), 0)
    return out


def _pitstop_file_stats(season, meeting) -> dict:
    """Median stationary / pit-lane time from data/pitstops (when collected)."""
    out = {"pit_stationary_med_s": None, "pit_lane_med_s": None}
    san = re.sub(r"[^A-Za-z0-9_\-]", "_", str(meeting)).strip("_")
    p = PITSTOPS_DIR / f"{season}__{san}__Race__pitstops.parquet"
    if not p.exists():
        return out
    try:
        df = pd.read_parquet(p)
    except Exception:
        return out
    st = pd.to_numeric(df.get("StationaryTime_s"), errors="coerce").dropna()
    pl = pd.to_numeric(df.get("PitLaneTime_s"), errors="coerce").dropna()
    if len(st):
        out["pit_stationary_med_s"] = round(float(st.median()), 2)
    if len(pl):
        out["pit_lane_med_s"] = round(float(pl.median()), 1)
    return out


def _pit_league_rows(season, meeting, circuit, results: pd.DataFrame) -> list[dict]:
    """One row per pit stop with the team attached (results DriverNumber →
    TeamName). Jolpica-sourced stops carry only pit-lane time (no stationary)."""
    san = re.sub(r"[^A-Za-z0-9_\-]", "_", str(meeting)).strip("_")
    p = PITSTOPS_DIR / f"{season}__{san}__Race__pitstops.parquet"
    if not p.exists() or results.empty:
        return []
    try:
        df = pd.read_parquet(p)
    except Exception:
        return []
    team = {str(r.DriverNumber).strip(): str(r.TeamName)
            for r in results.itertuples()}
    rows = []
    for r in df.itertuples():
        dno = str(r.DriverNo).strip()
        rows.append({
            "season": season, "meeting": meeting, "circuit_key": circuit,
            "team": team.get(dno, ""), "driver": str(r.Driver_Short),
            "lap": int(r.LapNo) if pd.notna(r.LapNo) else None,
            "stationary_s": (round(float(r.StationaryTime_s), 2)
                             if pd.notna(r.StationaryTime_s) else None),
            "pitlane_s": (round(float(r.PitLaneTime_s), 1)
                          if pd.notna(r.PitLaneTime_s) else None),
        })
    return rows


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    rounds = _round_map()
    stats_rows, limits_rows, lap1_rows, pit_rows = [], [], [], []

    # BOTH session stores, not just the full one. They are disjoint by design:
    # data/sessions/ carries telemetry and so only holds 2023-2026 (86 races),
    # while data/sessions_lite/ is the laps-only backfill and holds 2019-2022
    # (82 races). Globbing one directory silently discarded HALF the archive —
    # every safety-car, lap-1 and pit figure here was measured on 59 races when
    # ~160 were available, which is why per-circuit safety-car rates looked
    # like noise (3 races a circuit rather than 8-16).
    #
    # Same blind spot, same fix as driver_ratings._race_driver_gaps and
    # compute_team_pace.py, both of which already read both stores. The lite
    # store carries every column used here (TrackStatus, Position, ...); what
    # it has less of is side files, which _side() already treats as optional.
    seen: set[str] = set()
    lap_files = []
    for base in (SESSIONS, SESSIONS_LITE):
        for p in sorted(Path(base).glob("*__Race__laps.parquet")):
            if p.name in seen:
                continue          # the full cache wins for the same event
            seen.add(p.name)
            lap_files.append(p)

    # A race occasionally sits in the archive under two meeting names (e.g.
    # 2025 "Barcelona Grand Prix" = "Spanish Grand Prix"). When several
    # meetings share a (season, circuit) and only some have a round number in
    # the standings, the round-less ones are the duplicates — skip them.
    index = []
    for lp in lap_files:
        head = pd.read_parquet(lp, columns=["season", "meeting"]).iloc[0]
        season, meeting = int(head["season"]), str(head["meeting"])
        circuit = _EVENT_TO_CIRCUIT.get(_slugify(meeting), "")
        index.append((lp, season, meeting, circuit,
                      rounds.get((season, _slugify(meeting)))))
    with_round = {(s, c) for _, s, _, c, r in index if r is not None and c}
    kept = [t for t in index
            if not (t[4] is None and t[3] and (t[1], t[3]) in with_round)]
    if len(kept) < len(index):
        for t in index:
            if t not in kept:
                print(f"  skipping duplicate archive entry: {t[1]} {t[2]}")

    print(f"Scanning {len(kept)} cached races …")
    for lp, season, meeting, circuit, _rnd in kept:
        key = lp.name.replace("__laps.parquet", "")
        laps = pd.read_parquet(lp)

        def _side(name):
            p = SESSIONS / f"{key}__{name}.parquet"
            try:
                return pd.read_parquet(p) if p.exists() else pd.DataFrame()
            except Exception:
                return pd.DataFrame()

        ts, rcm, wx, res = (_side("track_status"), _side("race_control"),
                            _side("weather"), _side("results"))
        if res.empty:                       # laps-only store: no side files
            res = _archive_results(season, meeting)

        leader = laps[pd.to_numeric(laps["Position"], errors="coerce") == 1]
        row = {"season": season, "meeting": meeting, "circuit_key": circuit,
               "round": rounds.get((season, _slugify(meeting)))}
        row.update(_safety_stats(ts, leader))
        row["overtakes"] = _overtakes(laps)

        swing, drivers = _lap1(laps, res)
        row["lap1_avg_swing"] = swing
        for drow in drivers:
            lap1_rows.append({"season": season, "meeting": meeting,
                              "circuit_key": circuit, **drow})

        n_del, per_turn = _deleted_laps(rcm)
        row["deleted_laps"] = n_del
        for turn, n in sorted(per_turn.items()):
            limits_rows.append({"season": season, "meeting": meeting,
                                "circuit_key": circuit, "turn": turn,
                                "deleted": n})

        if not wx.empty:
            row["airtemp_c"] = round(float(pd.to_numeric(
                wx["AirTemp"], errors="coerce").mean()), 1)
            row["tracktemp_c"] = round(float(pd.to_numeric(
                wx["TrackTemp"], errors="coerce").mean()), 1)
            row["rain"] = bool(wx["Rainfall"].astype(bool).any())
        else:
            row["airtemp_c"] = row["tracktemp_c"] = None
            row["rain"] = None

        row.update(_pit_and_strategy(laps, res))
        row.update(_pitstop_file_stats(season, meeting))
        pit_rows += _pit_league_rows(season, meeting, circuit, res)

        stats_rows.append(row)
        if VERBOSE:
            print(f"  {season} {meeting:<28} SC {row['sc_count']} "
                  f"({row['sc_laps']} laps) VSC {row['vsc_count']} "
                  f"red {row['red_flags']} OT {row['overtakes']} "
                  f"del {row['deleted_laps']} pitloss {row['pit_loss_s']} "
                  f"win {row['winner']} {row['winner_strategy']}")

    cols = ["season", "round", "meeting", "circuit_key",
            "sc_count", "sc_laps", "vsc_count", "vsc_laps", "red_flags",
            "overtakes", "lap1_avg_swing", "deleted_laps",
            "rain", "airtemp_c", "tracktemp_c",
            "pit_loss_s", "pit_stationary_med_s", "pit_lane_med_s",
            "winner", "winner_strategy", "stops_mode", "one_stop_pct"]
    df = pd.DataFrame(stats_rows)[cols].sort_values(["season", "round"])
    df.to_csv(OUT_STATS, index=False)
    pd.DataFrame(limits_rows).to_csv(OUT_LIMITS, index=False)
    pd.DataFrame(lap1_rows).to_csv(OUT_LAP1, index=False)
    pd.DataFrame(pit_rows).to_csv(OUT_PITS, index=False)
    print(f"Wrote {OUT_STATS}  ({len(df)} races)")
    print(f"Wrote {OUT_LIMITS} ({len(limits_rows)} corner rows)")
    print(f"Wrote {OUT_LAP1}   ({len(lap1_rows)} driver rows)")
    print(f"Wrote {OUT_PITS}   ({len(pit_rows)} pit stops)")


if __name__ == "__main__":
    main()
