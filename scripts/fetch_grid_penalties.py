"""Build data/grid_penalties.csv — every grid drop and pit-lane start of a
season, one row per car per event, from the FIA's final starting grids.

WHY A LEDGER. data/pu_penalties.csv holds ONE penalty per driver
(`penalties_places` at `penalty_event`), because the QUALI tab needs "what
drops this weekend's grid". Read as a season total it silently forgets every
earlier penalty: by R16 2026 it had lost Hadjar's 30 places and Norris' and
Sainz's 10 at Spa, and Stroll's 80 PU places read as 20. The engine
championship's attrition panel needs the cumulative figure, so it reads this.

SOURCE. `<season>_<slug>_-_final_starting_grid.pdf`: its footnotes list every
drop with the stewards' wording, e.g.

    Car 6 - 30 place grid penalty - Additional power unit elements have been
    used - Stewards' document no. 44
    Cars 18, 1 & 55 - 10 place grid penalties - Additional power unit element
    has been used - Stewards' document nos. 22, 23 & 54
    Car 14 - Required to start from the pit lane - Car modified whilst under
    Parc Fermé conditions and additional power unit elements have been used

`pu` is set from that wording ("power unit element"), never inferred from the
element counts — at R10 2026 Hadjar and Alonso were over on three elements
each yet drew 30 and 20 places. Pit-lane starts carry places = 0 and
pit_lane = True: a pit-lane start is not a number of places, and inventing
one would make the panel's arithmetic look more precise than it is.

Some grids carry pit-lane footnotes only as an image (2026 R2, R5, R7, R12);
those starts are invisible here and the run says so.

Usage
-----
    python scripts/fetch_grid_penalties.py                 # latest season
    python scripts/fetch_grid_penalties.py --season 2026
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import io
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from f1lib.circuits import fia_doc_slug
from f1lib.config import HISTORICAL_DIR

OUT = Path("data/grid_penalties.csv")
URL = ("https://www.fia.com/system/files/decision-document/"
       "{season}_{slug}_-_final_starting_grid.pdf")
# Up to 2024 the FIA filed decision documents under their display title.
LEGACY_URL = ("https://www.fia.com/sites/default/files/decision-document/"
              "{season}%20{title}%20-%20Final%20Starting%20Grid.pdf")
_UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["season", "round", "event", "car", "driver", "team", "places",
        "pit_lane", "pu", "reason", "stewards_doc", "source"]

# One footnote: "Car(s) <numbers> - <what> - <why> - Stewards' document ..."
_NOTE = re.compile(
    r"Cars?\s+(?P<cars>\d+(?:\s*(?:,|&|and)\s*\d+)*)\s+-\s+"
    r"(?P<what>\d+\s+place\s+grid\s+penalt(?:y|ies)|Required to start from the pit lane)"
    r"\s+-\s+(?P<why>.+?)\s+-\s+Stewards'?\s*(?P<doc>document\s+nos?\.\s*[\d ,&]+(?:\s*\([^)]*\))?)?",
    re.IGNORECASE)


def _pdf_text(url: str) -> str | None:
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers=_UA), timeout=30).read()
    except Exception:
        return None
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    return re.sub(r"\s+", " ", text)


def _races(season: int) -> pd.DataFrame:
    """(round, event, car number → driver code, driver → team) from the archive."""
    r = pd.read_parquet(Path(HISTORICAL_DIR) / "race_results_all.parquet",
                        columns=["season", "round_number", "event_name",
                                 "DriverNumber", "Abbreviation", "TeamName"])
    return r[r["season"] == season]


def _ascii(s: str) -> str:
    """'São Paulo' -> 'Sao Paulo' (the FIA's file names drop accents)."""
    return (unicodedata.normalize("NFKD", s).encode("ascii", "ignore")
            .decode("ascii"))


def parse(text: str) -> list[dict]:
    rows = []
    # Only the footnote block: the grid table above it holds car numbers and
    # lap times that the pattern must never see.
    i = text.find("PENALTIES")
    body = text[i:] if i >= 0 else text
    for m in _NOTE.finditer(body):
        what = m.group("what").lower()
        places = int(re.match(r"\d+", what).group()) if "place" in what else 0
        why = m.group("why").strip()
        for car in re.findall(r"\d+", m.group("cars")):
            rows.append({
                "car": int(car), "places": places,
                "pit_lane": "pit lane" in what,
                "pu": "power unit element" in why.lower(),
                "reason": why,
                "stewards_doc": (m.group("doc") or "").strip(),
            })
    return rows


def build(season: int) -> pd.DataFrame:
    races = _races(season)
    if races.empty:
        raise SystemExit(f"No {season} races in the results archive.")
    out = []
    for (rnd, event), g in races.groupby(["round_number", "event_name"]):
        url = URL.format(season=season, slug=fia_doc_slug(event, season))
        text = _pdf_text(url)
        if text is None:
            for title in dict.fromkeys([event, _ascii(event)]):
                legacy = LEGACY_URL.format(season=season,
                                           title=urllib.parse.quote(title))
                text = _pdf_text(legacy)
                if text is not None:
                    url = legacy
                    break
        if text is None:
            print(f"  R{int(rnd):02d} {event}: no final starting grid at {url}")
            continue
        notes = parse(text)
        driver_of = dict(zip(g["DriverNumber"].astype(int), g["Abbreviation"]))
        team_of = dict(zip(g["Abbreviation"], g["TeamName"]))
        for n in notes:
            drv = driver_of.get(n["car"], "")
            out.append({"season": season, "round": int(rnd), "event": event,
                        "driver": drv, "team": team_of.get(drv, ""),
                        "source": url, **n})
        starters = text.count("REQUIRED TO START FROM THE PIT LANE")
        noted = sum(n["pit_lane"] for n in notes)
        flag = ("  (pit-lane footnote not in the PDF text)"
                if starters and not noted else "")
        print(f"  R{int(rnd):02d} {event}: {len(notes)} footnote row(s){flag}")
    return pd.DataFrame(out, columns=COLS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
    if a.season is None:
        r = pd.read_parquet(Path(HISTORICAL_DIR) / "race_results_all.parquet",
                            columns=["season"])
        a.season = int(r["season"].max())
    print(f"Final starting grids, {a.season}:")
    new = build(a.season)
    if OUT.exists():
        old = pd.read_csv(OUT)
        old = old[old["season"] != a.season]
        new = pd.concat([old, new], ignore_index=True)
    new.sort_values(["season", "round", "car"]).to_csv(OUT, index=False)
    s = new[new["season"] == a.season]
    pu = s[s["pu"].astype(str).str.lower().eq("true")]
    print(f"\n{len(s)} row(s) -> {OUT}  ·  PU: {int(pu['places'].sum())} places, "
          f"{int(pu['pit_lane'].sum())} pit-lane start(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
