# Snapshot: degraded telemetry feeds masked (2026-10-09)

**What changed:** `f1lib/telemetry_quality.py` flags each driver-lap whose
live-timing feed is missing or stair-stepped. It flags the two sources
separately:

- `pos_bad`: X/Y.
- `car_bad`: Speed, Throttle, Brake, RPM.

`scripts/audit_telemetry_quality.py` writes `data/telemetry_quality.csv` (one
row per session) and `data/telemetry_degraded_laps.csv` (one row per degraded lap).
It runs in after_race (`telquality` step) and in during_weekend.

**Consumers:**
- mistakes (`f1lib/mistakes._analysis_lap_mask`, so DUEL as well) and the
  section-profile team laps skip `car_bad` laps.
- The section-profile reference lap also skips `pos_bad` laps, because it supplies the curvature.
- The car-profile telemetry traits skip `car_bad` laps.
- A session with more than 50% bad laps on a channel is dropped entirely for
  that channel (`session_unusable`). Its few clean laps are not representative.
- The 2D race replay shows a warning when at least 5% of laps have a bad position feed.

**What the feed looks like.** A fresh FastF1 download (empty cache, 2026-10-09)
gives identical numbers, so the defect is upstream (F1 live timing):

| session | defect |
|---|---|
| 2026 Hungarian GP Race | from lap ~7: Speed/RPM change on ~33% of samples, X/Y on ~8%; 1299/1431 laps car_bad → session dropped |
| 2026 Monaco GP Race | position stream stops ~8 min after the start (1352/1452 laps pos_bad); car channels fine |
| 2026 Chinese GP Practice 1 | car channels frozen for 161/540 laps |
| 2026 Japanese GP Race / Chinese GP Race & Sprint | individual cars' car feed frozen for whole stints (JPN #41, #87; CHN #10, #27) |
| 2026 Canadian GP / Azerbaijan GP Practice 1 | individual cars' or all cars' pos missing on a few laps |

35 of 226 cached sessions have at least one degraded lap. Most have only 1–3 scattered laps.

## `pre_feed_quality/`: the files as they were before the re-run
These were written the same day, after the lap-sync fix.

- `mistakes_all.parquet`, `mistakes_pressure_all.parquet`, `mistakes/`. The
  re-run recomputed the 22 sessions with car_bad laps. The 2026 Hungarian race
  went from 1801 mistakes on 20,208 corner-laps (8.9%) to no rows.
- `section_profile.csv`. Only the 2026 Japanese race (≤0.06 s) and the 2026
  Monaco race (≤0.15 s) change; the Monaco reference lap now has real X/Y.
- `car_profile.csv`. `save_pct` changes for 2025 Bahrain, 2026 China and 2026
  Japan; the 2026 Hungary values are now empty. 2026 season means: max change
  0.13 pp, same team order.
