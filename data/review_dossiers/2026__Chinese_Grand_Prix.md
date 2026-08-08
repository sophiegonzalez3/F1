# WHY THE MODEL MISSED — evidence dossier
2026 R2 · Chinese Grand Prix · dossier built 2026-08-08

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
Practice_1   air 13.0C  track 21.3C (range 11-28)  all on slicks
Practice_2   —
Practice_3   —
Sprint_Qualifying air 16.4C  track 28.2C (range 25-31)  all on slicks
Sprint_Shootout —
Sprint       air 14.9C  track 15.4C (range 12-23)  all on slicks
Qualifying   air 17.8C  track 31.0C (range 29-32)  all on slicks
Race         air 15.6C  track 22.6C (range 20-28)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.487 s/lap   (-0.50% of a lap)
  MEDIUM   -0.073 s/lap   (-0.08% of a lap)
  HARD     +0.185 s/lap   (+0.19% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 39% of each driver's laps (range 10–77%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-03-15 07:20:04  SAFETY CAR DEPLOYED
  2026-03-15 07:26:11  SAFETY CAR IN THIS LAP
```

## 2 · Per-driver evidence

### QUALIFYING

#### COL · Alpine

predicted +0.863 → actual -0.177 · **miss -1.040%** (1.4 sd) · FASTER than predicted

- **Teammate**: GAS missed -1.016% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Sprint 19, Sprint Qualifying 12
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q2 (93.357s)  [Q1 93.634  Q2 93.357]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.511 → actual -0.505 · **miss -1.016%** (1.3 sd) · FASTER than predicted

- **Teammate**: COL missed -1.040% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 15
- **SCREEN** · ATTEMPTS  9 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (92.873s)  [Q1 93.788  Q2 93.003  Q3 92.873]
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### RUS · Mercedes

predicted -2.209 → actual -1.070 · **miss +1.138%** (1.6 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 7 clean quali-sim laps (field median 3) · sessions run: Practice_1 29, Sprint 19, Sprint Qualifying 13
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 6
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 4 vs 6 predicts a +0.26% penalty, moving the miss +1.138% → +0.883%, cutting it by 22% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q3 (92.286s)  [Q1 93.262  Q2 92.523  Q3 92.286]
- **SCREEN** · deleted lap 117.937s, slower than its counted 92.286s — no effect on the number
- **Race control** (qualifying):
    - `2026-03-14 07:12:12  CAR 63 (RUS) LAP DELETED - TRACK LIMITS AT TURN 2 LAP 4 15:10:15 (PIT)`
    - `2026-03-14 07:42:02  CAR 63 (RUS) TIME 1:57.937 DELETED - DOUBLE YELLOW AT TURN 16`
    - `2026-03-14 08:03:40  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 63 (RUS) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-03-14 08:03:49  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 63 (RUS) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-03-14 08:04:23  FIA STEWARDS: Q3 INCIDENT INVOLVING CAR 63 (RUS) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

### RACE PACE

#### COL · Alpine

predicted +0.561 → actual -0.307 · **miss -0.869%** (1.5 sd) · FASTER than predicted

- **Teammate**: GAS missed -0.811% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 33 clean long-run laps (field median 32) · sessions run: Practice_1 26, Sprint 19, Sprint Qualifying 12
- **What made the actual**: 25 clean laps of 55 run (laps 2–47 of 56) · MEDIUM 13, HARD 12
- **Dropped before the median**: 22 dirty-air, 14 perturbed, 5 invalid
- **What the filter did**: kept 45% of his laps (field 39%). Model measured -0.324%; over EVERY racing lap he is -0.150%. Scoring him on all laps would move the miss -0.869% → **-0.695%** (shrinks by 20%).
- **SCREEN** · TRUNCATED  last clean lap 47 of 56 — the median covers only the first 84% of the race
- **Race control** (race):
    - `2026-03-15 08:01:25  TURN 2 INCIDENT INVOLVING CARS 31 (OCO) AND 43 (COL) NOTED - CAUSING A COLLISION`
    - `2026-03-15 08:01:43  FIA STEWARDS: TURN 2 INCIDENT INVOLVING CARS 31 (OCO) AND 43 (COL) UNDER INVESTIGATION - CAUSING A COLLISION`
- *(2 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 34: contact — CAUSING A COLLISION vs OCO → investigated
- **Pit stops** (1): lap 32 (2.6s stationary)

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.377 → actual -0.434 · **miss -0.811%** (1.4 sd) · FASTER than predicted

- **Teammate**: COL missed -0.869% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 33 clean long-run laps (field median 32) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 15
- **What made the actual**: 32 clean laps of 56 run (laps 4–56 of 56) · HARD 26, MEDIUM 6
- **Dropped before the median**: 19 dirty-air, 13 perturbed, 4 invalid
- **What the filter did**: kept 57% of his laps (field 39%). Model measured -0.452%; over EVERY racing lap he is -0.543%. Scoring him on all laps would move the miss -0.811% → **-0.902%** (GROWS by 11%).
- **Race control** (race):
    - `2026-03-15 07:36:56  TURN 6 INCIDENT INVOLVING CARS 10 (GAS) AND 3 (VER) NOTED - MOVING UNDER BRAKING`
    - `2026-03-15 07:41:41  TURN 6 INCIDENT INVOLVING CARS 10 (GAS) AND 3 (VER) NOTED - MOVING UNDER BRAKING`
    - `2026-03-15 07:43:13  FIA STEWARDS: TURN 6 INCIDENT INVOLVING CARS 10 (GAS) AND 3 (VER) REVIEWED NO FURTHER INVESTIGATION - MOVING UNDER BRAKING`
    - `2026-03-15 07:48:39  FIA STEWARDS: TURN 6 INCIDENT INVOLVING CARS 10 (GAS) AND 3 (VER) REVIEWED NO FURTHER INVESTIGATION - MOVING UNDER BRAKING`
- **Incident** lap 19: contact — MOVING UNDER BRAKING vs VER → no action
- **Pit stops** (1): lap 10 (2.8s stationary)

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.367 → actual +2.114 · **miss +0.747%** (1.3 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 20 clean long-run laps (field median 32) · sessions run: Practice_1 13, Sprint 19
- **What made the actual**: 20 clean laps of 55 run (laps 2–55 of 56) · HARD 12, MEDIUM 8
- **Dropped before the median**: 27 dirty-air, 13 perturbed, 3 invalid
- **What the filter did**: kept 36% of his laps (field 39%). Model measured +2.091%; over EVERY racing lap he is +1.910%. Scoring him on all laps would move the miss +0.747% → **+0.566%** (shrinks by 24%).
- **Race control** (race):
    - `2026-03-15 07:07:33  TURN 3 INCIDENT INVOLVING CARS 11 (PER) AND 77 (BOT) NOTED - CAUSING A COLLISION`
    - `2026-03-15 07:11:17  FIA STEWARDS: TURN 3 INCIDENT INVOLVING CARS 11 (PER) AND 77 (BOT) REVIEWED NO FURTHER INVESTIGATION - CAUSING A COLLISION`
- *(6 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 3: contact — CAUSING A COLLISION vs BOT → no action
- **Pit stops** (1): lap 11 (5.5s stationary)

  > category: ______   note: ______

#### LEC · Ferrari

predicted -1.499 → actual -0.675 · **miss +0.824%** (1.4 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 31 clean long-run laps (field median 32) · sessions run: Practice_1 28, Sprint 19, Sprint Qualifying 16
- **What made the actual**: 18 clean laps of 56 run (laps 16–56 of 56) · HARD 18
- **Dropped before the median**: 31 dirty-air, 14 perturbed, 4 invalid
- **What the filter did**: kept 32% of his laps (field 39%). Model measured -0.692%; over EVERY racing lap he is -1.030%. Scoring him on all laps would move the miss +0.824% → **+0.486%** (shrinks by 41%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.486%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **Pit stops** (1): lap 10 (3.5s stationary)

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.