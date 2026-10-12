"""Per-event driver KPIs and the "last N events" window over them.

The TEAM & TEAMATE tab used to compute everything from the laps of the ONE
loaded event. To show any KPI over a window of events without re-loading N
events of raw laps, every KPI is first reduced to one value per
(season, round, driver) by `scripts/compute_driver_event_kpis.py`, written to
data/driver_event_kpis.csv, and the tab only filters and aggregates.

Window-validity rules (why the columns look the way they do)
-----------------------------------------------------------
* Anything in SECONDS that depends on the circuit (lap time, pit-lane time)
  is stored relative to that event's field — a % gap or a delta to the event
  median — so it can be averaged across circuits.
* Anything that is a rate is stored as its numerator AND denominator
  (pit_lane_delta_sum / pit_n, gained_sum / gained_n, ...) so a window
  aggregate is sum/sum, not a mean of means.
* Rows are keyed on (season, round, driver). Drivers are unique within an
  event, so stores that spell the team differently (pit_league, lap_retention)
  join on the driver and the team comes from the results archive — the
  spelling the sidebar and TEAM_COLORS use for that season.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

KPI_CSV = Path("data/driver_event_kpis.csv")

# lap_retention session name -> lap-count bucket shown on the tab
SESSION_BUCKET = {
    "Practice 1": "fp", "Practice 2": "fp", "Practice 3": "fp",
    "Qualifying": "q", "Sprint Qualifying": "q", "Sprint Shootout": "q",
    "Sprint": "sprint", "Race": "race",
}
LAP_BUCKETS = ("fp", "q", "sprint", "race")

# A stop this far above the event's median pit-lane time is "slow" — clear of
# the normal 0.3-0.6 s crew scatter, below a drive-through.
SLOW_STOP_S = 1.0

# consistency: minimum clean laps in a stint before its spread is trusted
CONS_MIN_STINT_LAPS = 6


# ─────────────────────────────────────────────────────────────
# Race-lap computations
# ─────────────────────────────────────────────────────────────

def overtake_pairs(laps: pd.DataFrame) -> list[tuple[int, str, str]]:
    """(lap, passer, passed) for every green-flag, non-pit on-track pass.

    A pass is a pairwise inversion of the running order between two
    consecutive laps, counted only between cars that were both on track on
    both laps, both under green, and neither touching the pit lane — so a
    place gained because a rival pitted or retired is not a pass. Two passes
    on one lap count as two. Lap 1 is excluded (no previous lap to compare;
    the start has its own lap-1 KPI).
    """
    need = {"Driver", "LapNo", "Position", "PitIn", "PitOut", "TrackStatus"}
    if not need.issubset(laps.columns):
        return []
    d = laps.dropna(subset=["LapNo", "Position"]).copy()
    d["LapNo"] = d["LapNo"].astype(int)
    d["green"] = d["TrackStatus"].astype(str) == "1"
    d["pit"] = d["PitIn"].notna() | d["PitOut"].notna()

    by_lap: dict[int, dict[str, tuple[float, bool, bool]]] = {}
    for r in d.itertuples():
        by_lap.setdefault(r.LapNo, {})[r.Driver] = (r.Position, r.pit, r.green)

    out: list[tuple[int, str, str]] = []
    for n in sorted(by_lap):
        if n <= 1 or (n - 1) not in by_lap:
            continue
        prev, cur = by_lap[n - 1], by_lap[n]
        drs = [a for a in cur
               if a in prev and cur[a][2] and prev[a][2]
               and not cur[a][1] and not prev[a][1]]
        if len(drs) < 2:
            continue
        order_prev = sorted(drs, key=lambda a: prev[a][0])
        pos_cur = {a: cur[a][0] for a in drs}
        for i in range(len(order_prev)):
            for j in range(i + 1, len(order_prev)):
                if pos_cur[order_prev[j]] < pos_cur[order_prev[i]]:
                    out.append((n, order_prev[j], order_prev[i]))
    return out


def driver_abbr(driver_field: str) -> str:
    """'NOR-McLaren' (raw lap Driver field) -> 'NOR'."""
    return str(driver_field).split("-", 1)[0]


def stint_consistency(fl: pd.DataFrame) -> pd.DataFrame:
    """Per-driver lap-to-lap spread inside race stints, % of lap time.

    Within each stint the fuel-corrected lap is detrended on tyre age (a
    straight line absorbs fuel burn left over plus linear wear), and the
    robust spread of what is left (1.4826 x MAD) is taken as % of the stint
    median. Stints are pooled weighted by their lap count. What this
    removes, compared with the old IQR over all laps of all sessions, is
    the run PLAN (fuel loads, compounds, session mix); what is left is how
    repeatably the driver laps once the plan is fixed.
    Clean laps only: valid, not perturbed (SC/VSC/yellow), not in/out laps.
    """
    if fl.empty or "Stint" not in fl.columns:
        return pd.DataFrame(columns=["driver", "cons_pct", "cons_n"])
    y = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in fl.columns \
        else "LapTime_s"
    m = fl["ValidLap"].astype(bool)
    for c in ("Perturbed_Lap", "InLap", "OutLap"):
        if c in fl.columns:
            m &= ~fl[c].fillna(False).astype(bool)
    c = fl[m & fl[y].notna()]
    rows = []
    for drv, g in c.groupby("Driver_Short"):
        num = den = 0.0
        for _, s in g.groupby("Stint"):
            if len(s) < CONS_MIN_STINT_LAPS:
                continue
            t = s[y].to_numpy(dtype=float)
            age = (pd.to_numeric(s["TyreAge"], errors="coerce").to_numpy(dtype=float)
                   if "TyreAge" in s.columns else np.arange(len(s), dtype=float))
            if np.isnan(age).any() or np.ptp(age) == 0:
                age = np.arange(len(s), dtype=float)
            resid = t - np.polyval(np.polyfit(age, t, 1), age)
            spread = 1.4826 * float(np.median(np.abs(resid - np.median(resid))))
            num += spread / float(np.median(t)) * 100.0 * len(s)
            den += len(s)
        if den:
            rows.append({"driver": drv, "cons_pct": round(num / den, 4),
                         "cons_n": int(den)})
    return pd.DataFrame(rows, columns=["driver", "cons_pct", "cons_n"])


# ─────────────────────────────────────────────────────────────
# Window
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=2)
def _load(mtime: float) -> pd.DataFrame:
    return pd.read_csv(KPI_CSV)


def load_kpis() -> pd.DataFrame:
    """The per-event table (cached until the file changes)."""
    if not KPI_CSV.exists():
        return pd.DataFrame()
    return _load(KPI_CSV.stat().st_mtime)


def window_rounds(kpis: pd.DataFrame, season: int, round_end: int,
                  n: int) -> list[int]:
    """The last `n` rounds of `season` up to and including `round_end`.
    Never crosses into the previous season: the window stops at round 1."""
    if kpis.empty:
        return []
    rs = sorted(int(r) for r in kpis.loc[kpis["season"] == season, "round"].unique()
                if int(r) <= round_end)
    return rs[-n:] if n > 0 else rs


def window(kpis: pd.DataFrame, season: int, round_end: int, n: int
           ) -> pd.DataFrame:
    rs = window_rounds(kpis, season, round_end, n)
    return kpis[(kpis["season"] == season) & kpis["round"].isin(rs)].copy()


# ─────────────────────────────────────────────────────────────
# Split-half reliability (the derived-axis validation bar)
# ─────────────────────────────────────────────────────────────
# Each KPI as the tab aggregates it: ("mean", col) = mean of a per-event
# column; ("ratio", num, den) = sum(num) / sum(den). Derived columns are
# built by _with_derived below.
RELIABILITY_KPIS = {
    "race":   ("mean", "race_gap_pct"),
    "quali":  ("mean", "quali_gap_pct"),
    "best":   ("mean", "best_lap_pct"),
    "cons":   ("mean", "cons_pct"),
    "laps":   ("mean", "_laps"),
    "pit":    ("ratio", "pit_lane_delta_sum", "pit_n"),
    "gain":   ("mean", "_gained"),
    "pass":   ("mean", "passes_made"),
    "pts":    ("mean", "_pts"),
    "mk":     ("ratio", "mk_n", "mk_laps"),
    "mkp":    ("ratio", "mk_n_p", "mk_laps_p"),
    "delr":   ("mean", "deleted_race"),
    "delq":   ("mean", "deleted_quali"),
    "bw":     ("mean", "bw_flags"),
    "pen":    ("mean", "pen_n"),
    "inc":    ("mean", "inc_n"),
    "purple": ("mean", "_purple"),
    "fl":     ("mean", "race_fl_rank"),
    "ideal":  ("mean", "ideal_gap_pct"),
    "l1":     ("mean", "lap1_gain"),
    "dnfc":   ("mean", "dnf_car"),
    "dnfd":   ("mean", "dnf_driver"),
}
RELIABILITY_JSON = Path("data/driver_event_kpis_reliability.json")
RELIABILITY_BAR = 0.6
_MIN_HALF_EVENTS = 4


def _with_derived(k: pd.DataFrame) -> pd.DataFrame:
    k = k.copy()
    k["_laps"] = k[[f"laps_{b}" for b in LAP_BUCKETS]].sum(axis=1, min_count=1)
    k["_gained"] = (k["race_gained"].fillna(0) + k["spr_gained"].fillna(0)).where(
        k["race_gained"].notna() | k["spr_gained"].notna())
    k["_pts"] = k["race_points"] + k["spr_points"].fillna(0)
    k["_purple"] = (k["purple_quali"].fillna(0) + k["purple_race"].fillna(0)).where(
        k["purple_quali"].notna() | k["purple_race"].notna())
    return k


def _half_values(ks: pd.DataFrame, spec) -> pd.DataFrame:
    """(team, driver) x half(0/1) value table, drivers with enough events."""
    kind, a = spec[0], spec[1]
    if kind == "mean":
        d = ks.dropna(subset=[a])
        g = d.groupby(["team", "driver", "half"])[a]
        v = g.mean().where(g.count() >= _MIN_HALF_EVENTS)
    else:
        b = spec[2]
        d = ks.dropna(subset=[a, b])
        d = d[d[b] > 0]
        g = d.groupby(["team", "driver", "half"])
        v = (g[a].sum() / g[b].sum()).where(g.size() >= _MIN_HALF_EVENTS)
    return v.unstack("half").dropna() if not v.empty else pd.DataFrame()


def split_half(k: pd.DataFrame, min_season: int = 2023) -> dict:
    """Odd-round vs even-round Spearman r per season, averaged, then
    Spearman-Brown stepped up to the full season: 2r / (1 + r).

    'driver'   — does the driver's own value repeat? (team half reading)
    'teammate' — does the gap to the teammate repeat? (teammate half)
    """
    k = _with_derived(k[k["season"] >= min_season])
    k["half"] = k["round"] % 2
    out = {}
    for name, spec in RELIABILITY_KPIS.items():
        if spec[1] not in k.columns or k[spec[1]].notna().sum() == 0:
            continue
        rd, rt = [], []
        for _, ks in k.groupby("season"):
            v = _half_values(ks, spec)
            if v.shape[1] < 2 or len(v) < 8:
                continue
            rd.append(v[0].corr(v[1], method="spearman"))
            pair = v[v.groupby(level="team")[0].transform("size") == 2]
            dlt = (pair - pair.groupby(level="team").transform("mean"))
            dlt = dlt.groupby(level="team").head(1)
            if len(dlt) >= 6:
                rt.append(dlt[0].corr(dlt[1], method="spearman"))

        def sb(rs):
            rs = [r for r in rs if pd.notna(r)]
            if not rs:
                return None
            r = float(np.mean(rs))
            return round(2 * r / (1 + r), 2) if r > 0 else round(r, 2)
        out[name] = {"driver": sb(rd), "teammate": sb(rt), "seasons": len(rd)}
    return out


def load_reliability() -> dict:
    import json
    try:
        return json.loads(RELIABILITY_JSON.read_text())
    except Exception:
        return {}
