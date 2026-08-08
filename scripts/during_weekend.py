"""Mid-weekend refresh: cache the sessions that have run so far, then report
what still needs a human.

Run it after each session of a live weekend (FP1 → FP2 → FP3 → Sprint →
Qualifying). Everything the dashboard derives mid-weekend comes straight from
the session cache, so caching is the whole automated job:

  1. cache every session of the event that has already run  (data/sessions/)
  2. warm the circuit's track map                           (data/track_maps/)
  3. top up the calendar ribbon if the season is missing     (season_calendar.csv)
  4. print the hand-curated checklist for this event (tyres, upgrades, pools)

It is the headless equivalent of picking the event in the app's Data tab — the
BRIEF tab's pace prediction sharpens with every session added, and re-running
is cheap because cached sessions are skipped.

Nothing here is post-race: once the Race is cached, run `after_race.py`.

Usage
-----
    python scripts/during_weekend.py                        # latest event that has run
    python scripts/during_weekend.py 2026 "Hungarian Grand Prix"
    python scripts/during_weekend.py --check-only           # skip fetching, just the checklist
    python scripts/during_weekend.py --no-track-map         # skip the (slow) map warm-up
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import contextlib
import difflib
import io
import logging
import re
import subprocess
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

import f1lib.data_loader as dl

ROOT = Path(__file__).resolve().parent.parent
CALENDAR = Path("data/season_calendar.csv")
TYRES = Path("data/tyre_allocations.csv")
UPGRADES = Path("data/upgrades.csv")
PU_POOL = Path("data/pu_penalties.csv")
GEARBOX = Path("data/gearbox_penalties.csv")


# ─────────────────────────────────────────────────────────────
# Event resolution
# ─────────────────────────────────────────────────────────────

def resolve_event(season: int | None, meeting: str | None) -> tuple[int, str]:
    """The event to work on: the one asked for, else the latest that has run."""
    if season and meeting:
        return int(season), meeting
    year = int(season or date.today().year)
    season_, meeting_, _ = dl.most_recent_event(year, fallback_seasons=(year - 1,))
    return season_, meeting_


def known_events(season: int) -> list[str]:
    """Every event name of the season we could work on: the ones that have run
    (FastF1's schedule) plus the ones still to come (the calendar CSV)."""
    names = list(dl.season_meetings(season))
    cal = _read(CALENDAR)
    if not cal.empty:
        upcoming = cal[cal["season"].astype(int) == season]["event"].astype(str)
        names += [n for n in upcoming if n not in names]
    return names


def check_event_name(season: int, meeting: str) -> bool:
    """Guard against a misspelled meeting. Without it a wrong name just yields
    a checklist of TODOs that looks like missing data — the meeting must be the
    exact FastF1 event name ("Belgian Grand Prix", not "Belgium GP")."""
    known = known_events(season)
    if not known or meeting in known:
        return True
    print(f"  !! '{meeting}' is not a {season} event name.")
    close = difflib.get_close_matches(meeting, known, n=3, cutoff=0.4)
    if close:
        print(f"     did you mean: {', '.join(repr(c) for c in close)}?")
    else:
        print(f"     known events: {', '.join(known[:6])}...")
    return False


# ─────────────────────────────────────────────────────────────
# 1–2. sessions + track map
# ─────────────────────────────────────────────────────────────

def cache_sessions(season: int, meeting: str) -> list[dict]:
    """Fetch every session of the event that has run. Returns the session-info
    list (all of them, cached or not) so later steps know what exists."""
    infos = dl.sessions_for_meeting(season, meeting)
    if not infos:
        print(f"  no sessions listed yet for {season} {meeting} "
              "(none has run, or FastF1's schedule is unreachable)")
        return []

    missing = [i for i in infos
               if not dl.is_cached(str(season), meeting, i["SESSION"])]
    have = [i["SESSION"] for i in infos if i not in missing]
    if have:
        print(f"  cached already : {', '.join(have)}")
    if not missing:
        return infos

    print(f"  fetching       : {', '.join(i['SESSION'] for i in missing)}"
          " (a few minutes per session)", flush=True)
    data = dl.load_sessions(missing)         # skips sessions FastF1 can't serve yet
    laps = data.get("laps")
    print(f"  fetched        : {0 if laps is None or laps.empty else len(laps)} laps")
    return infos


def warm_track_map(season: int, meeting: str, infos: list[dict]) -> None:
    """Build + cache the circuit's corner geometry from the cleanest session
    already cached. The app does this in a background thread on load; doing it
    here means compute_mistakes.py (post-race) never hits a missing map."""
    # Importing a tab module drags in f1lib.state, which prints its startup
    # banner (loaded event, archive row counts). Swallow that — it's about the
    # app's default session, not about this event.
    with contextlib.redirect_stdout(io.StringIO()):
        from tabs.telemetry import _GEOMETRY_SESSION_PREF
        from tabs.track import get_track_map

    cached = {i["SESSION"] for i in infos
              if dl.is_cached(str(season), meeting, i["SESSION"])}
    for label, sid in _GEOMETRY_SESSION_PREF:
        if label not in cached:
            continue
        try:
            tm = get_track_map(season, meeting, sid)
        except Exception as exc:
            print(f"  {sid}: failed ({type(exc).__name__}: {exc})")
            continue
        if tm and tm.get("corners") is not None and not tm["corners"].empty:
            print(f"  map ready from {label} - {len(tm['corners'])} corners")
            return
    print("  no track map yet (no cached session has a clean fast lap)")


# ─────────────────────────────────────────────────────────────
# 3. calendar
# ─────────────────────────────────────────────────────────────

def ensure_calendar(season: int) -> None:
    cal = _read(CALENDAR)
    if not cal.empty and season in set(cal["season"].astype(int)):
        return
    print(f"  season {season} missing from {CALENDAR} - fetching", flush=True)
    subprocess.run([_sys.executable, "scripts/fetch_calendar.py",
                    "--seasons", str(season)], cwd=ROOT)


# ─────────────────────────────────────────────────────────────
# 4. hand-curated checklist
# ─────────────────────────────────────────────────────────────

def refresh_session_weather(season: int) -> None:
    """Re-derive per-session rain/tyre conditions for whatever is cached NOW.

    Deliberately mid-weekend rather than after the race only. Two reasons, both
    about being able to ask the question later:

    - conditions in an EARLIER session are a plausible predictor of a bad read
      later in the weekend. A wet or interrupted FP2 means fewer usable laps,
      which is exactly the `thin_read` / `heavy_exclusion` failure the model
      review keeps landing on. Recording it only after the race would mean the
      cause is always logged after the effect.
    - a rain threat, not just rain, is what makes a strategist reach for the
      unusual call. That is only visible if the record exists at the time.

    Cheap to re-run — it re-reads cached parquet and writes one CSV — so it
    runs on every invocation rather than trying to be clever about deltas.
    """
    out = subprocess.run(
        [_sys.executable, "scripts/compute_session_weather.py",
         "--season", str(season)],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f"  !! failed ({out.returncode}) - "
              f"{(out.stderr or '').strip().splitlines()[-1:] or ['no stderr']}")
        return
    head = [ln for ln in (out.stdout or "").splitlines() if ln.startswith("Wrote")]
    print(f"  {head[0] if head else 'done'}")
    p = Path("data/session_weather.csv")
    if not p.exists():
        return
    try:
        d = pd.read_csv(p)
        d = d[d["season"] == season]
        wet = d[d["condition"] != "dry"]
        if wet.empty:
            print(f"  every {season} session so far: dry")
        else:
            print(f"  not-dry so far: " + "; ".join(
                f"{r['event']} {r['session']} [{r['condition']}]"
                for _, r in wet.iterrows()))
    except Exception:
        pass


def snapshot_odds() -> None:
    """Record what the betting market thinks, right now.

    Deliberately here rather than only after the race, and for a stronger
    reason than session weather: a price is only observable while the market
    is open. `race_forecast.py` emits p_win / p_podium and has never been
    scored on either, and the market is a well-calibrated probability
    reference for exactly those quantities that exists BEFORE the result. A
    snapshot taken after the race is worth nothing for that.

    Each session of the weekend is a natural sampling point because the market
    reprices on the same information the model does — so the pairs (our
    prediction after FP2, the market after FP2) line up by construction.

    Never fatal: no odds must never block caching a session.
    """
    out = subprocess.run(
        [_sys.executable, "scripts/fetch_odds.py"],
        capture_output=True, text=True)
    lines = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    if out.returncode != 0:
        tail = (out.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
        print(f"  !! odds snapshot failed ({out.returncode}) - {tail[0]}")
        print("     not fatal; the market is a benchmark, not an input")
        return
    for ln in lines[1:]:
        print(f"  {ln.strip()}")


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _event_round(season: int, meeting: str) -> int | None:
    cal = _read(CALENDAR)
    if cal.empty:
        return None
    row = cal[(cal["season"].astype(int) == season) & (cal["event"] == meeting)]
    return int(row["round"].iloc[0]) if not row.empty else None


def _as_of_round(df: pd.DataFrame, season: int) -> int | None:
    """Highest round number mentioned in an `as_of` column ('R10 Belgian ...')."""
    if df.empty or "as_of" not in df.columns:
        return None
    s = df[df["season"].astype(int) == season]["as_of"].astype(str)
    rounds = [int(m.group(1)) for m in (re.match(r"\s*R(\d+)", v) for v in s) if m]
    return max(rounds) if rounds else None


def checklist(season: int, meeting: str) -> None:
    rnd = _event_round(season, meeting)
    rlabel = f"R{rnd}" if rnd else "?"

    tyres = _read(TYRES)
    has_tyres = (not tyres.empty
                 and not tyres[(tyres["season"].astype(int) == season)
                               & (tyres["event"] == meeting)].empty)
    _line("data/tyre_allocations.csv", has_tyres,
          f"C-compound nomination for {meeting}",
          "press.pirelli.com preview (announced weeks ahead)")

    ups = _read(UPGRADES)
    n_ups = 0 if ups.empty else len(ups[(ups["season"].astype(int) == season)
                                        & (ups["event"] == meeting)])
    _line("data/upgrades.csv", n_ups > 0,
          f"{n_ups} upgrade rows for {meeting}",
          'FIA "Car Presentation Submissions" PDF, published race Friday')

    pu_r = _as_of_round(_read(PU_POOL), season)
    _line("data/pu_penalties.csv", rnd is not None and pu_r is not None and pu_r >= rnd,
          f"pool is as-of R{pu_r}, event is {rlabel}",
          "FIA new-PU-elements decision document for this event")
    _verify_pu_counts(season, meeting)

    gb_r = _as_of_round(_read(GEARBOX), season)
    _line("data/gearbox_penalties.csv",
          rnd is not None and gb_r is not None and gb_r >= rnd,
          f"pool is as-of R{gb_r}, event is {rlabel}",
          "no public per-driver gearbox RNC table exists (checked 2026-07-25) - "
          "the file is a labelled placeholder, so this line stays TODO by design")


def _verify_pu_counts(season: int, meeting: str) -> None:
    """Diff the PU pool against the FIA's cumulative table for this event.

    The as_of line above only compares a round *label*, which cannot see wrong
    numbers underneath it — on 2026-07-25 the file read "R10" while Lawson's and
    Stroll's rows were still R9. This checks the counts themselves.

    Advisory: the table is published early on the Friday, so before then (and
    offline) there is simply nothing to compare against and we say so.
    """
    try:
        from scripts.check_pu_table import check
        with contextlib.redirect_stdout(io.StringIO()):   # it echoes the URL
            fia, diffs = check(season, meeting, PU_POOL)
    except Exception as exc:                 # not published yet, offline, format change
        reason = getattr(exc, "code", None) or type(exc).__name__
        print(f"         -> FIA table not checked ({reason}); it is published "
              "early on the Friday")
        return
    if not diffs:
        print(f"         -> FIA table: counts match for all {len(fia)} drivers")
        return
    print(f"         -> FIA table: {len(diffs)} count(s) disagree - "
          f'run  python scripts/check_pu_table.py --event "{meeting}"')
    for drv, col, have, want, _ in sorted(diffs)[:6]:
        print(f"            {drv} {col}: {have} -> {want}")


def _line(name: str, ok: bool, detail: str, source: str) -> None:
    # ASCII only: this runs in the Windows console (cp1252).
    print(f"  {('[ok]' if ok else '[TODO]'):<6} {name:<30} {detail}")
    if not ok:
        print(f"         -> source: {source}")


# ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", nargs="?", type=int)
    ap.add_argument("meeting", nargs="?")
    ap.add_argument("--check-only", action="store_true",
                    help="skip fetching; only print the curated-data checklist")
    ap.add_argument("--no-track-map", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
    logging.getLogger("fastf1").setLevel(logging.WARNING)   # its INFO chatter is per-request
    try:
        import fastf1
        fastf1.set_log_level("WARNING")                     # fastf1 also owns its own handler
    except Exception:
        pass

    season, meeting = resolve_event(args.season, args.meeting)
    print(f"=== {season} {meeting} ===")
    if not check_event_name(season, meeting):
        return 2

    if not args.check_only:
        print("\n[1/6] sessions")
        infos = cache_sessions(season, meeting)

        print("\n[2/6] track map")
        if args.no_track_map:
            print("  skipped (--no-track-map)")
        else:
            warm_track_map(season, meeting, infos)

        print("\n[3/6] calendar")
        ensure_calendar(season)

        print("\n[4/6] session weather")
        refresh_session_weather(season)

        print("\n[5/6] market odds")
        snapshot_odds()

    print("\n[6/6] hand-curated data for this event")
    checklist(season, meeting)

    print("\nNext:")
    if dl.is_cached(str(season), meeting, "Qualifying") and not _has_quali_scene(season, meeting):
        print(f'  quali is cached but the 3D replay is not baked - run'
              f'\n    python scripts/build_quali_scenes.py {season} "{meeting}"')
    if dl.is_cached(str(season), meeting, "Race"):
        print("  the Race is cached - run  python scripts/after_race.py")
    else:
        print("  re-run this after the next session; once the race is cached,")
        print("  run  python scripts/after_race.py")
    return 0


def _has_quali_scene(season: int, meeting: str) -> bool:
    """Any baked QUALI 3D payload for this event (version-agnostic glob, so we
    don't import the heavy replay module just to answer a yes/no)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(meeting)).strip("_").lower()
    return any(Path("data/replays").glob(f"{season}_{slug}_quali3d_v*.json.gz"))


if __name__ == "__main__":
    raise SystemExit(main())
