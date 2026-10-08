# WHY THE MODEL MISSED — evidence dossier
2026 R14 · Spanish Grand Prix · dossier built 2026-10-06

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
Practice_1   air 27.2C  track 49.8C (range 47-52)  all on slicks
Practice_2   air 30.2C  track 50.9C (range 48-53)  all on slicks
Practice_3   air 25.4C  track 46.8C (range 43-50)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 30.8C  track 53.8C (range 52-55)  all on slicks
Race         air 30.6C  track 53.3C (range 50-55)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  HARD     -0.151 s/lap   (-0.15% of a lap)
  SOFT     +0.055 s/lap   (+0.06% of a lap)
  MEDIUM   +0.204 s/lap   (+0.21% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 61% of each driver's laps (range 16–81%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  no safety car, VSC or red flag
```

## 2 · Per-driver evidence

### QUALIFYING

#### COL · Alpine

predicted +0.182 → actual -0.708 · **miss -0.889%** (1.8 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 24, Practice_2 22, Practice_3 14
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (92.903s)  [Q1 93.963  Q2 93.038  Q3 92.903]
- **Race control** (qualifying):
    - `2026-09-12 14:20:19  CAR 43 (COL) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 7 16:18:21 (PIT)`
    - `2026-09-12 14:22:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:41:41  CAR 43 (COL) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 12 16:39:57 (PIT)`
    - `2026-09-12 15:01:53  CAR 43 (COL) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 18 17:00:05 (PIT)`
    - `2026-09-12 15:03:28  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### LAW · Red Bull Racing

predicted -0.428 → actual -0.997 · **miss -0.569%** (1.9 sd) · FASTER than predicted

- **Teammate**: VER missed -0.365% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Practice_2 21, Practice_3 14
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (92.316s)  [Q1 93.310  Q2 92.780  Q3 92.316]
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### ALO · Aston Martin

predicted +1.756 → actual +1.220 · **miss -0.536%** (1.1 sd) · FASTER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 0 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Practice_2 16, Practice_3 16
- **SCREEN** · THIN READ  the model had 0 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q1 (95.388s)  [Q1 95.388]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### PER · Cadillac

predicted +2.221 → actual +1.780 · **miss -0.441%** (1.1 sd) · FASTER than predicted

- **Teammate**: BOT missed +1.888% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Practice_2 24, Practice_3 13
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 6
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 6 predicts a +0.43% penalty, moving the miss -0.441% → -0.866% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (95.913s)  [Q1 95.913]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.389 → actual -0.033 · **miss -0.422%** (1.1 sd) · FASTER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 25, Practice_2 26, Practice_3 12
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 6
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 6 predicts a +0.43% penalty, moving the miss -0.422% → -0.847% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q2 (93.667s)  [Q1 94.667  Q2 93.667]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### VER · Red Bull Racing

predicted -0.994 → actual -1.359 · **miss -0.365%** (1.2 sd) · FASTER than predicted

- **Teammate**: LAW missed -0.569% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 25, Practice_2 22, Practice_3 9
- **SCREEN** · ATTEMPTS  8 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (91.964s)  [Q1 93.381  Q2 92.431  Q3 91.964]
- **Race control** (qualifying):
    - `2026-09-12 14:22:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 15:03:28  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### TSU · Racing Bulls

predicted -0.414 → actual +0.071 · **miss +0.485%** (1.4 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 16, Practice_2 26, Practice_3 12
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  7 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q2 (94.084s)  [Q1 94.311  Q2 94.084]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-09-12 14:22:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:29:52  CAR 22 (TSU) TIME 8:35.899 DELETED - TRACK LIMITS AT TURN 15 LAP 11 16:27:25`
    - `2026-09-12 15:03:28  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.129 → actual +4.017 · **miss +1.888%** (4.5 sd) · SLOWER than predicted

- **Teammate**: PER missed -0.441% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 25, Practice_2 24, Practice_3 13
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 6
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 6 predicts a +0.60% penalty, moving the miss +1.888% → +1.293%, cutting it by 32% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (98.011s)  [Q1 98.011]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-09-12 14:19:50  TURN 7 INCIDENT INVOLVING CARS 55 (SAI) AND 77 (BOT) NOTED - IMPEDING (16:17:31)`
    - `2026-09-12 14:21:49  FIA STEWARDS: TURN 7 INCIDENT INVOLVING CARS 55 (SAI) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - IMPEDING (16:17:31)`
    - `2026-09-12 14:22:05  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 14:22:19  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 5 (BOR), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-09-12 15:03:28  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 81 (PIA), 63 (RUS), 3 (VER), 27 (HUL), 10 (GAS), 43 (COL), 22 (TSU) AND 77 (BOT) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

### RACE PACE

#### BEA · Haas F1 Team

predicted +0.566 → actual -0.116 · **miss -0.682%** (1.3 sd) · FASTER than predicted

- **Teammate**: OCO missed -0.663% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 16 clean long-run laps (field median 20) · sessions run: Practice_1 24, Practice_2 26, Practice_3 11
- **What made the actual**: 25 clean laps of 56 run (laps 23–56 of 57) · HARD 22, MEDIUM 3
- **Dropped before the median**: 26 dirty-air, 9 perturbed, 6 invalid
- **What the filter did**: kept 45% of his laps (field 61%). Model measured +0.000%; over EVERY racing lap he is +0.924%. Scoring him on all laps would move the miss -0.682% → **+0.242%** (shrinks by 65%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.242%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- *(3 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 33 (4.5s stationary); lap 43

  > category: ______   note: ______

#### NOR · McLaren

predicted -1.221 → actual -1.889 · **miss -0.668%** (1.2 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 13 clean long-run laps (field median 20) · sessions run: Practice_1 27, Practice_2 2, Practice_3 13
- **What made the actual**: 29 clean laps of 57 run (laps 2–39 of 57) · HARD 20, MEDIUM 9
- **Dropped before the median**: 21 dirty-air, 7 perturbed, 3 invalid
- **What the filter did**: kept 51% of his laps (field 61%). Model measured -1.773%; over EVERY racing lap he is -1.945%. Scoring him on all laps would move the miss -0.668% → **-0.841%** (GROWS by 26%).
- **SCREEN** · TRUNCATED  last clean lap 39 of 57 — the median covers only the first 68% of the race
- **SCREEN** · PACE STEP  +0.98% at lap 12 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-13 14:34:03  CAR 1 (NOR) TIME 1:36.934 DELETED - TRACK LIMITS AT TURN 6 LAP 54 16:32:29`
- **Pit stops** (1): lap 15
- **Radio** 13:51:25: "Russell's deployment is like a boost press into turn five every lap, I'll have to do something else."
- **Radio** 14:01:34: "I know the hard tyre looks robust, but if you have some pace, we think we should use it. Maintain the precision, pace is there."
- **Radio** 14:36:37: "Yeah, he went off. He went off defending against me. He cut the chicane, he just passed it around the business ship. Pretty obvious. Yeah, we're on our way."
- **Radio** 14:43:44: "Let's take it on the chin, go too quick, that's all it was, very unlucky today guys, we deserve the win quite easily so a big thank you, didn't think we're gonna have a chance here, we should have won. Well done guys, ke"

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.747 → actual +0.084 · **miss -0.663%** (1.3 sd) · FASTER than predicted

- **Teammate**: BEA missed -0.682% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 21 clean long-run laps (field median 20) · sessions run: Practice_1 25, Practice_2 26, Practice_3 12
- **What made the actual**: 38 clean laps of 56 run (laps 18–56 of 57) · HARD 38
- **Dropped before the median**: 17 dirty-air, 5 perturbed, 2 invalid
- **What the filter did**: kept 68% of his laps (field 61%). Model measured +0.200%; over EVERY racing lap he is +0.177%. Scoring him on all laps would move the miss -0.663% → **-0.686%** (GROWS by 3%).
- **SCREEN** · PACE STEP  -0.81% at lap 25 (faster afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- *(2 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 14 (2.6s stationary)

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.976 → actual +1.323 · **miss -0.654%** (1.3 sd) · FASTER than predicted

- **Teammate**: BOT missed +0.906% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 23 clean long-run laps (field median 20) · sessions run: Practice_1 26, Practice_2 24, Practice_3 13
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 15 clean laps of 31 run (laps 8–25 of 57) · HARD 10, MEDIUM 5
- **Dropped before the median**: 9 dirty-air, 10 perturbed, 5 invalid
- **What the filter did**: kept 48% of his laps (field 61%). Model measured +1.439%; over EVERY racing lap he is +2.562%. Scoring him on all laps would move the miss -0.654% → **+0.468%** (shrinks by 28%).
- **SCREEN** · THIN SLICE  only 48% of his laps survived against a field 61%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · TRUNCATED  last clean lap 25 of 57 — the median covers only the first 44% of the race
- **Race control** (race):
    - `2026-09-13 13:32:14  UPDATE: TURN 5 INCIDENT INVOLVING CARS 11 (PER) AND 22 (TSU) NOTED (15:23:41)`
    - `2026-09-13 13:36:19  FIA STEWARDS: TURN 5 INCIDENT INVOLVING CARS 11 (PER) AND 22 (TSU) REVIEWED NO FURTHER INVESTIGATION (15:23:41)`
    - `2026-09-13 13:51:15  CAR 11 (PER) TIME 1:43.523 DELETED - TRACK LIMITS AT TURN 15 LAP 26 15:49:02`
    - `2026-09-13 13:53:04  CAR 11 (PER) TIME 1:43.767 DELETED - TRACK LIMITS AT TURN 15 LAP 27 15:50:46`
    - `2026-09-13 13:59:33  CAR 11 (PER) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 31 15:57:15 (PIT)`
- *(7 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 17: contact — INCIDENT (reason unstated) vs TSU → no action
- **Pit stops** (2): lap 14 (3.0s stationary); lap 31  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### VER · Red Bull Racing

predicted -0.857 → actual -1.445 · **miss -0.588%** (1.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 19 clean long-run laps (field median 20) · sessions run: Practice_1 25, Practice_2 22, Practice_3 9
- **What made the actual**: 46 clean laps of 57 run (laps 2–57 of 57) · HARD 36, SOFT 10
- **Dropped before the median**: 7 dirty-air, 6 perturbed, 3 invalid
- **What the filter did**: kept 81% of his laps (field 61%). Model measured -1.329%; over EVERY racing lap he is -1.629%. Scoring him on all laps would move the miss -0.588% → **-0.888%** (GROWS by 51%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -0.888%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **SCREEN** · PACE STEP  +1.42% at lap 12 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-13 13:09:06  TURN 1 INCIDENT INVOLVING CAR 3 (VER) NOTED - LEAVING THE TRACK AND GAINING AN ADVANTAGE (15:04:12)`
    - `2026-09-13 13:10:55  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CAR 3 (VER) REVIEWED NO FURTHER INVESTIGATION - LEAVING THE TRACK AND GAINING AN ADVANTAGE (15:04:12)`
    - `2026-09-13 14:39:15  TURN 5 INCIDENT INVOLVING CAR 3 (VER) NOTED - LEAVING THE TRACK AND GAINING AN ADVANTAGE (16:35:42)`
    - `2026-09-13 14:39:32  CAR 3 (VER) TIME 1:37.837 DELETED - TRACK LIMITS AT TURN 6 LAP 56 16:35:43`
    - `2026-09-13 14:41:31  FIA STEWARDS: TURN 5 INCIDENT INVOLVING CAR 3 (VER) REVIEWED NO FURTHER INVESTIGATION - LEAVING THE TRACK AND GAINING AN ADVANTAGE (16:35:42)`
- **Incident** lap 4: off-track — LEAVING THE TRACK AND GAINING AN ADVANTAGE → no action
- **Incident** lap 57: off-track — LEAVING THE TRACK AND GAINING AN ADVANTAGE → no action
- **Pit stops** (1): lap 14 (2.4s stationary)
- **Radio** 13:09:48: "Max, we think we should give the position back to Hamilton, so that will mean letting Antonelli through as well."
- **Radio** 13:09:48: "Wait, what are you guys talking about? If I just stay on the track, we are out of the race."
- **Radio** 14:41:11: "Solid there by Max, well done, it's P2, not what we get out of that one, so well done. Well done Max, you extracted everything once again today, it was a strong fight, I know we have to think the same a little bit, but i"

  > category: ______   note: ______

#### ANT · Mercedes

predicted -1.867 → actual -1.403 · **miss +0.464%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 16 clean long-run laps (field median 20) · sessions run: Practice_1 27, Practice_2 24, Practice_3 13
- **What made the actual**: 37 clean laps of 57 run (laps 4–57 of 57) · HARD 29, MEDIUM 8
- **Dropped before the median**: 14 dirty-air, 6 perturbed, 4 invalid
- **What the filter did**: kept 65% of his laps (field 61%). Model measured -1.287%; over EVERY racing lap he is -1.601%. Scoring him on all laps would move the miss +0.464% → **+0.150%** (shrinks by 68%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.150%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · PACE STEP  +1.67% at lap 12 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-13 13:15:06  CAR 12 (ANT) TIME 1:41.166 DELETED - TRACK LIMITS AT TURN 17 LAP 6 15:13:39`
    - `2026-09-13 13:43:26  CAR 12 (ANT) TIME 1:39.145 DELETED - TRACK LIMITS AT TURN 6 LAP 23 15:41:55`
- **Pit stops** (1): lap 14 (3.0s stationary)
- **Radio** 13:03:12: "[unintelligible]"
- **Radio** 13:34:40: "Just make sure you stay on top of the management, we don't want to open these tyres up, they are bulletproof."
- **Radio** 13:43:19: "Check the car. Which corner? No, I didn't touch any wall, but the thing feels weird."
- **Radio** 13:45:49: "We have two track limits now, so turn six and then turn 17 will be at hour eight, so no more track limits please, keep it clean."
- **Radio** 14:40:40: "Beautiful work, Kimi, absolute masterpiece. Good job, guys. Well done, mate. That took a lot of mental strength and I think you did the job. Yeah, lucky for the safety car, weirdo. Yeah, feel a bit bad for Lando, but rea"
- **Radio** 14:43:13: "Kimi, well done, another one, that's so good points in the pocket, with some not finishing. Very, very good. Yeah, thank you, Toto. Can you contain this one, Sergi? Sergi, home race! Good effort."

  > category: ______   note: ______

#### ALB · Williams

predicted +0.935 → actual +1.590 · **miss +0.655%** (1.1 sd) · SLOWER than predicted

- **Teammate**: SAI missed +1.362% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 20 clean long-run laps (field median 20) · sessions run: Practice_1 25, Practice_2 22, Practice_3 2
- **What made the actual**: 45 clean laps of 56 run (laps 3–56 of 57) · HARD 35, MEDIUM 10
- **Dropped before the median**: 3 dirty-air, 7 perturbed, 4 invalid
- **What the filter did**: kept 80% of his laps (field 61%). Model measured +1.705%; over EVERY racing lap he is +1.458%. Scoring him on all laps would move the miss +0.655% → **+0.408%** (shrinks by 38%).
- **Race control** (race):
    - `2026-09-13 13:32:54  CAR 23 (ALB) TIME 1:42.132 DELETED - TRACK LIMITS AT TURN 1 LAP 16 15:31:05`
    - `2026-09-13 14:19:03  CAR 23 (ALB) TIME 1:40.060 DELETED - TRACK LIMITS AT TURN 18 LAP 43 16:17:43`
- *(8 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 14 (3.7s stationary)

  > category: ______   note: ______

#### TSU · Racing Bulls

predicted -0.184 → actual +0.518 · **miss +0.702%** (1.7 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 15 clean long-run laps (field median 20) · sessions run: Practice_1 16, Practice_2 26, Practice_3 12
- **What made the actual**: 37 clean laps of 56 run (laps 16–56 of 57) · HARD 20, MEDIUM 17
- **Dropped before the median**: 13 dirty-air, 8 perturbed, 6 invalid
- **What the filter did**: kept 66% of his laps (field 61%). Model measured +0.634%; over EVERY racing lap he is +0.491%. Scoring him on all laps would move the miss +0.702% → **+0.559%** (shrinks by 20%).
- **SCREEN** · PACE STEP  -0.87% at lap 50 (faster afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-13 13:09:49  TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 22 (TSU) NOTED - CAUSING A COLLISION (15:04:12)`
    - `2026-09-13 13:15:52  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 22 (TSU) REVIEWED NO FURTHER INVESTIGATION - CAUSING A COLLISION (15:04:12)`
    - `2026-09-13 13:17:18  CAR 22 (TSU) TIME 1:43.517 DELETED - TRACK LIMITS AT TURN 15 LAP 7 15:15:43`
    - `2026-09-13 13:20:27  CAR 22 (TSU) TIME 1:43.759 DELETED - TRACK LIMITS AT TURN 15 LAP 8 15:17:27`
    - `2026-09-13 13:26:24  CAR 22 (TSU) TIME 1:44.359 DELETED - TRACK LIMITS AT TURN 6 LAP 12 15:23:41`
    - `2026-09-13 13:30:27  TURN 5 INCIDENT INVOLVING CAR 22 (TSU) NOTED (15:23:41)`
    - `2026-09-13 13:32:14  UPDATE: TURN 5 INCIDENT INVOLVING CARS 11 (PER) AND 22 (TSU) NOTED (15:23:41)`
    - `2026-09-13 13:36:19  FIA STEWARDS: TURN 5 INCIDENT INVOLVING CARS 11 (PER) AND 22 (TSU) REVIEWED NO FURTHER INVESTIGATION (15:23:41)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 4: contact — CAUSING A COLLISION vs SAI → no action
- **Incident** lap 17: contact — INCIDENT (reason unstated) vs PER → no action
- **Pit stops** (1): lap 36 (2.7s stationary)

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.341 → actual +3.247 · **miss +0.906%** (1.7 sd) · SLOWER than predicted

- **Teammate**: PER missed -0.654% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 27 clean long-run laps (field median 20) · sessions run: Practice_1 25, Practice_2 24, Practice_3 13
- **What made the actual**: 39 clean laps of 54 run (laps 3–54 of 57) · HARD 32, SOFT 7
- **Dropped before the median**: 2 dirty-air, 14 perturbed, 5 invalid
- **What the filter did**: kept 72% of his laps (field 61%). Model measured +3.363%; over EVERY racing lap he is +3.366%. Scoring him on all laps would move the miss +0.906% → **+0.909%** (GROWS by 0%).
- **SCREEN** · PACE STEP  +1.82% at lap 42 (slower afterwards; bigger than 96% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- *(25 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 29 (2.9s stationary); lap 43
- **Radio** 14:02:37: "My left seat is very, very hot, my heel is very hot."

  > category: ______   note: ______

#### SAI · Williams

predicted +0.836 → actual +2.198 · **miss +1.362%** (2.3 sd) · SLOWER than predicted

- **Teammate**: ALB missed +0.655% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 27 clean long-run laps (field median 20) · sessions run: Practice_1 30, Practice_2 25, Practice_3 15
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 23 clean laps of 43 run (laps 4–39 of 57) · HARD 19, MEDIUM 4
- **Dropped before the median**: 8 dirty-air, 13 perturbed, 10 invalid
- **What the filter did**: kept 53% of his laps (field 61%). Model measured +2.313%; over EVERY racing lap he is +2.655%. Scoring him on all laps would move the miss +1.362% → **+1.704%** (GROWS by 25%).
- **SCREEN** · TRUNCATED  last clean lap 39 of 57 — the median covers only the first 68% of the race
- **SCREEN** · PACE STEP  +0.77% at lap 28 (slower afterwards; bigger than 94% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-13 13:09:49  TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 22 (TSU) NOTED - CAUSING A COLLISION (15:04:12)`
    - `2026-09-13 13:15:52  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 55 (SAI) AND 22 (TSU) REVIEWED NO FURTHER INVESTIGATION - CAUSING A COLLISION (15:04:12)`
    - `2026-09-13 13:25:40  CAR 55 (SAI) TIME 1:44.117 DELETED - TRACK LIMITS AT TURN 5 LAP 12 15:23:43`
    - `2026-09-13 13:29:13  CAR 55 (SAI) TIME 1:43.256 DELETED - TRACK LIMITS AT TURN 15 LAP 13 15:26:08`
    - `2026-09-13 13:30:58  TURN 5 INCIDENT INVOLVING CARS 55 (SAI) AND 14 (ALO) NOTED (15:23:42)`
    - `2026-09-13 13:33:55  FIA STEWARDS: TURN 5 INCIDENT INVOLVING CARS 55 (SAI) AND 14 (ALO) UNDER INVESTIGATION (15:23:42)`
    - `2026-09-13 13:37:59  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) (15:23:42)`
    - `2026-09-13 13:43:13  CAR 55 (SAI) TIME 1:42.021 DELETED - TRACK LIMITS AT TURN 15 LAP 22 15:42:09`
    - `2026-09-13 13:44:37  BLACK AND WHITE FLAG FOR CAR 55 (SAI) - TRACK LIMITS`
    - `2026-09-13 13:47:58  CAR 55 (SAI) TIME 2:23.167 DELETED - TRACK LIMITS AT TURN 15 LAP 24 15:46:17`
    - `2026-09-13 13:49:20  FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 55 (SAI) (15:23:42)`
    - `2026-09-13 14:07:00  CAR 55 (SAI) TIME 1:44.517 DELETED - TRACK LIMITS AT TURN 11 LAP 35 16:05:11`
- *(15 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 4: contact — CAUSING A COLLISION vs TSU → no action
- **Incident** lap 16: contact — INCIDENT (reason unstated) vs ALO → investigated
- **Incident** lap 27: procedural — 5 SECOND TIME PENALTY FOR CAR 55 (SAI) → penalty: 5 second time penalty
- **Pit stops** (3): lap 23 (17.9s stationary); lap 31; lap 43  ·  *1 not in pitstops.parquet*
- **Radio** 14:06:08: "Yeah, the track limits, Verstappen by, he touched me too quick, that's the shooting car. We'll be understood with feedback."
- **Radio** 14:06:39: "I had no other way to get out of the way, in that sector."

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.