# WHY THE MODEL MISSED — evidence dossier
2026 R1 · Australian Grand Prix · dossier built 2026-08-08

Facts only. Nothing here is a verdict; the category and the note are yours to write.

## 0 · What these two numbers can and cannot see

```
onelap  = best qualifying lap, session-normalised across Q1/Q2/Q3,
          expressed vs the field median.
longrun = MEDIAN of clean-air race laps, fuel- and track-corrected,
          after ValidLap & ~Dirty_Air & ~Perturbed_Lap, >=10 laps.
```

Dirty-air, safety-car and in/out laps are removed BEFORE the race median is taken. So on a `longrun` row:

- **`traffic` is almost never admissible** — the laps behind another car are already gone from the statistic.
- **`penalty` is almost never admissible** — five seconds at the flag does not change a lap time.
- **`strategy` needs a stated mechanism** that moves the *median clean lap* — compound mix or stint length, not the pit call itself. The compound screen below prices that mechanism at this race's own numbers.

On an `onelap` row the admissible causes are only those inside the qualifying hour: a deleted best lap, a flag on the flyer, a car change, weather moving between segments. Anything about the race is not evidence about this number.

## 1 · Field-wide context

```
Practice_1   air 20.8C  track 35.3C (range 32-38)  all on slicks
Practice_2   air 22.5C  track 33.3C (range 31-36)  all on slicks
Practice_3   air 20.6C  track 36.9C (range 34-40)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 20.5C  track 34.3C (range 31-38)  all on slicks
Race         air 24.2C  track 36.1C (range 33-39)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MEDIUM   -0.290 s/lap   (-0.35% of a lap)
  SOFT     -0.233 s/lap   (-0.28% of a lap)
  HARD     +0.312 s/lap   (+0.37% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 53% of each driver's laps (range 12–81%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  no safety car, VSC or red flag
```

## 2 · Per-driver evidence

### RACE PACE

#### ANT · Mercedes

predicted -0.872 → actual -1.790 · **miss -0.918%** (1.0 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 32 clean long-run laps (field median 31) · sessions run: Practice_1 24, Practice_2 31, Practice_3 18
- **What made the actual**: 41 clean laps of 58 run (laps 6–58 of 58) · HARD 38, MEDIUM 3
- **Dropped before the median**: 11 dirty-air, 12 perturbed, 3 invalid
- **What the filter did**: kept 71% of his laps (field 53%). Model measured -1.947%; over EVERY racing lap he is -2.243%. Scoring him on all laps would move the miss -0.918% → **-1.213%** (GROWS by 32%).
- **SCREEN** · COMPOUND SKEW  ran HARD 93%, MEDIUM 7% vs field HARD 67%, MEDIUM 20%, SOFT 13% — worth +0.18% of a lap at this race's measured offsets
- **SCREEN** · PACE STEP  +0.88% at lap 53 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Pit stops** (1): lap 12 (2.5s stationary)

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.720 → actual +2.961 · **miss +1.240%** (1.3 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 15 clean long-run laps (field median 31) · sessions run: Practice_1 14, Practice_2 2, Practice_3 21
- **SCREEN** · THIN READ  the model had 15 laps of this type against a field median of 31 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **What made the actual**: 39 clean laps of 55 run (laps 4–53 of 58) · HARD 21, MEDIUM 10, SOFT 8
- **Dropped before the median**: 5 dirty-air, 12 perturbed, 5 invalid
- **What the filter did**: kept 71% of his laps (field 53%). Model measured +2.801%; over EVERY racing lap he is +2.558%. Scoring him on all laps would move the miss +1.240% → **+0.997%** (shrinks by 20%).
- **Race control** (race):
    - `2026-03-08 04:34:21  TURN 11 INCIDENT INVOLVING CARS 11 (PER) AND 30 (LAW) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK`
    - `2026-03-08 04:37:32  FIA STEWARDS: TURN 11 INCIDENT INVOLVING CARS 11 (PER) AND 30 (LAW) UNDER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK`
    - `2026-03-08 04:40:49  FIA STEWARDS: TURN 11 INCIDENT INVOLVING CARS 11 (PER) AND 30 (LAW) NO FURTHER ACTION - FORCING ANOTHER DRIVER OFF THE TRACK`
    - `2026-03-08 04:43:19  INCIDENT INVOLVING CAR 11 (PER) NOTED - IGNORING BLUE FLAGS`
    - `2026-03-08 04:53:27  FIA STEWARDS: INCIDENT INVOLVING CAR 11 (PER) REVIEWED NO FURTHER INVESTIGATION - IGNORING BLUE FLAGS`
- *(23 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 21: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs LAW → no action
- **Incident** lap 27: procedural — IGNORING BLUE FLAGS → no action
- **Pit stops** (2): lap 18 (5.5s stationary); lap 43  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.