"""Per-(session, driver) row index over the loaded telemetry frame.

`state.telemetry` is a single multi-million-row frame (5.3 M rows on a sprint
weekend). Every card that needs one lap's samples used to locate them with a
boolean mask over the whole frame — plus `DriverNo.astype(str).str.strip()`
on every row, ~1.5 s per lap. The TELEMETRY tab did that per selected lap in
four separate callbacks, and rebuilt per-driver pools three times per render.

This module builds, once per DATA_GENERATION, the row positions of each
(session_name, DriverNo) group sorted by timestamp. A lap is then two
searchsorted calls and one small `iloc` take (a few ms). DriverNo keys are
stripped strings, matching every caller's `str(DriverNo).strip()`.

Timestamps are those of `state.telemetry`, i.e. already lap-sync corrected
by `lap_sync.read_telemetry` at load time.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

import f1lib.state as state

_LOCK = threading.Lock()
# (DATA_GENERATION, telemetry frame, index) — replaced as ONE tuple so a
# lock-free reader can never see a frame paired with another frame's index
_SNAP: tuple | None = None


def _build(tel: pd.DataFrame) -> dict[tuple[str, str], tuple[np.ndarray, np.ndarray]]:
    # groupby().indices factorizes the key columns once — no per-row str ops
    groups = tel.groupby(["session_name", "DriverNo"], sort=False).indices
    ts_all = tel["timestamp"].to_numpy(float)
    merged: dict[tuple[str, str], list[np.ndarray]] = {}
    for (sess, dno), pos in groups.items():
        merged.setdefault((sess, str(dno).strip()), []).append(pos)
    index = {}
    for key, parts in merged.items():
        pos = np.concatenate(parts) if len(parts) > 1 else parts[0]
        ts = ts_all[pos]
        order = np.argsort(ts, kind="stable")
        index[key] = (pos[order], ts[order])
    return index


def snapshot() -> tuple[pd.DataFrame | None, dict]:
    """(telemetry frame, its index) as one consistent pair — positions are only
    valid against the frame they were built from, so a reload mid-call must
    never mix the new frame with the old index."""
    tel = state.telemetry
    if tel is None or tel.empty:
        return None, {}
    global _SNAP
    gen = state.DATA_GENERATION
    snap = _SNAP
    if snap is not None and snap[0] == gen and snap[1] is tel:
        return snap[1], snap[2]
    with _LOCK:
        snap = _SNAP
        if snap is None or snap[0] != gen or snap[1] is not tel:
            snap = _SNAP = (gen, tel, _build(tel))
        return snap[1], snap[2]


def driver_index() -> dict[tuple[str, str], tuple[np.ndarray, np.ndarray]]:
    """{(session_name, DriverNo): (row positions, timestamps)}, both sorted by
    timestamp. Rebuilt lazily when the loaded data changes; thread-safe (the
    tab prewarm thread and request threads may ask at the same time).
    Positions index into ``state.telemetry`` as of this call."""
    return snapshot()[1]


def driver_frame(session_name, driver_no) -> pd.DataFrame | None:
    """All telemetry of one driver in one session, sorted by timestamp."""
    tel, index = snapshot()
    hit = index.get((session_name, str(driver_no).strip()))
    if hit is None:
        return None
    return tel.iloc[hit[0]]


def window(session_name, driver_no, t0: float, t1: float) -> pd.DataFrame | None:
    """Samples of one driver in one session with t0 <= timestamp <= t1,
    sorted by timestamp (same bounds as the old boolean mask)."""
    tel, index = snapshot()
    hit = index.get((session_name, str(driver_no).strip()))
    if hit is None:
        return None
    pos, ts = hit
    i0 = np.searchsorted(ts, t0, side="left")
    i1 = np.searchsorted(ts, t1, side="right")
    return tel.iloc[pos[i0:i1]]


def prewarm() -> None:
    """Build the index for the current data in a daemon thread, so the first
    TELEMETRY / DUEL visit after a load doesn't pay the ~1 s build."""
    def _worker():
        try:
            driver_index()
        except Exception:
            pass
    threading.Thread(target=_worker, name="tel-index-prewarm", daemon=True).start()
