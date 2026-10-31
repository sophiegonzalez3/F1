# WHY THE MODEL MISSED — evidence dossier
2026 R18 · United States Grand Prix · dossier built 2026-10-31

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
Practice_1   air 28.0C  track 41.1C (range 0-43)  all on slicks
Practice_2   air 29.6C  track 40.5C (range 0-43)  all on slicks
Practice_3   air 27.5C  track 39.2C (range 0-43)  all on slicks
Sprint_Qualifying —
Sprint_Shootout —
Sprint       —
Qualifying   air 29.7C  track 38.4C (range 36-41)  all on slicks
Race         air 27.0C  track 36.3C (range 0-39)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  HARD     -0.120 s/lap   (-0.12% of a lap)
  SOFT     +0.077 s/lap   (+0.08% of a lap)
  MEDIUM   +0.080 s/lap   (+0.08% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 54% of each driver's laps (range 12–79%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-10-25 20:06:06  VSC DEPLOYED
  2026-10-25 20:06:20  VSC ENDING
  2026-10-25 21:29:34  VSC DEPLOYED
  2026-10-25 21:33:25  VSC ENDING
```

## 2 · Per-driver evidence

### QUALIFYING

#### OCO · Haas F1 Team

predicted +0.427 → actual +0.872 · **miss +0.445%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 4 clean quali-sim laps (field median 3) · sessions run: Practice_1 26, Practice_2 26, Practice_3 18
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% penalty, moving the miss +0.445% → +0.275%, cutting it by 38% — worth recording, not enough to be the verdict.
- **SCREEN** · BEST LAP from Q1 (96.531s)  [Q1 96.531]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-10-24 21:21:35  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 81 (PIA), 63 (RUS), 12 (ANT) AND 43 (COL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-24 21:21:46  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 81 (PIA), 63 (RUS), 12 (ANT) AND 43 (COL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-24 22:03:37  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 31 (OCO), 81 (PIA), 63 (RUS), 12 (ANT) AND 43 (COL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

### RACE PACE

#### BOT · Cadillac

predicted +2.289 → actual +1.697 · **miss -0.592%** (1.1 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 21 clean long-run laps (field median 22) · sessions run: Practice_1 21, Practice_2 24, Practice_3 22
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 32 clean laps of 49 run (laps 5–48 of 56) · SOFT 17, HARD 15
- **Dropped before the median**: 10 dirty-air, 12 perturbed, 3 invalid
- **What the filter did**: kept 65% of his laps (field 54%). Model measured +1.507%; over EVERY racing lap he is +1.435%. Scoring him on all laps would move the miss -0.592% → **-0.665%** (GROWS by 12%).
- *(5 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 29

  > category: ______   note: ______

#### PIA · McLaren

predicted -0.948 → actual -0.280 · **miss +0.668%** (1.2 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 18 clean long-run laps (field median 22) · sessions run: Practice_1 23, Practice_2 27, Practice_3 16
- **What made the actual**: 30 clean laps of 56 run (laps 9–56 of 56) · HARD 24, MEDIUM 6
- **Dropped before the median**: 19 dirty-air, 15 perturbed, 6 invalid
- **What the filter did**: kept 54% of his laps (field 54%). Model measured -0.468%; over EVERY racing lap he is -0.634%. Scoring him on all laps would move the miss +0.668% → **+0.502%** (shrinks by 25%).
- **SCREEN** · PACE STEP  +0.68% at lap 33 (slower afterwards; bigger than 96% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-10-25 20:16:53  CAR 81 (PIA) TIME 1:42.300 DELETED - TRACK LIMITS AT TURN 12 LAP 7 15:15:17`
    - `2026-10-25 20:51:22  CAR 81 (PIA) TIME 1:42.880 DELETED - TRACK LIMITS AT TURN 2 LAP 26 15:47:01`
    - `2026-10-25 21:37:16  CAR 81 (PIA) TIME 1:41.297 DELETED - TRACK LIMITS AT TURN 12 LAP 54 16:36:01`
- **Pit stops** (1): lap 15

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.