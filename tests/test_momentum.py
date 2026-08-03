"""The Momentum card's window and its noise floor.

The card answers "who is moving NOW". It used to answer it with a
first-half-vs-second-half split, which cannot: with 11 rounds that averages six
of them into the recent number, so a fresh result moves the answer by a sixth
and the card sits about three races behind. The observed failure was Aston
Martin reading as the grid's biggest loser (+0.90 pp) in the same week they
brought the best-scoring upgrade package of the 2026 season.

Two properties are pinned here:

1. the window is ROLLING and short, so a new round actually moves it;
2. the card knows its own noise floor. A 3-round window is more responsive AND
   noisier than a half-season one — ~0.31 pp vs ~0.23 pp at 2026's spread — and
   the plain-English line must not name a "riser" for a move smaller than the
   measurement can resolve.

Circuit character is deliberately NOT corrected out; see
_momentum_confound_note for the out-of-sample result that killed that idea.
"""
import numpy as np
import pandas as pd
import pytest

from tabs.season import (
    MOMENTUM_WINDOW, _momentum_window, _momentum_noise, _momentum_frame,
    _momentum_headline_floor, _momentum_title, _momentum_plain,
)


def _season(n_rounds, teams=("A", "B", "C"), pace=None, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(1, n_rounds + 1):
        for t in teams:
            v = pace(t, r) if pace else float(rng.normal(0, 0.3))
            rows.append({"season": 2026, "round": r, "event": f"E{r}",
                         "team": t, "onelap_speed_pct": v,
                         "points": 10.0, "cum_points": 10.0 * r})
    return pd.DataFrame(rows)


# ── window ───────────────────────────────────────────────────

def test_window_is_the_last_w_against_the_w_before():
    s = _season(11)
    early, late = _momentum_window(s)
    assert late == [9, 10, 11]
    assert early == [6, 7, 8]
    assert len(late) == MOMENTUM_WINDOW


def test_window_ignores_the_early_season_entirely():
    """The whole point: rounds 1-5 must not dilute the current reading."""
    early, late = _momentum_window(_season(11))
    assert 1 not in early + late


def test_window_shrinks_rather_than_refusing_on_a_young_season():
    for n, expect in ((4, 2), (5, 2), (6, 3), (11, 3)):
        early, late = _momentum_window(_season(n))
        assert len(late) == expect, f"{n} rounds -> window {len(late)}"
        assert len(early) == expect


def test_window_declines_when_there_is_nothing_to_compare():
    assert _momentum_window(_season(3)) == ([], [])
    assert _momentum_frame(_season(3)).empty


def test_a_new_round_moves_the_answer():
    """A half-split barely reacts to one new result; this must."""
    def pace(t, r):
        # team A steps 1.5pp faster from round 10 onward
        return -1.5 if (t == "A" and r >= 10) else 0.0
    before = _momentum_frame(_season(10, pace=pace))
    after = _momentum_frame(_season(11, pace=pace))
    a_before = before.set_index("team").loc["A", "d_pace"]
    a_after = after.set_index("team").loc["A", "d_pace"]
    assert a_after < a_before, "adding a round did not move the measure"
    assert a_after < -0.4, "a 1.5pp step should be clearly visible"


# ── noise floor ──────────────────────────────────────────────

def test_noise_floor_grows_as_the_window_shrinks():
    s = _season(12, seed=3)
    assert _momentum_noise(s, 2) > _momentum_noise(s, 3) > _momentum_noise(s, 6)


def test_noise_floor_is_zero_for_a_perfectly_steady_field():
    s = _season(11, pace=lambda t, r: 1.0)
    assert _momentum_noise(s, 3) == pytest.approx(0.0, abs=1e-9)


def test_headline_bar_is_stricter_than_the_single_dot_floor():
    """The sentence names the extreme of the whole grid, so it needs a
    multiple-comparisons bar — the biggest of eleven noisy teams clears a
    one-team floor by luck alone."""
    s = _season(12, teams=list("ABCDEFGHIJK"), seed=5)
    assert _momentum_headline_floor(s, 3) > _momentum_noise(s, 3) * 1.8


def test_headline_bar_collapses_to_the_floor_for_a_lone_team():
    s = _season(12, teams=("A",), seed=5)
    assert _momentum_headline_floor(s, 3) == pytest.approx(
        _momentum_noise(s, 3))


def test_plain_line_rarely_names_a_mover_in_a_trendless_season():
    """A noisy but trendless field must usually read as 'nobody moved'.

    Stated as a rate, not as a property of one lucky draw: the guard is a
    family-wise significance bar, so it is allowed to fire occasionally — the
    noise floor is itself estimated from a finite sample. What must never come
    back is the old behaviour, which named a riser and a faller in essentially
    every season regardless of whether anything happened.
    """
    named = 0
    trials = 40
    for seed in range(trials):
        s = _season(12, teams=list("ABCDEFGHIJK"), seed=seed)
        txt = _momentum_plain(s) or ""
        if "resolve" not in txt:
            named += 1
    rate = named / trials
    assert rate <= 0.25, (
        f"named a mover in {rate:.0%} of trendless seasons — the "
        "significance bar is not doing its job")


def test_plain_line_names_a_real_move():
    def pace(t, r):
        return -3.0 if (t == "A" and r >= 10) else 0.0
    s = _season(12, teams=list("ABCDEFGHIJK"), pace=pace)
    txt = _momentum_plain(s)
    assert txt and "found the most lap time" in txt


def test_plain_line_reads_as_english_without_a_riser():
    """'gone the other way' has no referent when no riser was named."""
    def pace(t, r):
        return 3.0 if (t == "A" and r >= 10) else 0.0     # only a faller
    txt = _momentum_plain(_season(12, teams=list("ABCDEFGHIJK"), pace=pace))
    assert txt and "gone the other way" not in txt
    assert "lost the most lap time" in txt


# ── title ────────────────────────────────────────────────────

def test_title_states_the_window():
    """A card called 'who is actually moving' must say over what."""
    t = _momentum_title(_season(11))
    assert "R9–11" in t and "R6–8" in t


def test_title_survives_a_season_too_short_to_compare():
    assert "Momentum" in _momentum_title(_season(2))


# ── real data ────────────────────────────────────────────────

def test_real_season_window_beats_the_half_split_on_aston(tmp_path):
    """The regression that motivated all of this, pinned against real data."""
    from pathlib import Path
    p = Path("data/team_pace_by_event.csv")
    if not p.exists():
        pytest.skip("pace table not built")
    s = pd.read_csv(p)
    s = s[(s["season"] == 2026) & s["onelap_speed_pct"].notna()]
    if s.empty or "Aston Martin" not in set(s["team"]):
        pytest.skip("2026 Aston Martin rows not present")
    d = _momentum_frame(s).set_index("team")
    if "Aston Martin" not in d.index:
        pytest.skip("Aston Martin dropped from the frame")
    ast = d.loc["Aston Martin", "d_pace"]
    floor = _momentum_noise(s, len(_momentum_window(s)[1]))
    # the half-split read +0.90 pp — the worst on the grid. On the rolling
    # window Aston must no longer be an outlier of that size.
    assert ast < 0.5, f"Aston still reads {ast:+.2f} pp on the rolling window"
    assert abs(ast) < floor, (
        f"Aston {ast:+.2f} pp should sit inside the {floor:.2f} pp floor — "
        "i.e. 'flat', which is the honest reading")
