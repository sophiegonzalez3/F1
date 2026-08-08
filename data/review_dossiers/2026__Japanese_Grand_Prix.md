# WHY THE MODEL MISSED — evidence dossier
2026 R3 · Japanese Grand Prix · dossier built 2026-08-08

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
Practice_1   air 16.4C  track 36.9C (range 32-39)  all on slicks
Practice_2   air 17.2C  track 28.6C (range 24-35)  all on slicks
Practice_3   air 16.1C  track 36.7C (range 34-39)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 16.5C  track 29.7C (range 26-33)  all on slicks
Race         air 18.6C  track 34.1C (range 29-38)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MEDIUM   -0.036 s/lap   (-0.04% of a lap)
  HARD     +0.036 s/lap   (+0.04% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 33% of each driver's laps (range 5–75%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-03-29 05:48:11  SAFETY CAR DEPLOYED
  2026-03-29 05:57:32  LAPPED CARS MAY NOW OVERTAKE THE SAFETY CAR: 77
  2026-03-29 06:00:06  SAFETY CAR IN THIS LAP
```

## 2 · Per-driver evidence

### QUALIFYING

#### GAS · Alpine

predicted -0.248 → actual -0.805 · **miss -0.557%** (1.2 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 4) · sessions run: Practice_1 25, Practice_2 29, Practice_3 20
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (89.691s)  [Q1 90.584  Q2 89.874  Q3 89.691]

  > category: ______   note: ______

#### HAD · Red Bull Racing

predicted -0.005 → actual -0.518 · **miss -0.513%** (1.2 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 6 clean quali-sim laps (field median 4) · sessions run: Practice_1 27, Practice_2 29, Practice_3 21
- **SCREEN** · ATTEMPTS  5 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (89.978s)  [Q1 90.662  Q2 90.104  Q3 89.978]
- **Race control** (qualifying):
    - `2026-03-28 06:19:23  TURN 14 INCIDENT INVOLVING CARS 55 (SAI) AND 6 (HAD) NOTED - IMPEDING`
    - `2026-03-28 06:20:53  FIA STEWARDS: TURN 14 INCIDENT INVOLVING CARS 55 (SAI) AND 6 (HAD) REVIEWED NO FURTHER INVESTIGATION - IMPEDING`

  > category: ______   note: ______

#### NOR · McLaren

predicted -1.476 → actual -1.118 · **miss +0.358%** (1.0 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 4) · sessions run: Practice_1 20, Practice_2 17, Practice_3 13
- **SCREEN** · ATTEMPTS  8 flying laps against a field median of 6
- **SCREEN** · BEST LAP from Q3 (89.409s)  [Q1 90.401  Q2 89.795  Q3 89.409]

  > category: ______   note: ______

#### ALO · Aston Martin

predicted +1.606 → actual +2.062 · **miss +0.456%** (1.2 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 4) · sessions run: Practice_2 24, Practice_3 14
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 6
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 6 predicts a +0.43% penalty, moving the miss +0.456% → +0.031%. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (92.646s)  [Q1 92.646]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### PIA · McLaren

predicted -0.833 → actual -1.658 · **miss -0.825%** (1.4 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 26 clean long-run laps (field median 28) · sessions run: Practice_1 23, Practice_2 29, Practice_3 19
- **What made the actual**: 40 clean laps of 53 run (laps 1–53 of 53) · HARD 24, MEDIUM 16
- **Dropped before the median**: 9 dirty-air, 9 perturbed, 8 invalid
- **What the filter did**: kept 75% of his laps (field 33%). Model measured -1.311%; over EVERY racing lap he is -1.642%. Scoring him on all laps would move the miss -0.825% → **-1.156%** (GROWS by 40%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -1.156%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **Pit stops** (1): lap 18 (2.4s stationary)

  > category: ______   note: ______

#### BOR · Audi

predicted -0.540 → actual +0.169 · **miss +0.709%** (1.3 sd) · SLOWER than predicted

- **Teammate**: NO actual for this kind — too few clean laps to measure (retirement or early exit). Scope is UNKNOWN, not driver-specific: check the other car's raw pace by hand before concluding anything about this driver.
- **Practice evidence the model read**: 24 clean long-run laps (field median 28) · sessions run: Practice_1 27, Practice_2 11, Practice_3 21
- **What made the actual**: 11 clean laps of 53 run (laps 30–53 of 53) · HARD 11
- **Dropped before the median**: 41 dirty-air, 11 perturbed, 6 invalid
- **What the filter did**: kept 21% of his laps (field 33%). Model measured +0.521%; over EVERY racing lap he is +0.109%. Scoring him on all laps would move the miss +0.709% → **+0.297%** (shrinks by 58%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.297%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- **SCREEN** · THIN SAMPLE  only 11 clean laps entered the median (field median 15+ is normal)
- **Pit stops** (1): lap 22 (2.6s stationary)

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.