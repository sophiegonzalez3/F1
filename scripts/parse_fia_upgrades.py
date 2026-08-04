"""Parse FIA "Car Presentation Submissions" PDFs -> upgrade rows.

The FIA publishes, per event, every aerodynamic/mechanical change each team
brought, with the reason it was brought. That document is the only public
ground truth on car development, and it is what data/upgrades.csv holds.

Until now the CSV was transcribed by hand, so it covered 2026 only — which
also meant the upgrade event study had a single season and the pace model's
upgrade constants could not be tuned off the holdout. The FIA has published
these since 2025 (2024 and earlier return 404), so this parser exists to
pull the rest of the era in one pass.

Why pdfplumber and not pdftotext
--------------------------------
These are real tables with multi-line cells, and `pdftotext -layout` cannot
put them back together: a component's reason routinely lands on a different
visual line from its own row number, interleaved with the neighbouring
cell's wrapped text. Parsing that by column offsets recovered only 87% of
the known-good 2026 rows and lost them SILENTLY, which for a part COUNT is
the worst possible failure — the dose-response would read a smaller package.
pdfplumber extracts genuine cells, and reproduces the hand-curated counts
exactly.

Layout
------
One team per page (sometimes two pages for a big package), with a
"Car Presentation - <Event>" header followed by the team name, then a table:

    | Updated component | Primary reason for update | Geometric ... | Brief ... |
    | 1 | Rear Wing | Circuit specific - Drag Range | ...            | ...       |

A row that opens with an index is a new component; rows with an empty index
are continuations of the one above, and the reason sometimes only appears
there. A team's package can run over a page break, in which case the second
page carries no header — so the current team is carried forward rather than
reset, or half a package goes missing (Aston Martin at Hungary 2026 is 8
components on one page and 8 on the next).

"No updates submitted for this event." is a real answer and yields no rows.

Verified against the hand-curated 2026 rows before being trusted — see
--verify, which re-parses a season already in the CSV and reports how the
counts differ.

Usage
-----
    python scripts/parse_fia_upgrades.py --pdf-dir <dir> --season 2025
    python scripts/parse_fia_upgrades.py --pdf-dir <dir> --season 2026 --verify
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

UPGRADES_CSV = Path("data/upgrades.csv")

# Substring -> canonical team. Longest match wins, so "Racing Bulls" is
# tested before "Red Bull" would ever see it.
_TEAM_PATTERNS = [
    ("racing bulls", "Racing Bulls"), ("visa cash app", "Racing Bulls"),
    ("alphatauri", "Racing Bulls"),
    ("red bull", "Red Bull Racing"),
    ("ferrari", "Ferrari"),
    ("mercedes", "Mercedes"),
    ("mclaren", "McLaren"),
    ("aston martin", "Aston Martin"),
    ("alpine", "Alpine"),
    ("williams", "Williams"),
    ("haas", "Haas F1 Team"),
    ("kick sauber", "Sauber"), ("stake f1", "Sauber"), ("sauber", "Sauber"),
    ("audi", "Audi"),
    ("cadillac", "Cadillac"),
]

_CATEGORIES = ("Performance", "Circuit specific", "Reliability")

_HEADER = re.compile(r"car\s+presentation", re.I)
_NO_UPDATES = re.compile(r"no\s+updates?\s+submitted", re.I)


def _team_of(line: str) -> str | None:
    """Canonical team named in `line`, or None.

    Matched on WORD BOUNDARIES, not raw substrings. "Saudi Arabian Grand
    Prix" contains "audi", and since every page's header carries the event
    name, a substring match silently reassigned all eighteen Saudi 2025
    components — McLaren's, Ferrari's, Red Bull's and Mercedes' — to Audi.
    Longest pattern still wins, so "racing bulls" beats "red bull".
    """
    low = line.lower()
    best = None
    for pat, canon in _TEAM_PATTERNS:
        if re.search(rf"\b{re.escape(pat)}\b", low) \
                and (best is None or len(pat) > len(best[0])):
            best = (pat, canon)
    return best[1] if best else None


def _category_of(text: str) -> str | None:
    """The FIA's top-level reason, before its ' - ' qualifier."""
    head = text.split("-")[0].strip().rstrip(",").strip()
    low = head.lower()
    for c in _CATEGORIES:
        if low.startswith(c.lower()):
            return c
    return None


def _clean(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


def _page_team(text: str) -> str | None:
    """Team named in this page's 'Car Presentation - <event>' header, or None
    when the page is a continuation (which must NOT reset the current team)."""
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if _HEADER.search(line):
            for cand in (line, *lines[i + 1:i + 3]):
                found = _team_of(cand)
                if found:
                    return found
    return None


def parse_pdf(pdf: Path, season: int, event: str) -> pd.DataFrame:
    import pdfplumber

    rows = []
    team = None
    with pdfplumber.open(str(pdf)) as doc:
        for page in doc.pages:
            text = page.extract_text() or ""
            found = _page_team(text)
            if found:
                team = found
            if team is None or _NO_UPDATES.search(text):
                continue
            table = page.extract_table()
            if not table:
                # Some events' PDFs draw the table without ruling lines (all
                # of São Paulo 2025), so the default line-based strategy
                # finds nothing. Fall back to inferring columns from text
                # alignment before giving up on the page.
                table = page.extract_table({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                })
            if not table:
                continue
            pending = None          # component awaiting its category
            last_cat = None         # last stated reason, for merged cells
            for raw in table:
                cells = [_clean(c) for c in raw]
                if not cells:
                    continue
                idx = cells[0]
                if idx.isdigit():
                    if pending:
                        rows.append(pending)
                    body = [c for c in cells[1:] if c]
                    component = body[0] if body else ""
                    cat = next((_category_of(c) for c in body
                                if _category_of(c)), None)
                    if not component or component.lower().startswith("component"):
                        pending = None
                        continue
                    if cat:
                        last_cat = cat
                    pending = {
                        "season": season, "event": event, "team": team,
                        "component": component.title(),
                        # The FIA merges the reason cell across consecutive
                        # components that share one — Ferrari's eight-part
                        # Barcelona floor package states it on rows 1, 4 and 8
                        # only. An unstated reason therefore means "same as
                        # above", not "unknown", and certainly not a default.
                        "category": cat or last_cat,
                        # last populated cell = the FIA's "brief description
                        # on how the update works"; the UPGRADES tab shows it
                        "description": body[-1] if len(body) > 1 else "",
                        "source": "FIA Car Presentation Submissions",
                    }
                elif pending and pending["category"] is None:
                    # the reason can also land on a continuation row
                    cat = next((_category_of(c) for c in cells
                                if _category_of(c)), None)
                    if cat:
                        pending["category"] = last_cat = cat
            if pending:
                rows.append(pending)
    out = pd.DataFrame(rows)
    if not out.empty:
        n_unknown = int(out["category"].isna().sum())
        if n_unknown:
            print(f"    [warn] {n_unknown} component(s) with no stated reason "
                  f"in {pdf.name} — left uncategorised")
    return out


def event_of(pdf: Path, season: int) -> str:
    """'spanish.pdf' -> 'Spanish Grand Prix', matching the archive's naming."""
    stem = pdf.stem.replace("_", " ").strip()
    special = {"sao paulo": "São Paulo", "united states": "United States",
               "mexico city": "Mexico City", "abu dhabi": "Abu Dhabi",
               "las vegas": "Las Vegas", "emilia romagna": "Emilia Romagna",
               "saudi arabian": "Saudi Arabian"}
    name = special.get(stem.lower(), stem.title())
    return f"{name} Grand Prix"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--verify", action="store_true",
                    help="parse a season already in the CSV and compare, "
                         "instead of writing anything")
    ap.add_argument("--write", action="store_true",
                    help="append the parsed rows to data/upgrades.csv")
    args = ap.parse_args()

    pdfs = sorted(Path(args.pdf_dir).glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.pdf_dir}")
        return 1
    frames = []
    for pdf in pdfs:
        try:
            df = parse_pdf(pdf, args.season, event_of(pdf, args.season))
        except Exception as exc:
            print(f"  [FAIL] {pdf.name}: {exc}")
            continue
        frames.append(df)
        print(f"  {pdf.stem:22s} {len(df):3d} rows, "
              f"{df['team'].nunique() if not df.empty else 0} teams")
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if out.empty:
        print("Nothing parsed.")
        return 1
    print(f"\nParsed {len(out)} rows across {out['event'].nunique()} events")
    print(out["category"].value_counts().to_string())

    if args.verify:
        cur = pd.read_csv(UPGRADES_CSV, encoding="utf-8-sig")
        cur = cur[cur["season"] == args.season]
        print(f"\n--- verify against {len(cur)} hand-curated rows ---")
        a = cur.groupby("event").size().rename("curated")
        b = out.groupby("event").size().rename("parsed")
        cmp = pd.concat([a, b], axis=1).fillna(0).astype(int)
        cmp["delta"] = cmp["parsed"] - cmp["curated"]
        print(cmp.to_string())
        ca = cur["category"].value_counts().rename("curated")
        cb = out["category"].value_counts().rename("parsed")
        print("\n" + pd.concat([ca, cb], axis=1).fillna(0).astype(int).to_string())
        return 0

    if args.write:
        cur = pd.read_csv(UPGRADES_CSV, encoding="utf-8-sig")
        cur = cur[cur["season"] != args.season]        # idempotent re-runs
        merged = pd.concat([cur, out], ignore_index=True)
        merged = merged.sort_values(["season", "event", "team", "component"])
        merged.to_csv(UPGRADES_CSV, index=False, encoding="utf-8-sig")
        print(f"\nWrote {len(merged)} rows -> {UPGRADES_CSV} "
              f"(seasons {sorted(merged['season'].unique())})")
    else:
        print("\n(dry run — pass --write to update data/upgrades.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
