"""Per-(session, driver) telemetry row index (f1lib/telemetry_index.py).

The index replaced full-frame boolean masks (plus a per-row
`DriverNo.astype(str).str.strip()`) that made every TELEMETRY lap selection
take seconds. The properties pinned are the ones the old mask had:

1. a window holds exactly the rows with t0 <= timestamp <= t1 (inclusive),
   for that session and driver only, sorted by timestamp;
2. DriverNo is matched stripped — " 4" and "4" are the same driver;
3. NaN timestamps never fall in a window;
4. a reload (new frame / DATA_GENERATION) rebuilds the index.
"""
import numpy as np
import pandas as pd
import pytest

import f1lib.state as state
import f1lib.telemetry_index as ti


def _frame():
    return pd.DataFrame({
        "session_name": ["Q_X_2026"] * 6 + ["R_X_2026"] * 2,
        "DriverNo":     ["4", " 4", "4", "16", "4", "4", "4", "4"],
        "timestamp":    [3.0, 1.0, 2.0, 1.5, np.nan, 4.0, 1.0, 2.0],
        "Speed":        [30., 10., 20., 99., 0., 40., 50., 60.],
    })


@pytest.fixture
def loaded(monkeypatch):
    tel = _frame()
    monkeypatch.setattr(state, "telemetry", tel)
    monkeypatch.setattr(state, "DATA_GENERATION", 101)
    monkeypatch.setattr(ti, "_SNAP", None)
    return tel


def test_window_matches_mask(loaded):
    w = ti.window("Q_X_2026", "4", 1.0, 3.0)
    assert w["timestamp"].tolist() == [1.0, 2.0, 3.0]          # inclusive, sorted
    assert w["Speed"].tolist() == [10., 20., 30.]
    assert set(w["session_name"]) == {"Q_X_2026"}               # no Race rows


def test_driver_no_is_stripped(loaded):
    assert len(ti.window("Q_X_2026", " 4 ", 0.0, 10.0)) == 4    # NaN row excluded
    assert ti.window("Q_X_2026", "16", 0.0, 10.0)["Speed"].tolist() == [99.]
    assert ti.window("Q_X_2026", "99", 0.0, 10.0) is None


def test_driver_frame_sorted(loaded):
    f = ti.driver_frame("R_X_2026", 4)
    assert f["timestamp"].tolist() == [1.0, 2.0]


def test_reload_rebuilds(loaded, monkeypatch):
    assert len(ti.window("Q_X_2026", "16", 0.0, 10.0)) == 1
    new = _frame().iloc[:3]                                     # driver 16 gone
    monkeypatch.setattr(state, "telemetry", new)
    monkeypatch.setattr(state, "DATA_GENERATION", 102)
    assert ti.window("Q_X_2026", "16", 0.0, 10.0) is None
    tel, _ = ti.snapshot()
    assert tel is new
