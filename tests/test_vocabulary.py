"""House rule: SPEED is one lap, PACE is many laps.

`PACE_MEASURES` defines five measures and three of them used to be called
"pace" — ONE-LAP PACE, RACE PACE, STINT PACE. The badge therefore carried no
information on its own: you had to read the qualifier to know whether a number
came from 90 seconds or 90 minutes. The Upgrade Impact trend, which plots a
one-lap series and a race series on one chart in identical units with hover
strings differing by a single word, is where that became unworkable.

So in this dashboard's user-facing copy:

    SPEED  — instantaneous, one flat-out lap  → "one-lap speed"
    PACE   — a rate sustained over distance   → "race pace", "stint pace"

The sport itself says "qualifying pace" and that is fine English; the glossary
still resolves it so a reader who types it gets an answer. It is simply not
what the dashboard says. This test stops the old wording creeping back.

Scope note: only string LITERALS are checked, via the AST. Identifiers and
column names are matched on whitespace, so an underscore-joined name like
`race_pace_pct` or `team_pace_df` can never trip the pattern — which is what
lets the data-layer names be renamed on their own schedule.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Where the banned wording is deliberate: the glossary keeps it resolvable as
# an alias, and components.py documents why the rule exists.
EXEMPT = {"f1lib/glossary.py", "f1lib/components.py"}

# "<one-lap|quali|qualifying> <whitespace> pace" in any casing.
BANNED = re.compile(r"(?:one[- ]lap|quali(?:fying)?)\s+pace", re.IGNORECASE)

# Compound terms that legitimately contain "pace" and are NOT a measure name:
# a team's reserve of pace, and how much of it qualifying revealed.
ALLOWED_PHRASES = ("pace in hand", "pace unlocked")


def _source_files():
    for d in ("tabs", "f1lib"):
        yield from sorted((ROOT / d).glob("*.py"))
    yield ROOT / "app.py"


def _string_literals(path: Path):
    """(lineno, value) for every string constant in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


@pytest.mark.parametrize(
    "path", [p for p in _source_files()
             if p.relative_to(ROOT).as_posix() not in EXEMPT],
    ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_pace_wording_for_single_lap_measures(path):
    bad = []
    for lineno, text in _string_literals(path):
        for m in BANNED.finditer(text):
            window = text[max(0, m.start() - 20):m.end() + 20].lower()
            if any(a in window for a in ALLOWED_PHRASES):
                continue
            bad.append(f"  line {lineno}: …{text[max(0, m.start()-40):m.end()+40]}…")
    assert not bad, (
        f"{path.relative_to(ROOT).as_posix()} calls a single-lap measure "
        f"'pace'. Say 'one-lap speed' — see f1lib/components.py PACE_MEASURES:\n"
        + "\n".join(bad))


def test_badge_label_says_speed():
    from f1lib.components import PACE_MEASURES
    label, _colour, definition = PACE_MEASURES["one-lap"]
    assert label == "ONE-LAP SPEED"
    assert "speed" in definition.lower()


def test_sustained_measures_keep_the_word_pace():
    """The rule cuts both ways — race and stint measures must NOT be renamed
    to 'speed', or the distinction collapses from the other side."""
    from f1lib.components import PACE_MEASURES
    assert PACE_MEASURES["race"][0] == "RACE PACE"
    assert PACE_MEASURES["stint"][0] == "STINT PACE"


def test_every_gloss_call_resolves():
    """A gloss() term that isn't in the glossary degrades to a bare span — no
    underline, no hover, no error. Silent, so it needs a test: renaming a key
    (as the speed/pace change did) can orphan call sites nothing would flag.
    """
    from f1lib.glossary import _resolve

    bad = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "gloss"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                term = node.args[0].value
                if _resolve(term) is None:
                    bad.append(f"  {path.relative_to(ROOT).as_posix()}:"
                               f"{node.lineno}  gloss({term!r})")
    assert not bad, "gloss() terms missing from the glossary:\n" + "\n".join(bad)


def test_glossary_still_answers_the_paddock_wording():
    """A reader who hovers 'one-lap pace' — the term used everywhere outside
    this dashboard — must still get the definition."""
    from f1lib.glossary import _resolve

    canonical = _resolve("one-lap speed")
    assert canonical, "one-lap speed missing from the glossary"
    for legacy in ("one-lap pace", "one lap pace", "one-lap",
                   "qualifying pace", "quali pace"):
        assert _resolve(legacy) == canonical, (
            f"gloss({legacy!r}) no longer resolves — ~100 call sites use these")
