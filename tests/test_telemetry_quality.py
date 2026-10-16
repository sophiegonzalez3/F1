"""Telemetry feed quality (f1lib/telemetry_quality.py): the frozen car packet.

Found 2026-10-13 on real laps (Stroll, Singapore 2026 Q: 133 km/h / 12502 rpm
held for 3.5 s while changing up from 2nd to 4th). The moving-share test
misses it because the rest of the lap moves, so it is measured separately as
`car_frozen_s` and turns car_bad on at MAX_FROZEN_S. The properties pinned:

1. A whole frozen PACKET (Speed + RPM + Throttle) over the threshold is bad.
2. A Speed-only plateau is NOT bad: at the top of a straight - or under 2026
   energy clipping - the speed is genuinely constant while RPM still moves.
3. A parked or crawling car (< MIN_SPEED_KMH) repeats legitimately.
"""
import numpy as np
import pandas as pd

import f1lib.telemetry_quality as tq


def _session(speed, rpm, throttle, dt=0.27):
    n = len(speed)
    t = np.arange(n) * dt
    tel = pd.DataFrame({"DriverNo": "18", "timestamp": t, "Source": "car",
                        "Speed": speed, "RPM": rpm, "Throttle": throttle,
                        "X": np.arange(n) * 10.0, "Y": 0.0})
    pos = tel.assign(Source="pos")
    laps = pd.DataFrame({"DriverNo": ["18"], "LapNo": [1],
                         "LapStartTime": [0.0], "Time": [t[-1]]})
    return laps, pd.concat([tel, pos], ignore_index=True)


def _healthy(n=300):
    rng = np.random.default_rng(0)
    speed = 150 + 80 * np.sin(np.linspace(0, 6, n)) + rng.integers(0, 3, n)
    rpm = 10000 + rng.integers(0, 900, n)
    thr = rng.integers(0, 101, n)
    return speed.astype(float), rpm.astype(float), thr.astype(float)


def test_healthy_lap_is_not_frozen():
    q = tq.lap_quality(*_session(*_healthy()))
    assert q["car_frozen_s"].iloc[0] < tq.MAX_FROZEN_S
    assert not q["car_bad"].iloc[0]


def test_frozen_packet_over_threshold_is_car_bad():
    s, r, th = _healthy()
    s[100:115], r[100:115], th[100:115] = 133.0, 12502.0, 100.0   # 14 x 0.27 s = 3.8 s
    q = tq.lap_quality(*_session(s, r, th))
    assert q["car_frozen_s"].iloc[0] >= 3.5
    assert q["car_bad"].iloc[0]


def test_speed_only_plateau_is_not_a_freeze():
    s, r, th = _healthy()
    s[100:120] = 312.0                     # top speed held 5 s ...
    r[100:120] = 11800 + np.arange(20)     # ... while the engine still moves
    q = tq.lap_quality(*_session(s, r, th))
    assert q["car_frozen_s"].iloc[0] < tq.MAX_FROZEN_S
    assert not q["car_bad"].iloc[0]


def test_parked_car_repeats_legitimately():
    s, r, th = _healthy()
    s[100:130], r[100:130], th[100:130] = 0.0, 4000.0, 0.0   # stopped under red
    q = tq.lap_quality(*_session(s, r, th))
    assert not q["car_bad"].iloc[0]
