"""
F1 Dashboard – Team-Radio Loader & Transcriber
==============================================
Fetches **race** team-radio audio from the F1 live-timing archive, downloads
the per-driver mp3 clips, transcribes them locally with faster-whisper, and
caches the result as Parquet so the (slow) fetch+transcribe only happens once.

Why this exists
---------------
FastF1 exposes no transcribed team radio — the live-timing feed only carries
radio as audio capture files. So we go one layer lower than FastF1's public
API: we reuse its `fastf1.api` helpers to fetch the `TeamRadio.jsonStream`
page for the *race* session, then download + transcribe the referenced mp3s
ourselves.

Availability note
-----------------
F1 keeps race-radio audio only for *recent* events; older sessions return
HTTP 403 for the mp3s. `race_radio_available()` checks this up front.

Public API
----------
race_radio_available(season, meeting) -> bool
load_race_radio(season, meeting, force=False, limit=None) -> pd.DataFrame
    columns: Utc, RacingNumber, Driver_Short, Url, Mp3, Transcript,
             SecondsIn, Clock
RADIO_ROUTE_DIR  -> Path of the on-disk mp3 cache (served by the Dash app)
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

import pandas as pd

from f1lib.config import RADIO_DIR, FASTF1_CACHE_DIR, RADIO_WHISPER_MODEL

logger = logging.getLogger(__name__)

_BASE = "https://livetiming.formula1.com/static/"
_UA   = {"User-Agent": "Mozilla/5.0"}

RADIO_ROUTE_DIR = Path(RADIO_DIR)

_WHISPER_MODEL = None   # lazy singleton


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _sanitize(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(text)).strip("_")


def _key(season, meeting) -> str:
    return f"{_sanitize(season)}__{_sanitize(meeting)}__Race"


def _parquet_path(season, meeting) -> Path:
    return RADIO_ROUTE_DIR / f"{_key(season, meeting)}__radio.parquet"


def _clip_dir(season, meeting) -> Path:
    return RADIO_ROUTE_DIR / _key(season, meeting)


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _race_session(season, meeting):
    """Load the race session via FastF1 (metadata only, no laps/telemetry)."""
    import fastf1
    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
    sess = fastf1.get_session(int(season), meeting, "R")   # RACE only
    sess.load(laps=False, telemetry=False, weather=False, messages=False)
    return sess


def _race_api_path(season, meeting) -> str | None:
    """Resolve the race session's live-timing static path via FastF1
    (race session only)."""
    sess = _race_session(season, meeting)
    path = sess.api_path                       # e.g. /static/2026/..._Race/
    return path.lstrip("/").replace("static/", "", 1)


def _driver_last_names(sess) -> list[str]:
    """Last names of the session's entry list — used to bias whisper toward
    the right proper nouns. Empty list if driver info is unavailable."""
    try:
        names = sess.results["LastName"].dropna().unique().tolist()
        return [n for n in names if n]
    except Exception:
        return []


def _fetch_captures(rel_path: str) -> list[dict]:
    """Download + parse the race TeamRadio.jsonStream into a deduped list of
    {Utc, RacingNumber, Path} capture dicts."""
    url = _BASE + rel_path + "TeamRadio.jsonStream"
    try:
        txt = _http_get(url).decode("utf-8-sig", "ignore")
    except Exception as exc:
        logger.warning("TeamRadio fetch failed (%s): %s", url, exc)
        return []
    seen, caps = set(), []
    for line in txt.splitlines():
        brace = line.find("{")
        if brace < 0:
            continue
        try:
            obj = json.loads(line[brace:])
        except Exception:
            continue
        block = obj.get("Captures")
        items = (block.values() if isinstance(block, dict)
                 else block if isinstance(block, list) else [])
        for c in items:
            p = c.get("Path")
            if p and p not in seen:
                seen.add(p)
                caps.append(c)
    return caps


def _driver_from_path(path: str) -> str:
    """Race-radio filenames look like 'TeamRadio/NOR_1_20260524_124627.mp3' —
    the leading token is the 3-letter driver code."""
    base = path.rsplit("/", 1)[-1]
    tok = base.split("_", 1)[0]
    return tok.upper() if re.fullmatch(r"[A-Z]{3}", tok or "") else ""


# ─────────────────────────────────────────────────────────────
# Topic tagging (keyword-based, applied to transcripts)
# ─────────────────────────────────────────────────────────────
# Order matters only for display; a clip can carry several topics.
_TOPIC_RULES: dict[str, re.Pattern] = {
    "PIT CALL": re.compile(
        r"\bbox\b|\bpit(?:s|ting|stop| stop)?\b|stay out|in this lap", re.I),
    "TYRES": re.compile(
        r"tyre|tire|\bdeg\b|degradation|grip|grain|blister|puncture|"
        r"flat.?spot|vibration|front (?:left|right)|rear (?:left|right)|"
        r"\b(?:softs|mediums|hards|inters|slicks|wets)\b|"
        r"the (?:soft|medium|hard|inter)\b|warm.?up", re.I),
    "WEATHER": re.compile(
        r"\brain(?:ing)?\b|drizzle|shower|\bwet\b|damp|drying|spitting|"
        r"few drops|\bwind\b", re.I),
    "TRAFFIC / FLAGS": re.compile(
        r"blue flag|traffic|safety car|\bvsc\b|virtual safety|yellow|"
        r"red flag|\bgap\b|car (?:behind|ahead|in front)|\bdrs\b|backmarker|"
        r"\bP\d{1,2}\b|podium|penalt|investigat|track limits|five.second|"
        r"\bbehind\b|\bahead\b|overtake\b|pushed (?:me|him) off", re.I),
    "ENERGY / MODE": re.compile(
        r"\bmode\b|\bstrat\b|battery|deploy|\benergy\b|recharge|derate|"
        r"harvest|lift and coast|overtake button|\bcharge\b|\bsoc\b|"
        r"\bpower\b", re.I),
    "STRATEGY": re.compile(
        r"\bplan [abc]\b|undercut|overcut|\bextend\b|\boffset\b|"
        r"target(?: lap)?|opposite|\bpush\b|hammer time|\bfuel\b|"
        r"\bswitch\b|we are (?:pitting|staying)|go(?:ing)? (?:long|short)|"
        r"one.stop|two.stop", re.I),
    "CAR / DAMAGE": re.compile(
        r"\bbrakes?\b|suspension|\bbroken\b|damage|overheat|temperature|"
        r"degrees|\bwing\b|\bfloor\b|\bseat\b|steering|gearbox|\bengine\b|"
        r"upshift|downshift|\bride\b|cockpit|wheel shield", re.I),
}


def tag_topics(text) -> str:
    """Comma-joined topic labels found in a transcript ('' when none match).
    Keyword-based on purpose: cheap, transparent, easy to tune."""
    t = str(text or "")
    if not t.strip():
        return ""
    return ", ".join(name for name, rx in _TOPIC_RULES.items() if rx.search(t))


def _ensure_topics(df: pd.DataFrame) -> pd.DataFrame:
    """Add/refresh the Topics column from the working transcript."""
    df["Topics"] = df.get("Transcript", pd.Series("", index=df.index)).map(tag_topics)
    return df


def _get_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        logger.info("Loading faster-whisper model %r …", RADIO_WHISPER_MODEL)
        _WHISPER_MODEL = WhisperModel(
            RADIO_WHISPER_MODEL, device="cpu", compute_type="int8"
        )
    return _WHISPER_MODEL


# Static F1 vocabulary fed to whisper as `initial_prompt` — biases decoding
# toward radio jargon it otherwise mishears (per-event driver names are
# prepended at transcription time). Whisper caps the prompt at 224 tokens.
_F1_PROMPT = (
    "Formula 1 team radio between driver and race engineer. Phrases: "
    "box box, box this lap, stay out, undercut, overcut, deg, degradation, "
    "DRS enabled, safety car, VSC, blue flags, track limits, five-second "
    "penalty, strat mode, mode push, brake bias, front wing, gap to car "
    "behind, plan B, softs, mediums, hards, inters, copy that."
)


def _build_prompt(driver_names: list[str]) -> str:
    if not driver_names:
        return _F1_PROMPT
    return _F1_PROMPT[:_F1_PROMPT.index("Phrases:")] + \
        "Drivers: " + ", ".join(driver_names) + ". " + \
        _F1_PROMPT[_F1_PROMPT.index("Phrases:"):]


def _transcribe(mp3: Path, prompt: str = _F1_PROMPT) -> str:
    """Transcribe one clip. VAD strips the squelch/static that makes whisper
    hallucinate on near-silent clips; segments whisper itself scores as
    probable non-speech are dropped for the same reason."""
    try:
        segs, _ = _get_model().transcribe(
            str(mp3), language="en", beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        kept = [s.text.strip() for s in segs
                if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return " ".join(kept).strip()
    except Exception as exc:
        logger.warning("Transcription failed for %s: %s", mp3.name, exc)
        return ""


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def radio_cached(season, meeting) -> bool:
    """True if a transcript Parquet already exists (loads instantly)."""
    return _parquet_path(season, meeting).exists()


def race_radio_available(season, meeting) -> bool:
    """True if the F1 archive still serves race-radio audio for this meeting.
    A cached transcript Parquet also counts as available (offline-safe)."""
    if _parquet_path(season, meeting).exists():
        return True
    try:
        rel = _race_api_path(season, meeting)
        if not rel:
            return False
        url = _BASE + rel + "TeamRadio.jsonStream"
        req = urllib.request.Request(url, method="HEAD", headers=_UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def load_race_radio(season, meeting, force: bool = False,
                    limit: int | None = None) -> pd.DataFrame:
    """Fetch + transcribe (or load from cache) the race team radio for a
    meeting. Returns one row per clip; empty DataFrame if no radio exists.

    Parameters
    ----------
    force : re-download + re-transcribe even if a cache exists.
    limit : transcribe at most N clips (newest first) — handy for a quick
            first pass; omitted = all clips.
    """
    pq = _parquet_path(season, meeting)
    if pq.exists() and not force:
        df = pd.read_parquet(pq)
        if "Transcript_raw" not in df.columns:
            df["Transcript_raw"] = df.get("Transcript", "")
        if "reviewed" not in df.columns:
            df["reviewed"] = False
        # Topics are recomputed in memory on every load (cheap regex pass) so
        # tuning the keyword rules takes effect without invalidating caches.
        df = _ensure_topics(df)
        logger.info("[radio cache HIT] %s (%d clips)", _key(season, meeting), len(df))
        return df

    # Hand-corrected transcripts survive a force re-transcription: remember
    # the reviewed rows (keyed by mp3 filename) before rebuilding.
    reviewed_keep: dict[str, str] = {}
    if pq.exists() and force:
        old = pd.read_parquet(pq)
        if "reviewed" in old.columns:
            kept = old[old["reviewed"].fillna(False).astype(bool)]
            reviewed_keep = dict(zip(kept["Mp3"], kept["Transcript"]))

    sess = _race_session(season, meeting)
    path = sess.api_path
    rel = path.lstrip("/").replace("static/", "", 1) if path else None
    if not rel:
        return pd.DataFrame()
    prompt = _build_prompt(_driver_last_names(sess))
    caps = _fetch_captures(rel)
    if not caps:
        logger.info("[radio] no captures for %s", _key(season, meeting))
        return pd.DataFrame()

    caps.sort(key=lambda c: c.get("Utc", ""))
    if limit:
        caps = caps[-int(limit):]

    clip_dir = _clip_dir(season, meeting)
    clip_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    n = len(caps)
    for i, c in enumerate(caps, 1):
        path = c.get("Path", "")
        url  = _BASE + rel + path
        fname = path.rsplit("/", 1)[-1]
        local = clip_dir / fname
        if not local.exists():
            try:
                local.write_bytes(_http_get(url))
            except Exception as exc:
                logger.warning("Download failed %s: %s", fname, exc)
                continue
        print(f"  [radio] transcribing {i}/{n}  {fname}", flush=True)
        text = _transcribe(local, prompt)
        mp3_key = f"{_key(season, meeting)}/{fname}"   # relative to RADIO_DIR
        rows.append({
            "Utc":           c.get("Utc"),
            "RacingNumber":  str(c.get("RacingNumber", "")),
            "Driver_Short":  _driver_from_path(path),
            "Url":           url,
            "Mp3":           mp3_key,
            "Transcript_raw": text,   # verbatim whisper output, never edited
            # working copy — hand corrections from a previous review win
            "Transcript":    reviewed_keep.get(mp3_key, text),
            "reviewed":      mp3_key in reviewed_keep,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _ensure_topics(df)
    df["Utc"] = pd.to_datetime(df["Utc"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.sort_values("Utc").reset_index(drop=True)
    t0 = df["Utc"].min()
    df["SecondsIn"] = (df["Utc"] - t0).dt.total_seconds()
    df["Clock"]     = df["Utc"].dt.strftime("%H:%M:%S")
    df["season"], df["meeting"] = str(season), meeting

    pq.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(pq, index=False)
    logger.info("[radio] saved %s (%d clips)", _key(season, meeting), len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    import sys
    yr  = sys.argv[1] if len(sys.argv) > 1 else "2026"
    mtg = sys.argv[2] if len(sys.argv) > 2 else "Canadian Grand Prix"
    print("available:", race_radio_available(yr, mtg))
    out = load_race_radio(yr, mtg, limit=int(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(out[["Clock", "Driver_Short", "Transcript"]].to_string() if not out.empty else "no radio")
