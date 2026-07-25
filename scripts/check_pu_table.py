"""Diff data/pu_penalties.csv against the FIA's cumulative PU-element table.

The FIA Technical Delegate publishes a per-driver cumulative table at nearly
every event — the whole CSV in one document. This fetches it, extracts the
table, and reports any element count that disagrees. `--write` applies the FIA
figures.

Two traps this exists to close, both of which bit us on 2026-07-25:

* **Column order.** The FIA table runs `ICE, TC, EXH, MGU-K, ES, PU-CE, PU-ANC`;
  the CSV runs `ice, tc, mguk, es, ce, ex, anc`. Transcribing in document order
  silently swaps EXH with MGU-K. The re-map here is by name, never by position.
* **Partial updates.** Patching only the drivers you read about in the press
  leaves the rest of the file at older vintages — Lawson's and Stroll's rows sat
  two rounds stale, and nothing surfaced it. Diff every row, every time.

The table is the state *entering* its event, so the R11 document certifies the
end of R10. Those are two different labels in the CSV and `--write` sets
neither: `as_of` says how fresh the file is (R11 here), while `penalty_event`
names the race whose grid drops `penalties_places` records (R10). Collapsing
them puts the penalties on the wrong grid in the QUALI tab. See read_local.md →
data/pu_penalties.csv.

`penalties_places` is never written here either: it comes from that event's
`..._-_final_starting_grid.pdf`, whose footnotes list every drop. Deriving it
from the allowances gets it wrong — at R10 both Hadjar and Alonso were over on
three elements each yet drew 30 and 20 places.

Usage
-----
    python scripts/check_pu_table.py --event "Hungarian Grand Prix"
    python scripts/check_pu_table.py --event "Hungarian Grand Prix" --write
    python scripts/check_pu_table.py --pdf some_already_downloaded.pdf

Exits 1 if the CSV disagrees with the table, so it can gate a runner.
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import io
import re
import urllib.request
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

CSV = Path("data/pu_penalties.csv")
URL = ("https://www.fia.com/system/files/decision-document/"
       "{season}_{slug}_-_pu_elements_used_per_driver_up_to_now.pdf")
_UA = {"User-Agent": "Mozilla/5.0"}

# CSV column -> its name in the FIA table. The whole point of the file.
FIA_OF_CSV = {"ice": "ICE", "tc": "TC", "mguk": "MGU-K",
              "es": "ES", "ce": "PU-CE", "ex": "EXH", "anc": "PU-ANC"}
FIA_ORDER = ["ICE", "TC", "EXH", "MGU-K", "ES", "PU-CE", "PU-ANC"]
CSV_ORDER = list(FIA_OF_CSV)

# Fragment of each driver's name as it survives pypdf extraction, keyed by the
# CSV's three-letter code. Mostly the surname, but the extractor drops accents
# to U+FFFD and sprinkles spaces mid-word ("Geor ge Russell", "Pierre Gasl y"),
# so these are the longest reliably-intact runs — hence "lkenber" for
# Hülkenberg. Add a line here when the grid changes; a missing or ambiguous
# driver is a hard failure, never a silent skip.
FRAGMENTS = {
    "PIA": "Piastri",   "NOR": "Norris",    "RUS": "Russell",
    "ANT": "Antonelli", "VER": "Verstappen", "HAD": "Hadjar",
    "LEC": "Leclerc",   "HAM": "Hamilton",  "ALB": "Albon",
    "SAI": "Sainz",     "LIN": "Lindblad",  "LAW": "Lawson",
    "STR": "Stroll",    "ALO": "Alonso",    "OCO": "Ocon",
    "BEA": "Bearman",   "HUL": "lkenber",   "BOR": "Bortoleto",
    "GAS": "Gasl",      "COL": "Colapinto", "PER": "Perez",
    "BOT": "Bottas",
}

# A data row ends in its seven counts; everything before them is car number,
# team and driver, whose spacing the extractor mangles.
_TAIL7 = re.compile(r"((?:\d+\s+){6}\d+)\s*$")


def fetch(season: int, event: str) -> io.BytesIO:
    slug = event.strip().lower().replace(" ", "_")
    url = URL.format(season=season, slug=slug)
    print(f"fetching {url}")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return io.BytesIO(r.read())


def parse(src) -> dict[str, dict[str, int]]:
    """{driver code: {FIA element name: count}} for all 22 drivers.

    Raises ValueError rather than exiting, so during_weekend.py can call this
    and degrade to its round-label check instead of dying mid-run.
    """
    text = "\n".join(p.extract_text() for p in PdfReader(src).pages)
    rows: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        m = _TAIL7.search(line)
        if not m:
            continue
        hits = [c for c, frag in FRAGMENTS.items() if frag in line]
        if len(hits) > 1:
            raise ValueError(f"line matches {hits}, fragments are ambiguous: {line!r}")
        if not hits:
            continue                      # header/legend row, not a driver
        code = hits[0]
        if code in rows:
            raise ValueError(f"duplicate row for {code}: {line!r}")
        rows[code] = dict(zip(FIA_ORDER, [int(v) for v in m.group(1).split()]))
    missing = sorted(set(FRAGMENTS) - set(rows))
    if missing:
        raise ValueError(f"no row parsed for {missing} - has the grid changed? "
                         "Update FRAGMENTS.")
    return rows


def diff(fia: dict, df: pd.DataFrame, season: int) -> list[tuple]:
    """[(driver, column, csv_value, fia_value, row_index)] for every mismatch."""
    rows = df[df["season"] == season]
    if rows.empty:
        raise ValueError(f"no {season} rows in {CSV}")
    out = []
    for i, row in rows.iterrows():
        for col in CSV_ORDER:
            have, want = int(row[col]), fia[row["driver"]][FIA_OF_CSV[col]]
            if have != want:
                out.append((row["driver"], col, have, want, i))
    return out


def check(season: int, event: str, csv_path: Path = CSV) -> tuple[dict, list]:
    """(parsed FIA table, diffs). For callers that just want the verdict."""
    fia = parse(fetch(season, event))
    return fia, diff(fia, pd.read_csv(csv_path), season)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--event", help='e.g. "Hungarian Grand Prix"')
    ap.add_argument("--pdf", help="use an already-downloaded PDF instead")
    ap.add_argument("--write", action="store_true",
                    help="apply the FIA element counts to the CSV")
    args = ap.parse_args()
    if not args.pdf and not args.event:
        ap.error("pass --event or --pdf")

    try:
        fia = parse(args.pdf or fetch(args.season, args.event))
        df = pd.read_csv(CSV)
        diffs = diff(fia, df, args.season)
    except ValueError as exc:
        raise SystemExit(str(exc))
    season = df[df["season"] == args.season]

    print(f"parsed {len(fia)} drivers; checked {len(season)} CSV rows")
    if diffs:
        print(f"\n{len(diffs)} disagreement(s), csv -> fia:")
        for drv, col, have, want, _ in sorted(diffs):
            print(f"  {drv:<4} {col:<5} {have} -> {want}")
    else:
        print("MATCH: every element count agrees with the FIA table")

    # Advisory only, and judged on the FIA counts rather than what the CSV
    # currently says — the point is to flag a driver whose *corrected* usage
    # implies a penalty the file doesn't record, which is how Sainz's missing
    # 10 places at R10 stayed hidden. Being over may still be legitimate: the
    # penalty may have been served at an earlier event, where 0 here is right.
    from tabs.pu_pool import _LIMITS_2026
    for _, row in season.iterrows():
        counts = fia[row["driver"]]
        over = [c for c in CSV_ORDER if counts[FIA_OF_CSV[c]] > _LIMITS_2026[c]]
        if over and not int(row["penalties_places"]):
            print(f"  note: {row['driver']} is over on {', '.join(over)} with "
                  "penalties_places 0 - check the final starting grid, or it "
                  "was served at an earlier event")

    if diffs and args.write:
        for drv, col, _, want, i in diffs:
            df.at[i, col] = want
        df.to_csv(CSV, index=False, lineterminator="\n")
        print(f"\nwrote {CSV} ({len(diffs)} cell(s))")
        print("still by hand: penalties_places + penalty_event from the event's "
              "final starting grid, then as_of/source together")
        return 0
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
