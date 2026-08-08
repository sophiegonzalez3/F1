# WHY THE MODEL MISSED — evidence dossier
2026 R10 · Belgian Grand Prix · dossier built 2026-08-08

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
Practice_1   air 24.0C  track 39.5C (range 34-43)
Practice_2   air 24.0C  track 33.1C (range 30-36)
Practice_3   air 20.3C  track 34.2C (range 32-37)
Qualifying   air 21.1C  track 36.1C (range 34-39)
Race         air 18.0C  track 31.0C (range 26-37)
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  SOFT     -0.265 s/lap   (-0.24% of a lap)
  MEDIUM   -0.104 s/lap   (-0.09% of a lap)
  HARD     +0.242 s/lap   (+0.22% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 43% of each driver's laps (range 2–68%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  2026-07-19 13:05:25  SAFETY CAR DEPLOYED
  2026-07-19 13:12:32  SAFETY CAR IN THIS LAP
```

## 2 · Per-driver evidence

### QUALIFYING

#### BOT · Cadillac

predicted +1.567 → actual +1.107 · **miss -0.460%** (1.2 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 8 clean quali-sim laps (field median 6) · sessions run: Practice_1 21, Practice_2 19, Practice_3 22
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q1 (107.823s)  [Q1 107.823]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

#### LIN · Racing Bulls

predicted -0.223 → actual -0.641 · **miss -0.418%** (1.0 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 7 clean quali-sim laps (field median 6) · sessions run: Practice_1 24, Practice_2 20, Practice_3 23
- **SCREEN** · ATTEMPTS  6 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (105.143s)  [Q1 106.191  Q2 105.629  Q3 105.143]

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.539 → actual +1.087 · **miss +0.548%** (1.4 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 6) · sessions run: Practice_1 21, Practice_2 19, Practice_3 22
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% shift, 62% of this +0.548% miss. Consider `measurement_artifact` before blaming the model.
- **SCREEN** · BEST LAP from Q1 (107.801s)  [Q1 107.801]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### HAD · Red Bull Racing

predicted -0.508 → actual -1.202 · **miss -0.694%** (1.1 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 25 clean long-run laps (field median 17) · sessions run: Practice_1 23, Practice_2 20, Practice_3 19
- **What made the actual**: 28 clean laps of 44 run (laps 5–44 of 44) · HARD 28
- **Dropped before the median**: 10 dirty-air, 8 perturbed, 7 invalid
- **What the filter did**: kept 64% of his laps (field 43%). Model measured -1.526%; over EVERY racing lap he is -1.254% — a shift of **+0.272%**, 39% the size of the miss being explained.
- **SCREEN** · PACE STEP  -0.85% at lap 19 (faster afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-07-19 14:14:42  CAR 6 (HAD) TIME 1:50.241 DELETED - TRACK LIMITS AT TURN 19 LAP 36 16:14:16`
- **Pit stops** (3): lap 1 (3.6s stationary); lap 2; lap 20  ·  *2 not in pitstops.parquet*
- **Radio** 14:34:05: "Good pace today as well mate, good pace. Yeah, nothing I can do more honestly, so a lot, it's a bit frustrating because, yeah, I could be on this podium, so... Yeah, I've copied you there, unfortunately there's a penalty"

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.