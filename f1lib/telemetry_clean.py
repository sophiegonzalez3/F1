"""
Position-telemetry cleaning for the 3D replay payload builders.

The merged FastF1 telemetry (car + pos sources) contains three kinds of
position garbage that wreck an XY replay:

* placeholder samples — the livetiming pos feed publishes X = Y = 0 when it
  has no fix for a car (notably the whole grid period at some races: Monaco
  2026 only starts publishing real coordinates as each car crosses the
  timing line). The 'car'-source rows in between carry X/Y interpolated
  FROM those zeros, i.e. plausible-looking but entirely fictional sweeps
  across the map.
* frozen / stalled runs — the pos feed re-emits the SAME coordinate for a
  second or more while the car is really flying down a straight, then
  catches up with a burst of huge jumps. Interpolated, the car parks itself
  mid-straight (its heading collapses to due-east — a stationary frame has
  no direction) and then teleports. This is what made Leclerc "loop over
  himself" on lap 1 at Spa 2026 (feed stall at Les Combes).
* lone teleports — a single fix lands hundreds of metres off before the
  next one is correct again.

All three are caught the same way: the car-ECU Speed channel is trustworthy
even when the GPS position feed is not, so a good fix's displacement from
the last good fix must match the distance implied by integrating Speed over
the interval. `clean_pos_samples` keeps 'pos'-source rows, drops (0,0)
placeholders, then walks the samples keeping only those whose displacement
from the current anchor is consistent with the Speed integral — a frozen run
(displacement far below the integral) and a catch-up burst / teleport
(displacement far above it) are both skipped, and the walk re-locks onto the
first fix that lands where the integrated speed says the car should be.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# displacement-vs-speed-integral consistency band. A good fix's straight-line
# distance from the anchor sits near the integrated distance E; GPS jitter and
# corner-cutting (chord < arc) pull it a little either side, so the band is
# generous. Frozen runs fall below the floor, catch-up bursts / teleports blow
# through the ceiling.
_LO_FRAC = 0.45          # reject below 0.45·E − slack  (frozen / stalled)
_HI_FRAC = 1.80          # reject above 1.80·E + slack  (catch-up / teleport)
_SLACK_M = 9.0           # absolute slack (m): dominates at low speed / short dt


def _speed_consistent_mask(t: np.ndarray, xm: np.ndarray, ym: np.ndarray,
                           spd_kmh: np.ndarray) -> np.ndarray:
    """True = keep. Coordinates in metres, speed in km/h, aligned to `t`.

    Forward walk anchored on the last accepted fix. `E` is the distance the
    car should have covered since the anchor (trapezoid integral of Speed),
    so it stays meaningful across dropped runs of any length — the walk
    resyncs onto the first fix whose displacement matches the integral."""
    n = len(t)
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    # cumulative speed-distance (m); reliable even where XY is not.
    v = np.clip(spd_kmh, 0, None) / 3.6                       # m/s
    seg = np.diff(t) * 0.5 * (v[1:] + v[:-1])                 # trapezoid
    S = np.concatenate([[0.0], np.cumsum(seg)])
    keep[0] = True
    anchor = 0
    for i in range(1, n):
        E = S[i] - S[anchor]
        disp = np.hypot(xm[i] - xm[anchor], ym[i] - ym[anchor])
        lo = _LO_FRAC * E - _SLACK_M
        hi = _HI_FRAC * E + _SLACK_M
        if lo <= disp <= hi:
            keep[i] = True
            anchor = i
        # else: frozen, stalled or teleported — skip, keep measuring from
        # the same anchor until the feed lands where Speed says it should.
    return keep


def monotonic_didx(xi, yi, scene, tree,
                   relock_m: float = 25.0, relock_frames: int = 6):
    """Nearest scene section per frame, constrained to move forward along the
    lap — a global nearest-XY lookup breaks on crossover circuits (Suzuka's
    figure-8: bridge and underpass share XY, cars would snap to the wrong
    level's elevation).

    Recovery: if the windowed match stays > `relock_m` off for
    `relock_frames` consecutive frames the tracker is lost (e.g. a car
    running the length of the pit lane, which parallels distant sections) —
    re-lock to the global nearest. At a genuine crossover the car is close
    to BOTH levels' sections, so the relock never triggers there."""
    n_sc = len(scene["cx"])
    cxa = np.asarray(scene["cx"])
    cya = np.asarray(scene["cy"])
    out = np.empty(len(xi), dtype=np.int64)
    _, prev = tree.query([xi[0], yi[0]])
    out[0] = prev = int(prev)
    lost = 0
    r2 = relock_m * relock_m
    for i in range(1, len(xi)):
        cand = np.arange(prev - 4, prev + 41) % n_sc      # forward-biased
        d2 = (cxa[cand] - xi[i]) ** 2 + (cya[cand] - yi[i]) ** 2
        j = int(np.argmin(d2))
        prev = int(cand[j])
        if d2[j] > r2:
            lost += 1
            if lost >= relock_frames:
                _, prev = tree.query([xi[i], yi[i]])
                prev = int(prev)
                lost = 0
        else:
            lost = 0
        out[i] = prev
    return out


def clean_pos_samples(seg: pd.DataFrame) -> pd.DataFrame:
    """Ground-truth position fixes from a merged-telemetry slice.

    Expects a per-driver slice already sorted / deduplicated on 'timestamp'
    with X/Y in decimetres (FastF1 convention). Returns the subset of rows
    safe to interpolate positions from; other channels (Speed, Throttle…)
    should still be read from the full slice.
    """
    out = seg
    # 'car'-source rows have no native position — their X/Y are FastF1
    # interpolations (garbage whenever a neighbouring pos fix is garbage).
    if "Source" in out.columns:
        pos_only = out[out["Source"].astype(str).str.strip() == "pos"]
        if len(pos_only) >= 20:
            out = pos_only
    # (0, 0) is the feed's "no fix" placeholder, never a real coordinate.
    out = out[out["X"].abs().to_numpy() + out["Y"].abs().to_numpy() > 1.0]
    if len(out) < 5:
        return out
    spd = (pd.to_numeric(out["Speed"], errors="coerce").ffill().bfill()
           .fillna(0.0).to_numpy(float)) if "Speed" in out.columns \
        else np.zeros(len(out))
    keep = _speed_consistent_mask(out["timestamp"].to_numpy(float),
                                  out["X"].to_numpy(float) * 0.1,
                                  out["Y"].to_numpy(float) * 0.1,
                                  spd)
    return out[keep]
