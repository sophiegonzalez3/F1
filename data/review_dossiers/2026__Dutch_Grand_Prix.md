# WHY THE MODEL MISSED — evidence dossier
2026 R12 · Dutch Grand Prix · dossier built 2026-08-23

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
Practice_1   air 18.8C  track 27.0C (range 23-31)  INTERMEDIATE 5% of laps  rain on 15% of samples
Practice_2   —
Practice_3   —
Sprint_Qualifying air 19.4C  track 33.0C (range 30-36)  all on slicks  rain on 5% of samples
Sprint_Shootout —
Sprint       air 17.8C  track 25.4C (range 22-30)  all on slicks  rain on 9% of samples
Qualifying   air 18.1C  track 32.5C (range 30-36)  all on slicks  rain on 6% of samples
Race         air 18.5C  track 32.1C (range 26-38)  all on slicks  rain on 17% of samples
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  HARD     -0.127 s/lap   (-0.17% of a lap)
  SOFT     +0.049 s/lap   (+0.06% of a lap)
  MEDIUM   +0.188 s/lap   (+0.25% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 48% of each driver's laps (range 25–75%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-08-23 12:55:02  SAFETY CAR LIGHTS ON
  2026-08-23 13:05:28  RED FLAG - RACE SUSPENDED
  2026-08-23 13:28:11  SAFETY CAR LIGHTS ON
```

## 2 · Per-driver evidence

### QUALIFYING

#### LAW · Red Bull Racing

predicted -0.101 → actual -0.655 · **miss -0.554%** (1.7 sd) · FASTER than predicted

- **Teammate**: VER missed -0.318% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 30, Sprint 24, Sprint Qualifying 13
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  13 flying laps against a field median of 7
- **SCREEN** · BEST LAP from Q3 (71.733s)  [Q1 73.392  Q2 72.301  Q3 71.733]
- **Race control** (qualifying):
    - `2026-08-22 14:21:09  FIA STEWARDS: Q1 INCIDENT INVOLVING CAR 30 (LAW) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-08-22 14:21:16  FIA STEWARDS: Q1 INCIDENT INVOLVING CAR 30 (LAW) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-08-22 15:01:07  FIA STEWARDS: Q1 INCIDENT INVOLVING CAR 30 (LAW) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### STR · Aston Martin

predicted +1.546 → actual +1.053 · **miss -0.493%** (1.0 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 24, Sprint 24, Sprint Qualifying 5
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 7
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 4 vs 7 predicts a +0.51% penalty, moving the miss -0.493% → -1.003% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (73.818s)  [Q1 73.818]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 74.225s, slower than its counted 73.818s — no effect on the number
- **Race control** (qualifying):
    - `2026-08-22 14:11:22  CAR 18 (STR) TIME 1:14.225 DELETED - TRACK LIMITS AT TURN 13 LAP 7 16:10:35`

  > category: ______   note: ______

#### VER · Red Bull Racing

predicted -0.708 → actual -1.026 · **miss -0.318%** (1.0 sd) · FASTER than predicted

- **Teammate**: LAW missed -0.554% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 25, Sprint 24, Sprint Qualifying 15
- **SCREEN** · ATTEMPTS  12 flying laps against a field median of 7
- **SCREEN** · BEST LAP from Q3 (71.618s)  [Q1 73.290  Q2 71.874  Q3 71.618]

  > category: ______   note: ______

#### SAI · Williams

predicted +0.207 → actual +0.717 · **miss +0.510%** (1.2 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 32, Sprint 23, Sprint Qualifying 7
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 7
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 4 vs 7 predicts a +0.51% penalty, moving the miss +0.510% → +0.000%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (73.574s)  [Q1 73.574]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 85.773s, slower than its counted 73.574s — no effect on the number
- **Race control** (qualifying):
    - `2026-08-22 14:04:59  CAR 55 (SAI) TIME 1:25.773 DELETED - TRACK LIMITS AT TURN 3 LAP 3 16:02:37`

  > category: ______   note: ______

#### HUL · Audi

predicted -0.353 → actual +0.188 · **miss +0.541%** (1.7 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 34, Sprint 7, Sprint Qualifying 13
- **SCREEN** · ATTEMPTS  7 flying laps against a field median of 7
- **SCREEN** · BEST LAP from Q2 (72.797s)  [Q1 73.188  Q2 72.797]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### LEC · Ferrari

predicted -1.682 → actual -2.379 · **miss -0.696%** (1.6 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 54 clean long-run laps (field median 40) · sessions run: Practice_1 39, Sprint 24, Sprint Qualifying 16
- **What made the actual**: 31 clean laps of 72 run (laps 17–67 of 72) · SOFT 14, MEDIUM 10, HARD 7
- **Dropped before the median**: 30 dirty-air, 18 perturbed, 10 invalid
- **What the filter did**: kept 43% of his laps (field 48%). Model measured -2.613%; over EVERY racing lap he is -2.504%. Scoring him on all laps would move the miss -0.696% → **-0.586%** (shrinks by 16%).
- **Pit stops** (4): lap 2; lap 21 (4.2s stationary); lap 43; lap 55  ·  *3 not in pitstops.parquet*
- **Radio** 14:28:39: "Now back to our spots. What do you mean back to our spots?"

  > category: ______   note: ______

#### STR · Aston Martin

predicted +1.684 → actual +1.020 · **miss -0.663%** (1.2 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 33 clean long-run laps (field median 40) · sessions run: Practice_1 24, Sprint 24, Sprint Qualifying 5
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 15 clean laps of 45 run (laps 13–39 of 72) · HARD 13, SOFT 2
- **Dropped before the median**: 22 dirty-air, 11 perturbed, 9 invalid
- **What the filter did**: kept 33% of his laps (field 48%). Model measured +0.786%; over EVERY racing lap he is +0.346%. Scoring him on all laps would move the miss -0.663% → **-1.104%** (GROWS by 66%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -1.104%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **SCREEN** · TRUNCATED  last clean lap 39 of 72 — the median covers only the first 54% of the race
- **Race control** (race):
    - `2026-08-23 14:01:26  CAR 18 (STR) TIME 1:19.923 DELETED - TRACK LIMITS AT TURN 3 LAP 20 16:00:15`
- *(5 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (4): lap 2; lap 15 (2.6s stationary); lap 35; lap 45  ·  *3 not in pitstops.parquet*
- **Radio** 14:10:48: "I don't understand why you boxed me, man. We said that the Cadillacs would be a problem, we didn't. I understood, Lance. We thought we were struggling so much on the soft, we thought the hard would give us better perform"

  > category: ______   note: ______

#### SAI · Williams

predicted +0.822 → actual +1.305 · **miss +0.483%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 40 clean long-run laps (field median 40) · sessions run: Practice_1 32, Sprint 23, Sprint Qualifying 7
- **What made the actual**: 24 clean laps of 70 run (laps 9–70 of 72) · SOFT 14, HARD 10
- **Dropped before the median**: 30 dirty-air, 22 perturbed, 10 invalid
- **What the filter did**: kept 34% of his laps (field 48%). Model measured +1.071%; over EVERY racing lap he is +1.089%. Scoring him on all laps would move the miss +0.483% → **+0.501%** (GROWS by 4%).
- **SCREEN** · THIN SLICE  only 34% of his laps survived against a field 48%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **Race control** (race):
    - `2026-08-23 12:36:56  INCIDENT INVOLVING CAR 55 (SAI) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS`
    - `2026-08-23 12:41:05  FIA STEWARDS: INCIDENT INVOLVING CAR 55 (SAI) REVIEWED NO FURTHER INVESTIGATION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS`
    - `2026-08-23 14:37:25  CAR 55 (SAI) TIME 1:21.602 DELETED - TRACK LIMITS AT TURN 3 LAP 47 16:36:03`
    - `2026-08-23 15:03:29  CAR 55 (SAI) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 65 17:00:31 (PIT)`
    - `2026-08-23 15:06:10  TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 23 (ALB) NOTED - CAUSING A COLLISION (17:04:55)`
    - `2026-08-23 15:06:16  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 23 (ALB) UNDER INVESTIGATION - CAUSING A COLLISION (17:04:55)`
    - `2026-08-23 15:06:43  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 55 (SAI) - CAUSING A COLLISION (17:04:55)`
- *(15 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 1: procedural — FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS → no action
- **Incident** lap 71: contact — CAUSING A COLLISION vs ALB → penalty: 10 second time penalty
- **Pit stops** (3): lap 2; lap 30 (2.7s stationary); lap 65  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted +0.043 → actual +0.893 · **miss +0.850%** (2.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 54 clean long-run laps (field median 40) · sessions run: Practice_1 37, Sprint 24, Sprint Qualifying 15
- **What made the actual**: 37 clean laps of 71 run (laps 7–71 of 72) · HARD 23, MEDIUM 14
- **Dropped before the median**: 21 dirty-air, 16 perturbed, 9 invalid
- **What the filter did**: kept 52% of his laps (field 48%). Model measured +0.659%; over EVERY racing lap he is +0.209%. Scoring him on all laps would move the miss +0.850% → **+0.400%** (shrinks by 53%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.400%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Race control** (race):
    - `2026-08-23 13:11:46  TURN 14 INCIDENT INVOLVING CAR 41 (LIN) NOTED - YELLOW FLAG INFRINGEMENT (15:04:49)`
    - `2026-08-23 13:24:01  FIA STEWARDS: TURN 14 INCIDENT INVOLVING CAR 41 (LIN) UNDER INVESTIGATION - YELLOW FLAG INFRINGEMENT (15:04:49)`
    - `2026-08-23 13:40:19  FIA STEWARDS: DRIVE THROUGH PENALTY FOR CAR 41 (LIN) - YELLOW FLAG INFRINGEMENT (15:04:49)`
    - `2026-08-23 13:42:52  CAR 41 (LIN) TIME 1:29.772 DELETED - TRACK LIMITS AT TURN 3 LAP 6 15:41:36`
    - `2026-08-23 13:50:51  FIA STEWARDS: PENALTY SERVED - DRIVE THROUGH PENALTY FOR CAR 41 (LIN) - YELLOW FLAG INFRINGEMENT (15:04:49)`
- *(6 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: procedural — YELLOW FLAG INFRINGEMENT → penalty: drive through
- **Pit stops** (3): lap 2; lap 5; lap 36 (3.2s stationary)  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### LAW · Red Bull Racing

predicted -1.347 → actual -0.450 · **miss +0.897%** (2.1 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 47 clean long-run laps (field median 40) · sessions run: Practice_1 30, Sprint 24, Sprint Qualifying 13
- **What made the actual**: 54 clean laps of 72 run (laps 9–72 of 72) · MEDIUM 42, SOFT 12
- **Dropped before the median**: 8 dirty-air, 14 perturbed, 9 invalid
- **What the filter did**: kept 75% of his laps (field 48%). Model measured -0.684%; over EVERY racing lap he is -1.119%. Scoring him on all laps would move the miss +0.897% → **+0.462%** (shrinks by 49%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.462%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · COMPOUND SKEW  ran MEDIUM 78%, SOFT 22% vs field HARD 56%, SOFT 27%, MEDIUM 17% — worth +0.24% of a lap at this race's measured offsets
- **SCREEN** · PACE STEP  +0.77% at lap 35 (slower afterwards; bigger than 90% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-08-23 14:54:17  INCIDENT INVOLVING CAR 30 (LAW) NOTED - YELLOW FLAG INFRINGEMENT (16:44:04)`
    - `2026-08-23 15:02:48  FIA STEWARDS: INCIDENT INVOLVING CAR 30 (LAW) UNDER INVESTIGATION - YELLOW FLAG INFRINGEMENT (16:44:04)`
    - `2026-08-23 15:04:30  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 30 (LAW) - YELLOW FLAG INFRINGEMENT (16:44:04)`
- **Incident** lap 62: procedural — YELLOW FLAG INFRINGEMENT → penalty: 10 second time penalty
- **Pit stops** (3): lap 2; lap 21; lap 47  ·  *3 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.