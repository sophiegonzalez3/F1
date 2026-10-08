# WHY THE MODEL MISSED — evidence dossier
2026 R15 · Azerbaijan Grand Prix · dossier built 2026-10-06

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
Practice_1   air 29.1C  track 50.4C (range 49-51)  all on slicks
Practice_2   air 29.3C  track 44.9C (range 41-49)  all on slicks
Practice_3   air 25.4C  track 43.5C (range 0-47)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 24.4C  track 38.1C (range 34-41)  all on slicks
Race         air 26.3C  track 43.4C (range 0-48)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.159 s/lap   (-0.15% of a lap)
  MEDIUM   +0.159 s/lap   (+0.15% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 38% of each driver's laps (range 3–73%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-09-26 11:58:05  SAFETY CAR DEPLOYED
  2026-09-26 12:06:24  LAPPED CARS MAY NOW OVERTAKE THE SAFETY CAR: 77
  2026-09-26 12:09:15  SAFETY CAR IN THIS LAP
  2026-09-26 12:12:40  SAFETY CAR DEPLOYED
  2026-09-26 12:17:06  SAFETY CAR IN THIS LAP
```

## 2 · Per-driver evidence

### QUALIFYING

#### SAI · Williams

predicted +1.225 → actual -0.124 · **miss -1.349%** (2.4 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 22, Practice_3 24
- **SCREEN** · ATTEMPTS  13 flying laps against a field median of 12
- **SCREEN** · BEST LAP from Q3 (104.566s)  [Q1 105.104  Q2 104.629  Q3 104.566]
- **SCREEN** · deleted lap 144.687s, slower than its counted 104.566s — no effect on the number
- **Race control** (qualifying):
    - `2026-09-25 13:02:09  CAR 55 (SAI) TIME 2:24.687 DELETED - TRACK LIMITS AT TURN 15 LAP 23 17:00:45`
    - `2026-09-25 13:07:46  INCIDENT INVOLVING CAR 55 (SAI) NOTED - YELLOW FLAG INFRINGEMENT (17:03:40)`
    - `2026-09-25 13:10:41  FIA STEWARDS: INCIDENT INVOLVING CAR 55 (SAI) WILL BE INVESTIGATED AFTER THE SESSION - YELLOW FLAG INFRINGEMENT (17:03:40)`

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.160 → actual -1.883 · **miss -0.724%** (2.2 sd) · FASTER than predicted

- **Teammate**: ANT missed +1.524% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 3) · sessions run: Practice_1 24, Practice_2 24, Practice_3 21
- **SCREEN** · ATTEMPTS  20 flying laps against a field median of 12
- **SCREEN** · BEST LAP from Q3 (102.526s)  [Q1 103.615  Q2 103.462  Q3 102.526]

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.708 → actual +0.006 · **miss -0.702%** (1.6 sd) · FASTER than predicted

- **Teammate**: BEA missed -0.530% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 3) · sessions run: Practice_1 19, Practice_2 25, Practice_3 21
- **SCREEN** · ATTEMPTS  14 flying laps against a field median of 12
- **SCREEN** · BEST LAP from Q2 (105.016s)  [Q1 105.039  Q2 105.016]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-09-25 12:44:58  INCIDENT INVOLVING CAR 31 (OCO) NOTED - YELLOW FLAG INFRINGEMENT (16:42:35)`
    - `2026-09-25 12:45:46  CAR 31 (OCO) LAP DELETED - TRACK LIMITS AT TURN 2 LAP 19 16:43:26 (PIT)`

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.044 → actual -0.623 · **miss -0.667%** (1.4 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 23, Practice_3 20
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  12 flying laps against a field median of 12
- **SCREEN** · BEST LAP from Q3 (104.047s)  [Q1 104.489  Q2 104.106  Q3 104.047]
- **Race control** (qualifying):
    - `2026-09-25 12:12:36  CAR 10 (GAS) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 5 16:10:18 (PIT)`

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.545 → actual +0.015 · **miss -0.530%** (1.2 sd) · FASTER than predicted

- **Teammate**: OCO missed -0.702% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 9, Practice_3 25
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  13 flying laps against a field median of 12
- **SCREEN** · BEST LAP from Q2 (104.775s)  [Q1 105.228  Q2 104.775]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### BOT · Cadillac

predicted +1.867 → actual +3.101 · **miss +1.234%** (2.0 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 0 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 26, Practice_3 19
- **SCREEN** · THIN READ  the model had 0 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 12
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 6 vs 12 predicts a +1.02% penalty, moving the miss +1.234% → +0.214%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (108.290s)  [Q1 108.290]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · DELETED LAP WAS FASTER  107.147s vs counted 108.290s — DOUBLE YELLOW AT TURN 3 LAP 10  (this DOES move the actual)
- **Race control** (qualifying):
    - `2026-09-25 12:24:16  CAR 77 (BOT) TIME 1:47.147 DELETED - DOUBLE YELLOW AT TURN 3 LAP 10 16:21:53`
    - `2026-09-25 12:26:58  INCIDENT INVOLVING CAR 77 (BOT) NOTED - YELLOW FLAG INFRINGEMENT (16:21:45)`
    - `2026-09-25 12:28:47  FIA STEWARDS: INCIDENT INVOLVING CAR 77 (BOT) REVIEWED NO FURTHER INVESTIGATION - YELLOW FLAG INFRINGEMENT (16:21:45)`

  > category: ______   note: ______

#### ANT · Mercedes

predicted -1.076 → actual +0.449 · **miss +1.524%** (4.6 sd) · SLOWER than predicted

- **Teammate**: RUS missed -0.724% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 3) · sessions run: Practice_1 9, Practice_2 16, Practice_3 21
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 3 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 12
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 12 predicts a +1.53% penalty, moving the miss +1.524% → -0.006%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (105.504s)  [Q1 105.504]
- **SCREEN** · NO TIME IN Q2  reached Q2 (P16) but set no lap there — the counted lap is a Q1 lap, so it under-states what the car could do. Ask why (a sacrificed run, a tow, a grid penalty, a problem)
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### HUL · Audi

predicted -0.780 → actual +0.845 · **miss +1.625%** (3.0 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 6 clean quali-sim laps (field median 3) · sessions run: Practice_1 22, Practice_2 20, Practice_3 18
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 12
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 6 vs 12 predicts a +1.02% penalty, moving the miss +1.625% → +0.605%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (105.920s)  [Q1 105.920]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### OCO · Haas F1 Team

predicted +0.890 → actual +0.226 · **miss -0.665%** (1.3 sd) · FASTER than predicted

- **Teammate**: BEA missed -0.544% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 29 clean long-run laps (field median 34) · sessions run: Practice_1 19, Practice_2 25, Practice_3 21
- **What made the actual**: 10 clean laps of 51 run (laps 10–49 of 51) · MEDIUM 9, SOFT 1
- **Dropped before the median**: 33 dirty-air, 16 perturbed, 9 invalid
- **What the filter did**: kept 20% of his laps (field 38%). Model measured +0.059%; over EVERY racing lap he is +0.080%. Scoring him on all laps would move the miss -0.665% → **-0.644%** (shrinks by 3%).
- **SCREEN** · THIN SLICE  only 20% of his laps survived against a field 38%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · THIN SAMPLE  only 10 clean laps entered the median (field median 15+ is normal)
- **Race control** (race):
    - `2026-09-26 12:45:44  CAR 31 (OCO) TIME 1:48.925 DELETED - TRACK LIMITS AT TURN 15 LAP 51 16:41:51`
- **Pit stops** (2): lap 30 (3.3s stationary); lap 36

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.709 → actual +0.165 · **miss -0.544%** (1.0 sd) · FASTER than predicted

- **Teammate**: OCO missed -0.665% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 32 clean long-run laps (field median 34) · sessions run: Practice_1 22, Practice_2 9, Practice_3 25
- **What made the actual**: 20 clean laps of 51 run (laps 6–28 of 51) · SOFT 20
- **Dropped before the median**: 21 dirty-air, 18 perturbed, 9 invalid
- **What the filter did**: kept 39% of his laps (field 38%). Model measured -0.002%; over EVERY racing lap he is -0.010%. Scoring him on all laps would move the miss -0.544% → **-0.552%** (GROWS by 1%).
- **SCREEN** · TRUNCATED  last clean lap 28 of 51 — the median covers only the first 55% of the race
- **SCREEN** · COMPOUND SKEW  ran SOFT 100% vs field MEDIUM 58%, SOFT 42% — worth -0.17% of a lap at this race's measured offsets
- **Race control** (race):
    - `2026-09-26 12:45:49  CAR 87 (BEA) TIME 1:48.360 DELETED - TRACK LIMITS AT TURN 15 LAP 51 16:41:53`
- **Pit stops** (2): lap 30 (3.5s stationary); lap 36
- **Radio** 10:59:17: "When in the pit stop, remind me of the white line on pit entry, it's quite easy to cross accidentally, a lot of F2 drivers did it."

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.072 → actual -0.389 · **miss -0.461%** (1.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 34 clean long-run laps (field median 34) · sessions run: Practice_1 22, Practice_2 23, Practice_3 20
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 20 clean laps of 36 run (laps 10–29 of 51) · MEDIUM 20
- **Dropped before the median**: 9 dirty-air, 10 perturbed, 6 invalid
- **What the filter did**: kept 56% of his laps (field 38%). Model measured -0.555%; over EVERY racing lap he is -0.598%. Scoring him on all laps would move the miss -0.461% → **-0.504%** (GROWS by 9%).
- **SCREEN** · TRUNCATED  last clean lap 29 of 51 — the median covers only the first 57% of the race
- **Race control** (race):
    - `2026-09-26 12:18:38  TURN 1 INCIDENT INVOLVING CARS 1 (NOR), 10 (GAS) AND 43 (COL) NOTED`
    - `2026-09-26 12:24:07  UPDATE: TURN 1 INCIDENT INVOLVING CARS 1 (NOR), 10 (GAS) AND 43 (COL) NOTED - CAUSING A COLLISION (16:11:31)`
    - `2026-09-26 12:24:27  FIA STEWARDS: TURN 1 INCIDENT INVOLVING CARS 1 (NOR), 10 (GAS) AND 43 (COL) UNDER INVESTIGATION - CAUSING A COLLISION (16:11:31)`
- **Pit stops** (1): lap 30 (2.6s stationary)
- **Radio** 10:58:16: "Come on, let's have a good day guys."
- **Radio** 12:17:33: "Oh my God, I cannot believe it, cannot believe it, so many points gone."

  > category: ______   note: ______

#### ANT · Mercedes

predicted -1.610 → actual -0.910 · **miss +0.700%** (1.8 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 24 clean long-run laps (field median 34) · sessions run: Practice_1 9, Practice_2 16, Practice_3 21
- **What made the actual**: 20 clean laps of 51 run (laps 12–48 of 51) · MEDIUM 13, SOFT 7
- **Dropped before the median**: 24 dirty-air, 15 perturbed, 9 invalid
- **What the filter did**: kept 39% of his laps (field 38%). Model measured -1.076%; over EVERY racing lap he is -1.009%. Scoring him on all laps would move the miss +0.700% → **+0.767%** (GROWS by 10%).
- **Pit stops** (2): lap 30 (2.6s stationary); lap 36

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.