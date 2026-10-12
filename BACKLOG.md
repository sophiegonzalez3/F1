# Backlog

Ideas parked for later. One entry per idea: what, why, and what is already
known that it can start from.

## Era comparison — this season vs previous ones

A tab (or a SEASON section) comparing key factors of the running season with
earlier seasons, possibly organised as an "era" view (2022-25 ground-effect
era vs the 2026 aero + power-unit regulations).

Why: several questions only make sense against the previous seasons — is tyre
wear a factor this year, is the field more spread out, has dirty air come
back. Each card today answers inside one season only.

Already measured, ready to reuse:
- **Tyre wear by real Pirelli compound × season** (Oct 2026): 2026 C4/C5 race
  deg 0.028 / 0.012 s/lap vs 0.048 / 0.048 in 2025 — the softer compounds wear
  far less this year (consistent with conservative 2026 Pirelli choices).
  Data: `data/tyre_allocations.csv` now covers every cached race 2023-26
  (C-numbers per event; 2025 includes gapped sets like C1/C3/C4).
- **Compound pace offsets are not measurable per race** in any season
  (race-wide drift between stints swamps them) — don't build an era
  comparison of offsets, compare deg instead.
- Cost-cap convergence card (CONTEXT) already compares eras 2011-26 for
  field spread — the template for the layout.

Candidate factors: field pace spread (one-lap and race), tyre deg per
C-compound, pit-stop count and strategy mix, overtakes / dirty-air penalty,
safety-car rate, reliability (DNF families), qualifying-to-race position
retention.
