"""Hover-formatting rules for the shared Plotly theme.

Every chart in the dashboard goes through `theme()`, so the house rounding
rule is applied there once rather than in ~200 hovertemplates. Two things can
go wrong and both are silent:

* forgetting it — the hover prints raw float64 ("1.2999999999999998%"), which
  is unreadable and implies precision the measurement does not have;
* over-applying it — Plotly reads `hoverformat` on a DATE axis as a d3-time
  format, so a numeric one renders literally and the calendar hover would show
  ".3~f" where a date belongs.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]

from f1lib.components import HOVER_FMT, theme, theme_axes, BASE_NO_AXES


def test_numeric_axes_get_the_house_format():
    fig = theme(go.Figure(go.Scatter(x=[1, 2, 3], y=[1.23456, 2.5, 3.0])), 300)
    assert fig.layout.xaxis.hoverformat == HOVER_FMT
    assert fig.layout.yaxis.hoverformat == HOVER_FMT


def test_date_axis_keeps_its_own_formatting():
    """The season calendar ribbon plots dates on x. A numeric hoverformat
    there is worse than none at all."""
    dates = pd.to_datetime(["2026-03-01", "2026-04-05", "2026-05-10"])
    fig = theme(go.Figure(go.Scatter(x=dates, y=[1.5, 2.5, 3.5])), 300)
    assert fig.layout.xaxis.hoverformat is None
    # …but the numeric y axis on the same figure still gets it
    assert fig.layout.yaxis.hoverformat == HOVER_FMT


def test_date_axis_detected_when_typed_after_theming():
    """Callers routinely set type="date" after theme(), so the detection can't
    rely on layout.type alone — it reads the trace data."""
    dates = np.array(["2026-03-01", "2026-04-05"], dtype="datetime64[ns]")
    fig = go.Figure(go.Scatter(x=dates, y=[0, 0]))
    theme(fig, 300)
    fig.update_xaxes(type="date")
    assert fig.layout.xaxis.hoverformat is None


def test_subplots_get_the_format_on_every_panel():
    """layout.xaxis only reaches panel 1 — the reason theme_axes exists."""
    fig = make_subplots(rows=2, cols=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[1.5, 2.5]), row=1, col=1)
    fig.add_trace(go.Scatter(x=[1, 2], y=[3.5, 4.5]), row=2, col=1)
    fig.update_layout(**BASE_NO_AXES)
    theme_axes(fig)
    assert fig.layout.xaxis.hoverformat == HOVER_FMT
    assert fig.layout.xaxis2.hoverformat == HOVER_FMT
    assert fig.layout.yaxis.hoverformat == HOVER_FMT
    assert fig.layout.yaxis2.hoverformat == HOVER_FMT


def test_format_trims_trailing_zeros_but_caps_at_three_decimals():
    """'.3~f' is the rule: enough for a lap time, never a float64 tail."""
    assert HOVER_FMT == ".3~f"


def test_house_hover_format_carries_no_sign_flag():
    """HOVER_FMT goes on the AXIS, where the same parser bug applies — an
    axis hoverformat of '+.2f' is ignored exactly like the template one."""
    assert not HOVER_FMT.lstrip(".0123456789").startswith("+")
    assert "+" not in HOVER_FMT


# ── the sign-flag trap ───────────────────────────────────────

# Plotly 3.6 silently REJECTS a hovertemplate d3-format spec that begins with
# the sign flag and prints the raw float64 instead:
#
#     %{y:+.2f}   ->  -7.8595041322313985     (broken, and looks deliberate)
#     %{y:.2f}    ->  -7.86
#     %{y:>+.2f}  ->  -7.86  /  +7.86         (align char first: accepted)
#
# Measured on the live bundle, not inferred. It is a nasty one because the
# template LOOKS correct in review, the chart renders fine, and only the hover
# gives it away — 49 call sites across eleven modules were affected. Always
# write the explicit align char before the sign.
SIGN_FIRST = re.compile(r"%\{[^}]+?:\+")


def _py_sources():
    for d in ("tabs", "f1lib"):
        yield from sorted((ROOT / d).glob("*.py"))
    yield ROOT / "app.py"


@pytest.mark.parametrize("path", list(_py_sources()),
                         ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_hovertemplate_uses_a_leading_sign_flag(path):
    src = path.read_text(encoding="utf-8")
    bad = [src[max(0, m.start() - 30):m.end() + 12].replace("\n", " ")
           for m in SIGN_FIRST.finditer(src)]
    assert not bad, (
        f"{path.relative_to(ROOT).as_posix()} has a hovertemplate format "
        "starting with '+', which Plotly ignores — write ':>+' instead:\n  "
        + "\n  ".join(bad))


# ── multi-measure badges ─────────────────────────────────────

def _badge_labels(c):
    """The measure-badge labels rendered into a card header, in order.

    Derived from PACE_MEASURES rather than hard-coded, so renaming a label
    (ONE-LAP → ONE-LAP SPEED) doesn't break this test — test_vocabulary.py is
    what pins the wording itself.
    """
    from f1lib.components import PACE_MEASURES
    known = {lbl for lbl, _c, _d in PACE_MEASURES.values()}
    return [ch.children for ch in c.children[0].children
            if getattr(ch, "children", None) in known]


def test_card_renders_every_measure_badge():
    """A card that plots two measures must name both. One badge on a
    two-measure card silently mislabels the series it does not cover."""
    from f1lib.components import card, PACE_MEASURES

    one = card("t", "body", measure="one-lap")
    two = card("t", "body", measure=("one-lap", "race"))

    assert _badge_labels(one) == [PACE_MEASURES["one-lap"][0]]
    assert _badge_labels(two) == [PACE_MEASURES["one-lap"][0],
                                  PACE_MEASURES["race"][0]]


def test_card_measure_accepts_a_plain_string_unchanged():
    """The 40-odd existing single-measure call sites must keep working."""
    from f1lib.components import card, PACE_MEASURES
    c = card("t", "body", measure="stint")
    assert _badge_labels(c) == [PACE_MEASURES["stint"][0]]
