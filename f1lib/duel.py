"""Head-to-head duel analysis — how does driver A beat driver B at this event?

The DUEL tab's engine. Everything here is pure analysis on dataframes the tab
passes in; no Dash imports. Four families of machinery:

1. duel_simulation      pairwise Monte Carlo from the existing RaceForecaster:
                        P(A finishes ahead of B) plus a channel decomposition —
                        pace draw only → + grid & track position → + race-day
                        chaos → + reliability — and the conditional "paths to
                        victory" (outqualify-and-convert, comeback, B retires).
2. archive head-to-head h2h_record / circuit_results from the historical
                        results archive (2021+), overall and at this circuit.
3. situational profiles lap-1 habits (lap1_league.csv), per-team mechanical
                        DNF rates, circuit SC/VSC probability (race_stats.csv).
4. on-track comparison  corner-by-corner time deltas between two laps'
                        telemetry + DRS-zone tagging → attack zones.

Honesty notes are attached to the numbers where the data is thin — the tab
surfaces them; nothing here pretends single-weekend samples are destiny.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HIST = Path("data/historical_results")
LAP1_CSV = Path("data/lap1_league.csv")
RACE_STATS_CSV = Path("data/race_stats.csv")
MISTAKES_ALL = Path("data/mistakes_all.parquet")
MISTAKES_PRESSURE = Path("data/mistakes_pressure_all.parquet")

_DNF_MECH_KEYWORDS = (
    "Engine", "Gearbox", "Hydraulics", "Power", "Brakes", "Suspension",
    "Transmission", "Electrical", "Overheating", "Mechanical", "Puncture",
    "Wheel", "Fuel", "Water", "Oil", "Clutch", "Driveshaft", "Battery",
    "Exhaust", "Radiator", "Vibrations", "Steering", "Retired", "Withdrew",
)
_DNF_INCIDENT_KEYWORDS = ("Accident", "Collision", "Spun", "Damage", "Debris")


# ─────────────────────────────────────────────────────────────
# 1. Pairwise Monte Carlo with channel decomposition
# ─────────────────────────────────────────────────────────────

def duel_simulation(forecaster, race_pred: pd.DataFrame, *, event: str,
                    a: str, b: str,
                    grid: dict[str, int] | None = None,
                    quali_pred: pd.DataFrame | None = None,
                    dnf_rates: dict[str, float] | None = None) -> dict | None:
    """P(A finishes ahead of B) with a decomposition into channels.

    Runs the RaceForecaster Monte Carlo four times with channels switched on
    one at a time (same model, different noise/DNF settings) so the ladder

        pace draw → + grid & passability → + race-day chaos → + reliability

    shows where A's chances come from. The full run also yields conditionals:
    how often A out-qualifies B and converts, wins from behind on the grid,
    or inherits the place through a B retirement.
    """
    if race_pred is None or race_pred.empty:
        return None
    drivers = set(race_pred["driver"])
    if a not in drivers or b not in drivers:
        return None

    def _sim(seed, noise=None, no_dnf=False):
        rates = ({d: 0.0 for d in drivers} if no_dnf else dnf_rates)
        return forecaster.simulate(
            race_pred, event=event, grid=grid, quali_pred=quali_pred,
            rng=np.random.default_rng(seed), dnf_rates=rates,
            race_noise=noise)

    full = _sim(23)
    if full is None:
        return None
    ia, ib = full["drivers"].index(a), full["drivers"].index(b)

    def _p_ahead(sim):
        return float((sim["finish"][:, ia] < sim["finish"][:, ib]).mean())

    # ladder: each stage adds one channel
    s_pace = _sim(23, noise=0.0, no_dnf=True)
    p_pace = float((s_pace["pace_rank"][:, ia]
                    < s_pace["pace_rank"][:, ib]).mean())
    p_track = _p_ahead(s_pace)                    # + grid & passability
    s_noise = _sim(23, no_dnf=True)
    p_chaos = _p_ahead(s_noise)                   # + race-day shuffle
    p_full = _p_ahead(full)                       # + reliability

    fin_a, fin_b = full["finish"][:, ia], full["finish"][:, ib]
    dnf_a, dnf_b = full["dnf"][:, ia], full["dnf"][:, ib]
    grid_a, grid_b = full["grid_rank"][:, ia], full["grid_rank"][:, ib]
    ahead = fin_a < fin_b
    outq = grid_a < grid_b

    def _safe(num, den):
        return float(num / den) if den > 0 else float("nan")

    # championship points swing at this event (DNF = no points)
    pts_map = np.zeros(len(full["drivers"]) + 2)
    pts_map[1:11] = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1][: min(10, len(pts_map) - 1)]
    pts_a = np.where(dnf_a, 0.0, pts_map[np.clip(fin_a, 0, len(pts_map) - 1)])
    pts_b = np.where(dnf_b, 0.0, pts_map[np.clip(fin_b, 0, len(pts_map) - 1)])
    swing = pts_a - pts_b

    n = len(fin_a)
    out = {
        "a": a, "b": b, "pull": full["pull"],
        "p_ahead": p_full,
        "ladder": {"pace": p_pace, "track": p_track,
                   "chaos": p_chaos, "full": p_full},
        # paths to victory (decomposition of the winning sims)
        "p_outqualify": float(outq.mean()),
        "p_convert_from_ahead": _safe((ahead & outq).sum(), outq.sum()),
        "p_comeback": _safe((ahead & ~outq).sum(), (~outq).sum()),
        "share_win_from_behind": _safe((ahead & ~outq).sum(), ahead.sum()),
        "share_win_b_dnf": _safe((ahead & dnf_b).sum(), ahead.sum()),
        "p_a_dnf": float(dnf_a.mean()), "p_b_dnf": float(dnf_b.mean()),
        "e_finish_a": float(fin_a.mean()), "e_finish_b": float(fin_b.mean()),
        "p_win_a": float((fin_a == 1).mean()),
        "p_win_b": float((fin_b == 1).mean()),
        "e_swing": float(swing.mean()),
        "p_swing_pos": float((swing > 0).mean()),
        "swing_q10": float(np.quantile(swing, 0.10)),
        "swing_q90": float(np.quantile(swing, 0.90)),
        "n_sims": n,
    }
    return out


def team_dnf_rates(seasons: tuple[int, ...] | None = None,
                   shrink: float = 20.0) -> tuple[dict[str, float], pd.DataFrame]:
    """Per-team retirement probability per race from the results archive,
    shrunk toward the field mean (a team with 3 DNFs in 20 starts is not a
    15% DNF team with certainty). Returns ({team: rate}, detail_df with
    mechanical/incident split)."""
    p = HIST / "race_results_all.parquet"
    if not p.exists():
        return {}, pd.DataFrame()
    r = pd.read_parquet(p)
    if seasons:
        r = r[r["season"].isin(seasons)]
    if r.empty:
        return {}, pd.DataFrame()
    s = r["Status"].astype(str)
    finished = s.str.startswith("Finished") | s.str.match(r"^\+\d") \
        | s.str.contains("Lap", na=False)
    mech = ~finished & s.str.contains("|".join(_DNF_MECH_KEYWORDS),
                                      case=False, na=False)
    incident = ~finished & ~mech
    d = pd.DataFrame({"team": r["TeamName"], "dnf": ~finished,
                      "mech": mech, "incident": incident})
    agg = d.groupby("team").agg(starts=("dnf", "size"), dnfs=("dnf", "sum"),
                                mech=("mech", "sum"),
                                incidents=("incident", "sum")).reset_index()
    field_rate = agg["dnfs"].sum() / max(agg["starts"].sum(), 1)
    agg["rate"] = (agg["dnfs"] + shrink * field_rate) / (agg["starts"] + shrink)
    agg["mech_rate"] = agg["mech"] / agg["starts"]
    return dict(zip(agg["team"], agg["rate"])), agg


# ─────────────────────────────────────────────────────────────
# 2. Archive head-to-head
# ─────────────────────────────────────────────────────────────

def _quali_best(row) -> float:
    """Best quali time in seconds across Q1-Q3 (NaN if none). The archive
    stores these as float seconds; older frames may carry timedeltas."""
    vals = []
    for q in ("Q1", "Q2", "Q3"):
        v = row.get(q)
        if pd.isna(v):
            continue
        if isinstance(v, (int, float, np.floating)):
            vals.append(float(v))
        else:
            v = pd.to_timedelta(v, errors="coerce")
            if pd.notna(v):
                vals.append(v.total_seconds())
    return min(vals) if vals else float("nan")


def h2h_record(a: str, b: str, circuit_key: str | None = None,
               seasons: tuple[int, ...] | None = None) -> dict:
    """Meetings where both drivers appear: who finished / qualified ahead.
    DNFs excluded from the race count (a retirement is reliability, not pace);
    they're reported separately. Filter to one circuit with `circuit_key`."""
    out = {"race_n": 0, "race_a": 0, "quali_n": 0, "quali_a": 0,
           "a_dnfs": 0, "b_dnfs": 0, "rows": []}
    rp, qp = HIST / "race_results_all.parquet", HIST / "quali_results_all.parquet"
    if not rp.exists():
        return out
    r = pd.read_parquet(rp)
    if seasons:
        r = r[r["season"].isin(seasons)]
    if circuit_key:
        r = r[r["circuit_key"] == circuit_key]
    s = r["Status"].astype(str)
    finished = s.str.startswith("Finished") | s.str.match(r"^\+\d") \
        | s.str.contains("Lap", na=False)
    r = r.assign(_fin=finished)

    for (season, rnd), g in r.groupby(["season", "round_number"]):
        ra = g[g["Abbreviation"] == a]
        rb = g[g["Abbreviation"] == b]
        if ra.empty or rb.empty:
            continue
        ra, rb = ra.iloc[0], rb.iloc[0]
        row = {"season": int(season), "event": str(ra["event_name"]),
               "a_pos": ra["Position"], "b_pos": rb["Position"],
               "a_fin": bool(ra["_fin"]), "b_fin": bool(rb["_fin"])}
        out["rows"].append(row)
        if not ra["_fin"]:
            out["a_dnfs"] += 1
        if not rb["_fin"]:
            out["b_dnfs"] += 1
        if ra["_fin"] and rb["_fin"] \
                and pd.notna(ra["Position"]) and pd.notna(rb["Position"]):
            out["race_n"] += 1
            if ra["Position"] < rb["Position"]:
                out["race_a"] += 1

    if qp.exists():
        q = pd.read_parquet(qp)
        if seasons:
            q = q[q["season"].isin(seasons)]
        if circuit_key:
            q = q[q["circuit_key"] == circuit_key]
        for (season, rnd), g in q.groupby(["season", "round_number"]):
            qa = g[g["Abbreviation"] == a]
            qb = g[g["Abbreviation"] == b]
            if qa.empty or qb.empty:
                continue
            ta, tb = _quali_best(qa.iloc[0]), _quali_best(qb.iloc[0])
            if np.isfinite(ta) and np.isfinite(tb):
                out["quali_n"] += 1
                if ta < tb:
                    out["quali_a"] += 1
    return out


def circuit_results(a: str, b: str, circuit_key: str) -> pd.DataFrame:
    """Season-by-season grid → finish for both drivers at one circuit."""
    rp = HIST / "race_results_all.parquet"
    if not rp.exists() or not circuit_key:
        return pd.DataFrame()
    r = pd.read_parquet(rp)
    r = r[(r["circuit_key"] == circuit_key)
          & (r["Abbreviation"].isin([a, b]))]
    if r.empty:
        return pd.DataFrame()
    rows = []
    for season, g in r.groupby("season"):
        row = {"season": int(season)}
        for drv, tag in ((a, "a"), (b, "b")):
            gd = g[g["Abbreviation"] == drv]
            if gd.empty:
                row[f"{tag}_grid"] = row[f"{tag}_fin"] = np.nan
                row[f"{tag}_status"] = ""
            else:
                gd = gd.iloc[0]
                row[f"{tag}_grid"] = gd["GridPosition"]
                row[f"{tag}_fin"] = gd["Position"]
                st = str(gd["Status"])
                row[f"{tag}_status"] = "" if (st.startswith("Finished")
                                              or st.startswith("+")) else st
        rows.append(row)
    return pd.DataFrame(rows).sort_values("season", ascending=False)


# ─────────────────────────────────────────────────────────────
# 3. Situational profiles
# ─────────────────────────────────────────────────────────────

def circuit_key_fr(circuit_key: str | None) -> str | None:
    """Bridge the archive circuit key (slugified event name) to the French
    slug used by race_stats.csv / lap1_league.csv / circuit_characteristics."""
    if not circuit_key:
        return None
    from f1lib.config import HIST_CIRCUIT_KEY_MAP
    for fr, keys in HIST_CIRCUIT_KEY_MAP.items():
        if circuit_key in keys:
            return fr
    return None

def lap1_profile(a: str, b: str, circuit_key: str | None = None) -> dict:
    """Lap-1 position-change habits from the measured lap-1 league."""
    out = {}
    if not LAP1_CSV.exists():
        return out
    d = pd.read_csv(LAP1_CSV)
    for drv, tag in ((a, "a"), (b, "b")):
        g = d[d["driver"] == drv]
        gc = g[g["circuit_key"] == circuit_key] if circuit_key else g.iloc[0:0]
        out[tag] = {
            "n": len(g), "mean_gain": float(g["gain"].mean()) if len(g) else np.nan,
            "p_gain": float((g["gain"] > 0).mean()) if len(g) else np.nan,
            "p_loss": float((g["gain"] < 0).mean()) if len(g) else np.nan,
            "circuit_n": len(gc),
            "circuit_mean": float(gc["gain"].mean()) if len(gc) else np.nan,
        }
    return out


def sc_profile(circuit_key_fr: str | None) -> dict:
    """Safety-car / VSC likelihood and pit loss at this circuit, measured from
    race_stats.csv (which uses the French circuit slugs — pass that key)."""
    out = {}
    if not RACE_STATS_CSV.exists() or not circuit_key_fr:
        return out
    d = pd.read_csv(RACE_STATS_CSV)
    g = d[d["circuit_key"] == circuit_key_fr]
    if g.empty:
        return out
    return {
        "n_races": len(g),
        "p_sc": float((g["sc_count"] > 0).mean()),
        "p_vsc": float((g["vsc_count"] > 0).mean()),
        "mean_sc_laps": float(g["sc_laps"].mean()),
        "pit_loss_s": float(g["pit_loss_s"].dropna().median())
        if g["pit_loss_s"].notna().any() else np.nan,
        "overtakes_med": float(g["overtakes"].dropna().median())
        if g["overtakes"].notna().any() else np.nan,
        "one_stop_pct": float(g["one_stop_pct"].dropna().median())
        if "one_stop_pct" in g and g["one_stop_pct"].notna().any() else np.nan,
    }


def wet_profile(a: str, b: str) -> dict:
    """How each driver's race-day conversion (grid → finish positions gained)
    changes in the rain, using the measured per-race rain flag from
    race_stats.csv joined onto the results archive. Retirements excluded —
    this reads racecraft in the wet, not survival luck."""
    out = {}
    rp = HIST / "race_results_all.parquet"
    if not RACE_STATS_CSV.exists() or not rp.exists():
        return out
    rs = pd.read_csv(RACE_STATS_CSV)[["season", "meeting", "rain"]]
    rs["rain"] = rs["rain"].astype(str).str.lower() == "true"
    r = pd.read_parquet(rp)
    r = r[r["Abbreviation"].isin([a, b])]
    m = r.merge(rs, left_on=["season", "event_name"],
                right_on=["season", "meeting"], how="inner")
    if m.empty:
        return out
    s = m["Status"].astype(str)
    fin = s.str.startswith("Finished") | s.str.match(r"^\+\d") \
        | s.str.contains("Lap", na=False)
    m = m[fin]
    m = m[pd.to_numeric(m["GridPosition"], errors="coerce").notna()
          & pd.to_numeric(m["Position"], errors="coerce").notna()]
    m["gained"] = m["GridPosition"].astype(float) - m["Position"].astype(float)
    for drv, tag in ((a, "a"), (b, "b")):
        g = m[m["Abbreviation"] == drv]
        wet, dry = g[g["rain"]], g[~g["rain"]]
        out[tag] = {
            "wet_n": len(wet), "dry_n": len(dry),
            "wet_gain": float(wet["gained"].mean()) if len(wet) else np.nan,
            "dry_gain": float(dry["gained"].mean()) if len(dry) else np.nan,
        }
        d = out[tag]
        d["rain_delta"] = (d["wet_gain"] - d["dry_gain"]
                           if np.isfinite(d["wet_gain"])
                           and np.isfinite(d["dry_gain"]) else np.nan)
    return out


# ─────────────────────────────────────────────────────────────
# 4. Corner deltas & attack zones
# ─────────────────────────────────────────────────────────────

def corner_time_deltas(tel_a: pd.DataFrame, tel_b: pd.DataFrame,
                       fracs: pd.DataFrame) -> pd.DataFrame:
    """Per-corner traversal-time delta between two laps' telemetry.

    Both frames need t_rel / Distance (as produced by the telemetry tab's
    _lap_telemetry). Times are interpolated at zone boundaries placed at the
    midpoints between corner apexes, using each lap's own measured length —
    so the comparison is positionally aligned even if the integrated lap
    lengths differ slightly. delta_s = tA − tB (negative = A faster). vmin
    columns carry each driver's apex speed for the style read."""
    if (tel_a is None or tel_b is None or tel_a.empty or tel_b.empty
            or fracs.empty):
        return pd.DataFrame()

    def _seg(tel):
        t = tel.sort_values("Distance")
        dist = pd.to_numeric(t["Distance"], errors="coerce").to_numpy(float)
        trel = pd.to_numeric(t["t_rel"], errors="coerce").to_numpy(float)
        spd = pd.to_numeric(t["Speed"], errors="coerce").to_numpy(float)
        total = dist[-1]
        centers = fracs["frac"].to_numpy(float) * total
        bounds = np.empty(len(centers) + 1)
        bounds[0], bounds[-1] = 0.0, total
        bounds[1:-1] = (centers[:-1] + centers[1:]) / 2.0
        tb = np.interp(bounds, dist, trel)
        times = np.diff(tb)
        vmins = np.array([
            np.nanmin(spd[(dist >= bounds[i]) & (dist <= bounds[i + 1])])
            if ((dist >= bounds[i]) & (dist <= bounds[i + 1])).sum() >= 2
            else np.nan
            for i in range(len(centers))])
        return times, vmins

    try:
        t_a, v_a = _seg(tel_a)
        t_b, v_b = _seg(tel_b)
    except Exception as exc:
        logger.warning("corner delta failed: %s", exc)
        return pd.DataFrame()
    out = fracs[["label", "frac"]].copy()
    out["t_a"], out["t_b"] = t_a, t_b
    out["delta_s"] = t_a - t_b
    out["vmin_a"], out["vmin_b"] = v_a, v_b
    return out


def drs_zone_fracs(line: pd.DataFrame) -> list[tuple[float, float]]:
    """(start_frac, end_frac) of each DRS/active-aero zone on the cached
    racing line (line needs the 'frac' + 'drs' columns from load_track_line)."""
    if line.empty or "drs" not in line.columns or "frac" not in line.columns:
        return []
    drs = line["drs"].to_numpy(int)
    frac = line["frac"].to_numpy(float)
    edges = np.diff(np.concatenate([[0], drs, [0]]))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0] - 1
    zones = []
    for s, e in zip(starts, ends):
        s, e = min(s, len(frac) - 1), min(e, len(frac) - 1)
        if frac[e] > frac[s]:
            zones.append((float(frac[s]), float(frac[e])))
    return zones


def tag_attack_corners(deltas: pd.DataFrame,
                       zones: list[tuple[float, float]],
                       lead_frac: float = 0.08) -> pd.DataFrame:
    """Mark corners that feed a DRS zone (within `lead_frac` of a zone start,
    or the last corner before it) — where a corner-exit advantage converts
    into a pass, not just lap time."""
    if deltas.empty:
        return deltas
    d = deltas.copy()
    feeds = []
    for f in d["frac"]:
        hit = any((zs - lead_frac) <= f <= (zs + 0.01) or
                  # zone that wraps the start line
                  (zs - lead_frac < 0 and f >= 1.0 + (zs - lead_frac))
                  for zs, _ in zones)
        feeds.append(hit)
    d["feeds_drs"] = feeds
    return d


# ─────────────────────────────────────────────────────────────
# Mistake-cache readers (written by compute_mistakes.py)
# ─────────────────────────────────────────────────────────────

def load_mistakes(circuit_key: str | None = None,
                  drivers: list[str] | None = None) -> pd.DataFrame:
    if not MISTAKES_ALL.exists():
        return pd.DataFrame()
    d = pd.read_parquet(MISTAKES_ALL)
    if circuit_key:
        d = d[d["circuit_key"] == circuit_key]
    if drivers:
        d = d[d["Driver_Short"].isin(drivers)]
    return d


def load_pressure(drivers: list[str] | None = None) -> pd.DataFrame:
    if not MISTAKES_PRESSURE.exists():
        return pd.DataFrame()
    d = pd.read_parquet(MISTAKES_PRESSURE)
    if drivers:
        d = d[d["Driver_Short"].isin(drivers)]
    return d


def pressure_summary(a: str, b: str) -> pd.DataFrame:
    """Career (archive-wide) mistake rate per clean lap, split by whether a
    car was within striking distance behind. Rates per 100 laps."""
    d = load_pressure([a, b])
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("Driver_Short")[["laps_p", "laps_f",
                                   "events_p", "events_f"]].sum()
    g["rate_free"] = 100 * g["events_f"] / g["laps_f"].clip(lower=1)
    g["rate_pressured"] = 100 * g["events_p"] / g["laps_p"].clip(lower=1)
    g["pressure_ratio"] = g["rate_pressured"] / g["rate_free"].replace(0, np.nan)
    return g.reset_index()


def mistake_map(circuit_key: str, driver: str) -> pd.DataFrame:
    """Per-corner mistake profile for one driver at one circuit, pooled across
    every archived session there. Adds a per-lap rate and the total time cost."""
    d = load_mistakes(circuit_key, [driver])
    if d.empty:
        return pd.DataFrame()
    g = (d.groupby("corner", as_index=False)
         .agg(n_laps=("n_laps", "sum"), n_slow=("n_slow", "sum"),
              n_lift=("n_lift", "sum"), n_brake_reapp=("n_brake_reapp", "sum"),
              n_mistakes=("n_mistakes", "sum"),
              time_lost_s=("time_lost_s", "sum"),
              tl_deletions=("tl_deletions", "sum")))
    g["rate_pct"] = 100 * g["n_mistakes"] / g["n_laps"].clip(lower=1)
    return g.sort_values("rate_pct", ascending=False)
