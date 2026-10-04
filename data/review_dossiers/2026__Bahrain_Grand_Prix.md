# WHY THE MODEL MISSED — evidence dossier
2026 R16 · Bahrain Grand Prix · dossier built 2026-10-04

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
Practice_1   air 32.6C  track 54.1C (range 0-58)  all on slicks
Practice_2   air 33.3C  track 54.8C (range 0-63)  all on slicks
Practice_3   air 32.6C  track 54.8C (range 0-59)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 32.8C  track 55.1C (range 0-59)  all on slicks
Race         air 26.8C  track 34.4C (range 0-46)  INTERMEDIATE 11% of laps  rain on 31% of samples
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.028 s/lap   (-0.03% of a lap)
  MISSING  -0.007 s/lap   (-0.01% of a lap)
  MEDIUM   +0.027 s/lap   (+0.03% of a lap)
  HARD     +0.034 s/lap   (+0.03% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 33% of each driver's laps (range 7–55%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-10-04 07:35:03  FORMATION LAP(S) BEHIND SAFETY CAR
  2026-10-04 08:28:06  SAFETY CAR LIGHTS ON
  2026-10-04 08:52:16  SAFETY CAR DEPLOYED
  2026-10-04 08:58:50  SAFETY CAR IN THIS LAP
  2026-10-04 08:59:29  SAFETY CAR LIGHTS OFF
  2026-10-04 09:58:26  SAFETY CAR DEPLOYED
  2026-10-04 10:03:36  LAPPED CARS MAY NOW OVERTAKE THE SAFETY CAR: 55, 5, 11
  2026-10-04 10:11:34  SAFETY CAR IN THIS LAP
  2026-10-04 10:12:34  SAFETY CAR LIGHTS OFF
```

## 2 · Per-driver evidence

### QUALIFYING

#### ANT · Mercedes

predicted +0.055 → actual -0.867 · **miss -0.922%** (2.2 sd) · FASTER than predicted

- **Teammate**: RUS missed -0.534% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 5) · sessions run: Practice_1 23, Practice_2 28, Practice_3 12
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (95.631s)  [Q1 97.041  Q2 95.959  Q3 95.631]
- **SCREEN** · deleted lap 96.075s, slower than its counted 95.631s — no effect on the number
- **Race control** (qualifying):
    - `2026-10-03 08:31:44  CAR 12 (ANT) TIME 1:36.075 DELETED - TRACK LIMITS AT TURN 6 LAP 6 16:29:41`

  > category: ______   note: ______

#### RUS · Mercedes

predicted -0.062 → actual -0.596 · **miss -0.534%** (1.3 sd) · FASTER than predicted

- **Teammate**: ANT missed -0.922% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 6 clean quali-sim laps (field median 5) · sessions run: Practice_1 25, Practice_2 28, Practice_3 11
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (95.871s)  [Q1 97.264  Q2 96.245  Q3 95.871]

  > category: ______   note: ______

#### VER · Red Bull Racing

predicted -0.926 → actual -1.362 · **miss -0.436%** (1.4 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 5) · sessions run: Practice_1 23, Practice_2 20, Practice_3 12
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (95.130s)  [Q1 96.477  Q2 95.696  Q3 95.130]
- **Race control** (qualifying):
    - `2026-10-03 08:28:17  BLACK AND WHITE FLAG FOR CAR 3 (VER) - DRIVING UNNECESSARILY SLOWLY (16:26:55)`

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.339 → actual +0.972 · **miss +0.633%** (1.7 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 5) · sessions run: Practice_1 23, Practice_2 30, Practice_3 12
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% penalty, moving the miss +0.633% → +0.463%, cutting it by 27% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (97.980s)  [Q1 97.980]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 99.780s, slower than its counted 97.980s — no effect on the number
- **Race control** (qualifying):
    - `2026-10-03 08:14:25  CAR 87 (BEA) TIME 1:39.780 DELETED - TRACK LIMITS AT TURN 15 LAP 6 16:10:47`
    - `2026-10-03 08:14:29  CAR 87 (BEA) LAP DELETED - TRACK LIMITS AT TURN 15 (NEXT LAP PIT)`

  > category: ______   note: ______

#### ALB · Williams

predicted +0.963 → actual +1.610 · **miss +0.647%** (1.6 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 6 clean quali-sim laps (field median 5) · sessions run: Practice_1 22, Practice_2 30, Practice_3 18
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% penalty, moving the miss +0.647% → +0.307%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (98.600s)  [Q1 98.600]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted -0.223 → actual +0.872 · **miss +1.095%** (2.8 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 5) · sessions run: Practice_1 27, Practice_2 33, Practice_3 24
- **SCREEN** · ATTEMPTS  1 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 1 vs 4 predicts a +0.51% penalty, moving the miss +1.095% → +0.585%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (97.883s)  [Q1 97.883]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### VER · Red Bull Racing

predicted -0.997 → actual -1.562 · **miss -0.565%** (1.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 28 clean long-run laps (field median 24) · sessions run: Practice_1 23, Practice_2 20, Practice_3 12
- **What made the actual**: 30 clean laps of 55 run (laps 14–55 of 55) · SOFT 30
- **Dropped before the median**: 7 dirty-air, 22 perturbed, 17 invalid
- **What the filter did**: kept 55% of his laps (field 33%). Model measured -1.890%; over EVERY racing lap he is -2.109%. Scoring him on all laps would move the miss -0.565% → **-0.784%** (GROWS by 39%).
- **SCREEN** · PACE STEP  +0.92% at lap 38 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Pit stops** (3): lap 9; lap 33; lap 43  ·  *3 not in pitstops.parquet*

  > category: ______   note: ______

#### LEC · Ferrari

predicted -1.052 → actual -0.413 · **miss +0.639%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 31 clean long-run laps (field median 24) · sessions run: Practice_1 25, Practice_2 29, Practice_3 19
- **What made the actual**: 19 clean laps of 55 run (laps 6–53 of 55) · SOFT 10, MISSING 7, INTERMEDIATE 2
- **Dropped before the median**: 16 dirty-air, 24 perturbed, 16 invalid
- **What the filter did**: kept 35% of his laps (field 33%). Model measured -0.742%; over EVERY racing lap he is -0.845%. Scoring him on all laps would move the miss +0.639% → **+0.536%** (shrinks by 16%).
- **Race control** (race):
    - `2026-10-04 08:45:26  CAR 16 (LEC) LAP DELETED - TRACK LIMITS AT TURN 12 LAP 3 16:41:20 (PIT)`
    - `2026-10-04 08:47:44  TURN 9 INCIDENT INVOLVING CARS 16 (LEC) AND 27 (HUL) NOTED - CAUSING A COLLISION (16:40:50)`
    - `2026-10-04 08:50:09  FIA STEWARDS: TURN 9 INCIDENT INVOLVING CARS 16 (LEC) AND 27 (HUL) REVIEWED NO FURTHER INVESTIGATION - CAUSING A COLLISION (16:40:50)`
- **Incident** lap 7: contact — CAUSING A COLLISION vs HUL → no action
- **Pit stops** (4): lap 3; lap 9; lap 28; lap 43  ·  *4 not in pitstops.parquet*

  > category: ______   note: ______

#### BOR · Audi

predicted +0.238 → actual +1.283 · **miss +1.046%** (2.2 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 22 clean long-run laps (field median 24) · sessions run: Practice_1 25, Practice_2 25, Practice_3 15
- **What made the actual**: 11 clean laps of 55 run (laps 5–54 of 55) · SOFT 7, INTERMEDIATE 2, HARD 2
- **Dropped before the median**: 27 dirty-air, 23 perturbed, 16 invalid
- **What the filter did**: kept 20% of his laps (field 33%). Model measured +0.953%; over EVERY racing lap he is +0.870%. Scoring him on all laps would move the miss +1.046% → **+0.963%** (shrinks by 8%).
- **SCREEN** · THIN SLICE  only 20% of his laps survived against a field 33%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · THIN SAMPLE  only 11 clean laps entered the median (field median 15+ is normal)
- **Race control** (race):
    - `2026-10-04 09:03:09  TURN 2 INCIDENT INVOLVING CARS 5 (BOR) AND 55 (SAI) NOTED - CAUSING A COLLISION (17:01:01)`
    - `2026-10-04 09:09:13  FIA STEWARDS: TURN 2 INCIDENT INVOLVING CARS 5 (BOR) AND 55 (SAI) UNDER INVESTIGATION - CAUSING A COLLISION (17:01:01)`
    - `2026-10-04 09:15:10  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 5 (BOR) - CAUSING A COLLISION (17:01:01)`
    - `2026-10-04 09:45:45  FIA STEWARDS: PENALTY SERVED - 10 SECOND TIME PENALTY FOR CAR 5 (BOR) - CAUSING A COLLISION (17:01:01)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 14: contact — CAUSING A COLLISION vs SAI → penalty: 10 second time penalty
- **Pit stops** (5): lap 2; lap 9; lap 15; lap 34; lap 44  ·  *5 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.