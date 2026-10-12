# Snapshot: lap-boundary / telemetry-clock sync (2026-10-09)

**What changed:** `f1lib/lap_sync.py` now shifts each mis-synced driver's telemetry
`timestamp` onto FastF1's lap clock whenever telemetry is read:

- `data_loader.load_session` applies it, which covers the app tabs (TELEMETRY,
  replay, race 3D, quali 3D).
- The derived scripts read through `lap_sync.read_telemetry`: compute_mistakes,
  compute_section_profile, compute_car_profile and compute_circuit_characteristics.

The correction comes from `scripts/audit_lap_sync.py`, which writes
`data/lap_sync_offsets.csv` and `data/lap_sync_knots.csv`. The cached
parquets keep FastF1's raw clock.

**Corrected sessions** (median lap-start distance from the start/finish line → after the shift):

| session | drivers | offset | before | after |
|---|---|---|---|---|
| 2026 Bahrain GP (Sepang) Race | 21/22 (not LEC) | +19.6 s | 367 m | 5 m |
| 2023 Dutch GP Race | 19 | +2.2 s | 171 m | 6 m |
| 2026 Dutch GP Race | 19 (not SAI) | +1.6 s | 138 m | 6 m |
| 2026 Austrian GP Race | 21 | −1.9 s | 156 m | 6 m |
| 2026 Austrian GP Qualifying | 22 | −1.2 → −1.5 s, then ~0 (drifts, then steps) | 99 m | 6 m |
| 2024 Las Vegas GP Race | 20 | +0.5 s | 43 m | 6 m |
| 2023 Australian GP Race | 1 (#63) | +0.26 s | 22 m | 4 m |
| 2024 Australian GP Race | 1 (#44) | +0.2–0.6 s | 20 m | 8 m |
| 2026 Dutch GP Practice 1 | 1 (#63) | +0.5 s | 53 m | 7 m |

**Not correctable:** the 2026 Hungarian GP race has a stair-stepped feed
(from about lap 7). The 2026 Monaco GP race has no position stream after about
8 minutes. That is a feed problem, not a clock offset. See
`../2026-10-09_feed_quality/`.

## `pre_lap_sync/`: the files as they were before the re-run
- `mistakes_all.parquet`, `mistakes_pressure_all.parquet`, `mistakes/`: written 2026-10-08 22:04.
  The re-run recomputed only the 9 sessions above. All other rows are identical.
- `section_profile.csv` (10-08 22:46), `car_profile.csv` (10-09 05:51),
  `circuit_characteristics_computed.csv` (08-03). In the new file only the
  autriche `lat_g_p90` value changed (3.28 → 3.19, score unchanged), patched in place.
- `replays/`: race / race3d / quali3d payloads for 2026 Austria and Zandvoort.
  They were rebuilt on the corrected clock.

## `ab_no_sync/`: clean A/B
`section_profile.csv` and `car_profile.csv` regenerated with the current code
and the correction switched off (knots file moved away). They are identical to
the `pre_lap_sync/` copies, so pre vs post isolates the sync fix.
