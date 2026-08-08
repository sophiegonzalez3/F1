# WHY THE MODEL MISSED — evidence dossier
2026 R5 · Canadian Grand Prix · dossier built 2026-08-08

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
Practice_1   air 16.6C  track 39.7C (range 36-42)  all on slicks
Practice_2   —
Practice_3   —
Sprint_Qualifying air 20.0C  track 41.4C (range 40-42)  all on slicks
Sprint_Shootout —
Sprint       air 20.0C  track 31.7C (range 29-33)  all on slicks
Qualifying   air 21.3C  track 30.9C (range 30-32)  all on slicks  rain flag: isolated sample
Race         air 12.8C  track 17.8C (range 16-19)  INTERMEDIATE 1% of laps
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MEDIUM   -0.054 s/lap   (-0.07% of a lap)
  HARD     +0.033 s/lap   (+0.04% of a lap)
  SOFT     +0.057 s/lap   (+0.08% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 50% of each driver's laps (range 17–64%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-05-24 20:12:54  INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NOTED - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE
  2026-05-24 20:13:25  INCIDENT INVOLVING CARS 30 (LAW) AND 27 (HUL) NOTED - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE
  2026-05-24 20:21:54  FIA STEWARDS: INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NO FURTHER ACTION - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE
  2026-05-24 20:33:06  FIA STEWARDS: INCIDENT INVOLVING CARS 30 (LAW) AND 27 (HUL) UNDER INVESTIGATION - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE
  2026-05-24 20:42:13  FIA STEWARDS: INCIDENT INVOLVING CARS 30 (LAW) AND 27 (HUL) WILL BE INVESTIGATED AFTER THE RACE - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE
```

## 2 · Per-driver evidence

### QUALIFYING

#### HAD · Red Bull Racing

predicted -0.175 → actual -1.177 · **miss -1.002%** (2.0 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 7 clean quali-sim laps (field median 2) · sessions run: Practice_1 29, Sprint 20, Sprint Qualifying 17
- **SCREEN** · ATTEMPTS  12 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q3 (72.935s)  [Q1 73.654  Q2 72.975  Q3 72.935]
- **Race control** (qualifying):
    - `2026-05-23 20:21:39  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:42:45  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:43:53  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:34  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:41  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### PER · Cadillac

predicted +2.315 → actual +1.488 · **miss -0.828%** (1.3 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 2) · sessions run: Practice_1 28, Sprint 23, Sprint Qualifying 8
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  7 flying laps against a field median of 14
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 7 vs 14 predicts a +1.10% penalty, moving the miss -0.828% → -1.933% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (75.429s)  [Q1 75.429]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-05-23 20:05:59  TURN 13 INCIDENT INVOLVING CARS 11 (PER) AND 14 (ALO) NOTED (16:03:41)`
    - `2026-05-23 20:11:16  UPDATE: TURN 13 INCIDENT INVOLVING CAR 11 (PER) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS (16:03:41)`
    - `2026-05-23 20:11:36  FIA STEWARDS: TURN 13 INCIDENT INVOLVING CAR 11 (PER) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS (16:03:41)`
    - `2026-05-23 20:21:39  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:34  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### COL · Alpine

predicted +0.841 → actual +0.017 · **miss -0.824%** (1.8 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 0 clean quali-sim laps (field median 2) · sessions run: Practice_1 1, Sprint 23, Sprint Qualifying 16
- **SCREEN** · THIN READ  the model had 0 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  15 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q3 (73.697s)  [Q1 74.466  Q2 73.857  Q3 73.697]
- **Race control** (qualifying):
    - `2026-05-23 20:21:39  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:42:45  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:43:53  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:16  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:34  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:41  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:03:19  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:06:07  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### SAI · Williams

predicted +0.351 → actual -0.063 · **miss -0.414%** (1.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 2) · sessions run: Practice_1 36, Sprint 23, Sprint Qualifying 24
- **SCREEN** · ATTEMPTS  12 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q2 (74.273s)  [Q1 74.276  Q2 74.273]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### LEC · Ferrari

predicted -1.038 → actual -0.670 · **miss +0.368%** (1.3 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 2) · sessions run: Practice_1 36, Sprint 23, Sprint Qualifying 19
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  19 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q3 (72.976s)  [Q1 73.825  Q2 73.496  Q3 72.976]
- **SCREEN** · deleted lap 76.346s, slower than its counted 72.976s — no effect on the number
- **Race control** (qualifying):
    - `2026-05-23 20:07:24  CAR 16 (LEC) TIME 1:16.346 DELETED - TRACK LIMITS AT TURN 14 LAP 4 16:06:29`

  > category: ______   note: ______

#### BOR · Audi

predicted -0.141 → actual +0.307 · **miss +0.448%** (1.0 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 33, Sprint 23, Sprint Qualifying 14
- **SCREEN** · ATTEMPTS  14 flying laps against a field median of 14
- **SCREEN** · BEST LAP from Q2 (74.071s)  [Q1 74.775  Q2 74.071]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 79.122s, slower than its counted 74.071s — no effect on the number
- **Race control** (qualifying):
    - `2026-05-23 20:09:40  CAR 5 (BOR) TIME 1:19.122 DELETED - TRACK LIMITS AT TURN 4 LAP 6 16:08:01`
    - `2026-05-23 20:21:39  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:42:45  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 20:43:53  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:34  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 11 (PER), 5 (BOR), 44 (HAM), 10 (GAS) AND 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-23 21:02:41  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 6 (HAD), 5 (BOR), 41 (LIN), 43 (COL), 10 (GAS) AND 12 (ANT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### STR · Aston Martin

predicted +1.952 → actual +2.518 · **miss +0.566%** (1.5 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 30, Sprint 22, Sprint Qualifying 9
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 14
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 6 vs 14 predicts a +1.28% penalty, moving the miss +0.566% → -0.709% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (76.195s)  [Q1 76.195]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-05-23 20:03:02  INCIDENT INVOLVING CAR 18 (STR) NOTED - UNSAFE CONDITION`
    - `2026-05-23 20:06:55  FIA STEWARDS: INCIDENT INVOLVING CAR 18 (STR) WILL BE INVESTIGATED AFTER THE SESSION - UNSAFE CONDITION`
    - `2026-05-23 20:20:39  TURN 5 INCIDENT INVOLVING CARS 18 (STR) AND 27 (HUL) NOTED - IMPEDING (16:17:48)`
    - `2026-05-23 20:20:50  CAR 18 (STR) LAP DELETED - TRACK LIMITS AT TURN 4 LAP 11 16:17:39 (PIT)`
    - `2026-05-23 20:28:48  FIA STEWARDS: TURN 5 INCIDENT INVOLVING CARS 18 (STR) AND 27 (HUL) WILL BE INVESTIGATED AFTER THE SESSION - IMPEDING (16:17:48)`

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.134 → actual +0.702 · **miss +0.568%** (1.2 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 32, Sprint 23, Sprint Qualifying 17
- **SCREEN** · ATTEMPTS  8 flying laps against a field median of 14
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 8 vs 14 predicts a +0.94% penalty, moving the miss +0.568% → -0.367%, cutting it by 35% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (74.845s)  [Q1 74.845]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### HAD · Red Bull Racing

predicted -0.265 → actual -1.427 · **miss -1.162%** (2.5 sd) · FASTER than predicted

- **Teammate**: VER missed -0.489% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 29 clean long-run laps (field median 40) · sessions run: Practice_1 29, Sprint 20, Sprint Qualifying 17
- **What made the actual**: 24 clean laps of 67 run (laps 6–65 of 68) · SOFT 16, MEDIUM 8
- **Dropped before the median**: 28 dirty-air, 25 perturbed, 7 invalid
- **What the filter did**: kept 36% of his laps (field 50%). Model measured -1.550%; over EVERY racing lap he is -1.345%. Scoring him on all laps would move the miss -1.162% → **-0.957%** (shrinks by 18%).
- **SCREEN** · THIN SLICE  only 36% of his laps survived against a field 50%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **Race control** (race):
    - `2026-05-24 20:16:33  CAR 6 (HAD) TIME 1:18.960 DELETED - TRACK LIMITS AT TURN 14 LAP 4 16:15:12`
    - `2026-05-24 20:56:18  INCIDENT INVOLVING CAR 6 (HAD) NOTED - YELLOW FLAG INFRINGEMENT (16:47:57)`
    - `2026-05-24 20:59:36  TURN 13 INCIDENT INVOLVING CAR 6 (HAD) NOTED - MORE THAN ONE CHANGE OF DIRECTION`
    - `2026-05-24 21:05:33  FIA STEWARDS: TURN 13 INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - MORE THAN ONE CHANGE OF DIRECTION (16:54:33)`
    - `2026-05-24 21:06:47  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 6 (HAD) - MORE THAN ONE CHANGE OF DIRECTION`
    - `2026-05-24 21:16:32  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) UNDER INVESTIGATION - YELLOW FLAG INFRINGEMENT (16:47:57)`
    - `2026-05-24 21:23:49  FIA STEWARDS: INCIDENT INVOLVING CAR 6 (HAD) WILL BE INVESTIGATED AFTER THE RACE - YELLOW FLAG INFRINGEMENT (16:47:57)`
    - `2026-05-24 21:24:52  FIA STEWARDS: PENALTY SERVED - 10 SECOND TIME PENALTY FOR CAR 6 (HAD) - MORE THAN ONE CHANGE OF DIRECTION`
    - `2026-05-24 21:30:03  FIA STEWARDS: STOP-AND-GO PENALTY FOR CAR 6 (HAD) - YELLOW FLAG INFRINGEMENT (16:47:57)`
    - `2026-05-24 21:33:10  FIA STEWARDS: PENALTY SERVED - STOP-AND-GO PENALTY FOR CAR 6 (HAD) - YELLOW FLAG INFRINGEMENT (16:47:57)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 36: procedural — YELLOW FLAG INFRINGEMENT → penalty: stop-and-go penalty
- **Incident** lap 39: procedural — MORE THAN ONE CHANGE OF DIRECTION → penalty: 10 second time penalty
- **Incident** lap 43: procedural — MORE THAN ONE CHANGE OF DIRECTION → investigated
- **Pit stops** (3): lap 31; lap 52; lap 62  ·  *3 not in pitstops.parquet*
- **Radio** 19:11:23: "You think it's worth your ready to go to the top? How do you feel the tires? They are still alive, so maybe wait a little bit. And for the moment, they're okay. The only thing can be rear overheating a little bit."

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.967 → actual +0.170 · **miss -0.797%** (1.7 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 38 clean long-run laps (field median 40) · sessions run: Practice_1 26, Sprint 22, Sprint Qualifying 17
- **What made the actual**: 30 clean laps of 67 run (laps 4–64 of 68) · MEDIUM 22, SOFT 8
- **Dropped before the median**: 19 dirty-air, 25 perturbed, 4 invalid
- **What the filter did**: kept 45% of his laps (field 50%). Model measured +0.045%; over EVERY racing lap he is +0.136%. Scoring him on all laps would move the miss -0.797% → **-0.706%** (shrinks by 11%).
- **SCREEN** · PACE STEP  -0.68% at lap 10 (faster afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-24 20:30:46  CAR 87 (BEA) TIME 1:17.509 DELETED - TRACK LIMITS AT TURN 14 LAP 15 16:29:52`
    - `2026-05-24 20:35:00  INCIDENT INVOLVING CAR 87 (BEA) NOTED - YELLOW FLAG INFRINGEMENT (16:26:52)`
    - `2026-05-24 21:01:02  FIA STEWARDS: INCIDENT INVOLVING CAR 87 (BEA) REVIEWED NO FURTHER INVESTIGATION - YELLOW FLAG INFRINGEMENT (16:26:52)`
- *(9 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 20: procedural — YELLOW FLAG INFRINGEMENT → no action
- **Pit stops** (1): lap 30  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.034 → actual -1.687 · **miss -0.653%** (1.9 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 51 clean long-run laps (field median 40) · sessions run: Practice_1 36, Sprint 23, Sprint Qualifying 23
- **What made the actual**: 27 clean laps of 68 run (laps 23–66 of 68) · MEDIUM 21, SOFT 6
- **Dropped before the median**: 30 dirty-air, 24 perturbed, 4 invalid
- **What the filter did**: kept 40% of his laps (field 50%). Model measured -1.810%; over EVERY racing lap he is -1.757%. Scoring him on all laps would move the miss -0.653% → **-0.601%** (shrinks by 8%).
- **SCREEN** · THIN SLICE  only 40% of his laps survived against a field 50%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **Race control** (race):
    - `2026-05-24 20:40:10  CAR 44 (HAM) TIME 1:20.199 DELETED - TRACK LIMITS AT TURN 8 LAP 22 16:37:36`
- **Pit stops** (1): lap 31 (4.3s stationary)
- **Radio** 20:21:31: "I got no power, man. Come on, guys."
- **Radio** 21:06:48: "You have same pace as Antonelli, P1, 2 tenths faster than Max in front."
- **Radio** 21:13:25: "We can do this, guys. Push it."
- **Radio** 21:25:37: "V4 copy."
- **Radio** 21:40:23: "And well done. P2, that was a great fight. Good job, good game. That was tough, guys. Mega job this weekend. Definitely the result we deserve. Thank you so much, for everyone back at the factory. Grazie tutti. Let's keep"

  > category: ______   note: ______

#### VER · Red Bull Racing

predicted -0.927 → actual -1.416 · **miss -0.489%** (1.1 sd) · FASTER than predicted

- **Teammate**: HAD missed -1.162% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 37 clean long-run laps (field median 40) · sessions run: Practice_1 31, Sprint 23, Sprint Qualifying 15
- **What made the actual**: 35 clean laps of 68 run (laps 9–60 of 68) · MEDIUM 21, SOFT 14
- **Dropped before the median**: 15 dirty-air, 22 perturbed, 4 invalid
- **What the filter did**: kept 51% of his laps (field 50%). Model measured -1.539%; over EVERY racing lap he is -1.554%. Scoring him on all laps would move the miss -0.489% → **-0.504%** (GROWS by 3%).
- **Race control** (race):
    - `2026-05-24 20:38:51  CAR 3 (VER) TIME 1:16.180 DELETED - TRACK LIMITS AT TURN 14 LAP 20 16:35:33`
- **Pit stops** (1): lap 31 (2.7s stationary)
- **Radio** 19:22:05: "Copy that, box, switch to slicks."
- **Radio** 21:40:53: "Good job Max, nice to see you fight out there today. Well done. Yeah, it's just a shame we didn't have the tyre advantage for the final stint. Really difficult with the individual approach. That's the first road in."

  > category: ______   note: ______

#### SAI · Williams

predicted +0.394 → actual -0.077 · **miss -0.471%** (1.1 sd) · FASTER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 48 clean long-run laps (field median 40) · sessions run: Practice_1 36, Sprint 23, Sprint Qualifying 24
- **What made the actual**: 43 clean laps of 67 run (laps 4–67 of 68) · MEDIUM 43
- **Dropped before the median**: 2 dirty-air, 21 perturbed, 9 invalid
- **What the filter did**: kept 64% of his laps (field 50%). Model measured -0.202%; over EVERY racing lap he is -0.215%. Scoring him on all laps would move the miss -0.471% → **-0.484%** (GROWS by 3%).
- **SCREEN** · PACE STEP  +0.94% at lap 15 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-24 20:25:33  CAR 55 (SAI) TIME 1:17.454 DELETED - TRACK LIMITS AT TURN 14 LAP 11 16:24:53`
    - `2026-05-24 21:23:57  CAR 55 (SAI) TIME 1:16.764 DELETED - TRACK LIMITS AT TURN 14 LAP 54 17:22:18`
    - `2026-05-24 21:38:41  CAR 55 (SAI) TIME 1:19.410 DELETED - TRACK LIMITS AT TURN 8 LAP 66 17:37:05`
- *(8 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 2 (2.7s stationary); lap 30  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### NOR · McLaren

predicted -1.520 → actual -0.772 · **miss +0.747%** (1.7 sd) · SLOWER than predicted

- **Teammate**: PIA missed +1.003% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 41 clean long-run laps (field median 40) · sessions run: Practice_1 32, Sprint 23, Sprint Qualifying 15
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 12 clean laps of 39 run (laps 1–36 of 68) · MEDIUM 11, INTERMEDIATE 1
- **Dropped before the median**: 18 dirty-air, 16 perturbed, 9 invalid
- **What the filter did**: kept 31% of his laps (field 50%). Model measured -0.896%; over EVERY racing lap he is -0.771%. Scoring him on all laps would move the miss +0.747% → **+0.872%** (GROWS by 17%).
- **SCREEN** · THIN SLICE  only 31% of his laps survived against a field 50%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · THIN SAMPLE  only 12 clean laps entered the median (field median 15+ is normal)
- **SCREEN** · TRUNCATED  last clean lap 36 of 68 — the median covers only the first 53% of the race
- **SCREEN** · PACE STEP  -1.12% at lap 24 (faster afterwards; bigger than 93% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-24 20:15:46  CAR 1 (NOR) TIME 1:21.170 DELETED - TRACK LIMITS AT TURN 4 LAP 4 16:14:33`
    - `2026-05-24 20:34:05  CAR 1 (NOR) TIME 1:23.114 DELETED - TRACK LIMITS AT TURN 10 LAP 16 16:31:10`
    - `2026-05-24 20:38:48  CAR 1 (NOR) TIME 1:18.118 DELETED - TRACK LIMITS AT TURN 14 LAP 18 16:34:05`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 2 (2.2s stationary); lap 15  ·  *1 not in pitstops.parquet*
- **Radio** 19:11:21: "That's all the way, men. That's all the way. You now need to keep it cool, reset."
- **Radio** 19:11:23: "I have a very big reason. If you get a penalty from Monaco, I'm going to win. Okay? So I want you to be back on track even if you are two or three laps down and we go slow. I don't care. I want the penalty today."
- **Radio** 20:03:12: "Any comments on conditions, Lando? Yeah, I don't know. We'll see."
- **Radio** 20:14:54: "although we could be going very long here"
- **Radio** 20:30:11: "We need to box this lap, it's a reliability problem."
- **Radio** 21:02:12: "Something's broken, gearbox or something."
- **Radio** 21:02:43: "Sorry about that. Not our day. All good."

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.094 → actual +2.856 · **miss +0.762%** (1.6 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 40 clean long-run laps (field median 40) · sessions run: Practice_1 28, Sprint 22, Sprint Qualifying 8
- **What made the actual**: 36 clean laps of 64 run (laps 5–64 of 68) · SOFT 19, MEDIUM 17
- **Dropped before the median**: 2 dirty-air, 27 perturbed, 10 invalid
- **What the filter did**: kept 56% of his laps (field 50%). Model measured +2.727%; over EVERY racing lap he is +3.043%. Scoring him on all laps would move the miss +0.762% → **+1.078%** (GROWS by 42%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to +1.078%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **Race control** (race):
    - `2026-05-24 19:32:11  FIA STEWARDS: INCIDENT INVOLVING CARS 5 (BOR), 77 (BOT) AND 10 (GAS) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-24 19:32:16  FIA STEWARDS: INCIDENT INVOLVING CARS 5 (BOR), 77 (BOT) AND 10 (GAS) WILL BE INVESTIGATED AFTER THE RACE - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-24 20:12:54  INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NOTED - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE`
    - `2026-05-24 20:21:54  FIA STEWARDS: INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NO FURTHER ACTION - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE`
    - `2026-05-24 20:37:42  CAR 77 (BOT) TIME 1:21.843 DELETED - TRACK LIMITS AT TURN 10 LAP 17 16:33:34`
    - `2026-05-24 21:09:56  INCIDENT INVOLVING CAR 77 (BOT) NOTED - SPEEDING IN THE PIT LANE`
    - `2026-05-24 21:10:27  FIA STEWARDS: INCIDENT INVOLVING CAR 77 (BOT) UNDER INVESTIGATION - SPEEDING IN THE PIT LANE`
    - `2026-05-24 21:10:56  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 77 (BOT) - SPEEDING IN THE PIT LANE`
    - `2026-05-24 21:25:16  FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 77 (BOT) - SPEEDING IN THE PIT LANE`
- *(32 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: procedural — OUT OF POSITION AT SAFETY CAR LINE vs STR → no action
- **Incident** lap 46: procedural — SPEEDING IN THE PIT LANE → penalty: 5 second time penalty
- **Pit stops** (4): lap 3 (6.4s stationary); lap 9; lap 29; lap 49  ·  *3 not in pitstops.parquet*

  > category: ______   note: ______

#### PIA · McLaren

predicted -1.327 → actual -0.324 · **miss +1.003%** (2.2 sd) · SLOWER than predicted

- **Teammate**: NOR missed +0.747% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 41 clean long-run laps (field median 40) · sessions run: Practice_1 32, Sprint 23, Sprint Qualifying 15
- **What made the actual**: 34 clean laps of 66 run (laps 5–64 of 68) · MEDIUM 28, SOFT 6
- **Dropped before the median**: 8 dirty-air, 24 perturbed, 11 invalid
- **What the filter did**: kept 52% of his laps (field 50%). Model measured -0.448%; over EVERY racing lap he is -0.276%. Scoring him on all laps would move the miss +1.003% → **+1.175%** (GROWS by 17%).
- **SCREEN** · PACE STEP  +0.86% at lap 19 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-24 20:29:58  TURN 10 INCIDENT INVOLVING CARS 81 (PIA) AND 23 (ALB) NOTED - CAUSING A COLLISION (16:25:37)`
    - `2026-05-24 20:37:51  FIA STEWARDS: TURN 10 INCIDENT INVOLVING CARS 81 (PIA) AND 23 (ALB) UNDER INVESTIGATION - CAUSING A COLLISION (16:25:37)`
    - `2026-05-24 20:38:36  FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 81 (PIA) - CAUSING A COLLISION (16:25:37)`
    - `2026-05-24 20:44:44  CAR 81 (PIA) TIME 1:16.666 DELETED - TRACK LIMITS AT TURN 14 LAP 18 16:34:20`
    - `2026-05-24 21:25:10  FIA STEWARDS: PENALTY SERVED - 10 SECOND TIME PENALTY FOR CAR 81 (PIA) - CAUSING A COLLISION (16:25:37)`
    - `2026-05-24 21:28:31  CAR 81 (PIA) TIME 1:16.439 DELETED - TRACK LIMITS AT TURN 2 LAP 58 17:26:53`
    - `2026-05-24 21:36:10  CAR 81 (PIA) TIME 1:16.439 DELETED - TRACK LIMITS AT TURN 1 LAP 58 17:26:52`
    - `2026-05-24 21:38:29  CAR 81 (PIA) TIME 1:16.575 DELETED - TRACK LIMITS AT TURN 14 LAP 65 17:36:50`
- *(14 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 16: contact — CAUSING A COLLISION vs ALB → penalty: 10 second time penalty
- **Pit stops** (3): lap 1 (2.7s stationary); lap 12; lap 51  ·  *2 not in pitstops.parquet*
- **Radio** 19:27:39: "Are you happy on these tyres or do you want the inter? Honestly I have no idea, it's really tough honestly but I'm surprised the inter isn't working."
- **Radio** 20:05:14: "It feels like the rain's stopped quite a lot now, what are we looking to do? Oscar, forecast, the rain should ease from here, everyone's gonna have very cold tires. Yeah, but I think now, I think it is time for slicks, s"
- **Radio** 20:08:48: "So Oscar, our tyres have dropped quite a lot, everyone on soft must have very cold tyres by this time. Yeah, but if we, if we pit now, we will have cold tyres, they will have warm tyres. So, I don't know, it's, I mean, i"

  > category: ______   note: ______

#### STR · Aston Martin

predicted +1.748 → actual +4.052 · **miss +2.303%** (5.3 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 38 clean long-run laps (field median 40) · sessions run: Practice_1 30, Sprint 22, Sprint Qualifying 9
- **What made the actual**: 32 clean laps of 64 run (laps 5–62 of 68) · SOFT 26, MEDIUM 6
- **Dropped before the median**: 6 dirty-air, 25 perturbed, 11 invalid
- **What the filter did**: kept 50% of his laps (field 50%). Model measured +3.921%; over EVERY racing lap he is +4.562%. Scoring him on all laps would move the miss +2.303% → **+2.944%** (GROWS by 28%).
- **Race control** (race):
    - `2026-05-24 20:12:54  INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NOTED - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE`
    - `2026-05-24 20:21:54  FIA STEWARDS: INCIDENT INVOLVING CARS 77 (BOT) AND 18 (STR) NO FURTHER ACTION - STARTING PROCEDURE INFRINGEMENT - OUT OF POSITION AT SAFETY CAR LINE`
    - `2026-05-24 20:23:41  CAR 18 (STR) TIME 1:23.593 DELETED - TRACK LIMITS AT TURN 8 LAP 8 16:20:29`
    - `2026-05-24 20:38:52  CAR 18 (STR) TIME 1:23.042 DELETED - TRACK LIMITS AT TURN 10 LAP 20 16:37:11`
    - `2026-05-24 21:09:01  CAR 18 (STR) TIME 1:21.728 DELETED - TRACK LIMITS AT TURN 2 LAP 42 17:06:40`
    - `2026-05-24 21:39:19  CAR 18 (STR) TIME 1:26.632 DELETED - TRACK LIMITS AT TURN 10 LAP 64 17:37:49`
- *(31 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: procedural — OUT OF POSITION AT SAFETY CAR LINE vs BOT → no action
- **Pit stops** (2): lap 14 (3.2s stationary); lap 49  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.