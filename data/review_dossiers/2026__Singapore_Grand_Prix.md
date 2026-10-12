# WHY THE MODEL MISSED — evidence dossier
2026 R17 · Singapore Grand Prix · dossier built 2026-10-12

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
Practice_1   air 32.2C  track 49.3C (range 0-54)  all on slicks
Practice_2   —
Practice_3   —
Sprint_Qualifying air 30.4C  track 42.6C (range 0-45)  all on slicks
Sprint_Shootout —
Sprint       air 29.9C  track 43.4C (range 38-50)  INTERMEDIATE 100% of laps  rain on 16% of samples
Qualifying   air 29.8C  track 39.4C (range 0-42)  all on slicks
Race         air 30.3C  track 42.5C (range 0-45)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.040 s/lap   (-0.04% of a lap)
  MEDIUM   +0.040 s/lap   (+0.04% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 50% of each driver's laps (range 21–82%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-10-11 12:16:35  VSC DEPLOYED
  2026-10-11 12:17:40  VSC ENDING
  2026-10-11 13:07:14  VSC DEPLOYED
  2026-10-11 13:09:13  VSC ENDING
```

## 2 · Per-driver evidence

### QUALIFYING

#### BEA · Haas F1 Team

predicted +0.673 → actual +0.009 · **miss -0.665%** (1.6 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 2) · sessions run: Practice_1 29, Sprint 20, Sprint Qualifying 12
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 7
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 4 vs 7 predicts a +0.51% penalty, moving the miss -0.665% → -1.175% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q2 (92.908s)  [Q1 93.356  Q2 92.908]
- **SCREEN** · ELIMINATED in Q2 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.039 → actual -1.478 · **miss -0.440%** (1.3 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 2) · sessions run: Practice_1 26, Sprint 20, Sprint Qualifying 14
- **SCREEN** · ATTEMPTS  13 flying laps against a field median of 7
- **SCREEN** · BEST LAP from Q3 (91.496s)  [Q1 92.429  Q2 91.529  Q3 91.496]
- **Race control** (qualifying):
    - `2026-10-10 13:53:17  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-10 13:53:30  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-10 14:33:16  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### BOT · Cadillac

predicted +1.634 → actual +2.875 · **miss +1.241%** (2.8 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 1 clean quali-sim laps (field median 2) · sessions run: Practice_1 25, Sprint 6, Sprint Qualifying 9
- **SCREEN** · THIN READ  the model had 1 laps of this type against a field median of 2 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 7
- **SCREEN** · BEST LAP from Q1 (95.984s)  [Q1 95.984]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **Race control** (qualifying):
    - `2026-10-10 13:53:17  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-10 13:53:30  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-10-10 14:33:16  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 6 (HAD), 77 (BOT), 18 (STR), 44 (HAM), 81 (PIA) AND 5 (BOR) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

### RACE PACE

#### LAW · Racing Bulls

predicted +0.239 → actual -0.319 · **miss -0.557%** (1.2 sd) · FASTER than predicted

- **Teammate**: LIN missed +0.537% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 27 clean long-run laps (field median 27) · sessions run: Practice_1 25, Sprint 20, Sprint Qualifying 15
- **What made the actual**: 51 clean laps of 62 run (laps 3–62 of 62) · MEDIUM 27, SOFT 24
- **Dropped before the median**: 4 dirty-air, 10 perturbed, 4 invalid
- **What the filter did**: kept 82% of his laps (field 50%). Model measured -0.392%; over EVERY racing lap he is -0.369%. Scoring him on all laps would move the miss -0.557% → **-0.534%** (shrinks by 4%).
- **Race control** (race):
    - `2026-10-11 13:04:17  CAR 30 (LAW) TIME 1:38.014 DELETED - TRACK LIMITS AT TURN 2 LAP 36 21:02:33`
- **Pit stops** (1): lap 31 (2.8s stationary)

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.678 → actual +0.138 · **miss -0.539%** (1.0 sd) · FASTER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 25 clean long-run laps (field median 27) · sessions run: Practice_1 25, Sprint 20, Sprint Qualifying 12
- **What made the actual**: 39 clean laps of 61 run (laps 6–60 of 62) · MEDIUM 23, SOFT 16
- **Dropped before the median**: 10 dirty-air, 17 perturbed, 4 invalid
- **What the filter did**: kept 64% of his laps (field 50%). Model measured +0.065%; over EVERY racing lap he is +0.269%. Scoring him on all laps would move the miss -0.539% → **-0.335%** (shrinks by 38%).
- **SCREEN** · PACE STEP  +0.64% at lap 43 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-10-11 13:39:32  CAR 31 (OCO) TIME 1:40.819 DELETED - TRACK LIMITS AT TURN 7 LAP 57 21:38:21`
- *(3 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 28 (3.0s stationary)

  > category: ______   note: ______

#### COL · Alpine

predicted +0.168 → actual +0.622 · **miss +0.455%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 14 clean long-run laps (field median 27) · sessions run: Practice_1 27, Sprint 2, Sprint Qualifying 12
- **SCREEN** · THIN READ  the model had 14 laps of this type against a field median of 27 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **Did not finish**: `Retired` (classified `R`) — the median rests only on the laps it completed, and whatever ended its race may have been slowing it before that
- **What made the actual**: 14 clean laps of 30 run (laps 10–29 of 62) · MEDIUM 14
- **Dropped before the median**: 14 dirty-air, 7 perturbed, 1 invalid
- **What the filter did**: kept 47% of his laps (field 50%). Model measured +0.549%; over EVERY racing lap he is +0.702%. Scoring him on all laps would move the miss +0.455% → **+0.608%** (GROWS by 34%).
- **SCREEN** · THIN SAMPLE  only 14 clean laps entered the median (field median 15+ is normal)
- **SCREEN** · TRUNCATED  last clean lap 29 of 62 — the median covers only the first 47% of the race

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted +0.426 → actual +0.962 · **miss +0.537%** (1.1 sd) · SLOWER than predicted

- **Teammate**: LAW missed -0.557% — OPPOSITE direction. Opposite directions point at something driver-specific.
- **Practice evidence the model read**: 29 clean long-run laps (field median 27) · sessions run: Practice_1 27, Sprint 20, Sprint Qualifying 6
- **What made the actual**: 23 clean laps of 61 run (laps 4–61 of 62) · MEDIUM 14, SOFT 9
- **Dropped before the median**: 32 dirty-air, 13 perturbed, 3 invalid
- **What the filter did**: kept 38% of his laps (field 50%). Model measured +0.889%; over EVERY racing lap he is +0.853%. Scoring him on all laps would move the miss +0.537% → **+0.501%** (shrinks by 7%).
- **SCREEN** · THIN SLICE  only 38% of his laps survived against a field 50%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · PACE STEP  +1.30% at lap 32 (slower afterwards; bigger than 97% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-10-11 12:19:46  CAR 41 (LIN) TIME 1:56.656 DELETED - TRACK LIMITS AT TURN 2 LAP 8 20:15:41`
- *(5 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 26 (2.5s stationary)
- **Radio** 12:15:33: "That was quite dangerous in what Sainz did. I had to brake, all three crash."

  > category: ______   note: ______

#### BOT · Cadillac

predicted +2.172 → actual +2.740 · **miss +0.568%** (1.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 15 clean long-run laps (field median 27) · sessions run: Practice_1 25, Sprint 6, Sprint Qualifying 9
- **SCREEN** · THIN READ  the model had 15 laps of this type against a field median of 27 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **What made the actual**: 41 clean laps of 59 run (laps 5–59 of 62) · SOFT 24, MEDIUM 17
- **Dropped before the median**: 4 dirty-air, 15 perturbed, 3 invalid
- **What the filter did**: kept 69% of his laps (field 50%). Model measured +2.667%; over EVERY racing lap he is +2.998%. Scoring him on all laps would move the miss +0.568% → **+0.900%** (GROWS by 58%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to +0.900%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **Race control** (race):
    - `2026-10-11 13:00:15  CAR 77 (BOT) TIME 1:43.948 DELETED - TRACK LIMITS AT TURN 7 LAP 32 20:58:19`
- *(26 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (1): lap 28 (7.4s stationary)

  > category: ______   note: ______

#### RUS · Mercedes

predicted -1.477 → actual -0.394 · **miss +1.084%** (2.1 sd) · SLOWER than predicted

- **Teammate**: measured and inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 28 clean long-run laps (field median 27) · sessions run: Practice_1 28, Sprint 2, Sprint Qualifying 21
- **What made the actual**: 13 clean laps of 62 run (laps 13–48 of 62) · MEDIUM 11, SOFT 2
- **Dropped before the median**: 46 dirty-air, 11 perturbed, 4 invalid
- **What the filter did**: kept 21% of his laps (field 50%). Model measured -0.467%; over EVERY racing lap he is -0.242%. Scoring him on all laps would move the miss +1.084% → **+1.309%** (GROWS by 21%).
- **SCREEN** · THIN SLICE  only 21% of his laps survived against a field 50%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · THIN SAMPLE  only 13 clean laps entered the median (field median 15+ is normal)
- **SCREEN** · TRUNCATED  last clean lap 48 of 62 — the median covers only the first 77% of the race
- **Race control** (race):
    - `2026-10-11 13:05:34  CAR 63 (RUS) TIME 1:38.502 DELETED - TRACK LIMITS AT TURN 2 LAP 37 21:03:56`
    - `2026-10-11 13:30:05  CAR 63 (RUS) TIME 1:38.393 DELETED - TRACK LIMITS AT TURN 16 LAP 51 21:29:01`
- **Pit stops** (1): lap 39 (2.6s stationary)

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.

**Whether you searched or not, put today's date in `press_checked` for every row you looked at — including the ones where you found nothing.** A blank `source` otherwise means both 'searched, nothing there' and 'never opened', and the next reader cannot tell them apart. Scope it to the drivers a search actually named, not to the whole event.