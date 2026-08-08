"""Assemble the EVIDENCE for a post-race model review — everything but the verdict.

`seed_model_review.py` says which drivers the model got wrong. It deliberately
refuses to say why, because a machine guessing at a cause is inventing race
history. That refusal is right, but it left the whole job to memory: you had to
recall, days later, whether a car picked up damage or simply never showed its
pace.

This script closes that gap without crossing the line. It gathers what the
archive already knows about each flagged driver — what the model read, what
went into the number it missed, which race-control messages named that car,
what the teammate did — and prints it as a dossier. Every line is a fact with a
provenance. It never writes to `data/model_review.csv`; the verdict stays a
human judgement, made faster because the evidence is already on the table.

    python scripts/review_dossier.py --latest
    python scripts/review_dossier.py --season 2026 --event "Hungarian Grand Prix"

WHY THE ADMISSIBILITY SECTION MATTERS MORE THAN THE REST. The two things being
predicted are narrow statistics, not "how the race went":

  onelap  = best qualifying lap, session-normalised across Q1/Q2/Q3
  longrun = MEDIAN of clean-air, fuel- and track-corrected race laps, after
            ValidLap & ~Dirty_Air & ~Perturbed_Lap and a >=10-lap floor

The race number therefore cannot see traffic (dirty-air laps are dropped before
the median is taken), cannot see pit calls, and cannot see a time penalty added
at the flag. A `traffic` or `penalty` verdict on a longrun row is a category
error — it explains the driver's afternoon rather than the statistic that
missed. The screens below exist to catch that mistake, which is the easy one to
make when writing the note from a race report instead of from the data.

Screens FIRE or stay silent on mechanical thresholds. A screen firing is not a
verdict; it is a reason to go and look.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.processing import (clean_and_enrich_laps, enrich_track_evolution,
                              flag_dirty_air, flag_perturbed_laps)

REVIEW = Path("data/model_review.csv")
SESS = Path("data/sessions")
OUT_DIR = Path("data/review_dossiers")

# Screen thresholds. Deliberately loose — a screen exists to make you look, and
# a screen that only fires on certainty tells you nothing you did not know.
MIN_CLEAN_LAPS = 15      # below this the median rests on a thin, late sample
TRUNCATED_SHARE = 0.85   # last clean lap earlier than this share of the race
COMPOUND_MATTERS = 0.15  # % of a lap; below this a compound skew is not a cause
PACE_BREAK = 0.40        # % step between race halves that wants explaining
SD_TEAMMATE = 1.0        # teammate miss beyond this many sd = team-level


# ─────────────────────────────────────────────────────────────
# loading
# ─────────────────────────────────────────────────────────────

def _key(season: int, event: str) -> str:
    return f"{season}__{event.replace(' ', '_')}"


def _load(season: int, event: str, session: str, part: str):
    p = SESS / f"{_key(season, event)}__{session}__{part}.parquet"
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def race_clean_laps(season: int, event: str):
    """The exact pipeline driver_ratings uses to build the `longrun` actual.

    Reproduced rather than imported because the point of the dossier is to show
    what went INTO the number; running a different cleaning here would compare
    the miss against a statistic nobody predicted.
    """
    raw = _load(season, event, "Race", "laps")
    if raw is None:
        return None, None, None
    rcm = _load(season, event, "Race", "race_control")
    fl = clean_and_enrich_laps(raw)
    fl = enrich_track_evolution(flag_dirty_air(flag_perturbed_laps(fl, rcm=rcm)))
    y = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in fl.columns
         else "LapTime_FuelCorrected")
    clean = fl[fl["ValidLap"] & ~fl.get("Dirty_Air", False)
               & ~fl.get("Perturbed_Lap", False)]
    return fl, clean, y


def practice_input(season: int, event: str):
    """How much clean practice evidence the model had, per driver AND per kind.

    A miss against a read taken from four long-run laps is a different animal
    from a miss against thirty, and the ledger's sd only partly carries that.
    Split by kind because the two predictions eat different laps: `onelap` is
    fitted on quali-sim laps only and `longrun` on everything else, so a car
    that skipped FP2 can have a healthy total and almost no race-pace evidence.
    """
    from f1lib.pace_features import enrich_for_features
    frames = []
    for s in ("Practice_1", "Practice_2", "Practice_3", "Sprint",
              "Sprint Qualifying"):
        raw = _load(season, event, s.replace(" ", "_"), "laps")
        if raw is None:
            continue
        try:
            fl = enrich_for_features(raw)
        except Exception:
            try:
                fl = clean_and_enrich_laps(raw)
                fl["Is_Quali_Sim"] = False
            except Exception:
                continue
        fl["_session"] = s
        frames.append(fl)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def practice_counts(prac: pd.DataFrame, kind: str) -> pd.Series:
    """Clean practice laps of the type this prediction is fitted on."""
    if prac is None or prac.empty:
        return pd.Series(dtype=int)
    p = prac[prac.get("ValidLap", True)]
    if "Is_Quali_Sim" in p.columns:
        p = p[p["Is_Quali_Sim"]] if kind == "onelap" else p[~p["Is_Quali_Sim"]]
    return p.groupby("Driver_Short").size()


# ─────────────────────────────────────────────────────────────
# field-wide context
# ─────────────────────────────────────────────────────────────

def filter_view(fl: pd.DataFrame, clean: pd.DataFrame, y: str) -> pd.DataFrame:
    """What the clean-air filter removed, per driver — MANDATORY reading.

    The model measures a counterfactual ("what would this car do in free air")
    and discards everything else: across 2026 it keeps roughly HALF of a race.
    That is a deliberate modelling choice, but it must not be treated as a
    neutral precondition when asking why prediction and reality diverged. The
    discarded laps are laps the driver actually drove, and a driver whose race
    was mostly spent in traffic is measured on a thin, unrepresentative slice
    of it. When the filter moves a driver further than the miss being
    explained, the filter IS the finding.

    Returns, per driver: retention, the model's clean-air gap, the same median
    over every racing lap (in/out laps dropped, nothing else), and the
    difference. Both gaps are field-relative on their OWN basis, so they are
    directly comparable.
    """
    racing = fl[fl["PitIn"].isna() & fl["PitOut"].isna() & fl[y].notna()]
    cm = clean.groupby("Driver_Short")[y].median()
    rm = racing.groupby("Driver_Short")[y].median()
    if cm.empty or rm.empty:
        return pd.DataFrame()
    n_tot = fl.groupby("Driver_Short").size()
    n_cl = clean.groupby("Driver_Short").size()
    out = pd.DataFrame({
        "n_total": n_tot, "n_clean": n_cl,
        "keep": n_cl / n_tot,
        "clean_gap": 100 * (cm / cm.median() - 1),
        "all_gap": 100 * (rm / rm.median() - 1),
    })
    out["delta"] = out["all_gap"] - out["clean_gap"]
    out["field_keep"] = float((n_cl / n_tot).median())
    return out


def compound_offsets(clean: pd.DataFrame, y: str) -> pd.Series:
    """Within-driver compound offset, measured on THIS race's clean laps.

    Within-driver so a fast car running softs cannot masquerade as a soft-tyre
    advantage. Returned in seconds; the caller converts to % of a lap.
    """
    rows = []
    for drv, g in clean.groupby("Driver_Short"):
        cc = g.groupby("Compound")[y].agg(["median", "size"])
        cc = cc[cc["size"] >= 5]
        if len(cc) < 2:
            continue
        for c, v in cc.iterrows():
            rows.append({"driver": drv, "compound": c,
                         "dev": v["median"] - cc["median"].mean()})
    if not rows:
        return pd.Series(dtype=float)
    cd = pd.DataFrame(rows)
    return cd.groupby("compound")["dev"].mean()


def weather_line(season: int, event: str, session: str) -> str:
    """One line per session — and the WET call comes from the tyres, not the
    rain flag.

    `Rainfall.any()` trips on a single True anywhere in the weather stream, so
    it labelled all three Monaco 2026 practices "RAIN RECORDED" when every car
    ran slicks throughout. That reading nearly produced a `weather` verdict for
    a weekend that was dry. What the model actually cares about is whether the
    session ran on wet tyres, which is what it uses to decide a session is
    unusable — so report that, and keep the rain flag as a footnote.
    """
    w = _load(season, event, session, "weather")
    if w is None or w.empty:
        return f"{session:<12} —"

    # Rain as a SHARE of the session, not a boolean. `Rainfall.any()` labelled
    # all three Monaco 2026 practices wet off a single sample while every car
    # ran slicks throughout, which nearly produced a `weather` verdict for a
    # dry weekend.
    rain_txt = ""
    if "Rainfall" in w.columns:
        share = float(w["Rainfall"].astype(bool).mean())
        if share > 0:
            rain_txt = (f"  rain on {100 * share:.0f}% of samples"
                        if share >= 0.02 else "  rain flag: isolated sample")

    # Name the actual tyre. INTERMEDIATE is the wet-weather tyre that gets used
    # — across the whole archive it outnumbers full WET ten to one, and in 2026
    # only one session saw either — so collapsing both into "wet" both
    # overstates the conditions and hides which tyre was on the car.
    tyre_txt = ""
    laps = _load(season, event, session.replace(" ", "_"), "laps")
    if laps is not None and "Compound" in laps.columns:
        c = laps["Compound"].astype(str).str.upper()
        c = c[~c.isin({"MISSING", "NAN", "NONE", "UNKNOWN"})]
        if len(c):
            inter = float(c.eq("INTERMEDIATE").mean())
            wet = float(c.eq("WET").mean())
            bits = []
            if inter > 0.005:
                bits.append(f"INTERMEDIATE {100 * inter:.0f}%")
            if wet > 0.005:
                bits.append(f"WET {100 * wet:.0f}%")
            tyre_txt = ("  " + " · ".join(bits) + " of laps" if bits
                        else "  all on slicks")
    return (f"{session:<12} air {w['AirTemp'].mean():.1f}C  "
            f"track {w['TrackTemp'].mean():.1f}C "
            f"(range {w['TrackTemp'].min():.0f}-{w['TrackTemp'].max():.0f})"
            + tyre_txt + rain_txt)


# Messages that name a car but carry no information about its pace. Blue flags
# are the worst offender: a car being lapped generates one every few laps, and
# they describe exactly the dirty-air laps the median has already discarded.
_RC_NOISE = ("WAVED BLUE FLAG", "FIRST CAR TO TAKE THE FLAG")


def race_control_for(rcm: pd.DataFrame, driver: str, car_no) -> tuple[list[str], int]:
    """(interesting messages naming this car, count of routine ones dropped)."""
    if rcm is None or rcm.empty or "Message" not in rcm.columns:
        return [], 0
    m = rcm["Message"].astype(str)
    pat = f"\\({driver}\\)"
    if car_no is not None and str(car_no) != "nan":
        pat += f"|CAR {int(float(car_no))}\\b"
    hit = rcm[m.str.contains(pat, case=False, na=False, regex=True)]
    keep, noise = [], 0
    for _, r in hit.iterrows():
        msg = str(r["Message"]).strip()
        if any(k in msg.upper() for k in _RC_NOISE):
            noise += 1
            continue
        keep.append(f"{str(r.get('Time', ''))[:19]}  {msg}")
    return keep, noise


# ─────────────────────────────────────────────────────────────
# per-driver screens
# ─────────────────────────────────────────────────────────────

def longrun_screens(drv: str, clean: pd.DataFrame, y: str, n_race_laps: float,
                    offs: pd.Series, field_med: float) -> list[str]:
    out = []
    g = clean[clean["Driver_Short"] == drv]
    if g.empty:
        return ["!! no clean laps at all — the actual cannot be trusted"]
    n = len(g)
    last = float(g["LapNo"].max())

    if n < MIN_CLEAN_LAPS:
        out.append(f"THIN SAMPLE  only {n} clean laps entered the median "
                   f"(field median {MIN_CLEAN_LAPS}+ is normal)")
    if n_race_laps and last < TRUNCATED_SHARE * n_race_laps:
        out.append(f"TRUNCATED  last clean lap {last:.0f} of {n_race_laps:.0f} "
                   f"— the median covers only the first "
                   f"{100 * last / n_race_laps:.0f}% of the race")

    # compound skew, valued at THIS race's measured offsets
    if len(offs):
        mix = g["Compound"].value_counts(normalize=True)
        exp = sum(offs.get(c, 0.0) * s for c, s in mix.items())
        field_mix = clean["Compound"].value_counts(normalize=True)
        exp_f = sum(offs.get(c, 0.0) * s for c, s in field_mix.items())
        d_pct = 100 * (exp - exp_f) / field_med
        if abs(d_pct) >= COMPOUND_MATTERS:
            out.append(f"COMPOUND SKEW  ran {', '.join(f'{c} {100*s:.0f}%' for c, s in mix.items())} "
                       f"vs field {', '.join(f'{c} {100*s:.0f}%' for c, s in field_mix.items())} "
                       f"— worth {d_pct:+.2f}% of a lap at this race's measured offsets")

    # Changepoint scan rather than a fixed halves split. WHERE the step falls is
    # the whole value of this screen: a step at the lap a driver made contact is
    # evidence, a step at the midpoint is arithmetic.
    #
    # CALIBRATED AGAINST A PERMUTATION NULL, and it has to be. Taking the
    # maximum over ~40 candidate splits guarantees a large number even in pure
    # noise, so the raw version fired on nine drivers out of nine — which is
    # the signature of a screen measuring its own search, not the race.
    # Shuffling the lap ORDER keeps each driver's own spread of lap times and
    # destroys only the time structure, which is exactly the null "this car's
    # pace never stepped, the laps just landed in some order".
    if n >= 12:
        gs = g.sort_values("LapNo")
        laps = gs["LapNo"].to_numpy()
        # Scan the FIELD-RELATIVE series, not the raw lap times. Raw times step
        # late in almost every race because the last stint is the oldest set of
        # tyres — the first version of this screen duly reported a step at laps
        # 48-64 for most of the grid, which is the race happening, not damage.
        # Subtracting the field's own median at each lap leaves only what this
        # car did differently.
        fieldmed = clean.groupby("LapNo")[y].median()
        v = (gs[y].to_numpy()
             - gs["LapNo"].map(fieldmed).to_numpy())

        def _max_split(arr):
            b, bi = 0.0, None
            for i in range(5, len(arr) - 5):
                d = float(np.median(arr[i:]) - np.median(arr[:i]))
                if abs(d) > abs(b):
                    b, bi = d, i
            return b, bi

        obs, idx = _max_split(v)
        rng = np.random.default_rng(0)      # fixed seed: same dossier twice
        null = np.array([abs(_max_split(rng.permutation(v))[0])
                         for _ in range(200)])
        pct = float((null < abs(obs)).mean())
        step = 100 * obs / field_med
        if abs(step) >= PACE_BREAK and idx is not None and pct >= 0.90:
            out.append(f"PACE STEP  {step:+.2f}% at lap {laps[idx]:.0f} "
                       f"({'slower' if step > 0 else 'faster'} afterwards; "
                       f"bigger than {100 * pct:.0f}% of shuffled orderings) "
                       f"— check this lap against race control before calling "
                       f"it damage; an unexplained step is not yet a cause")
    return out


ATTEMPT_COST = 0.170   # % of a lap per extra flying lap (n=78, p<1e-4)


def attempt_counts(qlaps: pd.DataFrame) -> pd.Series:
    """Flying laps completed per driver in qualifying.

    The onelap actual is a MINIMUM over these, so its expected value depends on
    how many a driver got — a measurement property, not a fact about the car.
    """
    if qlaps is None or qlaps.empty:
        return pd.Series(dtype=int)
    q = qlaps.copy()
    q["drv"] = q["Driver"].astype(str).str.split("-").str[0]
    s = pd.to_timedelta(q["LapTime"], errors="coerce").dt.total_seconds()
    if s.isna().all():
        s = pd.to_numeric(q["LapTime"], errors="coerce")
    fly = q[s.notna() & q["PitIn"].isna() & q["PitOut"].isna()]
    return fly.groupby("drv").size()


def onelap_screens(drv: str, qres: pd.DataFrame, qlaps: pd.DataFrame,
                   rcm: pd.DataFrame, miss: float = 0.0) -> list[str]:
    out = []
    n = attempt_counts(qlaps)
    if len(n) and drv in n.index:
        med = float(n.median())
        mine = int(n[drv])
        exp = (med - mine) * ATTEMPT_COST     # + = expected to look slower
        out.append(f"ATTEMPTS  {mine} flying laps against a field median of "
                   f"{med:.0f}")
        if med and mine < 0.8 * med:
            # Same sign discipline as the filter screen: subtract the expected
            # attempt penalty and see whether the miss actually shrinks. A
            # driver with few attempts who missed FASTER than predicted is
            # evidence against this channel, not for it.
            corrected = miss - exp
            red = ((abs(miss) - abs(corrected)) / abs(miss)) if miss else 0.0
            verdict = (". Consider `measurement_artifact` before blaming the "
                       "model." if red >= 0.4 else
                       f", cutting it by {100 * red:.0f}% — worth recording, "
                       f"not enough to be the verdict." if red > 0.05 else
                       " — it does NOT shrink the miss, so the attempt "
                       "deficit is not the cause here.")
            out.append(f"FEW ATTEMPTS  the actual is a MINIMUM over those laps, "
                       f"worth {ATTEMPT_COST:.3f}% each — {mine} vs {med:.0f} "
                       f"predicts a {exp:+.2f}% penalty, moving the miss "
                       f"{miss:+.3f}% → {corrected:+.3f}%" + verdict)
    if qres is None or qres.empty:
        return out
    row = qres[qres["Abbreviation"] == drv]
    if row.empty:
        return out
    row = row.iloc[0]
    seg = {}
    for c in ("Q1", "Q2", "Q3"):
        v = row.get(c)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = np.nan
        if pd.notna(v):
            seg[c] = v
    if seg:
        best_seg = min(seg, key=seg.get)
        out.append(f"BEST LAP from {best_seg} ({seg[best_seg]:.3f}s)  "
                   f"[{'  '.join(f'{k} {v:.3f}' for k, v in seg.items())}]")
        if best_seg != max(seg, key=lambda k: int(k[1])):
            out.append(f"WENT SLOWER  its later segment was worse than "
                       f"{best_seg} — the counted lap is not its last attempt")
        knocked = {"Q1": 1, "Q2": 2, "Q3": 3}[max(seg, key=lambda k: int(k[1]))]
        if knocked < 3:
            out.append(f"ELIMINATED in Q{knocked} — the counted lap was set on "
                       f"a greener track than the Q3 runners'; quali_norm "
                       f"corrects for this, so treat a residual as real")

    # a deleted lap faster than the counted best is a real, measurable cause
    if qlaps is not None and "IsDeleted" in qlaps.columns and seg:
        d = qlaps[(qlaps["Driver"].astype(str).str.startswith(drv))
                  & qlaps["IsDeleted"].fillna(False).astype(bool)]
        for _, r in d.iterrows():
            lt = r.get("LapTime")
            lt = (lt.total_seconds() if hasattr(lt, "total_seconds")
                  else float(lt) if pd.notna(lt) else np.nan)
            best = min(seg.values())
            if pd.notna(lt) and lt < best:
                out.append(f"DELETED LAP WAS FASTER  {lt:.3f}s vs counted "
                           f"{best:.3f}s — {r.get('DeletedReason', '')} "
                           f"(this DOES move the actual)")
            elif pd.notna(lt):
                out.append(f"deleted lap {lt:.3f}s, slower than its counted "
                           f"{best:.3f}s — no effect on the number")
    return out


# ─────────────────────────────────────────────────────────────
# report
# ─────────────────────────────────────────────────────────────

def build(season: int, event: str) -> str:
    if not REVIEW.exists():
        return "no data/model_review.csv — run seed_model_review.py first"
    rv = pd.read_csv(REVIEW)
    ev = rv[(rv["season"] == season) & (rv["event"] == event)]
    if ev.empty:
        return f"no review rows for {season} {event}"

    fl, clean, y = race_clean_laps(season, event)
    qres = _load(season, event, "Qualifying", "results")
    qlaps = _load(season, event, "Qualifying", "laps")
    qrcm = _load(season, event, "Qualifying", "race_control")
    rrcm = _load(season, event, "Race", "race_control")
    rres = _load(season, event, "Race", "results")
    prac = practice_input(season, event)

    n_race_laps = float(fl["LapNo"].max()) if fl is not None else 0.0
    offs = compound_offsets(clean, y) if clean is not None else pd.Series(dtype=float)
    field_med = float(clean[y].median()) if clean is not None else 1.0
    fv = filter_view(fl, clean, y) if clean is not None else None
    if fv is not None and fv.empty:
        fv = None

    # Who actually HAS an actual this weekend, per kind, and who drove for whom.
    # Needed to tell "team mate was measured and was fine" from "team mate was
    # never measured", which are opposite conclusions about the car.
    act_by_kind: dict[str, set] = {}
    team_of: dict[str, str] = {}
    pp = Path("data/driver_pace_by_event.csv")
    if pp.exists():
        try:
            dp = pd.read_csv(pp)
            dp = dp[(dp["season"] == season) & (dp["event"] == event)]
            for k, tgt in (("onelap", "quali"), ("longrun", "race")):
                act_by_kind[k] = set(
                    dp[(dp["kind"] == tgt) & dp["gap_pct"].notna()]["driver"])
            if "team" in dp.columns:
                team_of = dict(zip(dp["driver"], dp["team"]))
        except Exception:
            pass
    # roster fallback: the flagged rows themselves always carry a team
    for _, x in ev.iterrows():
        team_of.setdefault(str(x["driver"]), str(x["team"]))

    L = []
    a = L.append
    rnd = int(ev["round"].iloc[0])
    a(f"# WHY THE MODEL MISSED — evidence dossier")
    a(f"{season} R{rnd} · {event} · dossier built {date.today()}")
    a("")
    a("Facts only. Nothing here is a verdict; the category and the note are "
      "yours to write.")
    a("")

    a("## 0 · What these two numbers can and cannot see")
    a("")
    a("```")
    a("onelap  = best qualifying lap, session-normalised across Q1/Q2/Q3,")
    a("          expressed vs the field median.")
    a("longrun = MEDIAN of clean-air race laps, fuel- and track-corrected,")
    a("          after ValidLap & ~Dirty_Air & ~Perturbed_Lap, >=10 laps.")
    a("```")
    a("")
    a("Dirty-air, safety-car and in/out laps are removed BEFORE the race median "
      "is taken. So on a `longrun` row:")
    a("")
    a("- **`traffic` is almost never admissible** — the laps behind another car "
      "are already gone from the statistic.")
    a("- **`penalty` is almost never admissible** — five seconds at the flag "
      "does not change a lap time.")
    a("- **`strategy` needs a stated mechanism** that moves the *median clean "
      "lap* — compound mix or stint length, not the pit call itself. The "
      "compound screen below prices that mechanism at this race's own numbers.")
    a("")
    a("On an `onelap` row the admissible causes are only those inside the "
      "qualifying hour: a deleted best lap, a flag on the flyer, a car change, "
      "weather moving between segments. Anything about the race is not "
      "evidence about this number.")
    a("")

    a("## 1 · Field-wide context")
    a("")
    a("```")
    # Sprint sessions included: on a sprint weekend there is only one practice
    # and Sprint Qualifying / the Sprint ARE the model's input, so omitting
    # them hid the conditions the read was actually taken in. Sessions with no
    # cached weather render as "—" and cost a line.
    for s in ("Practice_1", "Practice_2", "Practice_3", "Sprint_Qualifying",
              "Sprint_Shootout", "Sprint", "Qualifying", "Race"):
        a(weather_line(season, event, s))
    a("```")
    a("")
    if len(offs):
        a(f"Within-driver compound offsets measured on this race's clean laps "
          f"(negative = faster):")
        a("")
        a("```")
        for c, v in offs.sort_values().items():
            a(f"  {c:<8} {v:+.3f} s/lap   ({100 * v / field_med:+.2f}% of a lap)")
        a("```")
        a("")
        a("Use these to price a compound story before believing it. A skew "
          "worth less than the miss is not the cause of the miss.")
        a("")
    if fv is not None:
        a(f"**How much of the race the model actually measured**: it kept a "
          f"median of {100 * fv['keep'].median():.0f}% of each driver's laps "
          f"(range {100 * fv['keep'].min():.0f}–{100 * fv['keep'].max():.0f}%). "
          f"Everything else — dirty air, safety car, in/out — is gone before "
          f"the median is taken. Read the per-driver 'what the filter did' "
          f"line before writing any verdict: where the filter moves a driver "
          f"further than the miss, the filter is the finding.")
        a("")

    if rrcm is not None and "Message" in rrcm.columns:
        # \b matters: "CHEQUERED FLAG" contains the substring "RED FLAG", so an
        # unanchored search reports a red flag at the end of every clean race.
        sc = rrcm[rrcm["Message"].astype(str).str.contains(
            r"SAFETY CAR|VIRTUAL SAFETY|\bRED FLAG\b", case=False, na=False,
            regex=True)]
        a("Race-control, session-wide:")
        a("")
        a("```")
        if len(sc):
            for _, r in sc.iterrows():
                a(f"  {str(r.get('Time',''))[:19]}  {str(r['Message']).strip()}")
        else:
            a("  no safety car, VSC or red flag")
        a("```")
        a("")

    a("## 2 · Per-driver evidence")
    a("")

    inc = pd.DataFrame()
    if Path("data/incidents.csv").exists():
        ic = pd.read_csv("data/incidents.csv")
        inc = ic[(ic["season"] == season) & (ic["event"] == event)]
    pit = pd.DataFrame()
    pp = Path(f"data/pitstops/{_key(season, event)}__Race__pitstops.parquet")
    if pp.exists():
        pit = pd.read_parquet(pp)
    rad = pd.DataFrame()
    rp = Path(f"data/radio/{_key(season, event)}__Race__radio.parquet")
    if rp.exists():
        rad = pd.read_parquet(rp)

    for kind, klabel in (("onelap", "QUALIFYING"), ("longrun", "RACE PACE")):
        sub = ev[ev["kind"] == kind]
        if sub.empty:
            continue
        a(f"### {klabel}")
        a("")
        for _, r in sub.sort_values("miss").iterrows():
            drv, team = str(r["driver"]), str(r["team"])
            miss, sd = float(r["miss"]), float(r["sd"])
            dirn = "FASTER than predicted" if miss < 0 else "SLOWER than predicted"
            a(f"#### {drv} · {team}")
            a("")
            a(f"predicted {r['predicted']:+.3f} → actual {r['actual']:+.3f} · "
              f"**miss {miss:+.3f}%** ({abs(miss)/sd:.1f} sd) · {dirn}")
            a("")

            # teammate — the single most diagnostic line in the dossier
            mate = sub[(sub["team"] == team) & (sub["driver"] != drv)]
            same_team_all = ev[(ev["team"] == team) & (ev["kind"] == kind)]
            if not mate.empty:
                m = mate.iloc[0]
                same = "SAME" if np.sign(float(m["miss"])) == np.sign(miss) else "OPPOSITE"
                a(f"- **Teammate**: {m['driver']} missed {float(m['miss']):+.3f}% "
                  f"— {same} direction. {'Both cars wrong the same way points at the CAR or the model read, not at this driver.' if same == 'SAME' else 'Opposite directions point at something driver-specific.'}")
            elif len(same_team_all) == 1:
                # "not flagged" and "not measurable" are different claims. The
                # race actual needs >=10 clean laps, so a team mate who retired
                # early has no row at all, and reading that as "driver-specific"
                # asserts the car was fine when nothing was measured.
                act_index = act_by_kind.get(kind, set())
                mates_ros = [d2 for d2, t2 in team_of.items()
                             if t2 == team and d2 != drv]
                mate_seen = any(m in act_index for m in mates_ros)
                if mate_seen:
                    a(f"- **Teammate**: measured and inside its band, so this "
                      f"is driver-specific, not a car-wide miss.")
                else:
                    a(f"- **Teammate**: NO actual for this kind — too few "
                      f"clean laps to measure (retirement or early exit). "
                      f"Scope is UNKNOWN, not driver-specific: check the other "
                      f"car's raw pace by hand before concluding anything "
                      f"about this driver.")

            # what the model read — the laps of THIS kind, not the weekend total
            if prac is not None:
                pg = prac[prac["Driver_Short"] == drv]
                cnt = practice_counts(prac, kind)
                mine, med = int(cnt.get(drv, 0)), float(cnt.median() or 0)
                if len(pg):
                    per = pg.groupby("_session").size()
                    a(f"- **Practice evidence the model read**: {mine} clean "
                      f"{'quali-sim' if kind == 'onelap' else 'long-run'} laps "
                      f"(field median {med:.0f}) · sessions run: "
                      f"{', '.join(f'{k} {v}' for k, v in per.items())}")
                    # A thin read is a cause in its own right and is NOT the
                    # same thing as the model being wrong — worth separating
                    # when the season's categories get counted.
                    if med and mine < 0.6 * med:
                        a(f"- **SCREEN** · THIN READ  the model had {mine} laps "
                          f"of this type against a field median of {med:.0f} — "
                          f"it was extrapolating for this car, so a large miss "
                          f"here is weak evidence about the model itself")

            if kind == "longrun" and rres is not None and not rres.empty:
                rr = rres[rres["Abbreviation"] == drv]
                if len(rr):
                    st = str(rr.iloc[0].get("Status", ""))
                    cls = str(rr.iloc[0].get("ClassifiedPosition", "")).strip()
                    # ClassifiedPosition, not Status: a car can be "Lapped" and
                    # still take the flag, and calling that a DNF invents a
                    # retirement. Only a non-numeric classification (R/D/W/N/F)
                    # means the car did not finish.
                    if cls and not cls.isdigit():
                        a(f"- **Did not finish**: `{st}` (classified `{cls}`) — "
                          f"the median rests only on the laps it completed, and "
                          f"whatever ended its race may have been slowing it "
                          f"before that")

            if kind == "longrun" and clean is not None:
                g = clean[clean["Driver_Short"] == drv]
                gf = fl[fl["Driver_Short"] == drv]
                if len(g):
                    mix = ", ".join(f"{c} {n}" for c, n in
                                    g["Compound"].value_counts().items())
                    a(f"- **What made the actual**: {len(g)} clean laps of "
                      f"{len(gf)} run (laps {g['LapNo'].min():.0f}–"
                      f"{g['LapNo'].max():.0f} of {n_race_laps:.0f}) · {mix}")
                    a(f"- **Dropped before the median**: "
                      f"{int(gf.get('Dirty_Air', pd.Series(dtype=bool)).sum())} dirty-air, "
                      f"{int(gf.get('Perturbed_Lap', pd.Series(dtype=bool)).sum())} perturbed, "
                      f"{int((~gf['ValidLap']).sum())} invalid")
                if fv is not None and drv in fv.index:
                    v = fv.loc[drv]
                    # THE SIGN MATTERS. Scoring on |delta| alone asks "is the
                    # filter big?" when the question is "does removing it make
                    # the model look right?". Those differ: at Monaco 2026 the
                    # filter moved HAM by 0.953% — larger than his whole miss —
                    # but in the direction that MASKED an even bigger one.
                    # Correcting for it there makes the model look worse, not
                    # better, so it is the opposite of an excuse.
                    corrected = miss + float(v["delta"])
                    red = ((abs(miss) - abs(corrected)) / abs(miss)) if miss else 0.0
                    a(f"- **What the filter did**: kept "
                      f"{100 * v['keep']:.0f}% of his laps (field "
                      f"{100 * v['field_keep']:.0f}%). Model measured "
                      f"{v['clean_gap']:+.3f}%; over EVERY racing lap he is "
                      f"{v['all_gap']:+.3f}%. Scoring him on all laps would "
                      f"move the miss {miss:+.3f}% → **{corrected:+.3f}%** "
                      f"({'shrinks' if red > 0 else 'GROWS'} by "
                      f"{abs(100 * red):.0f}%).")
                    if red >= 0.4:
                        a(f"- **SCREEN** · FILTER ARTIFACT  using every racing "
                          f"lap cuts the miss to {corrected:+.3f}%. The "
                          f"measured pace describes a slice of his race, not "
                          f"his race — consider `measurement_artifact` before "
                          f"any other cause.")
                    elif red <= -0.4:
                        a(f"- **SCREEN** · FILTER MASKING  the filter is "
                          f"FLATTERING the model here: on all laps the miss "
                          f"grows to {corrected:+.3f}%. Whatever the cause, it "
                          f"is not the measurement — the measurement is hiding "
                          f"part of it.")
                    elif v["keep"] < 0.8 * v["field_keep"]:
                        a(f"- **SCREEN** · THIN SLICE  only "
                          f"{100 * v['keep']:.0f}% of his laps survived against "
                          f"a field {100 * v['field_keep']:.0f}%, so this "
                          f"number rests on little — but correcting it barely "
                          f"moves the miss. Fragile, not wrong.")
                for s in longrun_screens(drv, clean, y, n_race_laps, offs, field_med):
                    a(f"- **SCREEN** · {s}")

            if kind == "onelap":
                for s in onelap_screens(drv, qres, qlaps, qrcm, miss):
                    a(f"- **SCREEN** · {s}")

            # events naming this car
            car_no = None
            if not inc.empty and "car_no" in inc.columns:
                ci = inc[inc["driver"] == drv]
                if len(ci):
                    car_no = ci["car_no"].iloc[0]
            rc_src = qrcm if kind == "onelap" else rrcm
            msgs, noise = race_control_for(rc_src, drv, car_no)
            if msgs:
                a(f"- **Race control** ({'qualifying' if kind == 'onelap' else 'race'}):")
                for m in msgs[:12]:
                    a(f"    - `{m}`")
            if noise:
                a(f"- *({noise} routine blue-flag / flag-order message"
                  f"{'s' if noise != 1 else ''} suppressed — those describe "
                  f"laps the median already discarded)*")

            # incidents.csv is a RACE log. Printing it under a qualifying row
            # was the tool committing the exact error section 0 warns about:
            # a lap-39 collision cannot explain a lap set on Saturday.
            if kind == "longrun" and not inc.empty:
                ci = inc[inc["driver"] == drv]
                for _, x in ci.iterrows():
                    other = x.get("counterparty")
                    other = "" if pd.isna(other) else f" vs {other}"
                    a(f"- **Incident** lap {x.get('lap'):.0f}: {x.get('kind')} — "
                      f"{x.get('reason')}{other} → {x.get('outcome')}")

            # Stops come from the LAPS, not pitstops.parquet. That file
            # under-reports: at Silverstone 2026 the laps show ANT entering the
            # pits on 35, 41 and 43 and the file lists only 35, so the dossier
            # was hiding exactly the unscheduled stops a review cares about.
            # Stationary times still come from the file where it has them.
            if kind == "longrun" and fl is not None:
                lap_in = sorted(fl[(fl["Driver_Short"] == drv)
                                   & fl["PitIn"].notna()]["LapNo"].astype(int))
                if lap_in:
                    stat = {}
                    if not pit.empty:
                        ps = pit[pit["Driver_Short"] == drv]
                        stat = {int(x["LapNo"]): x["StationaryTime_s"]
                                for _, x in ps.iterrows()}
                    bits = [f"lap {l}"
                            + (f" ({stat[l]:.1f}s stationary)" if l in stat else "")
                            for l in lap_in]
                    a(f"- **Pit stops** ({len(lap_in)}): " + "; ".join(bits)
                      + (f"  ·  *{len(lap_in) - len(stat)} not in "
                         f"pitstops.parquet*" if len(stat) < len(lap_in) else ""))

            if kind == "longrun" and not rad.empty and "Transcript" in rad.columns:
                rr = rad[rad["Driver_Short"] == drv]
                for _, x in rr.iterrows():
                    t = str(x.get("Transcript") or "").strip()
                    if t:
                        a(f"- **Radio** {x.get('Clock', '')}: \"{t[:220]}\"")

            a("")
            a("  > category: ______   note: ______")
            a("")
    a("---")
    a("")
    a("**Press check** — only for what the archive cannot hold (visible damage, "
      "a team saying what it changed, a mechanical problem never announced on "
      "the timing feed). Rules: the article must be published AFTER the session "
      "it describes and BEFORE it could be coloured by later rounds; quote the "
      "claim, record the URL and its publication date in `source`; a team "
      "principal's explanation is a claim, not a measurement — mark it as such.")
    a("")
    a("**Whether you searched or not, put today's date in `press_checked` for "
      "every row you looked at — including the ones where you found nothing.** "
      "A blank `source` otherwise means both 'searched, nothing there' and "
      "'never opened', and the next reader cannot tell them apart. Scope it to "
      "the drivers a search actually named, not to the whole event.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--event")
    ap.add_argument("--latest", action="store_true",
                    help="newest event present in data/model_review.csv")
    ap.add_argument("--out", help="write markdown here (default data/review_dossiers/)")
    args = ap.parse_args()

    if args.latest or not (args.season and args.event):
        rv = pd.read_csv(REVIEW)
        last = rv.sort_values(["season", "round"]).iloc[-1]
        season, event = int(last["season"]), str(last["event"])
        print(f"[latest] {season} {event}\n")
    else:
        season, event = args.season, args.event

    md = build(season, event)
    out = Path(args.out) if args.out else (
        OUT_DIR / f"{_key(season, event)}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    # The dossier is full of arrows and degree signs and the Windows console is
    # cp1252; printing it raw kills the run AFTER the file is safely written,
    # which looks like a failure and is not one.
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(md)
    print(f"\n\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
