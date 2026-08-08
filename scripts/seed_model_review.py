"""Seed the hand-curated post-race review with the rows that need writing.

The prediction ledger can say the model was wrong. It structurally cannot say
WHY — only somebody who watched the race knows a car picked up floor damage on
lap 3, or served a penalty and pitted out of sequence. Those causes are
precisely the things the pace model declines to model (strategy, incidents,
damage, weather), so this file is not patching a hidden gap; it documents the
gap the model already admits to.

What this script does is remove the tedious half of that job. It works out
which drivers finished OUTSIDE their own +/-1sd band, fills in every number
automatically, and appends a skeleton row per driver with two fields left
blank for a human: `category` and `note`. Typically three to six rows a race.

    python scripts/seed_model_review.py --season 2026 --event "Belgian Grand Prix"
    python scripts/seed_model_review.py --latest      # newest event in the pace table

Then open data/model_review.csv and fill in the blanks.

WHY `category` MATTERS more than `note`: free text gives a readable race diary
and nothing else. A category drawn from a fixed vocabulary turns a season of
anecdotes into a distribution, which answers the question that actually
directs the roadmap — "what share of our misses are unmodelled incidents
versus the model genuinely being wrong?" If most misses are `strategy`, the
next thing to build is a strategy model; if most are `model_miss`, the pace
model itself needs the work.

Nothing here writes `category` or `note`. A machine guessing why a car was
slow would be inventing race history, and this file is only worth having if
every word in it is something a person actually observed.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

OUT = Path("data/model_review.csv")

COLUMNS = ["season", "round", "event", "driver", "team", "kind",
           "predicted", "actual", "miss", "sd", "se_actual", "band",
           "scope", "flags",
           "category", "note", "source", "press_checked"]

# `sd` is the PREDICTION's spread, `se_actual` the MEASUREMENT's, and `band`
# the sqrt(sd^2 + se_actual^2) a row is actually judged against. All three are
# kept: the split is what tells a genuine model miss (`sd` dominates) apart
# from a thin read (`se_actual` dominates), which is the distinction the 2026
# review had to make by hand under the label `measurement_artifact`. Rows
# seeded before this existed have `sd` only and blanks here.

# `press_checked` = ISO date the press pass was RUN for this row, blank if it
# never was. It records COVERAGE, which `source` cannot: a row with no URL is
# otherwise three different states wearing the same face —
#
#   press_checked set   + URL in source : press found something, it is cited
#   press_checked set   + no URL        : SEARCHED AND FOUND NOTHING RELEVANT
#   press_checked blank                 : never searched
#
# The middle one is the reason this exists. Colapinto at Silverstone 2026 was
# searched and returned only 2025 Silverstone coverage of a different incident;
# that is a useful negative result, and without a coverage field it survives
# only as prose inside `note`, where it cannot be counted and invites the wrong
# inference next time ("no press cited, so no press exists"). It also makes
# "does a press pass actually change verdicts?" an answerable question.

# `scope` and `flags` are OBSERVATIONS, filled by machine; `category` is the
# VERDICT, filled by a person. Keeping them in separate columns is the whole
# point — see below.
SCOPES = ["car_wide",   # team mate also outside their band, same direction
          "driver",     # team mate MEASURED and inside the band (or opposite)
          "no_mate"]    # team mate has no actual at all — scope unknowable

# `no_mate` exists because conflating it with `driver` asserts something false.
# The race actual needs >=10 clean laps, so a team mate who retired early has
# no row, and the naive "no flagged team mate ⇒ driver-specific" reading turns
# a car-wide problem into a driver-specific one. Stroll at Canada 2026 is the
# worked example: he missed by +2.30% and read as `driver`, but Alonso's
# clean-lap pace was +3.73% against Stroll's +3.59% — the same car, both ~3.6%
# off the field — and he was invisible only because he retired on lap 23 with
# five clean laps. Seven 2026 rows were mislabelled this way.

# Events that DID happen to this car, whether or not they moved the statistic.
#
# WHY THESE ARE RECORDED SEPARATELY FROM `category`. The race median is taken
# over clean-air laps after ValidLap & ~Dirty_Air & ~Perturbed_Lap, and the
# damaged/limping laps of a bad afternoon are usually the ones that filter
# discards. So a car can retire from the lead with broken suspension and still
# post a normal median — which makes `damage` the wrong VERDICT and yet leaves
# "this car was damaged" a fact worth keeping. Writing the verdict alone threw
# that away and made a season of misses look causeless. With these flags the
# question "do rows carrying a mechanical flag miss differently from rows that
# do not?" becomes answerable across a season instead of re-litigated per race.
FLAGS = [
    "dnf",           # did not finish (non-numeric classified position)
    "collision",     # contact incident logged against this car
    "mechanical",    # retirement/status or team radio indicating a car problem
    "damage_radio",  # team radio tagged CAR / DAMAGE
    "penalty",       # time penalty or investigation with a penalty outcome
    "grid_penalty",  # started out of position on a PU/gearbox penalty
    "extra_stops",   # more pit stops than the field median that race
    "heavy_exclusion",  # model kept far fewer of this car's laps than the field
    "few_attempts",     # set far fewer flying quali laps than the field median
]

# Fixed vocabulary. Keep it SHORT — a long list gets used inconsistently and
# stops aggregating, which defeats the point.
CATEGORIES = [
    "damage",       # contact or debris cost lasting pace
    "strategy",     # tyre/pit calls the model does not simulate
    "traffic",      # stuck behind a slower car, never showed true pace
    "penalty",      # time penalty or serving cost
    "weather",      # conditions changed within or between sessions
    "reliability",  # mechanical trouble short of a retirement
    "driver_error", # spin, lock-up, off
    "setup",        # team changed the car between the read and the session
    "thin_read",    # the model had almost no practice evidence for this car
    "measurement_artifact",  # the ACTUAL does not describe the driver's session
    "model_miss",   # none of the above — the model was simply wrong
]

# `measurement_artifact` is the OUTPUT-side twin of `thin_read`. Both actuals
# are constructed quantities, and neither is "what the driver did":
#
#   longrun — a median over clean-air laps only. Across 2026 that keeps about
#     HALF of a race, so a driver who spent his afternoon in traffic is scored
#     on a thin, unrepresentative slice of it. Compare his clean-air gap with
#     his gap over EVERY racing lap; when the difference approaches the miss,
#     the measurement is the finding. (Hamilton, Austria 2026: 37% of laps
#     kept vs a field median of 57%, and the two measures differ by 0.644%
#     against a 0.573% miss.)
#
#   onelap — a MINIMUM over the driver's flying laps, so its expected value
#     depends on how many attempts he got. Measured across 78 driver-events:
#     -0.170% of a lap per extra flying lap, partial r = -0.491 (p<1e-4)
#     controlling for predicted pace, monotonic in attempt count and negative
#     in all four events independently. A driver eliminated in Q1 with two
#     laps is compared against a field that mostly had five or six.
#
# Recording either as `model_miss` blames the pace model for a choice made in
# the measurement, and hides a real and fixable limitation. The `flags` column
# says WHICH mechanism: `heavy_exclusion` or `few_attempts`.
#
# PRECEDENCE: when a row qualifies for BOTH, `thin_read` wins. If the model
# never had the evidence to make the prediction, arguing about how well the
# outcome was measured is arguing about the second-order term — there was no
# first-order prediction to test. Recording it as a measurement problem would
# also point the roadmap at the wrong fix.

# `thin_read` is deliberately NOT a flavour of model_miss. The tally exists to
# decide what to build next, and the two point at opposite jobs: model_miss
# says the pace model is wrong on good evidence, thin_read says it was
# extrapolating from a car that skipped a session. Merging them would hide the
# sparse-input problem inside a verdict about the model's accuracy.


def _key(season: int, event: str) -> str:
    return f"{season}__{event.replace(' ', '_')}"


def observed_flags(season: int, event: str) -> dict[str, set[str]]:
    """Per-driver set of FLAGS, read straight off the archive.

    Deliberately generous: a flag means "this happened to this car", NOT "this
    caused the miss". Deciding the second is the human's job and lives in
    `category`.
    """
    out: dict[str, set[str]] = {}

    def add(drv, flag):
        out.setdefault(str(drv), set()).add(flag)

    sess = Path("data/sessions") / f"{_key(season, event)}__Race__"

    # retirement + mechanical status
    try:
        res = pd.read_parquet(str(sess) + "results.parquet")
        for _, r in res.iterrows():
            cls = str(r.get("ClassifiedPosition", "")).strip()
            st = str(r.get("Status", ""))
            if cls and not cls.isdigit():
                add(r["Abbreviation"], "dnf")
            if any(k in st.lower() for k in
                   ("engine", "gearbox", "hydraul", "power unit", "brake",
                    "suspension", "transmission", "overheat", "electr",
                    "retired", "mechanical", "water", "oil", "fuel")):
                add(r["Abbreviation"], "mechanical")
    except Exception:
        pass

    # contact + penalties, from the incident register
    p = Path("data/incidents.csv")
    if p.exists():
        try:
            ic = pd.read_csv(p)
            ic = ic[(ic["season"] == season) & (ic["event"] == event)]
            for _, r in ic.iterrows():
                if str(r.get("kind", "")) == "contact":
                    add(r["driver"], "collision")
                if "penalty" in str(r.get("outcome", "")).lower():
                    add(r["driver"], "penalty")
        except Exception:
            pass

    # team radio that a human tagged as a car problem
    rp = Path(f"data/radio/{_key(season, event)}__Race__radio.parquet")
    if rp.exists():
        try:
            rad = pd.read_parquet(rp)
            for _, r in rad.iterrows():
                if "CAR / DAMAGE" in str(r.get("Topics", "")).upper():
                    add(r["Driver_Short"], "damage_radio")
        except Exception:
            pass

    # grid penalties actually taken at this event
    for pth, col in (("data/pu_penalties.csv", "penalty_event"),
                     ("data/gearbox_penalties.csv", None)):
        f = Path(pth)
        if not f.exists():
            continue
        try:
            t = pd.read_csv(f)
            t = t[t["season"] == season]
            ev_col = col if col and col in t.columns else None
            if ev_col is None:
                continue
            hit = t[t[ev_col].astype(str).str.contains(event, na=False)]
            for _, r in hit.iterrows():
                if float(r.get("penalties_places", 0) or 0) > 0:
                    add(r["driver"], "grid_penalty")
        except Exception:
            pass

    # extra stops — counted from the LAPS, not pitstops.parquet, which was
    # found to under-report (Silverstone 2026: laps show ANT stopping at 35,
    # 41 and 43, the file lists only 35).
    lp = Path(f"data/sessions/{_key(season, event)}__Race__laps.parquet")
    if lp.exists():
        try:
            lf = pd.read_parquet(lp)
            lf["drv"] = lf["Driver"].astype(str).str.split("-").str[0]
            n = lf[lf["PitIn"].notna()].groupby("drv").size()
            if len(n):
                med = float(n.median())
                for d, v in n.items():
                    if v > med:
                        add(d, "extra_stops")
        except Exception:
            pass

    # heavy_exclusion — the model kept far less of this car's race than of the
    # field's. Flagged separately from the `filter_artifact` verdict because
    # low retention is a fact and "the filter caused the miss" is a judgement.
    try:
        from f1lib.processing import (clean_and_enrich_laps, flag_dirty_air,
                                      flag_perturbed_laps)
        rcm_p = Path(f"data/sessions/{_key(season, event)}__Race__race_control.parquet")
        rcm = pd.read_parquet(rcm_p) if rcm_p.exists() else None
        lf = flag_dirty_air(flag_perturbed_laps(
            clean_and_enrich_laps(pd.read_parquet(lp)), rcm=rcm))
        keep = (lf[lf.ValidLap & ~lf.get("Dirty_Air", False)
                   & ~lf.get("Perturbed_Lap", False)]
                .groupby("Driver_Short").size()
                / lf.groupby("Driver_Short").size())
        med = float(keep.median())
        for d, v in keep.items():
            if v < 0.8 * med:
                add(d, "heavy_exclusion")
    except Exception:
        pass

    # few_attempts — the onelap actual is a MINIMUM over flying laps, so its
    # expected value depends on how many the driver got. Worth -0.170% of a
    # lap each (n=78, partial r=-0.491 controlling for predicted pace).
    qp = Path(f"data/sessions/{_key(season, event)}__Qualifying__laps.parquet")
    if qp.exists():
        try:
            q = pd.read_parquet(qp)
            q["drv"] = q["Driver"].astype(str).str.split("-").str[0]
            s = pd.to_timedelta(q["LapTime"], errors="coerce").dt.total_seconds()
            if s.isna().all():
                s = pd.to_numeric(q["LapTime"], errors="coerce")
            fly = q[s.notna() & q["PitIn"].isna() & q["PitOut"].isna()]
            n = fly.groupby("drv").size()
            med = float(n.median())
            for d, v in n.items():
                if med and v < 0.8 * med:
                    add(d, "few_attempts")
        except Exception:
            pass
    return out


def _driver_actuals(season: int, event: str
                    ) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Per-driver outcome for both kinds, mean-centred, from the pace table.

    Returns (value, standard error) per kind. The error is what makes the
    review test honest: the outcome is a MEASUREMENT, not a fact. A race
    median off 18 clean laps and one off 55 carry different weight, and
    scoring both against the prediction's sd alone books a thin read as a
    model miss. Blank (NaN) for the one-lap kind by design — see the note in
    driver_ratings._quali_driver_gaps.
    """
    p = Path("data/driver_pace_by_event.csv")
    if not p.exists():
        return {}
    d = pd.read_csv(p)
    d = d[(d["season"] == season) & (d["event"] == event)].dropna(
        subset=["gap_pct"])
    out = {}
    for kind, tgt in (("onelap", "quali"), ("longrun", "race")):
        sub = d[d["kind"] == tgt].set_index("driver")
        s = sub["gap_pct"]
        if len(s) >= 4:
            se = (sub["se_pct"] if "se_pct" in sub.columns
                  else pd.Series(np.nan, index=sub.index))
            out[kind] = (s - s.mean(), se)
    return out


def seed(season: int, event: str) -> pd.DataFrame:
    from f1lib.pace_model import PaceModel
    from f1lib.pace_features import event_measurements
    from f1lib.driver_ratings import DriverRatings

    model = PaceModel()
    round_ = model.round_of(season, event) or model.next_round_of(season)
    meas, _ = event_measurements(season, event)
    stages = model.predict_weekend(season, event,
                                   measurements=meas if meas is not None
                                   and not meas.empty else None,
                                   round_=round_)
    final = stages[list(stages)[-1]]
    dr = DriverRatings()
    roster = dr.roster(season, event)
    actuals = _driver_actuals(season, event)
    flags = observed_flags(season, event)
    rows = []
    for kind, (act, act_se) in actuals.items():
        pred = model.driver_predictions(final, roster, kind,
                                        as_of=(season, round_))
        if pred.empty:
            continue
        pred = pred.set_index("driver")
        common = [d for d in pred.index if d in act.index]
        if len(common) < 4:
            continue
        pv = pred.loc[common, "mean"] - pred.loc[common, "mean"].mean()
        av = act[common] - act[common].mean()
        # Every driver's miss, INCLUDING those inside the band — `scope` asks
        # what the team mate did, and the team mate is often not flagged.
        miss_all = {d: float(av[d] - pv[d]) for d in common}
        sd_all = {d: float(pred.loc[d, "sd"]) for d in common}
        team_of = {d: pred.loc[d, "team"] for d in common}
        # THE BAND IS BOTH UNCERTAINTIES, not the prediction's alone.
        # `miss` is the difference between a prediction and a MEASUREMENT, so
        # its spread is sqrt(sd_pred^2 + se_actual^2). Using sd_pred by itself
        # measured a 79%-inside-the-band calibration against roughly half the
        # uncertainty that is really there, and charged the model for reads
        # that were simply thin. Falls back to sd_pred wherever the actual has
        # no error bar (the whole one-lap kind), so nothing silently narrows.
        se_all = {d: (float(act_se.get(d)) if pd.notna(act_se.get(d))
                      else float("nan")) for d in common}
        band_all = {d: float(np.hypot(sd_all[d], se_all[d]))
                    if pd.notna(se_all[d]) else sd_all[d] for d in common}

        for d in common:
            miss, sd, band = miss_all[d], sd_all[d], band_all[d]
            if abs(miss) <= band:            # inside its own band: no review
                continue
            mates = [o for o in common
                     if o != d and team_of[o] == team_of[d]]
            scope = "driver" if mates else "no_mate"
            for m in mates:
                # Same widened band for the team mate, or "car_wide" would be
                # decided on a different test than the flag it explains.
                if (np.sign(miss_all[m]) == np.sign(miss)
                        and abs(miss_all[m]) > band_all[m]):
                    scope = "car_wide"
            rows.append({
                "season": season, "round": round_, "event": event,
                "driver": d, "team": team_of[d], "kind": kind,
                "predicted": round(float(pv[d]), 3),
                "actual": round(float(av[d]), 3),
                "miss": round(miss, 3), "sd": round(sd, 3),
                "se_actual": (round(se_all[d], 3)
                              if pd.notna(se_all[d]) else ""),
                "band": round(band, 3),
                "scope": scope,
                "flags": ";".join(sorted(flags.get(d, set()))),
                "category": "", "note": "", "source": "",
                "press_checked": "",
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--event")
    ap.add_argument("--latest", action="store_true",
                    help="use the newest event in the pace table")
    args = ap.parse_args()

    if args.latest or not (args.season and args.event):
        from f1lib.pace_model import PaceModel
        p = PaceModel().pace
        last = p.sort_values(["season", "round"]).iloc[-1]
        season, event = int(last["season"]), str(last["event"])
        print(f"[latest] {season} {event}")
    else:
        season, event = args.season, args.event

    new = seed(season, event)
    if new.empty:
        print("No driver fell outside their error bar — nothing to review. "
              "(That is a good weekend, not a bug.)")
        return 0

    if OUT.exists():
        old = pd.read_csv(OUT)
        # never clobber a note somebody already wrote
        key = ["season", "event", "driver", "kind"]
        merged = old.merge(new[key], on=key, how="right", indicator=True)
        already = int((merged["_merge"] == "both").sum())
        new = new.merge(old[key].assign(_seen=1), on=key, how="left")
        new = new[new["_seen"].isna()].drop(columns=["_seen"])
        if already:
            print(f"{already} row(s) already reviewed — left untouched")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"\nAdded {len(new)} row(s) awaiting a note -> {OUT}")
    if not new.empty:
        print(new[["driver", "kind", "predicted", "actual", "miss",
                   "sd", "se_actual", "band"]].to_string(index=False))
    print(f"\nFill in `category` (one of: {', '.join(CATEGORIES)}), `note` "
          f"and `source`.")
    print("Evidence for these rows: python scripts/review_dossier.py --latest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
