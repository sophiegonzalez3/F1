# Snapshot — adoption of compound intercepts in track evolution (2026-10-09)

What changed: `f1lib/processing.py::enrich_track_evolution` gained
`compound_intercepts=True` (per-compound dummies in the evolution regression).
Only `TrackEvo_s` (the time bins) is subtracted from lap times, never the
compound effect, so the *definition* of corrected pace is unchanged; what
changes is that a wet-tyre deficit is no longer booked as "slow early track".
All derived tables were regenerated on 2026-10-09 with `after_race.py`
(skipping odds / polymarket / forecast / radio / qualiscene / mistakes).

This folder keeps what was there before, for comparisons and deep dives.

## `pre_intercepts/` — the files as they were just before the re-run

| file | written | code state |
|---|---|---|
| team_pace_by_event.csv, driver_pace_by_event.csv | 2026-10-06 19:24 | no intercepts |
| backtest_pace_model.csv, backtest_pace_detail.csv | 2026-10-06 19:30 | scored on the **April 2026** measurement cache (stale, see below) |
| upgrade_study.csv, lap_retention.csv | 2026-10-06 | no intercepts |
| section_profile.csv | 2026-10-08 07:09 | no intercepts |
| weekend_decomp.csv | numbers 2026-10-06, `retirements` labels 2026-10-08 | no intercepts; labels already from curated DNF causes (`family_of`) |
| car_profile.csv | 2026-10-08 22:09 | **intercepts ON already** (+ Sepang curated corners) — not a "before" |
| race_stats.csv | 2026-10-08 21:44 | does not depend on evolution; after the Bahrain provisional-results heal |
| 2026__Bahrain_Grand_Prix.md | 2026-10-06 | review dossier the Bahrain categories in model_review.csv were judged against |

The same tables at commit `accf3ca` (2026-10-08 07:22) are also pre-intercepts:
`git show accf3ca:data/<file>`.

## `ab_backtest/` — clean A/B of the pace-model backtest

Same targets (team_pace_by_event of 2026-10-06), measurements recomputed per
variant, everything else identical. `*_intercepts_on.csv` / `*_off.csv` =
summary and per-team detail. Result (last pre-race stage, 128 event x kind):
mean dMAE +0.0005 pp, 95% CI [-0.0018, +0.0027], 52 better / 58 worse —
neutral. `on` loses 3 stages (Austria 2024 after-FP1 x2, Mexico 2024 raw-FP).

After the full re-run (targets regenerated too) vs the April-cache score:
dry races ~flat, wet races longrun MAE +0.045 (n=15) — the old correction
was hiding the wet-tyre deficit.

## `measurements/` — practice measurements (`event_measurements`), as parquet

- `no_intercepts_current_code/` — 64 events, today's code with
  `compound_intercepts=False`. The "with" counterpart is the live cache
  (`cache/pace_measurements/<fingerprint>/`).
- `april2026_cache/` — 271 entries from the old, never-invalidated cache
  (last written 2026-04-10); what the backtest silently scored until this
  re-run. Includes events/seasons outside the current backtest set.

File names: `<season>__<Event_slug>.parquet` (April) or
`<season>__<Event_slug>__<input signature>.parquet`.
