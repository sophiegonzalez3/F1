# WHY THE MODEL MISSED — evidence dossier
2026 R7 · Barcelona Grand Prix · dossier built 2026-08-08

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
Practice_1   air 29.3C  track 48.7C (range 47-50)  all on slicks
Practice_2   air 29.5C  track 47.3C (range 44-50)  all on slicks
Practice_3   air 31.5C  track 48.2C (range 46-50)  all on slicks
Qualifying   air 30.7C  track 50.2C (range 48-52)  all on slicks
Race         air 30.5C  track 50.3C (range 48-52)  all on slicks
```

Within-driver compound offsets measured on this race's clean laps (negative = faster):

```
  MEDIUM   -0.136 s/lap   (-0.16% of a lap)
  HARD     -0.007 s/lap   (-0.01% of a lap)
  SOFT     +0.260 s/lap   (+0.31% of a lap)
```

Use these to price a compound story before believing it. A skew worth less than the miss is not the cause of the miss.

**How much of the race the model actually measured**: it kept a median of 54% of each driver's laps (range 7–82%). Everything else — dirty air, safety car, in/out — is gone before the median is taken. Read the per-driver 'what the filter did' line before writing any verdict: where the filter moves a driver further than the miss, the filter is the finding.

Race-control, session-wide:

```
  no safety car, VSC or red flag
```

## 2 · Per-driver evidence

### QUALIFYING

#### HAD · Red Bull Racing

predicted -0.199 → actual -0.679 · **miss -0.479%** (1.2 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 2 clean quali-sim laps (field median 4) · sessions run: Practice_2 30, Practice_3 15
- **SCREEN** · THIN READ  the model had 2 laps of this type against a field median of 4 — it was extrapolating for this car, so a large miss here is weak evidence about the model itself
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q3 (75.077s)  [Q1 76.427  Q2 75.754  Q3 75.077]

  > category: ______   note: ______

#### LAW · Racing Bulls

predicted -0.159 → actual -0.574 · **miss -0.415%** (1.2 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 6 clean quali-sim laps (field median 4) · sessions run: Practice_1 24, Practice_2 8, Practice_3 15
- **SCREEN** · ATTEMPTS  4 flying laps against a field median of 4
- **SCREEN** · BEST LAP from Q2 (75.585s)  [Q1 76.673  Q2 75.585  Q3 76.542]
- **SCREEN** · WENT SLOWER  its later segment was worse than Q2 — the counted lap is not its last attempt

  > category: ______   note: ______

#### ALB · Williams

predicted +0.719 → actual +1.317 · **miss +0.599%** (1.9 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 3 clean quali-sim laps (field median 4) · sessions run: Practice_2 29, Practice_3 15
- **SCREEN** · ATTEMPTS  3 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 3 vs 4 predicts a +0.17% penalty, moving the miss +0.599% → +0.429% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (77.424s)  [Q1 77.424]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real
- **SCREEN** · deleted lap 80.269s, slower than its counted 77.424s — no effect on the number
- **Race control** (qualifying):
    - `2026-06-13 14:10:36  CAR 23 (ALB) TIME 1:20.269 DELETED - TRACK LIMITS AT TURN 9 LAP 6 16:09:43`
    - `2026-06-13 14:20:44  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 55 (SAI), 23 (ALB), 81 (PIA), 31 (OCO), 77 (BOT), 18 (STR), 63 (RUS) AND 27 (HUL) NOTED - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-13 14:21:01  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 55 (SAI), 23 (ALB), 81 (PIA), 31 (OCO), 77 (BOT), 18 (STR), 63 (RUS) AND 27 (HUL) WILL BE INVESTIGATED AFTER THE SESSION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`
    - `2026-06-13 15:14:26  FIA STEWARDS: Q1 INCIDENT INVOLVING CARS 55 (SAI), 23 (ALB), 81 (PIA), 31 (OCO), 77 (BOT), 18 (STR), 63 (RUS) AND 27 (HUL) NO FURTHER ACTION - FAILING TO FOLLOW RACE DIRECTORS INSTRUCTIONS - MAXIMUM DELTA TIME`

  > category: ______   note: ______

#### ALO · Aston Martin

predicted +2.291 → actual +3.140 · **miss +0.850%** (2.8 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 5 clean quali-sim laps (field median 4) · sessions run: Practice_1 23, Practice_2 21, Practice_3 18
- **SCREEN** · ATTEMPTS  2 flying laps against a field median of 4
- **SCREEN** · FEW ATTEMPTS  the actual is a MINIMUM over those laps, worth 0.170% each — 2 vs 4 predicts a +0.34% penalty, moving the miss +0.850% → +0.510% — it does NOT shrink the miss, so the attempt deficit is not the cause here.
- **SCREEN** · BEST LAP from Q1 (78.815s)  [Q1 78.815]
- **SCREEN** · ELIMINATED in Q1 — the counted lap was set on a greener track than the Q3 runners'; quali_norm corrects for this, so treat a residual as real

  > category: ______   note: ______

### RACE PACE

#### VER · Red Bull Racing

predicted -0.905 → actual -1.928 · **miss -1.024%** (1.9 sd) · FASTER than predicted

- **Teammate**: HAD missed -0.640% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 34 clean long-run laps (field median 18) · sessions run: Practice_1 29, Practice_2 33, Practice_3 12
- **What made the actual**: 48 clean laps of 66 run (laps 9–66 of 66) · MEDIUM 37, HARD 8, SOFT 3
- **Dropped before the median**: 11 dirty-air, 9 perturbed, 8 invalid
- **What the filter did**: kept 73% of his laps (field 54%). Model measured -2.459%; over EVERY racing lap he is -2.666%. Scoring him on all laps would move the miss -1.024% → **-1.231%** (GROWS by 20%).
- **SCREEN** · PACE STEP  +1.81% at lap 58 (slower afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Pit stops** (3): lap 12 (2.5s stationary); lap 29; lap 40  ·  *2 not in pitstops.parquet*
- **Radio** 13:18:47: "It's not like I'm up for the bias. I think that pulling on the straight, it's not impressive. Copy."
- **Radio** 14:40:24: "Well done Max. Yeah, I think so. Yeah, it's a fun race, the other ones ahead, it's great. Yeah, it's alright. Well done Max, it was a maximum. I have a few matches today, well done Lisa. It's a base, and I am a much more"

  > category: ______   note: ______

#### HAM · Ferrari

predicted -1.393 → actual -2.256 · **miss -0.863%** (1.4 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 15 clean long-run laps (field median 18) · sessions run: Practice_2 28, Practice_3 16
- **What made the actual**: 43 clean laps of 66 run (laps 3–66 of 66) · HARD 28, SOFT 8, MEDIUM 7
- **Dropped before the median**: 16 dirty-air, 10 perturbed, 8 invalid
- **What the filter did**: kept 65% of his laps (field 54%). Model measured -2.787%; over EVERY racing lap he is -3.191%. Scoring him on all laps would move the miss -0.863% → **-1.267%** (GROWS by 47%).
- **SCREEN** · FILTER MASKING  the filter is FLATTERING the model here: on all laps the miss grows to -1.267%. Whatever the cause, it is not the measurement — the measurement is hiding part of it.
- **SCREEN** · PACE STEP  -2.14% at lap 25 (faster afterwards; bigger than 100% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-14 14:04:01  INCIDENT INVOLVING CAR 44 (HAM) NOTED - YELLOW FLAG INFRINGEMENT (15:38:31)`
    - `2026-06-14 14:07:11  UPDATE: INCIDENT INVOLVING CAR 44 (HAM) NOTED - YELLOW FLAG INFRINGEMENT (15:58:31)`
    - `2026-06-14 14:10:20  FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) REVIEWED NO FURTHER INVESTIGATION - YELLOW FLAG INFRINGEMENT (15:58:31)`
- **Incident** lap 44: procedural — YELLOW FLAG INFRINGEMENT → noted
- **Incident** lap 46: procedural — YELLOW FLAG INFRINGEMENT → no action
- **Pit stops** (3): lap 11 (2.5s stationary); lap 27; lap 41  ·  *2 not in pitstops.parquet*
- **Radio** 12:24:31: "Ebound, what do you think of the, of what it says? Have you a look at yours?"
- **Radio** 13:47:45: "Let me know what time we need to do. 20.9. Charles has gone for a different strategy."
- **Radio** 13:50:47: "Am I catching now? You are catching really well. Keep pushing, keep pushing."
- **Radio** 13:57:23: "And we are planning other seven laps on this set. This is our race. Give everything these seven laps. It's the critical moment. We have our chance."
- **Radio** 14:01:58: "[unintelligible]"
- **Radio** 14:02:28: "[unintelligible]"
- **Radio** 14:15:10: "15 laps to go, you are doing a good job, so you can go on."
- **Radio** 14:24:48: "Bias minus three, suggestion. I'm happy where I am. Thank you."
- **Radio** 14:38:01: "Well done, Lewis, well done. Finally, God, you deserve the first year that we were a family member. Thank you. Congratulations with your dream. Good job. Grazie. Grazie. Thank you so much. You've helped me achieve this d"
- **Radio** 14:39:02: "Let's go! For the Ferrari! For the Ferrari! Guys, thank you for those great pit stops as well. I'm sorry I have to talk and I'm so proud of you. Thank you."

  > category: ______   note: ______

#### HAD · Red Bull Racing

predicted -0.323 → actual -0.962 · **miss -0.640%** (1.2 sd) · FASTER than predicted

- **Teammate**: VER missed -1.024% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 15 clean long-run laps (field median 18) · sessions run: Practice_2 30, Practice_3 15
- **What made the actual**: 38 clean laps of 65 run (laps 10–65 of 66) · HARD 34, MEDIUM 2, SOFT 2
- **Dropped before the median**: 14 dirty-air, 14 perturbed, 8 invalid
- **What the filter did**: kept 58% of his laps (field 54%). Model measured -1.494%; over EVERY racing lap he is -1.330%. Scoring him on all laps would move the miss -0.640% → **-0.476%** (shrinks by 26%).
- **Race control** (race):
    - `2026-06-14 13:13:56  TURN 12 INCIDENT INVOLVING CARS 87 (BEA) AND 6 (HAD) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
    - `2026-06-14 13:20:10  FIA STEWARDS: TURN 12 INCIDENT INVOLVING CARS 87 (BEA) AND 6 (HAD) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
- *(1 routine blue-flag / flag-order message suppressed — those describe laps the median already discarded)*
- **Incident** lap 8: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs BEA → no action
- **Pit stops** (3): lap 15 (2.7s stationary); lap 32; lap 58  ·  *2 not in pitstops.parquet*
- **Radio** 14:40:24: "I apologize for that strategy. Yeah, I mean, the whole weekend has been terrible, so, like, there's one task for us at the Red Bull Ring, it's just to stop this, because we're going back for a while."

  > category: ______   note: ______

#### ANT · Mercedes

predicted -1.691 → actual -2.117 · **miss -0.426%** (1.1 sd) · FASTER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 15 clean long-run laps (field median 18) · sessions run: Practice_2 31, Practice_3 12
- **What made the actual**: 14 clean laps of 62 run (laps 11–61 of 66) · HARD 12, MEDIUM 2
- **Dropped before the median**: 40 dirty-air, 9 perturbed, 10 invalid
- **What the filter did**: kept 23% of his laps (field 54%). Model measured -2.648%; over EVERY racing lap he is -2.569%. Scoring him on all laps would move the miss -0.426% → **-0.347%** (shrinks by 19%).
- **SCREEN** · THIN SLICE  only 23% of his laps survived against a field 54%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **SCREEN** · THIN SAMPLE  only 14 clean laps entered the median (field median 15+ is normal)
- **SCREEN** · PACE STEP  +1.84% at lap 23 (slower afterwards; bigger than 98% of shuffled orderings) — check this lap against race control before calling it damage; an unexplained step is not yet a cause
- **Race control** (race):
    - `2026-06-14 13:34:42  CAR 12 (ANT) TIME 1:22.049 DELETED - TRACK LIMITS AT TURN 10 LAP 20 15:31:08`
    - `2026-06-14 13:38:31  CAR 12 (ANT) TIME 1:22.677 DELETED - TRACK LIMITS AT TURN 10 LAP 25 15:38:00`
    - `2026-06-14 13:42:52  CAR 12 (ANT) TIME 1:22.055 DELETED - TRACK LIMITS AT TURN 10 LAP 28 15:42:07`
    - `2026-06-14 13:43:13  BLACK AND WHITE FLAG FOR CAR 12 (ANT) - TRACK LIMITS`
    - `2026-06-14 14:35:25  CAR 12 (ANT) TIME 1:23.882 DELETED - TRACK LIMITS AT TURN 10 LAP 10 15:16:59`
    - `2026-06-14 14:35:31  INCIDENT INVOLVING CAR 12 (ANT) NOTED - TRACK LIMITS`
    - `2026-06-14 14:36:14  FIA STEWARDS: INCIDENT INVOLVING CAR 12 (ANT) WILL BE INVESTIGATED AFTER THE RACE - TRACK LIMITS`
- **Incident** lap 66: off-track — TRACK LIMITS → investigated after race
- **Pit stops** (2): lap 14 (2.6s stationary); lap 37  ·  *1 not in pitstops.parquet*
- **Radio** 12:29:37: "Brakes feel quite bad already, quite long, feels like air is in the system."
- **Radio** 13:33:03: "Happy with functioning. Affirm, Kimi. Good lap times."
- **Radio** 13:44:11: "They've just given me a black and white flag for track limits, so no more of those please, otherwise it's a five-second penalty."
- **Radio** 13:49:46: "Give me a reminder, the track limits, let's not take any risks."
- **Radio** 13:51:17: "Take him in, won't be long for George, we are at risk from Norris behind, 3.9 seconds"
- **Radio** 13:51:48: "So let's not slow each other down, racing, we need to keep that gap to Norris, nice and healthy, now at 4.3."
- **Radio** 13:54:22: "It won't be long, can it? Got a copy, Norris."
- **Radio** 14:16:10: "Gap at 0.9, 1.3 behind. Copy that, Kimi."
- **Radio** 14:29:22: "Kimi, you've got five laps remaining, so just warning the track limits everywhere, turn 5, exit, turn 10, exit."

  > category: ______   note: ______

#### GAS · Alpine

predicted +0.145 → actual +0.748 · **miss +0.603%** (1.3 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 22 clean long-run laps (field median 18) · sessions run: Practice_1 23, Practice_2 29, Practice_3 15
- **What made the actual**: 27 clean laps of 65 run (laps 12–65 of 66) · HARD 26, MEDIUM 1
- **Dropped before the median**: 29 dirty-air, 8 perturbed, 7 invalid
- **What the filter did**: kept 42% of his laps (field 54%). Model measured +0.216%; over EVERY racing lap he is +0.100%. Scoring him on all laps would move the miss +0.603% → **+0.487%** (shrinks by 19%).
- **SCREEN** · THIN SLICE  only 42% of his laps survived against a field 54%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **Race control** (race):
    - `2026-06-14 13:19:38  CAR 10 (GAS) TIME 1:26.055 DELETED - TRACK LIMITS AT TURN 13 LAP 10 15:17:40`
    - `2026-06-14 14:05:19  CAR 10 (GAS) TIME 1:21.708 DELETED - TRACK LIMITS AT TURN 13 LAP 42 16:03:58`
- *(3 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (2): lap 14 (3.0s stationary); lap 40  ·  *1 not in pitstops.parquet*

  > category: ______   note: ______

#### OCO · Haas F1 Team

predicted +0.559 → actual +1.217 · **miss +0.657%** (1.5 sd) · SLOWER than predicted

- **Teammate**: BEA missed +1.277% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 27 clean long-run laps (field median 18) · sessions run: Practice_1 27, Practice_2 29, Practice_3 15
- **What made the actual**: 39 clean laps of 64 run (laps 10–64 of 66) · HARD 17, MEDIUM 17, SOFT 5
- **Dropped before the median**: 12 dirty-air, 13 perturbed, 7 invalid
- **What the filter did**: kept 61% of his laps (field 54%). Model measured +0.685%; over EVERY racing lap he is +0.473%. Scoring him on all laps would move the miss +0.657% → **+0.445%** (shrinks by 32%).
- **Race control** (race):
    - `2026-06-14 13:15:02  TURN 12 INCIDENT INVOLVING CARS 31 (OCO) AND 5 (BOR) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
    - `2026-06-14 13:20:32  FIA STEWARDS: TURN 12 INCIDENT INVOLVING CARS 31 (OCO) AND 5 (BOR) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
- *(13 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 9: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs BOR → no action
- **Pit stops** (3): lap 13 (3.4s stationary); lap 34; lap 58  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### PER · Cadillac

predicted +1.842 → actual +2.878 · **miss +1.036%** (1.9 sd) · SLOWER than predicted

- **Teammate**: not flagged — the other car landed inside its band, so this is driver-specific, not a car-wide miss.
- **Practice evidence the model read**: 22 clean long-run laps (field median 18) · sessions run: Practice_2 34, Practice_3 21
- **What made the actual**: 33 clean laps of 63 run (laps 11–63 of 66) · MEDIUM 19, HARD 13, SOFT 1
- **Dropped before the median**: 20 dirty-air, 12 perturbed, 7 invalid
- **What the filter did**: kept 52% of his laps (field 54%). Model measured +2.345%; over EVERY racing lap he is +1.683%. Scoring him on all laps would move the miss +1.036% → **+0.374%** (shrinks by 64%).
- **SCREEN** · FILTER ARTIFACT  using every racing lap cuts the miss to +0.374%. The measured pace describes a slice of his race, not his race — consider `measurement_artifact` before any other cause.
- *(22 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Pit stops** (3): lap 12 (4.2s stationary); lap 31; lap 39  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

#### BEA · Haas F1 Team

predicted +0.293 → actual +1.570 · **miss +1.277%** (2.8 sd) · SLOWER than predicted

- **Teammate**: OCO missed +0.657% — SAME direction. Both cars wrong the same way points at the CAR or the model read, not at this driver.
- **Practice evidence the model read**: 22 clean long-run laps (field median 18) · sessions run: Practice_1 25, Practice_2 31, Practice_3 13
- **What made the actual**: 22 clean laps of 60 run (laps 13–59 of 66) · HARD 13, SOFT 6, MEDIUM 3
- **Dropped before the median**: 31 dirty-air, 10 perturbed, 5 invalid
- **What the filter did**: kept 37% of his laps (field 54%). Model measured +1.037%; over EVERY racing lap he is +0.712%. Scoring him on all laps would move the miss +1.277% → **+0.952%** (shrinks by 25%).
- **SCREEN** · THIN SLICE  only 37% of his laps survived against a field 54%, so this number rests on little — but correcting it barely moves the miss. Fragile, not wrong.
- **Race control** (race):
    - `2026-06-14 13:13:56  TURN 12 INCIDENT INVOLVING CARS 87 (BEA) AND 6 (HAD) NOTED - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
    - `2026-06-14 13:20:10  FIA STEWARDS: TURN 12 INCIDENT INVOLVING CARS 87 (BEA) AND 6 (HAD) REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF THE TRACK (15:04:44)`
- *(16 routine blue-flag / flag-order messages suppressed — those describe laps the median already discarded)*
- **Incident** lap 8: contact — FORCING ANOTHER DRIVER OFF THE TRACK vs HAD → no action
- **Pit stops** (3): lap 18 (3.6s stationary); lap 39; lap 60  ·  *2 not in pitstops.parquet*

  > category: ______   note: ______

---

**Press check** — only for what the archive cannot hold (visible damage, a team saying what it changed, a mechanical problem never announced on the timing feed). Rules: the article must be published AFTER the session it describes and BEFORE it could be coloured by later rounds; quote the claim, record the URL and its publication date in `source`; a team principal's explanation is a claim, not a measurement — mark it as such.