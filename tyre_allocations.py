"""
F1 Dashboard – Pirelli tyre allocations
=======================================
Small shared module that owns the hand-maintained per-event Pirelli
C-compound nomination (data/tyre_allocations.csv) plus the compact
"SOFT C5 · MEDIUM C4 · HARD C3" chip strip. Used by the STINTS Compound
Offsets card, the RACE Strategy Simulator, and the RACE Tyre Strategy card
— extracted so those tab modules can share a single source.

Also carries `_laps_event`, a lightweight (season, meeting) inference from a
laps frame — grouped here because every current caller uses it right next
to _allocation_chips.
"""
from __future__ import annotations

import logging

import pandas as pd
from dash import html

from components import badge  # noqa: F401 — kept for future chip-badge use
from config import COMPOUND_COLORS, TEXT_DIM

_TYRE_ALLOC_CACHE: pd.DataFrame | None = None


def _tyre_allocations() -> pd.DataFrame:
    global _TYRE_ALLOC_CACHE
    if _TYRE_ALLOC_CACHE is None:
        try:
            df = pd.read_csv("data/tyre_allocations.csv")
            df["season"] = df["season"].astype(int)
            _TYRE_ALLOC_CACHE = df
        except Exception as exc:
            logging.info("No tyre allocation data: %s", exc)
            _TYRE_ALLOC_CACHE = pd.DataFrame()
    return _TYRE_ALLOC_CACHE


def _allocation_for(season, meeting) -> dict[str, str]:
    """{'SOFT': 'C5', 'MEDIUM': 'C4', 'HARD': 'C3'} for a meeting;
    {} when the event isn't in the CSV."""
    df = _tyre_allocations()
    if df.empty or season is None or not meeting:
        return {}
    try:
        m = df[(df["season"] == int(season)) &
               (df["event"].str.strip().str.lower()
                == str(meeting).strip().lower())]
    except (ValueError, TypeError):
        return {}
    if m.empty:
        return {}
    r = m.iloc[0]
    return {"SOFT": str(r["soft"]), "MEDIUM": str(r["medium"]),
            "HARD": str(r["hard"])}


def _allocation_chips(season, meeting):
    """A compact 'Pirelli allocation: SOFT C5 · MEDIUM C4 · HARD C3' strip,
    compound-coloured. None when the allocation is unknown."""
    alloc = _allocation_for(season, meeting)
    if not alloc:
        return None
    bits = [html.Span("PIRELLI ALLOCATION ", style={
        "color": TEXT_DIM, "fontSize": "0.68rem", "letterSpacing": "1px",
        "marginRight": "6px"})]
    for comp in ("SOFT", "MEDIUM", "HARD"):
        clr = COMPOUND_COLORS.get(comp, "#808080")
        bits.append(html.Span(f"{comp} {alloc[comp]}", style={
            "background": clr + "22", "color": clr,
            "border": f"1px solid {clr}66", "borderRadius": "4px",
            "padding": "1px 8px", "fontSize": "0.7rem", "fontWeight": "700",
            "marginRight": "6px", "whiteSpace": "nowrap",
        }))
    return html.Div(bits, style={"marginBottom": "8px"})


def _laps_event(df: pd.DataFrame) -> tuple[int | None, str | None]:
    """(season, meeting) when the frame covers exactly one meeting."""
    if df is None or df.empty or "meeting" not in df.columns:
        return None, None
    meetings = df["meeting"].dropna().unique()
    if len(meetings) != 1:
        return None, None
    season = pd.to_numeric(df["season"], errors="coerce").dropna().unique()
    return (int(season[0]) if len(season) == 1 else None), str(meetings[0])
