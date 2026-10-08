# WHY THE MODEL MISSED — evidence dossier
2026 R13 · Italian Grand Prix · dossier built 2026-10-06

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
Practice_1   air 31.0C  track 51.3C (range 47-54)  all on slicks
Practice_2   air 33.7C  track 54.9C (range 52-58)  all on slicks
Practice_3   air 31.3C  track 51.5C (range 49-54)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 34.0C  track 53.8C (range 51-56)  all on slicks
Race         air 32.2C  track 55.0C (range 51-57)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MEDIUM   -0.063 s/lap   (-0.07% of a lap)
  SOFT     +0.063 s/lap   (+0.07% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 43% of each driver's laps (range 13–75%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-09-06 13:06:49  SAFETY CAR DEPLOYED
  2026-09-06 13:07:43  RED FLAG - RACE SUSPENDED
  2026-09-06 13:34:00  SAFETY CAR LIGHTS ON
```

## 2 · Per-driver evidence

### QUALIFYING

#### GAS · Alpine

predicted -0.068 → actual -1.243 · **miss -1.175%** (3.1 sd) · FASTER than predicted

- **Teammate**: COL missed -0.971% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 4) · sessions run: Practice_2 27, Practice_3 24
- **SCREEN** · THIN READ  the model had 2 laps of this type against a field median of 4 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (81.786s)  [Q1 82.612  Q2 82.077  Q3 81.786]

  > category: ______   note: ______

#### COL · Alpine

predicted +0.254 → actual -0.717 · **miss -0.971%** (2.6 sd) · FASTER than predicted

- **Teammate**: GAS missed -1.175% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 4) · sessions run: Practice_1 27, Practice_2 28, Practice_3 23
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (82.220s)  [Q1 82.662  Q2 82.400  Q3 82.220]

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.433 → actual -0.266 · **miss -0.699%** (1.6 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 4) · sessions run: Practice_1 28, Practice_2 29, Practice_3 23
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q2 (82.756s)  [Q1 82.906  Q2 82.756]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### LEC · Ferrari

predicted -1.461 → actual -0.978 · **miss +0.483%** (1.4 sd) · SLOWER than predicted

- **Teammate**: HAM missed +0.501% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 4) · sessions run: Practice_1 29, Practice_2 29, Practice_3 21
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (82.004s)  [Q1 82.902  Q2 82.509  Q3 82.004]
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.451 → actual -0.950 · **miss +0.501%** (1.4 sd) · SLOWER than predicted

- **Teammate**: LEC missed +0.483% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 4) · sessions run: Practice_1 26, Practice_2 27, Practice_3 21
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (82.011s)  [Q1 82.847  Q2 82.516  Q3 82.011]

  > category: ______   note: ______

#### ALB · Williams

predicted +0.651 → actual +1.485 · **miss +0.833%** (1.8 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 4) · sessions run: Practice_2 31, Practice_3 29
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 4 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 5 predicts a +0.51% penalty, moving the miss +0.833% → +0.323%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (84.356s)  [Q1 84.356]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### TSU · Racing Bulls

predicted -0.535 → actual +0.759 · **miss +1.293%** (3.2 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 4) · sessions run: Practice_1 27, Practice_2 29, Practice_3 16
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 5 predicts a +0.51% penalty, moving the miss +1.293% → +0.783%, cutting it by 39% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (83.755s)  [Q1 83.755]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### SAI · Williams

predicted +0.730 → actual -0.342 · **miss -1.071%** (2.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 29 clean long-run laps (field median 29) · sessions run: Practice_1 25, Practice_2 30, Practice_3 28
- **What made the actual**: 20 clean laps of 53 run (laps 29–53 of 53) · MEDIUM 20
- **Dropped before the median**: 27 dirty-air, 8 perturbed, 7 invalid
- **What the filter did**: kept 38% of his laps (field 43%). Model measured -0.070%; over EVERY racing lap he is +0.057%. Scoring him on all laps would move the miss -1.071% → **-0.944%** (shrinks by 12%).
- **Race control** (race):
    - `2026-09-06 13:08:30  CAR 55 (SAI) LAP DELETED - TRACK LIMITS AT TURN 5 LAP 1 15:04:11`
    - `2026-09-06 13:25:10  CAR 55 (SAI) LAP 1 WILL BE REINSTATED`
    - `2026-09-06 14:36:10  CAR 55 (SAI) TIME 1:26.235 DELETED - TRACK LIMITS AT TURN 5 LAP 39 16:35:07`
- **Pit stops** (2): lap 3; lap 27 (2.6s stationary)

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.410 → actual +1.545 · **miss -0.865%** (1.6 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 31 clean long-run laps (field median 29) · sessions run: Practice_1 27, Practice_2 28, Practice_3 20
- **What made the actual**: 32 clean laps of 51 run (laps 9–51 of 53) · SOFT 19, MEDIUM 13
- **Dropped before the median**: 10 dirty-air, 14 perturbed, 7 invalid
- **What the filter did**: kept 63% of his laps (field 43%). Model measured +1.817%; over EVERY racing lap he is +1.787%. Scoring him on all laps would move the miss -0.865% → **-0.895%** (GROWS by 3%).
- **Race control** (race):
    - `2026-09-06 14:49:04  CAR 77 (BOT) TIME 1:37.053 DELETED - TRACK LIMITS AT TURN 2 LAP 47 16:47:44`
- *(13 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 3; lap 27 (6.9s stationary)

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.010 → actual -0.557 · **miss -0.566%** (1.3 sd) · FASTER than predicted

- **Teammate**: COL missed -0.521% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 24 clean long-run laps (field median 29) · sessions run: Practice_2 27, Practice_3 24
- **What made the actual**: 23 clean laps of 53 run (laps 1–53 of 53) · HARD 22, MEDIUM 1
- **Dropped before the median**: 25 dirty-air, 10 perturbed, 5 invalid
- **What the filter did**: kept 43% of his laps (field 43%). Model measured -0.285%; over EVERY racing lap he is -0.452%. Scoring him on all laps would move the miss -0.566% → **-0.733%** (GROWS by 29%).
- **SCREEN** · PACE STEP  -0.50% at lap 48 (faster afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Pit stops** (1): lap 3

  > category: ______   note: ______

#### COL · Alpine

predicted +0.250 → actual -0.272 · **miss -0.521%** (1.1 sd) · FASTER than predicted

- **Teammate**: GAS missed -0.566% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 35 clean long-run laps (field median 29) · sessions run: Practice_1 27, Practice_2 28, Practice_3 23
- **What made the actual**: 25 clean laps of 53 run (laps 21–53 of 53) · HARD 25
- **Dropped before the median**: 24 dirty-air, 6 perturbed, 6 invalid
- **What the filter did**: kept 47% of his laps (field 43%). Model measured +0.000%; over EVERY racing lap he is -0.141%. Scoring him on all laps would move the miss -0.521% → **-0.662%** (GROWS by 27%).
- **SCREEN** · PACE STEP  -0.44% at lap 48 (faster afterwards; bigger than 96% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-06 12:36:18  INCIDENT INVOLVING CAR 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT (14:27:01)`
    - `2026-09-06 12:41:23  FIA STEWARDS: INCIDENT INVOLVING CAR 43 (COL) WILL BE INVESTIGATED AFTER THE RACE - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT (14:27:01)`
    - `2026-09-06 13:48:29  CAR 43 (COL) TIME 2:47.838 DELETED - TRACK LIMITS AT TURN 6 LAP 6 15:46:31`
    - `2026-09-06 14:41:22  CAR 43 (COL) TIME 1:26.278 DELETED - TRACK LIMITS AT TURN 1 LAP 43 16:40:06`
- **Incident** lap 1: procedural — FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS – PRACTICE START INFRINGEMENT → investigated after race
- **Pit stops** (1): lap 3

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.557 → actual -0.453 · **miss +1.104%** (2.3 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 25 clean long-run laps (field median 29) · sessions run: Practice_1 26, Practice_2 27, Practice_3 21
- **What made the actual**: 16 clean laps of 53 run (laps 11–53 of 53) · MEDIUM 16
- **Dropped before the median**: 33 dirty-air, 7 perturbed, 7 invalid
- **What the filter did**: kept 30% of his laps (field 43%). Model measured -0.181%; over EVERY racing lap he is -0.575%. Scoring him on all laps would move the miss +1.104% → **+0.709%** (shrinks by 36%).
- **SCREEN** · THIN SLICE  only 30% of his laps survived against a field 43%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · PACE STEP  +0.66% at lap 48 (slower afterwards; bigger than 94% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-09-06 13:05:26  TURN 2 INCIDENT INVOLVING CARS 16 (LEC) AND 44 (HAM) NOTED (15:03:44)`
    - `2026-09-06 13:26:24  FIA STEWARDS: TURN 2 INCIDENT INVOLVING CARS 16 (LEC) AND 44 (HAM) REVIEWED NO FURTHER INVESTIGATION (15:03:44)`
    - `2026-09-06 13:59:05  CAR 44 (HAM) TIME 1:26.415 DELETED - TRACK LIMITS AT TURN 5 LAP 14 15:57:50`
    - `2026-09-06 14:29:32  CAR 44 (HAM) TIME 1:26.929 DELETED - TRACK LIMITS AT TURN 1 LAP 35 16:28:12`
- **Incident** lap 2: contact — INCIDENT (reason unstated) vs LEC → no action
- **Pit stops** (1): lap 3
- **Radio** 14:29:38: "This tyre is terrible, mate."
- **Radio** 15:01:54: "That one hurts, that one really hurts, but thank you for continuing to show up mate, great job all weekend guys, the garage is always still in me, but I've seen it through to you, thank you for turning out, giving us you"

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.