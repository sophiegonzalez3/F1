# Title

[BUG] Telemetry (pos_data / car_data) offset by several seconds from lap timing in some sessions (up to 19.5 s, 2026 Bahrain GP race)

---

# Describe the issue:

In some sessions, every lap's `LapStartTime` points to a spot far from the start/finish line in `pos_data` / `car_data`. The offset is a near-constant per driver for the whole session. Taken literally, the laps start several hundred metres before or after the line. Speed and position agree with each other (speed minima sit on the hairpins). Only the time alignment between lap timing and telemetry is off, so `Lap.get_telemetry()` returns the wrong stretch of track for these sessions.

**Clearest case: 2026 Bahrain Grand Prix, Race.**
- 21 of 22 drivers are offset by +19.5 to +19.8 s. Their laps "start" ~370 m before the line.
- LEC is not affected. His laps start within 7 m of the line, like everyone else in qualifying of the same weekend.
- The offset matches FastF1's own warning for the race winner: `Driver 3 completed the race distance 00:19.478000 before the recorded end of the session.`

**Which clock looks right.** The lap timing seems to be the consistent side:
- The order of `LapStartTime` across drivers matches the official running order (`Position`) exactly, lap by lap.
- The order of the actual line crossings in raw `pos_data` does not, because LEC's telemetry sits 19.5 s apart from everyone else's.

**What I would expect.** I know from #43 that telemetry is not actively synchronised and that a jitter of roughly ±10 m is expected. These offsets are much larger (up to ~370 m / 19.5 s) and systematic.

**How I measured it.**
- The start/finish point is the median car position at `LapStartTime` in the same weekend's sessions (all agree within a few metres).
- For each lap (lap ≥ 2, no pit-out lap) I take the pos sample nearest `LapStartTime`.
- The offset is the time of closest approach to the line, minus `LapStartTime`.

I ran this over all 226 sessions I have cached (2023–2026, all session types). The affected sessions:

| Session | Drivers affected | Offset | Median lap-start distance from line |
|---|---|---|---|
| 2026 Bahrain GP, Race | 21 / 22 (not LEC) | +19.6 s | 367 m |
| 2023 Dutch GP, Race | 19 | +2.2 s | 171 m |
| 2026 Dutch GP, Race | 19 (not SAI) | +1.6 s | 138 m |
| 2026 Austrian GP, Race | 21 | −1.9 s | 156 m |
| 2026 Austrian GP, Qualifying | 22 | −1.2 s drifting to −1.5 s, then stepping to ~0 within the session | 99 m |
| 2024 Las Vegas GP, Race | 20 | +0.5 s | 43 m |
| 2026 Dutch GP, Practice 1 | 1 (#63) | +0.5 s | 53 m |

All other sessions: median lap-start distance 2–7 m. A few single drivers are at most 0.2–0.3 s off (2023 and 2024 Australian GP races). Apart from the two cases in the table, practice, sprint and qualifying sessions are unaffected.

As a workaround, I currently estimate a per-driver offset per lap and shift each driver's telemetry onto the lap clock. After that, lap starts fall within ~6 m of the line in every session above.

---

# Reproduce the code example:

```python
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
```

Change `YEAR, EVENT` to `2026, "Dutch Grand Prix"` or `2026, "Austrian Grand Prix"` for the other cases.

---

# State your Fastf1 version number:

3.8.3 (Python 3.12, pandas 2.x, Windows 11)

---

# Error message:

No exception. Relevant output (warnings shortened):

```shell
core        WARNING 	Driver 3 completed the race distance 00:19.478000 before the recorded end of the session.
core        WARNING 	Driver 12 completed the race distance 00:17.248000 before the recorded end of the session.
[... same warning for 10 more drivers ...]
Qualifying: median lap-start distance from S/F = 5.9 m

Race, per driver (median over laps):
     laps  lap_start_dist_m  offset_s
LEC    50              7.18      0.01
NOR    51            374.54     19.52
GAS    50            370.07     19.52
SAI    51            374.05     19.52
ALB    38            365.18     19.54
BOR    49            354.41     19.55
HAD    51            369.62     19.55
COL    51            369.35     19.56
PIA    50            376.98     19.56
BEA    51            362.30     19.57
LIN    51            366.94     19.57
VER    51            385.79     19.57
HUL    50            367.10     19.59
PER    47            366.94     19.59
OCO    51            367.61     19.60
ANT    51            383.15     19.62
STR    50            364.04     19.62
ALO    51            373.60     19.65
RUS    46            377.32     19.66
LAW    51            371.19     19.68
HAM    52            382.72     19.68
BOT     7            151.97     19.77
```
