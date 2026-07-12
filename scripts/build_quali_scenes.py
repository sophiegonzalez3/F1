"""
Batch-build the Quali 3D Replay scenes + payloads for many circuits.

For each meeting: download the Qualifying session if it isn't cached yet
(FastF1 — a few minutes per session), build the georeferenced track scene
(Overpass + DTM providers, cached), then bake the best-lap replay payload.
Safe to re-run: everything is cached, failures on one circuit don't stop
the rest.

Usage:
    python scripts/build_quali_scenes.py            # build the standard list below
    python scripts/build_quali_scenes.py --force    # re-bake scenes + payloads
    python scripts/build_quali_scenes.py 2025 "Qatar Grand Prix"   # just one
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("fastf1").setLevel(logging.WARNING)

# (season, meeting) — prefer 2026 where its Qualifying is already cached,
# else the completed 2025 season. Existing scenes/payloads are skipped by
# the cache layer automatically.
MEETINGS: list[tuple[int, str]] = [
    (2026, "Australian Grand Prix"),
    (2026, "Monaco Grand Prix"),
    (2026, "Barcelona Grand Prix"),
    (2026, "Austrian Grand Prix"),
    (2025, "Dutch Grand Prix"),
    (2025, "Belgian Grand Prix"),
    (2026, "Canadian Grand Prix"),
    (2026, "Chinese Grand Prix"),
    (2026, "Japanese Grand Prix"),
    (2026, "Miami Grand Prix"),
    (2026, "British Grand Prix"),
    (2025, "Bahrain Grand Prix"),
    (2025, "Saudi Arabian Grand Prix"),
    (2025, "Emilia Romagna Grand Prix"),
    (2025, "Hungarian Grand Prix"),
    (2025, "Italian Grand Prix"),
    (2025, "Azerbaijan Grand Prix"),
    (2025, "Singapore Grand Prix"),
    (2025, "United States Grand Prix"),
    (2025, "Mexico City Grand Prix"),
    (2025, "São Paulo Grand Prix"),
    (2025, "Las Vegas Grand Prix"),
    (2025, "Qatar Grand Prix"),
    (2025, "Abu Dhabi Grand Prix"),
]


def build_one(season: int, meeting: str, force: bool = False) -> str:
    from tabs.quali_replay import (build_quali3d_payload,
                                   cached_quali3d_payload,
                                   _payload_cache_path, _PAYLOAD_MEM)
    from f1lib.track_scene import build_track_scene

    if force:
        build_track_scene(season, meeting, force=True)
        _payload_cache_path(season, meeting).unlink(missing_ok=True)
        _PAYLOAD_MEM.pop((int(season), meeting), None)
    elif cached_quali3d_payload(season, meeting) is not None:
        return "cached"
    p = build_quali3d_payload(season, meeting)
    if p is None:
        return "FAILED (no payload)"
    sc = p["scene"]
    sur = sc.get("surround") or {}
    geo = sc.get("geo")
    return (f"ok — {len(p['drivers'])} laps, pole {p['drivers'][0]['code']} "
            f"{p['drivers'][0]['lt']}, track={sc['sources']['track']}, "
            f"dtm={sc['sources']['dtm']}, "
            f"georef={'%.1f m' % geo['median_m'] if geo else 'NO'}, "
            f"bldgs={len(sur.get('buildings', []))}, "
            f"terrain={'y' if sur.get('terrain') else 'n'}")


def main() -> None:
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    todo = [(int(args[0]), args[1])] if len(args) >= 2 else MEETINGS
    for season, meeting in todo:
        t0 = time.time()
        try:
            msg = build_one(season, meeting, force=force)
        except Exception as exc:            # keep going — one bad circuit
            msg = f"FAILED: {exc}"          # shouldn't sink the batch
        print(f"[{season} {meeting}] {msg}  ({time.time() - t0:.0f}s)",
              flush=True)
        time.sleep(3)                       # be polite to Overpass


if __name__ == "__main__":
    main()
