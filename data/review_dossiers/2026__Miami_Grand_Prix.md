# WHY THE MODEL MISSED — evidence dossier
2026 R4 · Miami Grand Prix · dossier built 2026-08-08

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
Practice_1   air 31.0C  track 53.0C (range 46-58)  all on slicks
Practice_2   —
Practice_3   —
Sprint_Qualifying air 30.6C  track 52.3C (range 49-55)  all on slicks
Sprint_Shootout —
Sprint       air 31.7C  track 49.0C (range 44-53)  all on slicks
Qualifying   air 33.9C  track 51.9C (range 49-54)  all on slicks
Race         air 27.1C  track 37.0C (range 34-42)  all on slicks  rain flag: isolated sample
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.324 s/lap   (-0.35% of a lap)
  HARD     -0.103 s/lap   (-0.11% of a lap)
  MEDIUM   +0.120 s/lap   (+0.13% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 49% of each driver's laps (range 16–67%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-05-03 17:12:15  SAFETY CAR DEPLOYED
  2026-05-03 17:24:07  SAFETY CAR IN THIS LAP
```

## 2 · Per-driver evidence

### QUALIFYING

#### VER · Red Bull Racing

predicted -0.667 → actual -1.815 · **miss -1.148%** (2.6 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 41, Sprint 19, Sprint Qualifying 12
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (87.964s)  [Q1 89.099  Q2 88.116  Q3 87.964]

  > category: ______   note: ______

#### ANT · Mercedes

predicted -0.933 → actual -1.957 · **miss -1.024%** (2.5 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 24, Sprint 19, Sprint Qualifying 14
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (87.798s)  [Q1 88.653  Q2 88.289  Q3 87.798]
- **Race control** (qualifying):
    - `2026-05-02 20:44:30  CAR 12 (ANT) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 13 16:43:03 (PIT)`
    - `2026-05-02 20:46:59  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 12 (ANT) AND 63 (RUS) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 20:47:10  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 12 (ANT) AND 63 (RUS) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 21:07:37  FIA STEWARDS: Q2 INCIDENT INVOLVING CARS 12 (ANT) AND 63 (RUS) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### STR · Aston Martin

predicted +2.195 → actual +1.573 · **miss -0.622%** (1.5 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 3
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 5 predicts a +0.34% penalty, moving the miss -0.622% → -0.962% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (91.164s)  [Q1 91.164]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-05-02 20:21:34  CAR 18 (STR) LAP DELETED - TRACK LIMITS AT TURN 15 LAP 10 16:20:01 (PIT)`
    - `2026-05-02 20:22:50  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 20:23:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 21:07:31  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### PIA · McLaren

predicted -0.998 → actual -1.574 · **miss -0.576%** (1.3 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 35, Sprint 19, Sprint Qualifying 11
- **SCREEN** · ATTEMPTS  8 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q2 (88.332s)  [Q1 89.920  Q2 88.332  Q3 88.500]
- **SCREEN** · WENT SLOWER  its later segment was worse than Q2 — the counted lap is not its last attempt
- **Race control** (qualifying):
    - `2026-05-02 20:22:50  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 20:23:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 21:07:31  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.540 → actual +2.472 · **miss +0.932%** (1.3 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 25, Sprint 19, Sprint Qualifying 3
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 5 predicts a +0.34% penalty, moving the miss +0.932% → +0.592%, cutting it by 36% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (91.967s)  [Q1 91.967]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### BOR · Audi

predicted -0.172 → actual +4.451 · **miss +4.622%** (12.4 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 12
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  1 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 1 vs 5 predicts a +0.68% penalty, moving the miss +4.622% → +3.942%, cutting it by 15% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (93.737s)  [Q1 93.737]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-05-02 20:22:50  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 20:23:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-05-02 21:07:31  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 43 (COL), 23 (ALB), 55 (SAI), 5 (BOR), 44 (HAM), 14 (ALO), 18 (STR), 1 (NOR), 27 (HUL), 81 (PIA) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

### RACE PACE

#### STR · Aston Martin

predicted +2.029 → actual +1.264 · **miss -0.765%** (1.2 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 26 clean long-run laps (field median 38) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 3
- **What made the actual**: 31 clean laps of 56 run (laps 16–56 of 57) · SOFT 27, MEDIUM 4
- **Dropped before the median**: 14 dirty-air, 16 perturbed, 12 invalid
- **What the filter did**: kept 55% of his laps (field 49%). Model measured +1.556%; over EVERY racing lap he is +1.278%. Scoring him on all laps would move the miss -0.765% → **-1.043%** (GROWS by 36%).
- **SCREEN** · COMPOUND SKEW  ran SOFT 87%, MEDIUM 13% vs field HARD 61%, MEDIUM 32%, SOFT 7% — worth -0.24% of a lap at this race's measured offsets
- **SCREEN** · PACE STEP  -0.86% at lap 25 (faster afterwards; bigger than 97% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-03 17:35:19  CAR 18 (STR) TIME 1:40.953 DELETED - TRACK LIMITS AT TURN 17 LAP 15 13:32:27`
    - `2026-05-03 17:37:01  CAR 18 (STR) TIME 1:36.371 DELETED - TRACK LIMITS AT TURN 5 LAP 17 13:34:39`
- *(7 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 21 (2.8s stationary); lap 37  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.818 → actual -1.109 · **miss +0.709%** (2.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 34 clean long-run laps (field median 38) · sessions run: Practice_1 34, Sprint 19, Sprint Qualifying 15
- **What made the actual**: 21 clean laps of 57 run (laps 24–56 of 57) · HARD 21
- **Dropped before the median**: 31 dirty-air, 14 perturbed, 8 invalid
- **What the filter did**: kept 37% of his laps (field 49%). Model measured -0.823%; over EVERY racing lap he is -1.200%. Scoring him on all laps would move the miss +0.709% → **+0.332%** (shrinks by 53%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.332%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · PACE STEP  +1.02% at lap 30 (slower afterwards; bigger than 94% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-03 18:44:15  TURN 17 INCIDENT INVOLVING CAR 63 (RUS) NOTED - MOVING UNDER BRAKING`
    - `2026-05-03 18:47:41  TURN 1 INCIDENT INVOLVING CARS 3 (VER) AND 63 (RUS) NOTED - CAUSING A COLLISION`
    - `2026-05-03 18:49:32  TURN 17 INCIDENT INVOLVING CARS 16 (LEC) AND 63 (RUS) NOTED - CAUSING A COLLISION`
    - `2026-05-03 18:53:21  FIA STEWARDS: TURN 17 INCIDENT INVOLVING CAR 63 (RUS) REVIEWED NO FURTHER INVESTIGATION - MOVING UNDER BRAKING`
    - `2026-05-03 18:53:31  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 3 (VER) AND 63 (RUS) WILL BE INVESTIGATED AFTER THE RACE - CAUSING A COLLISION`
    - `2026-05-03 18:53:36  FIA STEWARDS: TURN 17 INCIDENT INVOLVING CARS 16 (LEC) AND 63 (RUS) WILL BE INVESTIGATED AFTER THE RACE - CAUSING A COLLISION`
- **Incident** lap 57: contact — CAUSING A COLLISION vs LEC → investigated after race
- **Incident** lap 57: contact — CAUSING A COLLISION vs VER → investigated after race
- **Incident** lap 57: contact — MOVING UNDER BRAKING → no action
- **Pit stops** (1): lap 20  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.616 → actual +3.696 · **miss +1.080%** (1.3 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 38 clean long-run laps (field median 38) · sessions run: Practice_1 33, Sprint 19, Sprint Qualifying 6
- **What made the actual**: 20 clean laps of 55 run (laps 18–53 of 57) · MEDIUM 18, SOFT 2
- **Dropped before the median**: 17 dirty-air, 21 perturbed, 10 invalid
- **What the filter did**: kept 36% of his laps (field 49%). Model measured +3.993%; over EVERY racing lap he is +3.581%. Scoring him on all laps would move the miss +1.080% → **+0.668%** (shrinks by 38%).
- **SCREEN** · THIN SLICE  only 36% of his laps survived against a field 49%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · PACE STEP  +2.14% at lap 33 (slower afterwards; bigger than 96% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-05-03 17:49:08  INCIDENT INVOLVING CAR 77 (BOT) NOTED - SPEEDING IN THE PIT LANE`
    - `2026-05-03 17:51:07  FIA STEWARDS: INCIDENT INVOLVING CAR 77 (BOT) UNDER INVESTIGATION - SPEEDING IN THE PIT LANE`
    - `2026-05-03 17:55:11  FIA STEWARDS: DRIVE THROUGH PENALTY FOR CAR 77 (BOT) - SPEEDING IN THE PIT LANE`
    - `2026-05-03 17:59:39  FIA STEWARDS: PENALTY SERVED - DRIVE THROUGH PENALTY FOR CAR 77 (BOT) - SPEEDING IN THE PIT LANE`
    - `2026-05-03 18:15:29  BLACK AND WHITE FLAG FOR CAR 77 (BOT) - IGNORING BLUE FLAGS`
- *(20 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 26: procedural — SPEEDING IN THE PIT LANE → penalty: drive through
- **Pit stops** (3): lap 6 (3.0s stationary); lap 21; lap 30  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.