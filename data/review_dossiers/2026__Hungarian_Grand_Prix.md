# WHY THE MODEL MISSED — evidence dossier
2026 R11 · Hungarian Grand Prix · dossier built 2026-08-08

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
Practice_1   air 23.3C  track 42.7C (range 38-47)
Practice_2   air 23.6C  track 30.3C (range 28-34)
Practice_3   air 24.9C  track 52.1C (range 49-54)
Qualifying   air 26.8C  track 46.4C (range 42-50)
Race         air 30.8C  track 50.5C (range 44-53)
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MISSING  -0.583 s/lap   (-0.69% of a lap)
  SOFT     -0.030 s/lap   (-0.04% of a lap)
  MEDIUM   -0.018 s/lap   (-0.02% of a lap)
  HARD     +0.077 s/lap   (+0.09% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 55% of each driver's laps (range 23–82%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  no safety car, VSC or red flag
```

## 2 · Per-driver evidence

### QUALIFYING

#### NOR · McLaren

predicted -0.586 → actual -1.741 · **miss -1.155%** (2.8 sd) · FASTER than predicted

- **Teammate**: PIA missed -0.674% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Practice_2 30, Practice_3 20
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (77.207s)  [Q1 78.277  Q2 77.456  Q3 77.207]

  > category: ______   note: ______

#### ALO · Aston Martin

predicted +2.293 → actual +1.197 · **miss -1.097%** (2.1 sd) · FASTER than predicted

- **Teammate**: STR missed -0.814% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 20, Practice_2 24, Practice_3 17
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q2 (79.808s)  [Q1 80.126  Q2 79.808]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### STR · Aston Martin

predicted +2.685 → actual +1.871 · **miss -0.814%** (1.6 sd) · FASTER than predicted

- **Teammate**: ALO missed -1.097% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 11, Practice_3 20
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% shift, 42% of this -0.814% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (80.659s)  [Q1 80.659]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### PIA · McLaren

predicted -0.464 → actual -1.138 · **miss -0.674%** (1.6 sd) · FASTER than predicted

- **Teammate**: NOR missed -1.155% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_2 28, Practice_3 22
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (77.684s)  [Q1 78.891  Q2 77.928  Q3 77.684]
- **Race control** (qualifying):
    - `2026-07-25 15:01:33  CAR 81 (PIA) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 16 16:59:52 (PIT)`
    - `2026-07-25 15:04:00  TURN 1 INCIDENT INVOLVING CARS 44 (HAM) AND 81 (PIA) NOTED - IMPEDING (16:59:46)`
    - `2026-07-25 15:05:52  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 44 (HAM) AND 81 (PIA) WILL BE INVESTIGATED AFTER THE SESSION - IMPEDING (16:59:46)`

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.071 → actual -1.726 · **miss -0.655%** (1.8 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 23, Practice_2 26, Practice_3 22
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (77.219s)  [Q1 78.730  Q2 77.803  Q3 77.219]
- **Race control** (qualifying):
    - `2026-07-25 15:04:00  TURN 1 INCIDENT INVOLVING CARS 44 (HAM) AND 81 (PIA) NOTED - IMPEDING (16:59:46)`
    - `2026-07-25 15:05:52  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 44 (HAM) AND 81 (PIA) WILL BE INVESTIGATED AFTER THE SESSION - IMPEDING (16:59:46)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### ANT · Mercedes

predicted -0.802 → actual -1.395 · **miss -0.593%** (1.7 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_2 30, Practice_3 16
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  8 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (77.479s)  [Q1 78.726  Q2 78.393  Q3 77.479]
- **SCREEN** · deleted lap 78.554s, slower than its counted 77.479s — no effect on the number
- **SCREEN** · deleted lap 78.178s, slower than its counted 77.479s — no effect on the number
- **Race control** (qualifying):
    - `2026-07-25 14:19:12  CAR 12 (ANT) TIME 1:18.554 DELETED - TRACK LIMITS AT TURN 14 LAP 7 16:16:02`
    - `2026-07-25 14:19:15  CAR 12 (ANT) LAP DELETED - TRACK LIMITS AT TURN 14 (NEXT LAP PIT)`
    - `2026-07-25 14:37:35  CAR 12 (ANT) TIME 1:18.178 DELETED - TRACK LIMITS AT TURN 7 LAP 11 16:30:53`
    - `2026-07-25 15:05:46  INCIDENT INVOLVING CAR 12 (ANT) NOTED - YELLOW FLAG INFRINGEMENT (16:59:52)`
    - `2026-07-25 15:06:15  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 12 (ANT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-07-25 15:06:30  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 12 (ANT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-07-25 15:09:10  FIA STEWARDS: INCIDENT INVOLVING CAR 12 (ANT) WILL BE INVESTIGATED AFTER THE SESSION - YELLOW FLAG INFRINGEMENT (16:59:52)`

  > category: ______   note: ______

#### HUL · Audi

predicted +0.054 → actual -0.484 · **miss -0.538%** (1.5 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 29, Practice_2 30, Practice_3 24
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q2 (78.639s)  [Q1 78.796  Q2 78.639  Q3 78.686]
- **SCREEN** · WENT SLOWER  its later segment was worse than Q2 — the counted lap is not its last attempt

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.593 → actual +1.051 · **miss +0.458%** (1.2 sd) · SLOWER than predicted

- **Teammate**: BEA missed +0.921% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 24, Practice_2 26, Practice_3 18
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q2 (79.734s)  [Q1 80.010  Q2 79.734]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### ALB · Williams

predicted +1.239 → actual +1.870 · **miss +0.630%** (2.2 sd) · SLOWER than predicted

- **Teammate**: SAI missed +0.730% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Practice_2 33, Practice_3 13
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% shift, 27% of this +0.630% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (80.658s)  [Q1 80.658]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### SAI · Williams

predicted +1.093 → actual +1.823 · **miss +0.730%** (2.6 sd) · SLOWER than predicted

- **Teammate**: ALB missed +0.630% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 23, Practice_2 31, Practice_3 17
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% shift, 23% of this +0.730% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (80.621s)  [Q1 80.621]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 83.576s, slower than its counted 80.621s — no effect on the number
- **Race control** (qualifying):
    - `2026-07-25 14:03:20  CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17`

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted -1.467 → actual -0.589 · **miss +0.878%** (2.1 sd) · SLOWER than predicted

- **Teammate**: LAW missed +1.384% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Practice_2 29, Practice_3 6
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (78.281s)  [Q1 79.233  Q2 78.360  Q3 78.281]

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.789 → actual +2.709 · **miss +0.920%** (1.8 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 28
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% shift, 18% of this +0.920% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (81.322s)  [Q1 81.322]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.411 → actual +1.332 · **miss +0.921%** (2.5 sd) · SLOWER than predicted

- **Teammate**: OCO missed +0.458% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_2 28, Practice_3 14
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% shift, 37% of this +0.921% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (80.233s)  [Q1 80.233]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### LAW · Racing Bulls

predicted -1.459 → actual -0.075 · **miss +1.384%** (3.3 sd) · SLOWER than predicted

- **Teammate**: LIN missed +0.878% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Practice_2 29, Practice_3 23
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q2 (78.765s)  [Q1 79.161  Q2 78.765]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### STR · Aston Martin

predicted +2.279 → actual +0.521 · **miss -1.758%** (2.2 sd) · FASTER than predicted

- **Teammate**: ALO missed -1.499% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 10 clean long-run laps (field median 25) · sessions run: Practice_1 11, Practice_3 20
- **SCREEN** · THIN READ  the model had 10 laps of this type against a field median of 25 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **What made the actual**: 44 clean laps of 69 run (laps 10–69 of 70) · SOFT 24, MEDIUM 20
- **Dropped before the median**: 19 dirty-air, 10 perturbed, 4 invalid
- **What the filter did**: kept 64% of his laps (field 55%). Model measured +0.212%; over EVERY racing lap he is +0.325% — a shift of **+0.113%**, 6% the size of the miss being explained.
- **SCREEN** · PACE STEP  +1.41% at lap 64 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:08:15  CAR 18 (STR) LAP DELETED - TRACK LIMITS AT TURN 14 LAP 1 15:04:56`
    - `2026-07-26 14:13:56  INCIDENT INVOLVING CAR 18 (STR) NOTED - YELLOW FLAG INFRINGEMENT (15:58:36)`
    - `2026-07-26 14:22:29  FIA STEWARDS: INCIDENT INVOLVING CAR 18 (STR) REVIEWED NO FURTHER INVESTIGATION - YELLOW FLAG INFRINGEMENT (15:58:36)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 50: procedural — YELLOW FLAG INFRINGEMENT → no action
- **Pit stops** (2): lap 8 (2.1s stationary); lap 37  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### ALO · Aston Martin

predicted +2.161 → actual +0.662 · **miss -1.499%** (1.9 sd) · FASTER than predicted

- **Teammate**: STR missed -1.758% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 25 clean long-run laps (field median 25) · sessions run: Practice_1 20, Practice_2 24, Practice_3 17
- **What made the actual**: 38 clean laps of 69 run (laps 17–69 of 70) · SOFT 26, MEDIUM 12
- **Dropped before the median**: 25 dirty-air, 8 perturbed, 5 invalid
- **What the filter did**: kept 55% of his laps (field 55%). Model measured +0.353%; over EVERY racing lap he is +0.382% — a shift of **+0.029%**, 2% the size of the miss being explained.
- **SCREEN** · PACE STEP  -1.36% at lap 37 (faster afterwards; bigger than 93% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:07:39  TURN 3 INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:03:49)`
    - `2026-07-26 13:08:24  FIA STEWARDS: TURN 3 INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:03:49)`
    - `2026-07-26 13:43:08  CAR 14 (ALO) TIME 1:29.776 DELETED - TRACK LIMITS AT TURN 13 LAP 26 15:41:25`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs BEA → no action
- **Pit stops** (2): lap 34; lap 55  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### PIA · McLaren

predicted -0.660 → actual -1.695 · **miss -1.035%** (1.7 sd) · FASTER than predicted

- **Teammate**: NOR missed -0.927% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 20 clean long-run laps (field median 25) · sessions run: Practice_2 28, Practice_3 22
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 46 clean laps of 56 run (laps 1–55 of 70) · HARD 31, MEDIUM 15
- **Dropped before the median**: 5 dirty-air, 9 perturbed, 5 invalid
- **What the filter did**: kept 82% of his laps (field 55%). Model measured -2.004%; over EVERY racing lap he is -2.008% — a shift of **-0.003%**, 0% the size of the miss being explained.
- **SCREEN** · TRUNCATED  last clean lap 55 of 70 — the median covers only the first 79% of the race
- **SCREEN** · PACE STEP  +1.25% at lap 48 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:58:52  TURN 2 INCIDENT INVOLVING CARS 55 (SAI) AND 81 (PIA) NOTED - CAUSING A COLLISION (15:57:04)`
    - `2026-07-26 14:00:09  FIA STEWARDS: TURN 2 INCIDENT INVOLVING CARS 55 (SAI) AND 81 (PIA) UNDER INVESTIGATION - CAUSING A COLLISION (15:57:04)`
- **Incident** lap 39: contact — CAUSING A COLLISION vs SAI → investigated
- **Pit stops** (2): lap 16; lap 33  ·  *2 not in pitstops.parquet*
- **Radio** 13:18:13: "How's the title? Currently we are thinking plan A target lap. I feel good."
- **Radio** 13:40:02: "We're aiming at plan A target lap, how's the time? Oh yeah it doesn't feel great."
- **Radio** 13:58:21: "Hey, don't do this. Don't do this."
- **Radio** 13:58:51: "get out of the radio idiots oh my god"
- **Radio** 14:01:55: "off to that site that's cost us that, target is to get to the end on this tyre."

  > category: ______   note: ______

#### NOR · McLaren

predicted -0.917 → actual -1.843 · **miss -0.927%** (1.5 sd) · FASTER than predicted

- **Teammate**: PIA missed -1.035% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 34 clean long-run laps (field median 25) · sessions run: Practice_1 26, Practice_2 30, Practice_3 20
- **What made the actual**: 30 clean laps of 70 run (laps 16–70 of 70) · HARD 17, SOFT 12, MEDIUM 1
- **Dropped before the median**: 33 dirty-air, 8 perturbed, 8 invalid
- **What the filter did**: kept 43% of his laps (field 55%). Model measured -2.152%; over EVERY racing lap he is -2.228% — a shift of **-0.076%**, 8% the size of the miss being explained.
- **SCREEN** · FILTER ARTIFACT  the clean-air filter moves this driver by -0.076% against a -0.927% miss. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Race control** (race):
    - `2026-07-26 13:45:09  CAR 1 (NOR) TIME 1:26.546 DELETED - TRACK LIMITS AT TURN 4 LAP 29 15:44:06`
    - `2026-07-26 14:30:45  CAR 1 (NOR) TIME 1:23.616 DELETED - TRACK LIMITS AT TURN 9 LAP 60 16:28:54`
- **Pit stops** (3): lap 17; lap 39; lap 56  ·  *3 not in pitstops.parquet*
- **Radio** 13:17:11: "How's the tyres, how's the pop? 30, yeah, really. Much faster, but it gets you."
- **Radio** 13:45:38: "OK mate, let's get back to the rhythm, know what you've been trying to do, can we see it? Back to the rhythm please."
- **Radio** 13:49:13: "Hamilton is currently stuck behind the jar."
- **Radio** 13:50:13: "You mean you won't let me, I'm miles faster."
- **Radio** 13:50:43: "Delta-L to 10-6, traffic, dirt, softs."
- **Radio** 14:04:27: "We're catching Antonelli 90 quickly, that's just been measured when we get there."
- **Radio** 14:20:14: "Lando, you're clearly the fastest car, so the snaps of four and eight, no more."
- **Radio** 14:38:32: "No exit curve. That may be what happened to Oscar's car."
- **Radio** 14:44:38: "what about what a beautiful car was unbelievable today well done guys incredible flying thank you so much for the car nice to finally be able to do it all for you again so it's like it's been a while so congrats very wel"
- **Radio** 14:46:18: "I only did it for him, thanks Bonzi for everything, beautiful career, I did it on a high, thank you very much for everything."

  > category: ______   note: ______

#### HAD · Red Bull Racing

predicted -0.335 → actual -0.920 · **miss -0.585%** (1.0 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 25 clean long-run laps (field median 25) · sessions run: Practice_1 25, Practice_2 20, Practice_3 17
- **What made the actual**: 55 clean laps of 70 run (laps 6–70 of 70) · HARD 42, MEDIUM 13
- **Dropped before the median**: 8 dirty-air, 9 perturbed, 4 invalid
- **What the filter did**: kept 79% of his laps (field 55%). Model measured -1.229%; over EVERY racing lap he is -1.282% — a shift of **-0.053%**, 9% the size of the miss being explained.
- **Pit stops** (2): lap 19 (2.6s stationary); lap 42  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.760 → actual -1.036 · **miss +0.724%** (1.7 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 29 clean long-run laps (field median 25) · sessions run: Practice_1 21, Practice_2 30, Practice_3 18
- **What made the actual**: 45 clean laps of 70 run (laps 12–70 of 70) · HARD 36, MEDIUM 9
- **Dropped before the median**: 19 dirty-air, 8 perturbed, 5 invalid
- **What the filter did**: kept 64% of his laps (field 55%). Model measured -1.345%; over EVERY racing lap he is -1.079% — a shift of **+0.266%**, 37% the size of the miss being explained.
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 27 (3.9s stationary); lap 54  ·  *1 not in pitstops.parquet*
- **Radio** 13:05:31: "Would I untie again or not?"
- **Radio** 13:05:31: "2% shallow, throttle penalty backed off, high RPM."

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.570 → actual +1.310 · **miss +0.740%** (1.3 sd) · SLOWER than predicted

- **Teammate**: BEA missed +1.290% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 32 clean long-run laps (field median 25) · sessions run: Practice_1 24, Practice_2 26, Practice_3 18
- **What made the actual**: 39 clean laps of 68 run (laps 8–68 of 70) · HARD 31, MEDIUM 8
- **Dropped before the median**: 21 dirty-air, 11 perturbed, 4 invalid
- **What the filter did**: kept 57% of his laps (field 55%). Model measured +1.001%; over EVERY racing lap he is +0.953% — a shift of **-0.048%**, 6% the size of the miss being explained.
- **SCREEN** · PACE STEP  +1.00% at lap 58 (slower afterwards; bigger than 92% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:07:56  CAR 31 (OCO) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 1 15:03:36`
- **Pit stops** (2): lap 17 (3.1s stationary); lap 35  ·  *1 not in pitstops.parquet*
- **Radio** 14:46:18: "Thank you, Laura. Yeah, positive weekend. It's a lot of good stuff. Even if the race was very difficult, not as good as we would have liked, it's take the positive for you guys and we'll come back stronger after the brea"

  > category: ______   note: ______

#### ALB · Williams

predicted +0.707 → actual +1.827 · **miss +1.120%** (2.1 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 30 clean long-run laps (field median 25) · sessions run: Practice_1 28, Practice_2 33, Practice_3 13
- **What made the actual**: 35 clean laps of 68 run (laps 8–53 of 70) · HARD 20, MEDIUM 15
- **Dropped before the median**: 23 dirty-air, 12 perturbed, 7 invalid
- **What the filter did**: kept 51% of his laps (field 55%). Model measured +1.518%; over EVERY racing lap he is +1.680% — a shift of **+0.162%**, 14% the size of the miss being explained.
- **SCREEN** · TRUNCATED  last clean lap 53 of 70 — the median covers only the first 76% of the race
- **SCREEN** · PACE STEP  +1.42% at lap 18 (slower afterwards; bigger than 99% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:21:51  CAR 23 (ALB) TIME 1:31.197 DELETED - TRACK LIMITS AT TURN 4 LAP 12 15:20:18`
    - `2026-07-26 13:30:57  CAR 23 (ALB) TIME 1:28.500 DELETED - TRACK LIMITS AT TURN 7 LAP 15 15:24:59`
    - `2026-07-26 13:33:18  CAR 23 (ALB) TIME 1:28.309 DELETED - TRACK LIMITS AT TURN 7 LAP 16 15:26:28`
- **Pit stops** (2): lap 26 (2.8s stationary); lap 54  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.364 → actual +1.654 · **miss +1.290%** (2.3 sd) · SLOWER than predicted

- **Teammate**: OCO missed +0.740% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 20 clean long-run laps (field median 25) · sessions run: Practice_2 28, Practice_3 14
- **What made the actual**: 33 clean laps of 68 run (laps 7–68 of 70) · HARD 21, MEDIUM 12
- **Dropped before the median**: 29 dirty-air, 11 perturbed, 5 invalid
- **What the filter did**: kept 49% of his laps (field 55%). Model measured +1.345%; over EVERY racing lap he is +1.239% — a shift of **-0.106%**, 8% the size of the miss being explained.
- **SCREEN** · PACE STEP  +2.52% at lap 59 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-26 13:07:39  TURN 3 INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:03:49)`
    - `2026-07-26 13:08:24  FIA STEWARDS: TURN 3 INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:03:49)`
    - `2026-07-26 14:00:02  CAR 87 (BEA) TIME 1:36.300 DELETED - TRACK LIMITS AT TURN 2 LAP 38 15:58:36`
    - `2026-07-26 14:09:19  INCIDENT INVOLVING CAR 87 (BEA) NOTED - IGNORING BLUE FLAGS (16:01:22)`
    - `2026-07-26 14:25:11  FIA STEWARDS: INCIDENT INVOLVING CAR 87 (BEA) UNDER INVESTIGATION - IGNORING BLUE FLAGS (16:01:22)`
    - `2026-07-26 14:25:36  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 87 (BEA) - IGNORING BLUE FLAGS (16:01:22)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs ALO → no action
- **Incident** lap 47: procedural — IGNORING BLUE FLAGS → penalty: 5 second time penalty
- **Pit stops** (2): lap 22 (3.2s stationary); lap 42  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.