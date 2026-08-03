"""Session-normalised one-lap speed, shared by the team and driver layers.

A qualifying "best lap" is not comparable across cars until the track state
it was set on is removed. Q3 runs on the most-rubbered track of the weekend
and Q1 on the greenest, worth roughly a percent a session — more than the
thing either the team-pace table or the driver ratings is trying to measure.

This module owns that correction so there is exactly one implementation of
it. `scripts/compute_team_pace.py` applies it per TEAM (best of the two
cars); `f1lib/driver_ratings.py` applies it per DRIVER, where it matters
even more: 31% of teammate pairs set their two best laps in different
Q-sessions, so without this the evolution offset lands directly inside the
teammate contrast that IS the driver rating.

How the offsets are estimated (MS-05)
-------------------------------------
Not by a team+session fixed-effects fit. That assumes every entrant's
relative pace is constant across Q1/Q2/Q3, and it is not: front-runners bank
a lap on used rubber in Q1 and do not push, so their Q1→Q2 "improvement" is
track evolution PLUS the sandbag coming off. An offset averaged over that
mixture over-states the evolution, and the excess is handed as a pace bonus
to whoever was measured only in Q1 — the backmarkers whose form is hardest
to read.

Instead each consecutive session pair is bridged by the MEDIAN of the
entrants present in both, preferring those ELIMINATED at the next cut: a car
knocked out in Q2 was flat out in Q1 (to escape it) and in Q2 (fighting
elimination), so its delta is evolution, not sandbag release. Every lap is
then corrected onto the final session's track state, and an entrant's
estimate is its BEST corrected lap — so a cruise lap never wins the min, and
a ruined final run falls back to an earlier session instead of poisoning the
estimate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

Q_SESSIONS = ("Q1", "Q2", "Q3")

# Minimum entrants eliminated at the next cut for the sandbag-robust offset.
# Below this the eliminated subset is too thin to take a median of and the
# estimate falls back to everyone present in both sessions.
OFFSET_MIN_PAIRS = 3

# Reject the whole fit when any entrant lands further than this from the
# field median. The original gate was 15%, which let anything short of a
# catastrophe through; the largest GENUINE one-lap spread observed (Aston,
# Spa 2026) was 3.9%, so 8% is double the worst real case.
MAX_PLAUSIBLE_PCT = 8.0


def to_long(g: pd.DataFrame, entity: str,
            reducer: str = "min") -> pd.DataFrame:
    """(entity, session, t) from a frame carrying Q1/Q2/Q3 columns.

    `reducer` collapses several rows per entity within a session — "min" for
    teams (best of the two cars); for drivers there is one row already, so it
    is a no-op.
    """
    out = []
    for s in Q_SESSIONS:
        if s not in g.columns:
            continue
        sub = g[[entity, s]].dropna()
        if sub.empty:
            continue
        sub = sub.rename(columns={s: "t"})
        sub = sub.groupby(entity, as_index=False)["t"].agg(reducer)
        sub["sess"] = s
        out.append(sub)
    if not out:
        return pd.DataFrame(columns=[entity, "t", "sess"])
    L = pd.concat(out, ignore_index=True)
    return L[L["t"] > 0]


def session_offsets(L: pd.DataFrame, entity: str
                    ) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Cumulative log-offset per session onto the FINAL session's track state,
    plus the wide {entity: {session: log time}} map used to derive it.

    Returns ({}, {}) when the offsets cannot be estimated.
    """
    if L.empty or L[entity].nunique() < 2:
        return {}, {}
    L = L.copy()
    L["logt"] = np.log(L["t"].to_numpy(dtype=float))
    wide: dict[str, dict[str, float]] = {}
    for row in L.itertuples(index=False):
        wide.setdefault(getattr(row, entity), {})[row.sess] = row.logt
    sessions = [s for s in Q_SESSIONS if (L["sess"] == s).any()]
    order = {s: i for i, s in enumerate(sessions)}
    last = {e: max(d, key=lambda s: order[s]) for e, d in wide.items()}
    entities = sorted(wide)

    cum: dict[str, float] = {sessions[-1]: 0.0}
    for a, b in reversed(list(zip(sessions, sessions[1:]))):
        pairs = [e for e in entities if a in wide[e] and b in wide[e]]
        # Entrants whose run ENDED at b pushed flat out in both a and b;
        # those who advanced past b may have cruised through a. Only the
        # Q1→Q2 step ever distinguishes the two — everyone reaching Q3 has
        # their last session there.
        fighters = [e for e in pairs if last[e] == b]
        use = fighters if len(fighters) >= OFFSET_MIN_PAIRS else pairs
        if not use:
            return {}, {}
        step = float(np.median([wide[e][b] - wide[e][a] for e in use]))
        cum[a] = step + cum[b]
    return cum, wide


def corrected_best(wide: dict[str, dict[str, float]],
                   cum: dict[str, float]) -> dict[str, float]:
    """Best corrected LOG lap per entity (lower = faster)."""
    return {e: min(sess_times[s] + cum[s] for s in sess_times)
            for e, sess_times in wide.items()}


def normalised_gap_pct(g: pd.DataFrame, entity: str, reducer: str = "min",
                       gate: float = MAX_PLAUSIBLE_PCT) -> dict[str, float]:
    """Session-normalised one-lap speed as % vs the field median, per entity.

    Negative = faster than the median entrant. Empty dict when the round
    cannot be normalised (caller falls back to a raw measure).
    """
    L = to_long(g, entity, reducer)
    cum, wide = session_offsets(L, entity)
    if not cum:
        return {}
    eff = corrected_best(wide, cum)
    med = float(np.median(list(eff.values())))
    out = {e: round((float(np.exp(v - med)) - 1) * 100, 3)
           for e, v in eff.items()}
    if out and max(abs(v) for v in out.values()) > gate:
        return {}
    return out


def n_sessions(g: pd.DataFrame, entity: str) -> dict[str, int]:
    """How many Q sessions each entity set a time in. 1 means the estimate
    leans entirely on the measured offsets — thinner data, worth flagging."""
    counts: dict[str, int] = {}
    for s in Q_SESSIONS:
        if s not in g.columns:
            continue
        for e in g.loc[g[s].notna(), entity].unique():
            counts[e] = counts.get(e, 0) + 1
    return counts
