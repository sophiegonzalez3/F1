# WHY THE MODEL MISSED — evidence dossier
2026 R9 · British Grand Prix · dossier built 2026-08-08

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
Practice_1   air 22.0C  track 40.7C (range 38-43)  all on slicks
Practice_2   —
Practice_3   —
Qualifying   air 25.2C  track 41.1C (range 38-44)  all on slicks
Race         air 24.8C  track 40.0C (range 38-44)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.400 s/lap   (-0.43% of a lap)
  MEDIUM   -0.020 s/lap   (-0.02% of a lap)
  HARD     +0.042 s/lap   (+0.05% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 52% of each driver's laps (range 14–73%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-07-05 15:18:50  SAFETY CAR DEPLOYED
  2026-07-05 15:25:51  LAPPED CARS MAY NOW OVERTAKE THE SAFETY CAR: 81, 14, 87, 31, 18, 11, 77
  2026-07-05 15:27:42  SAFETY CAR IN THIS LAP
  2026-07-05 15:27:50  SAFETY CAR DEPLOYED
  2026-07-05 15:29:51  SAFETY CAR IN THIS LAP
  2026-07-05 15:41:44  INCIDENT INVOLVING CAR 55 (SAI) NOTED - SAFETY CAR INFRINGEMENT (16:26:02)
  2026-07-05 15:41:57  FIA STEWARDS: INCIDENT INVOLVING CAR 55 (SAI) WILL BE INVESTIGATED AFTER THE RACE - SAFETY CAR INFRINGEMENT (16:26:02)
```

## 2 · Per-driver evidence

### QUALIFYING

#### STR · Aston Martin

predicted +3.827 → actual +3.106 · **miss -0.721%** (1.4 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Sprint 16, Sprint Qualifying 5
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 5 predicts a +0.34% penalty, moving the miss -0.721% → -1.061% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (92.863s)  [Q1 92.863]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### ANT · Mercedes

predicted -1.376 → actual -1.830 · **miss -0.454%** (1.5 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 29, Sprint 17, Sprint Qualifying 15
- **SCREEN** · ATTEMPTS  7 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q3 (88.111s)  [Q1 89.719  Q2 88.493  Q3 88.111]
- **SCREEN** · deleted lap 116.749s, slower than its counted 88.111s — no effect on the number
- **Race control** (qualifying):
    - `2026-07-04 15:39:26  CAR 12 (ANT) TIME 1:56.749 DELETED - TRACK LIMITS AT TURN 3 LAP 9 16:37:36`

  > category: ______   note: ______

#### ALB · Williams

predicted +0.273 → actual +0.620 · **miss +0.348%** (1.0 sd) · SLOWER than predicted

- **Teammate**: SAI missed +0.418% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 30, Sprint 17, Sprint Qualifying 13
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q1 (90.638s)  [Q1 90.638  Q2 91.341]
- **SCREEN** · WENT SLOWER  its later segment was worse than Q1 — the counted lap is not its last attempt
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 90.743s, slower than its counted 90.638s — no effect on the number
- **Race control** (qualifying):
    - `2026-07-04 15:53:22  CAR 23 (ALB) TIME 1:30.743 DELETED - TRACK LIMITS AT TURN 9 LAP 14 16:47:17`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### SAI · Williams

predicted +0.118 → actual +0.535 · **miss +0.418%** (1.2 sd) · SLOWER than predicted

- **Teammate**: ALB missed +0.348% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 33, Sprint 17, Sprint Qualifying 12
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 5
- **SCREEN** · BEST LAP from Q1 (90.562s)  [Q1 90.562  Q2 90.623]
- **SCREEN** · WENT SLOWER  its later segment was worse than Q1 — the counted lap is not its last attempt
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 93.460s, slower than its counted 90.562s — no effect on the number
- **Race control** (qualifying):
    - `2026-07-04 15:03:59  CAR 55 (SAI) TIME 1:33.460 DELETED - TRACK LIMITS AT TURN 3 LAP 3 16:02:18`

  > category: ______   note: ______

#### COL · Alpine

predicted +0.224 → actual +1.383 · **miss +1.160%** (3.3 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Sprint 17, Sprint Qualifying 9
- **SCREEN** · ATTEMPTS  1 flying laps against a field median of 5
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 1 vs 5 predicts a +0.68% penalty, moving the miss +1.160% → +0.480%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (91.321s)  [Q1 91.321]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-07-04 15:19:26  CAR 43 (COL) LAP DELETED - TRACK LIMITS AT TURN 13 LAP 6 16:16:56 (PIT)`

  > category: ______   note: ______

### RACE PACE

#### BOT · Cadillac

predicted +2.235 → actual +1.692 · **miss -0.544%** (1.2 sd) · FASTER than predicted

- **Teammate**: PER missed -0.485% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 29 clean long-run laps (field median 32) · sessions run: Practice_1 22, Sprint 17, Sprint Qualifying 6
- **What made the actual**: 29 clean laps of 52 run (laps 3–45 of 52) · MEDIUM 18, HARD 11
- **Dropped before the median**: 10 dirty-air, 18 perturbed, 4 invalid
- **What the filter did**: kept 56% of his laps (field 52%). Model measured +1.760%; over EVERY racing lap he is +2.179%. Scoring him on all laps would move the miss -0.544% → **-0.125%** (shrinks by 77%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to -0.125%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- *(13 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 29 (5.1s stationary); lap 46  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.790 → actual +1.306 · **miss -0.485%** (1.1 sd) · FASTER than predicted

- **Teammate**: BOT missed -0.544% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 25 clean long-run laps (field median 32) · sessions run: Practice_1 23, Sprint 16, Sprint Qualifying 6
- **What made the actual**: 27 clean laps of 52 run (laps 4–45 of 52) · MEDIUM 14, HARD 13
- **Dropped before the median**: 11 dirty-air, 17 perturbed, 5 invalid
- **What the filter did**: kept 52% of his laps (field 52%). Model measured +1.374%; over EVERY racing lap he is +1.482%. Scoring him on all laps would move the miss -0.485% → **-0.377%** (shrinks by 22%).
- *(13 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 21 (2.9s stationary); lap 46  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### ANT · Mercedes

predicted -2.039 → actual -1.707 · **miss +0.332%** (1.0 sd) · SLOWER than predicted

- **Teammate**: RUS missed +0.359% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 33 clean long-run laps (field median 32) · sessions run: Practice_1 29, Sprint 17, Sprint Qualifying 15
- **What made the actual**: 27 clean laps of 52 run (laps 11–46 of 52) · MEDIUM 25, HARD 2
- **Dropped before the median**: 13 dirty-air, 16 perturbed, 11 invalid
- **What the filter did**: kept 52% of his laps (field 52%). Model measured -1.640%; over EVERY racing lap he is -1.630%. Scoring him on all laps would move the miss +0.332% → **+0.342%** (GROWS by 3%).
- **SCREEN** · PACE STEP  +0.83% at lap 17 (slower afterwards; bigger than 97% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-05 15:11:36  CAR 12 (ANT) TIME 2:17.782 DELETED - TRACK LIMITS AT TURN 9 LAP 42 16:10:38`
    - `2026-07-05 15:11:38  CAR 12 (ANT) TIME 2:17.782 DELETED - TRACK LIMITS AT TURN 15 LAP 42 16:11:09`
    - `2026-07-05 15:13:00  CAR 12 (ANT) LAP DELETED - TRACK LIMITS AT TURN 6 LAP 43 16:12:00 (PIT)`
    - `2026-07-05 15:13:05  BLACK AND WHITE FLAG FOR CAR 12 (ANT) - TRACK LIMITS`
    - `2026-07-05 15:15:14  CAR 12 (ANT) TIME 2:01.316 DELETED - TRACK LIMITS AT TURN 6 LAP 44 16:14:04`
    - `2026-07-05 15:16:12  INCIDENT INVOLVING CAR 12 (ANT) NOTED - TRACK LIMITS`
    - `2026-07-05 15:16:26  FIA STEWARDS: INCIDENT INVOLVING CAR 12 (ANT) UNDER INVESTIGATION - TRACK LIMITS`
    - `2026-07-05 15:16:58  FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 12 (ANT) - TRACK LIMITS`
- **Incident** lap 46: off-track — TRACK LIMITS → penalty: 5 second time penalty
- **Pit stops** (3): lap 35 (2.4s stationary); lap 41; lap 43  ·  *2 not in pitstops.parquet*
- **Radio** 15:08:59: "Something's broken in the car."
- **Radio** 15:10:31: "No Bono, the suspension is broken. Okay, copy, copy."
- **Radio** 15:11:01: "We think it is just the wheel shield left hand side."
- **Radio** 15:13:04: "Okay, we're going to try to box the car, we'll try and remove the wheel shield and go again."
- **Radio** 15:15:05: "I may not, there's something deeper, I have no front, the wheel is in the air. OK, we'll box the car, so this is to retire."
- **Radio** 15:16:07: "We are just in P10, we've got Colapinto behind."
- **Radio** 15:18:10: "I'm going to go first."
- **Radio** 15:22:43: "Ah f*** mate, everything is going against us, unbelievable. Yes mate, it feels like one of those days."
- **Radio** 15:24:16: "We do have a five-second penalty for track limits. Yeah, but that's a joke mate, I didn't do it on purpose. Like, the car was broken. Yeah, understood. Like, I wasn't even getting time. Yeah, I know mate, I know mate."

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.999 → actual -1.639 · **miss +0.359%** (1.2 sd) · SLOWER than predicted

- **Teammate**: ANT missed +0.332% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 34 clean long-run laps (field median 32) · sessions run: Practice_1 31, Sprint 17, Sprint Qualifying 15
- **What made the actual**: 28 clean laps of 52 run (laps 4–46 of 52) · MEDIUM 26, HARD 2
- **Dropped before the median**: 13 dirty-air, 14 perturbed, 9 invalid
- **What the filter did**: kept 54% of his laps (field 52%). Model measured -1.571%; over EVERY racing lap he is -1.447%. Scoring him on all laps would move the miss +0.359% → **+0.483%** (GROWS by 34%).
- **SCREEN** · PACE STEP  -0.54% at lap 25 (faster afterwards; bigger than 90% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-05 14:59:46  TURN 15 INCIDENT INVOLVING CARS 63 (RUS) AND 3 (VER) NOTED (15:57:46)`
    - `2026-07-05 15:07:07  FIA STEWARDS: TURN 15 INCIDENT INVOLVING CARS 63 (RUS) AND 3 (VER) REVIEWED NO FURTHER INVESTIGATION (15:57:46)`
- **Incident** lap 36: contact — INCIDENT (reason unstated) vs VER → no action
- **Pit stops** (2): lap 23 (3.0s stationary); lap 34  ·  *1 not in pitstops.parquet*
- **Radio** 14:56:18: "Slow puncture right rear, move me or you do."
- **Radio** 14:59:22: "oh my god"
- **Radio** 15:33:22: "Yeah George, I think straight line was okay in the race."

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.