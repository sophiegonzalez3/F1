# WHY THE MODEL MISSED — evidence dossier
2026 R6 · Monaco Grand Prix · dossier built 2026-08-08

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
Practice_1   air 23.8C  track 32.5C (range 29-40)  all on slicks  rain on 4% of samples
Practice_2   air 23.2C  track 30.3C (range 28-32)  all on slicks  rain on 9% of samples
Practice_3   air 23.0C  track 29.9C (range 28-33)  all on slicks  rain flag: isolated sample
Qualifying   air 23.7C  track 38.5C (range 32-47)  all on slicks
Race         air 23.7C  track 38.0C (range 28-46)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.529 s/lap   (-0.69% of a lap)
  HARD     +0.053 s/lap   (+0.07% of a lap)
  MEDIUM   +0.269 s/lap   (+0.35% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 56% of each driver's laps (range 5–78%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-06-07 14:20:02  SAFETY CAR DEPLOYED
  2026-06-07 14:23:59  SAFETY CAR WILL USE START/FINISH STRAIGHT
  2026-06-07 14:26:32  LAPPED CARS MAY NOW OVERTAKE THE SAFETY CAR: 6, 63, 41, 23, 55, 31, 27, 43, 10, 81, 14, 30, 11, 5
  2026-06-07 14:29:41  SAFETY CAR IN THIS LAP
  2026-06-07 14:31:18  SAFETY CAR DEPLOYED
  2026-06-07 14:33:17  SAFETY CAR WILL USE START/FINISH STRAIGHT
  2026-06-07 14:35:07  RED FLAG - RACE SUSPENDED
  2026-06-07 14:46:56  INCIDENT INVOLVING CAR 6 (HAD) NOTED - SAFETY CAR INFRINGEMENT
  2026-06-07 14:47:03  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT
  2026-06-07 14:54:39  FIA STEWARDS: UPDATE: INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT (16:33:48)
  2026-06-07 14:58:50  INCIDENT INVOLVING CAR 44 (HAM) NOTED - SAFETY CAR INFRINGEMENT (16:34:03)
  2026-06-07 14:59:03  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT (16:34:03)
  2026-06-07 15:06:29  SAFETY CAR LIGHTS ON
  2026-06-07 15:13:47  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) NO FURTHER ACTION - SAFETY CAR INFRINGEMENT (16:34:03)
  2026-06-07 15:19:35  INCIDENT INVOLVING CAR 6 (HAD) NOTED - RED FLAG INFRINGEMENT
  2026-06-07 15:19:53  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) NO FURTHER ACTION - SAFETY CAR INFRINGEMENT (16:33:48)
  2026-06-07 15:20:11  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) WILL BE INVESTIGATED AFTER THE RACE - RED FLAG INFRINGEMENT
```

## 2 · Per-driver evidence

### QUALIFYING

#### PER · Cadillac

predicted +2.076 → actual +0.768 · **miss -1.308%** (2.3 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 28, Practice_2 31, Practice_3 19
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 14
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 6 vs 14 predicts a +1.36% penalty, moving the miss -1.308% → -2.668% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (74.747s)  [Q1 74.747]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 90.897s, slower than its counted 74.747s — no effect on the number
- **Race control** (qualifying):
    - `2026-06-06 14:05:52  CAR 11 (PER) TIME 1:30.897 DELETED - TRACK LIMITS AT TURN 10 LAP 5 16:05:06`
    - `2026-06-06 14:08:48  CAR 11 (PER) LAP DELETED - TRACK LIMITS AT TURN 10 LAP 7 16:07:51 (PIT)`

  > category: ______   note: ______

#### HAM · Ferrari

predicted -0.875 → actual -1.291 · **miss -0.416%** (1.4 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 28, Practice_2 36, Practice_3 30
- **SCREEN** · ATTEMPTS  16 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q3 (72.279s)  [Q1 73.777  Q2 72.934  Q3 72.279]
- **SCREEN** · deleted lap 96.716s, slower than its counted 72.279s — no effect on the number
- **Race control** (qualifying):
    - `2026-06-06 14:14:55  CAR 44 (HAM) TIME 1:36.716 DELETED - TRACK LIMITS AT TURN 1 LAP 9 16:12:12`
    - `2026-06-06 14:59:04  BLACK AND WHITE FLAG FOR CAR 44 (HAM) - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS`

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.492 → actual -1.065 · **miss +0.427%** (1.0 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 0 clean quali-sim laps (field median 2) · sessions run: Practice_1 29, Practice_2 35, Practice_3 23
- **SCREEN** · THIN READ  the model had 0 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  18 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q3 (72.445s)  [Q1 74.214  Q2 73.238  Q3 72.445]
- **SCREEN** · deleted lap 95.179s, slower than its counted 72.445s — no effect on the number
- **SCREEN** · deleted lap 93.532s, slower than its counted 72.445s — no effect on the number
- **SCREEN** · deleted lap 99.599s, slower than its counted 72.445s — no effect on the number
- **SCREEN** · deleted lap 93.562s, slower than its counted 72.445s — no effect on the number
- **SCREEN** · deleted lap 81.611s, slower than its counted 72.445s — no effect on the number
- **Race control** (qualifying):
    - `2026-06-06 14:03:43  CAR 63 (RUS) TIME 1:35.179 DELETED - TRACK LIMITS AT TURN 10 LAP 2 16:02:59`
    - `2026-06-06 14:05:14  CAR 63 (RUS) TIME 1:33.532 DELETED - TRACK LIMITS AT TURN 10 LAP 3 16:04:26`
    - `2026-06-06 14:08:46  CAR 63 (RUS) TIME 1:39.599 DELETED - TRACK LIMITS AT TURN 10 LAP 5 16:07:16`
    - `2026-06-06 14:09:49  CAR 63 (RUS) TIME 1:33.562 DELETED - TRACK LIMITS AT TURN 10 LAP 6 16:08:50`
    - `2026-06-06 14:09:50  CAR 63 (RUS) TIME 1:33.562 DELETED - TRACK LIMITS AT TURN 16 LAP 6 16:09:12`
    - `2026-06-06 14:17:48  CAR 63 (RUS) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 11 16:15:41 (PIT)`
    - `2026-06-06 14:45:19  CAR 63 (RUS) TIME 1:21.611 DELETED - TRACK LIMITS AT TURN 10 LAP 19 16:44:31`

  > category: ______   note: ______

#### BOR · Audi

predicted -0.128 → actual +0.681 · **miss +0.809%** (1.7 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 2) · sessions run: Practice_1 31, Practice_2 35, Practice_3 27
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 14
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 6 vs 14 predicts a +1.36% penalty, moving the miss +0.809% → -0.551%, cutting it by 32% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (74.683s)  [Q1 74.683]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 95.069s, slower than its counted 74.683s — no effect on the number
- **Race control** (qualifying):
    - `2026-06-06 14:14:59  CAR 5 (BOR) TIME 1:35.069 DELETED - TRACK LIMITS AT TURN 10 LAP 10 16:13:47`

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted -0.157 → actual +0.684 · **miss +0.841%** (1.8 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 34, Practice_2 37, Practice_3 24
- **SCREEN** · ATTEMPTS  14 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q2 (74.248s)  [Q1 74.685  Q2 74.248]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-06-06 14:42:38  PIT LANE INCIDENT INVOLVING CARS 23 (ALB) AND 41 (LIN) NOTED (16:41:02)`
    - `2026-06-06 14:48:37  FIA STEWARDS: PIT LANE INCIDENT INVOLVING CARS 23 (ALB) AND 41 (LIN) WILL BE INVESTIGATED AFTER THE SESSION (16:41:02)`
    - `2026-06-06 14:51:40  TURN 18 INCIDENT INVOLVING CAR 41 (LIN) NOTED - IMPEDING (16:46:05)`
    - `2026-06-06 15:00:38  FIA STEWARDS: TURN 18 INCIDENT INVOLVING CAR 41 (LIN) REVIEWED NO FURTHER INVESTIGATION - IMPEDING (16:46:05)`

  > category: ______   note: ______

### RACE PACE

#### HUL · Audi

predicted +0.174 → actual -0.934 · **miss -1.107%** (2.3 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 51 clean long-run laps (field median 49) · sessions run: Practice_1 27, Practice_2 34, Practice_3 22
- **What made the actual**: 12 clean laps of 78 run (laps 10–32 of 78) · HARD 10, MEDIUM 2
- **Dropped before the median**: 60 dirty-air, 17 perturbed, 14 invalid
- **What the filter did**: kept 15% of his laps (field 56%). Model measured -1.218%; over EVERY racing lap he is +0.368%. Scoring him on all laps would move the miss -1.107% → **+0.479%** (shrinks by 57%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.479%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · THIN SAMPLE  only 12 clean laps entered the median (field median 15+ is normal)
- **SCREEN** · TRUNCATED  last clean lap 32 of 78 — the median covers only the first 41% of the race
- **Race control** (race):
    - `2026-06-07 13:42:48  CAR 27 (HUL) TIME 1:19.870 DELETED - TRACK LIMITS AT TURN 10 LAP 29 15:41:18`
    - `2026-06-07 15:23:56  CAR 27 (HUL) TIME 1:19.754 DELETED - TRACK LIMITS AT TURN 10 LAP 72 17:19:04`
    - `2026-06-07 15:27:25  TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) NOTED - CAUSING A COLLISION`
    - `2026-06-07 15:28:00  FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) UNDER INVESTIGATION - CAUSING A COLLISION`
    - `2026-06-07 15:28:20  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 27 (HUL) - CAUSING A COLLISION`
- *(7 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 78: contact — CAUSING A COLLISION → penalty: 10 second time penalty
- **Incident** lap 78: contact — CAUSING A COLLISION vs SAI → investigated
- **Pit stops** (6): lap 12 (2.6s stationary); lap 58; lap 59; lap 65; lap 67; lap 68  ·  *5 not in pitstops.parquet*

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.389 → actual -0.222 · **miss -0.611%** (1.3 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 55 clean long-run laps (field median 49) · sessions run: Practice_1 31, Practice_2 35, Practice_3 24
- **What made the actual**: 26 clean laps of 78 run (laps 11–78 of 78) · HARD 23, SOFT 3
- **Dropped before the median**: 46 dirty-air, 18 perturbed, 12 invalid
- **What the filter did**: kept 33% of his laps (field 56%). Model measured -0.507%; over EVERY racing lap he is +0.394%. Scoring him on all laps would move the miss -0.611% → **+0.290%** (shrinks by 53%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.290%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · PACE STEP  +2.54% at lap 55 (slower afterwards; bigger than 94% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- *(13 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (5): lap 9 (3.4s stationary); lap 59; lap 65; lap 67; lap 68  ·  *4 not in pitstops.parquet*
- **Radio** 15:35:57: "Nice job, we definitely deserve this one. Yeah good job guys, good job. Hats off to the strategies today. Yeah that was quite impressive, thank you. Shout out to Hazard and Edge. Yes. Okay, we're P9 actually, because Nic"

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.167 → actual -1.716 · **miss -0.549%** (1.3 sd) · FASTER than predicted

- **Teammate**: LEC missed -0.433% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 54 clean long-run laps (field median 49) · sessions run: Practice_1 28, Practice_2 36, Practice_3 30
- **What made the actual**: 59 clean laps of 78 run (laps 3–78 of 78) · HARD 29, MEDIUM 25, SOFT 5
- **Dropped before the median**: 8 dirty-air, 18 perturbed, 13 invalid
- **What the filter did**: kept 76% of his laps (field 56%). Model measured -1.999%; over EVERY racing lap he is -2.952%. Scoring him on all laps would move the miss -0.549% → **-1.502%** (GROWS by 174%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -1.502%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **SCREEN** · PACE STEP  +0.91% at lap 58 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-07 13:45:03  INCIDENT INVOLVING CAR 44 (HAM) NOTED - SPEEDING IN THE PIT LANE (15:39:17)`
    - `2026-06-07 13:45:33  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) UNDER INVESTIGATION - SPEEDING IN THE PIT LANE (15:39:17)`
    - `2026-06-07 13:45:53  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - SPEEDING IN THE PIT LANE (15:39:17)`
    - `2026-06-07 14:28:23  FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - SPEEDING IN THE PIT LANE (15:39:17)`
    - `2026-06-07 14:58:50  INCIDENT INVOLVING CAR 44 (HAM) NOTED - SAFETY CAR INFRINGEMENT (16:34:03)`
    - `2026-06-07 14:59:03  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT (16:34:03)`
    - `2026-06-07 15:13:47  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) NO FURTHER ACTION - SAFETY CAR INFRINGEMENT (16:34:03)`
- **Incident** lap 33: procedural — SPEEDING IN THE PIT LANE → penalty: 5 second time penalty
- **Incident** lap 68: procedural — SAFETY CAR INFRINGEMENT → no action
- **Pit stops** (5): lap 28 (2.1s stationary); lap 60; lap 61; lap 66; lap 68  ·  *4 not in pitstops.parquet*
- **Radio** 13:13:52: "Where is the faster? It's five pair and three three and then three four."
- **Radio** 15:22:20: "And delay turn-in, five and six."
- **Radio** 15:28:56: "And well done, Lewis. Great job, guys. Sorry I couldn't pull the win. Sorry I couldn't get the win in the end. They just had the upper hand on us this weekend. But mega result. Really grateful for all the hard work and l"

  > category: ______   note: ______

#### LEC · Ferrari

predicted -1.344 → actual -1.778 · **miss -0.433%** (1.0 sd) · FASTER than predicted

- **Teammate**: HAM missed -0.549% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 55 clean long-run laps (field median 49) · sessions run: Practice_1 31, Practice_2 36, Practice_3 32
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 47 clean laps of 65 run (laps 5–59 of 78) · MEDIUM 28, HARD 19
- **Dropped before the median**: 6 dirty-air, 15 perturbed, 9 invalid
- **What the filter did**: kept 72% of his laps (field 56%). Model measured -2.061%; over EVERY racing lap he is -2.926%. Scoring him on all laps would move the miss -0.433% → **-1.298%** (GROWS by 200%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -1.298%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **SCREEN** · TRUNCATED  last clean lap 59 of 78 — the median covers only the first 76% of the race
- **SCREEN** · COMPOUND SKEW  ran MEDIUM 60%, HARD 40% vs field MEDIUM 52%, HARD 27%, SOFT 21% — worth +0.18% of a lap at this race's measured offsets
- **Race control** (race):
    - `2026-06-07 13:33:23  CAR 16 (LEC) TIME 1:17.884 DELETED - TRACK LIMITS AT TURN 10 LAP 23 15:32:30`
- **Pit stops** (3): lap 35; lap 60; lap 61  ·  *3 not in pitstops.parquet*
- **Radio** 14:32:36: "currency, I'm not going to take the f***ing plane, he's f***ing great"

  > category: ______   note: ______

#### COL · Alpine

predicted +0.093 → actual +0.589 · **miss +0.496%** (1.0 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 49 clean long-run laps (field median 49) · sessions run: Practice_1 32, Practice_2 31, Practice_3 21
- **What made the actual**: 22 clean laps of 78 run (laps 12–74 of 78) · MEDIUM 14, HARD 6, SOFT 2
- **Dropped before the median**: 43 dirty-air, 18 perturbed, 14 invalid
- **What the filter did**: kept 28% of his laps (field 56%). Model measured +0.303%; over EVERY racing lap he is +0.481%. Scoring him on all laps would move the miss +0.496% → **+0.674%** (GROWS by 36%).
- **SCREEN** · THIN SLICE  only 28% of his laps survived against a field 56%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · PACE STEP  +2.14% at lap 39 (slower afterwards; bigger than 97% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-07 13:28:19  CAR 43 (COL) TIME 1:18.809 DELETED - TRACK LIMITS AT TURN 10 LAP 15 15:22:49`
    - `2026-06-07 13:55:40  INCIDENT INVOLVING CAR 43 (COL) NOTED - SPEEDING IN THE PIT LANE (15:49:40)`
    - `2026-06-07 13:56:29  FIA STEWARDS: INCIDENT INVOLVING CAR 43 (COL) UNDER INVESTIGATION - SPEEDING IN THE PIT LANE (15:49:40)`
    - `2026-06-07 13:57:47  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 43 (COL) - SPEEDING IN THE PIT LANE (15:49:40)`
    - `2026-06-07 15:18:09  CAR 43 (COL) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 65 16:31:10 (PIT)`
    - `2026-06-07 15:21:30  TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) NOTED - CAUSING A COLLISION (17:17:33)`
    - `2026-06-07 15:22:02  FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) UNDER INVESTIGATION - CAUSING A COLLISION (17:17:33)`
    - `2026-06-07 15:28:29  FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) NO FURTHER ACTION - CAUSING A COLLISION (17:17:33)`
- *(10 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 41: procedural — SPEEDING IN THE PIT LANE → penalty: 5 second time penalty
- **Incident** lap 74: contact — CAUSING A COLLISION vs SAI → no action
- **Pit stops** (5): lap 35 (3.6s stationary); lap 59; lap 65; lap 67; lap 68  ·  *4 not in pitstops.parquet*

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted +0.470 → actual +1.009 · **miss +0.540%** (1.2 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 44 clean long-run laps (field median 49) · sessions run: Practice_1 34, Practice_2 37, Practice_3 24
- **What made the actual**: 19 clean laps of 78 run (laps 18–78 of 78) · MEDIUM 14, SOFT 5
- **Dropped before the median**: 46 dirty-air, 16 perturbed, 12 invalid
- **What the filter did**: kept 24% of his laps (field 56%). Model measured +0.721%; over EVERY racing lap he is +0.094%. Scoring him on all laps would move the miss +0.540% → **-0.087%** (shrinks by 84%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to -0.087%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Race control** (race):
    - `2026-06-07 13:28:24  CAR 41 (LIN) TIME 1:19.406 DELETED - TRACK LIMITS AT TURN 10 LAP 17 15:25:29`
    - `2026-06-07 13:48:43  CAR 41 (LIN) TIME 1:20.074 DELETED - TRACK LIMITS AT TURN 10 LAP 33 15:46:33`
    - `2026-06-07 15:23:57  CAR 41 (LIN) TIME 1:18.393 DELETED - TRACK LIMITS AT TURN 10 LAP 73 17:20:22`
- *(7 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (4): lap 59; lap 65; lap 67; lap 68 (11.8s stationary)  ·  *3 not in pitstops.parquet*
- **Radio** 15:33:31: "Well, congratulations everyone. Unbelievable result. Amazing work. Yeah, thank you to everyone. Thank you to everyone on the track and fans for thinking as well. Amazing results on the team. Congratulations. Well done ma"

  > category: ______   note: ______

#### HAD · Red Bull Racing

predicted -1.126 → actual -0.393 · **miss +0.733%** (1.4 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 36 clean long-run laps (field median 49) · sessions run: Practice_1 14, Practice_2 24, Practice_3 25
- **What made the actual**: 57 clean laps of 78 run (laps 3–78 of 78) · MEDIUM 26, HARD 25, SOFT 6
- **Dropped before the median**: 8 dirty-air, 17 perturbed, 11 invalid
- **What the filter did**: kept 73% of his laps (field 56%). Model measured -0.678%; over EVERY racing lap he is -1.508%. Scoring him on all laps would move the miss +0.733% → **-0.096%** (shrinks by 87%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to -0.096%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Race control** (race):
    - `2026-06-07 13:42:45  CAR 6 (HAD) TIME 1:19.074 DELETED - TRACK LIMITS AT TURN 10 LAP 27 15:38:06`
    - `2026-06-07 14:46:56  INCIDENT INVOLVING CAR 6 (HAD) NOTED - SAFETY CAR INFRINGEMENT`
    - `2026-06-07 14:47:03  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT`
    - `2026-06-07 14:54:39  FIA STEWARDS: UPDATE: INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - SAFETY CAR INFRINGEMENT (16:33:48)`
    - `2026-06-07 15:19:35  INCIDENT INVOLVING CAR 6 (HAD) NOTED - RED FLAG INFRINGEMENT`
    - `2026-06-07 15:19:53  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) NO FURTHER ACTION - SAFETY CAR INFRINGEMENT (16:33:48)`
    - `2026-06-07 15:20:11  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) WILL BE INVESTIGATED AFTER THE RACE - RED FLAG INFRINGEMENT`
- *(4 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 68: procedural — SAFETY CAR INFRINGEMENT → no action
- **Incident** lap 68: procedural — SAFETY CAR INFRINGEMENT → investigated
- **Incident** lap 73: procedural — RED FLAG INFRINGEMENT → investigated after race
- **Pit stops** (4): lap 32 (3.1s stationary); lap 60; lap 66; lap 68  ·  *3 not in pitstops.parquet*
- **Radio** 13:23:02: "Lap up, please, winging."
- **Radio** 13:29:08: "Board six, board six, we're looking into it mate, I'm looking into it, also the power is gone, the power."
- **Radio** 13:37:44: "Yeah, no power, alternate, alternate. Yeah, copy that mate, we can see the issue, we're trying to work on the fix, you're doing a great job. Engine 3, position 11. Engine 3, position 11."
- **Radio** 13:48:24: "The problem is still there. Yeah we're still looking for another fix, we are looking for another fix."
- **Radio** 15:14:12: "Yeah, keep pushing, keep pushing, it's coming back"

  > category: ______   note: ______

#### ALB · Williams

predicted +0.706 → actual +1.479 · **miss +0.773%** (1.5 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 62 clean long-run laps (field median 49) · sessions run: Practice_1 33, Practice_2 39, Practice_3 24
- **What made the actual**: 31 clean laps of 78 run (laps 22–78 of 78) · MEDIUM 19, SOFT 12
- **Dropped before the median**: 35 dirty-air, 20 perturbed, 13 invalid
- **What the filter did**: kept 40% of his laps (field 56%). Model measured +1.191%; over EVERY racing lap he is +0.000%. Scoring him on all laps would move the miss +0.773% → **-0.418%** (shrinks by 46%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to -0.418%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Race control** (race):
    - `2026-06-07 13:22:09  CAR 23 (ALB) TIME 1:18.836 DELETED - TRACK LIMITS AT TURN 10 LAP 14 15:21:23`
    - `2026-06-07 14:06:09  CAR 23 (ALB) TIME 1:22.221 DELETED - TRACK LIMITS AT TURN 10 LAP 46 16:04:13`
    - `2026-06-07 14:06:56  TURN 10 INCIDENT INVOLVING CAR 23 (ALB) NOTED - LEAVING THE TRACK AND GAINING AN ADVANTAGE (16:04:12)`
    - `2026-06-07 14:16:19  FIA STEWARDS: TURN 10 INCIDENT INVOLVING CAR 23 (ALB) REVIEWED NO FURTHER INVESTIGATION - LEAVING THE TRACK AND GAINING AN ADVANTAGE (16:04:12)`
- *(6 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 50: off-track — LEAVING THE TRACK AND GAINING AN ADVANTAGE → no action
- **Pit stops** (5): lap 43 (3.2s stationary); lap 59; lap 65; lap 67; lap 68  ·  *4 not in pitstops.parquet*
- **Radio** 14:03:09: "Is there a reason for this? Because it might be a concern, what are you trying to do? I mean, I'm happy to do it, but I just, I was just risking something for nothing."
- **Radio** 15:35:57: "Alex, it was a tough afternoon to walk away with, P8 is a good result, well done to you. I know it's tough out there with all the battery issues and the car, I'll look into that, but well done. P8, really good points for"

  > category: ______   note: ______

#### PIA · McLaren

predicted -1.115 → actual +0.037 · **miss +1.152%** (2.4 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 45 clean long-run laps (field median 49) · sessions run: Practice_1 29, Practice_2 31, Practice_3 20
- **What made the actual**: 53 clean laps of 78 run (laps 3–58 of 78) · MEDIUM 45, HARD 8
- **Dropped before the median**: 12 dirty-air, 19 perturbed, 11 invalid
- **What the filter did**: kept 68% of his laps (field 56%). Model measured -0.249%; over EVERY racing lap he is -1.238%. Scoring him on all laps would move the miss +1.152% → **+0.162%** (shrinks by 86%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.162%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · TRUNCATED  last clean lap 58 of 78 — the median covers only the first 74% of the race
- **SCREEN** · COMPOUND SKEW  ran MEDIUM 85%, HARD 15% vs field MEDIUM 52%, HARD 27%, SOFT 21% — worth +0.25% of a lap at this race's measured offsets
- **SCREEN** · PACE STEP  -0.90% at lap 8 (faster afterwards; bigger than 93% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-07 14:13:06  INCIDENT INVOLVING CAR 81 (PIA) NOTED - SPEEDING IN THE PIT LANE (16:06:07)`
    - `2026-06-07 14:13:16  FIA STEWARDS: INCIDENT INVOLVING CAR 81 (PIA) UNDER INVESTIGATION - SPEEDING IN THE PIT LANE (16:06:07)`
    - `2026-06-07 14:13:51  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 81 (PIA) - SPEEDING IN THE PIT LANE (16:06:07)`
    - `2026-06-07 14:26:44  FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 81 (PIA) - SPEEDING IN THE PIT LANE (16:06:07)`
- **Incident** lap 55: procedural — SPEEDING IN THE PIT LANE → penalty: 5 second time penalty
- **Pit stops** (5): lap 48; lap 59; lap 60; lap 66; lap 68 (67.2s stationary)  ·  *4 not in pitstops.parquet*
- **Radio** 15:10:39: "Oscar, the FIA have said unlikely to do the standing restart, could be some laps behind the safety car. They've said they'll take a dim view of people leaving more than ten car lengths."
- **Radio** 15:35:35: "good afternoon mate that was good good progress from a P7 start yeah yeah well done yeah definitely did make up those three spots on pace but uh we stuck in a little minute too and well done yeah i heard what you said we"

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.