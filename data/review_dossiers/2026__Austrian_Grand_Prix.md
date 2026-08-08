# WHY THE MODEL MISSED — evidence dossier
2026 R8 · Austrian Grand Prix · dossier built 2026-08-08

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
Practice_1   air 30.6C  track 50.3C (range 48-51)  all on slicks
Practice_2   air 31.9C  track 47.2C (range 44-50)  all on slicks
Practice_3   air 31.3C  track 50.7C (range 49-53)  all on slicks
Qualifying   air 33.3C  track 51.9C (range 51-54)  all on slicks
Race         air 34.5C  track 50.2C (range 43-53)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.100 s/lap   (-0.14% of a lap)
  HARD     +0.007 s/lap   (+0.01% of a lap)
  MEDIUM   +0.022 s/lap   (+0.03% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 57% of each driver's laps (range 21–86%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  no safety car, VSC or red flag
```

## 2 · Per-driver evidence

### QUALIFYING

#### LAW · Racing Bulls

predicted -0.014 → actual -0.718 · **miss -0.705%** (1.6 sd) · FASTER than predicted

- **Teammate**: LIN missed -0.474% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_2 34, Practice_3 21
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (66.955s)  [Q1 67.385  Q2 67.136  Q3 66.955]
- **Race control** (qualifying):
    - `2026-06-27 14:21:50  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 6 (HAD), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-27 14:22:13  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 6 (HAD), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-27 15:08:07  CAR 30 (LAW) LAP DELETED - DOUBLE YELLOW AT TURN 9`
    - `2026-06-27 15:09:00  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted -0.002 → actual -0.476 · **miss -0.474%** (1.0 sd) · FASTER than predicted

- **Teammate**: LAW missed -0.705% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 18, Practice_2 29, Practice_3 24
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (67.007s)  [Q1 67.549  Q2 67.155  Q3 67.007]
- **Race control** (qualifying):
    - `2026-06-27 14:21:50  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 6 (HAD), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-27 14:22:13  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 6 (HAD), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-27 14:51:35  INCIDENT INVOLVING CAR 41 (LIN) NOTED - UNSAFE RELEASE (16:50:09)`
    - `2026-06-27 14:57:56  FIA STEWARDS: INCIDENT INVOLVING CAR 41 (LIN) REVIEWED NO FURTHER INVESTIGATION - UNSAFE RELEASE (16:50:09)`
    - `2026-06-27 15:08:14  CAR 41 (LIN) LAP DELETED - DOUBLE YELLOW AT TURN 9`
    - `2026-06-27 15:09:00  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 63 (RUS), 41 (LIN), 30 (LAW), 5 (BOR), 27 (HUL), 11 (PER), 43 (COL) AND 87 (BEA) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### ALB · Williams

predicted +0.603 → actual +0.941 · **miss +0.338%** (1.1 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 30, Practice_2 34, Practice_3 25
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% penalty, moving the miss +0.338% → +0.168%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (68.509s)  [Q1 68.509]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### STR · Aston Martin

predicted +3.014 → actual +3.677 · **miss +0.662%** (1.4 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_2 32, Practice_3 19
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% penalty, moving the miss +0.662% → +0.322%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (70.363s)  [Q1 70.363]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### LAW · Racing Bulls

predicted +0.615 → actual -0.199 · **miss -0.814%** (1.9 sd) · FASTER than predicted

- **Teammate**: LIN missed -0.538% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 26 clean long-run laps (field median 22) · sessions run: Practice_2 34, Practice_3 21
- **What made the actual**: 35 clean laps of 70 run (laps 6–70 of 71) · MEDIUM 35
- **Dropped before the median**: 29 dirty-air, 10 perturbed, 5 invalid
- **What the filter did**: kept 50% of his laps (field 57%). Model measured -0.325%; over EVERY racing lap he is -0.281%. Scoring him on all laps would move the miss -0.814% → **-0.770%** (shrinks by 5%).
- **SCREEN** · PACE STEP  +0.58% at lap 62 (slower afterwards; bigger than 91% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-28 12:26:59  INCIDENT INVOLVING CAR 30 (LAW) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT (14:23:37)`
    - `2026-06-28 12:28:44  FIA STEWARDS: INCIDENT INVOLVING CAR 30 (LAW) WILL BE INVESTIGATED AFTER THE RACE - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT (14:23:37)`
- *(4 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 1: procedural — FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT → investigated after race
- **Pit stops** (2): lap 19 (2.9s stationary); lap 45  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted +0.719 → actual +0.181 · **miss -0.538%** (1.2 sd) · FASTER than predicted

- **Teammate**: LAW missed -0.814% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 33 clean long-run laps (field median 22) · sessions run: Practice_1 18, Practice_2 29, Practice_3 24
- **What made the actual**: 40 clean laps of 70 run (laps 8–70 of 71) · HARD 21, MEDIUM 19
- **Dropped before the median**: 23 dirty-air, 11 perturbed, 5 invalid
- **What the filter did**: kept 57% of his laps (field 57%). Model measured +0.054%; over EVERY racing lap he is -0.162%. Scoring him on all laps would move the miss -0.538% → **-0.754%** (GROWS by 40%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -0.754%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- *(3 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 18 (2.2s stationary); lap 46  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.502 → actual -0.929 · **miss +0.573%** (1.0 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 28 clean long-run laps (field median 22) · sessions run: Practice_1 25, Practice_2 33, Practice_3 22
- **What made the actual**: 26 clean laps of 71 run (laps 7–71 of 71) · HARD 22, MEDIUM 4
- **Dropped before the median**: 39 dirty-air, 11 perturbed, 6 invalid
- **What the filter did**: kept 37% of his laps (field 57%). Model measured -1.054%; over EVERY racing lap he is -1.698%. Scoring him on all laps would move the miss +0.573% → **-0.071%** (shrinks by 88%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to -0.071%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · PACE STEP  +0.86% at lap 64 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-28 13:10:19  CAR 44 (HAM) TIME 1:12.028 DELETED - TRACK LIMITS AT TURN 1 LAP 2 15:04:42`
    - `2026-06-28 13:11:11  CAR 44 (HAM) TIME 1:12.028 WILL BE REINSTATED`
    - `2026-06-28 13:20:50  TURN 6 INCIDENT INVOLVING CARS 44 (HAM) AND 3 (VER) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:16:15)`
    - `2026-06-28 13:28:02  FIA STEWARDS: TURN 6 INCIDENT INVOLVING CARS 44 (HAM) AND 3 (VER) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:16:15)`
- **Incident** lap 15: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs VER → no action
- **Pit stops** (3): lap 12 (2.4s stationary); lap 25; lap 42  ·  *2 not in pitstops.parquet*
- **Radio** 13:18:48: "Out-lap critical, out-lap critical, let's push."
- **Radio** 13:24:23: "Pace is okay, better now, you're faster than Charles."
- **Radio** 13:33:01: "And deg on other, seems lower, we are thinking also about plan B. It doesn't feel that way to me mate."
- **Radio** 13:34:34: "box, cross box, double too late, we're tied."
- **Radio** 13:43:11: "And mode TS, mode TS. Why do I have to go to mode TS?"
- **Radio** 13:51:18: "We need to get the Piastri, I know you are trying."

  > category: ______   note: ______

#### ALB · Williams

predicted +0.999 → actual +1.626 · **miss +0.627%** (1.4 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 41 clean long-run laps (field median 22) · sessions run: Practice_1 30, Practice_2 34, Practice_3 25
- **What made the actual**: 37 clean laps of 69 run (laps 14–69 of 71) · HARD 25, MEDIUM 12
- **Dropped before the median**: 22 dirty-air, 13 perturbed, 5 invalid
- **What the filter did**: kept 54% of his laps (field 57%). Model measured +1.498%; over EVERY racing lap he is +1.431%. Scoring him on all laps would move the miss +0.627% → **+0.560%** (shrinks by 11%).
- **SCREEN** · PACE STEP  +2.33% at lap 60 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-28 13:29:45  CAR 23 (ALB) TIME 1:31.904 DELETED - TRACK LIMITS AT TURN 3 LAP 19 15:26:37`
    - `2026-06-28 13:41:36  INCIDENT INVOLVING CAR 23 (ALB) NOTED - YELLOW FLAG INFRINGEMENT (15:32:25)`
    - `2026-06-28 13:51:26  FIA STEWARDS: INCIDENT INVOLVING CAR 23 (ALB) WILL BE INVESTIGATED AFTER THE RACE - YELLOW FLAG INFRINGEMENT (15:32:25)`
- *(15 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 31: procedural — YELLOW FLAG INFRINGEMENT → investigated after race
- **Pit stops** (2): lap 18; lap 37  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### COL · Alpine

predicted +0.147 → actual +0.889 · **miss +0.742%** (1.2 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 29 clean long-run laps (field median 22) · sessions run: Practice_1 27, Practice_2 30, Practice_3 18
- **What made the actual**: 34 clean laps of 70 run (laps 15–70 of 71) · MEDIUM 21, HARD 13
- **Dropped before the median**: 27 dirty-air, 12 perturbed, 6 invalid
- **What the filter did**: kept 49% of his laps (field 57%). Model measured +0.762%; over EVERY racing lap he is +0.717%. Scoring him on all laps would move the miss +0.742% → **+0.697%** (shrinks by 6%).
- *(9 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 20 (2.6s stationary); lap 46  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.527 → actual +1.369 · **miss +0.842%** (1.4 sd) · SLOWER than predicted

- **Teammate**: BEA missed +0.955% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 18 clean long-run laps (field median 22) · sessions run: Practice_2 33, Practice_3 15
- **What made the actual**: 45 clean laps of 69 run (laps 6–69 of 71) · HARD 29, MEDIUM 16
- **Dropped before the median**: 14 dirty-air, 12 perturbed, 7 invalid
- **What the filter did**: kept 65% of his laps (field 57%). Model measured +1.242%; over EVERY racing lap he is +1.214%. Scoring him on all laps would move the miss +0.842% → **+0.814%** (shrinks by 3%).
- **SCREEN** · PACE STEP  +1.50% at lap 55 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-28 13:45:10  INCIDENT INVOLVING CAR 31 (OCO) NOTED - YELLOW FLAG INFRINGEMENT (15:32:25)`
    - `2026-06-28 14:01:41  INCIDENT INVOLVING CARS 6 (HAD) AND 31 (OCO) NOTED (15:57:26)`
    - `2026-06-28 14:02:57  FIA STEWARDS: INCIDENT INVOLVING CAR 31 (OCO) REVIEWED NO FURTHER INVESTIGATION - YELLOW FLAG INFRINGEMENT (15:32:25)`
    - `2026-06-28 14:08:22  FIA STEWARDS: INCIDENT INVOLVING CARS 6 (HAD) AND 31 (OCO) REVIEWED NO FURTHER INVESTIGATION (15:57:26)`
    - `2026-06-28 14:29:15  CAR 31 (OCO) TIME 1:17.875 DELETED - TRACK LIMITS AT TURN 10 LAP 64 16:23:58`
    - `2026-06-28 14:29:16  CAR 31 (OCO) TIME 1:16.050 DELETED - TRACK LIMITS AT TURN 10 (NEXT LAP)`
- *(12 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 34: procedural — YELLOW FLAG INFRINGEMENT → no action
- **Incident** lap 48: contact — INCIDENT (reason unstated) vs HAD → no action
- **Pit stops** (2): lap 18 (2.8s stationary); lap 33  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.301 → actual +1.256 · **miss +0.955%** (1.6 sd) · SLOWER than predicted

- **Teammate**: OCO missed +0.842% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 28 clean long-run laps (field median 22) · sessions run: Practice_1 26, Practice_2 33, Practice_3 19
- **What made the actual**: 40 clean laps of 70 run (laps 14–70 of 71) · MEDIUM 28, HARD 12
- **Dropped before the median**: 24 dirty-air, 9 perturbed, 4 invalid
- **What the filter did**: kept 57% of his laps (field 57%). Model measured +1.130%; over EVERY racing lap he is +1.046%. Scoring him on all laps would move the miss +0.955% → **+0.871%** (shrinks by 9%).
- *(7 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 24 (2.8s stationary); lap 45  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.