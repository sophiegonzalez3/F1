"""Telemetry is offset by several seconds from lap boundaries in some sessions.

For each driver, compares the car's position at LapStartTime with the
start/finish line, and measures the time offset between LapStartTime and the
moment the position trace actually passes the line.

The start/finish point is taken from the same weekend's qualifying, where lap
starts are consistent within a few metres.
"""
import fastf1
import numpy as np
import pandas as pd

YEAR, EVENT = 2026, "Bahrain Grand Prix"


def lap_start_points(session):
    """Per lap (lap >= 2, no pit-out): X/Y of the pos sample nearest LapStartTime."""
    rows = []
    for drv in session.drivers:
        pos = session.pos_data[drv]
        pos = pos[(pos["X"] != 0) | (pos["Y"] != 0)]
        t = pos["SessionTime"].dt.total_seconds().to_numpy()
        laps = session.laps.pick_drivers(drv)
        laps = laps[(laps["LapNumber"] >= 2) & laps["PitOutTime"].isna()
                    & laps["LapStartTime"].notna()]
        for lst in laps["LapStartTime"].dt.total_seconds():
            i = int(np.argmin(np.abs(t - lst)))
            if abs(t[i] - lst) < 1.0:
                rows.append((drv, lst, pos["X"].iloc[i], pos["Y"].iloc[i]))
    return pd.DataFrame(rows, columns=["drv", "lst", "X", "Y"])


def crossing_offset(session, drv, lst, sf, window=25.0):
    """Seconds between LapStartTime and the closest approach to the line."""
    pos = session.pos_data[drv]
    pos = pos[(pos["X"] != 0) | (pos["Y"] != 0)]
    t = pos["SessionTime"].dt.total_seconds().to_numpy()
    m = (t > lst - window) & (t < lst + window)
    if m.sum() < 3:
        return np.nan
    d = np.hypot(pos["X"].to_numpy()[m] - sf[0], pos["Y"].to_numpy()[m] - sf[1])
    return t[m][np.argmin(d)] - lst


quali = fastf1.get_session(YEAR, EVENT, "Q")
quali.load(laps=True, telemetry=True, weather=False, messages=False)
q = lap_start_points(quali)
sf = (q["X"].median(), q["Y"].median())
q_dist = np.hypot(q["X"] - sf[0], q["Y"] - sf[1]) / 10          # X/Y are in 1/10 m
print(f"Qualifying: median lap-start distance from S/F = {q_dist.median():.1f} m")

race = fastf1.get_session(YEAR, EVENT, "R")
race.load(laps=True, telemetry=True, weather=False, messages=False)
r = lap_start_points(race)
r["dist_m"] = np.hypot(r["X"] - sf[0], r["Y"] - sf[1]) / 10
r["offset_s"] = [crossing_offset(race, d, l, sf) for d, l in zip(r["drv"], r["lst"])]

out = r.groupby("drv").agg(laps=("lst", "size"), lap_start_dist_m=("dist_m", "median"),
                           offset_s=("offset_s", "median"))
out.index = [race.get_driver(d)["Abbreviation"] for d in out.index]
print("\nRace, per driver (median over laps):")
print(out.round(2).sort_values("offset_s").to_string())
