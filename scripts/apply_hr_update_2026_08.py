"""Summer-break 2026 HR update for data/staff_moves.csv.

Two things happen here, both driven by scripts/check_source_independence.py:

1. PROMOTIONS. Fourteen Rumored rows get Confirmed. Each one clears both halves of
   the independence test: the original f1technical drop came from a poster who is
   NOT the org-structure doc's author (ralphster7), and that doc independently
   places the person at the destination we recorded. Rows where ralphster7 is the
   only forum source are deliberately left alone -- the doc is his own notes in a
   different container, not a second source.

2. NEW MOVES. Five drops from thread pages 825/840 postdating the last sweep
   (the CSV's newest row was Gwen Lagrue, flagged 2026-07-19).

Idempotent: re-running makes no further changes.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "staff_moves.csv"

DOC_URL = "https://docs.google.com/document/d/1eiZEmLfNBkGt4pWEjycdD7dZkN2Eb1tawQvfEQqY4v8/edit"
THREAD = "https://www.f1technical.net/forum/viewtopic.php?t=16879"

# name -> (destination seat the doc lists, forum user who made the original drop)
PROMOTE = {
    "Adil El Ouazizi":   ("Mercedes, Principal Aerodynamicist", "chrisc90"),
    "Ivan Roldan":       ("Williams, Aero Project Leader", "ScottR267"),
    "Matthew Ranft":     ("Mercedes, Lead Performance & Simulation Engineer", "mclaren_mircea"),
    "Adam Kenyon":       ("Williams, Head of Aerodynamics", "ScottR267"),
    "Gareth Read":       ("Williams, Head of Methods Engineering", "ScottR267"),
    "Mark Temple":       ("McLaren, Technical Director - Performance", "agnideep"),
    "Cedric Sambardier": ("Ferrari, Composites Technical Leader", "ScottR267"),
    "James Phillips":    ("Williams, Head of Model Design", "lio007 and mclaren_mircea"),
    "Marco Scourtis":    ("Audi, Senior Expert (Materials)", "ScottR267"),
    "Linghent Yang":     ("Red Bull Racing, Team Leader - Development", "lio007"),
    "Luke Skipper":      ("Aston Martin, Chief Communications Officer", "KimiRai"),
    "Rebecca Brodie":    ("Williams, Principal Engineer - Structures", "lio007"),
    "Carl Beddard":      ("Cadillac, Lead Engineer - Electronics Hardware", "lio007"),
    "Shaid Farzand":     ("Ferrari, Tyre Engineering Specialist", "Luscion"),
}

CORROB = ("Corroborated by the f1technical community org-structure doc (posted 2026-08-05, "
          f"compiled from public LinkedIn profiles), which lists them at {{seat}}. "
          "Original thread drop by {user}, who is not that doc's author, so the two are "
          f"independent sources. Doc: {DOC_URL}")

# Drops from thread pages 825/840 that postdate the last sweep.
# season follows the house rule: trackside/ops roles take the start year, factory
# design/development roles starting ~May or later take the following year.
NEW_ROWS = [
    dict(name="Luciano Nicomede", nationality="Italian",
         role="Senior Composite Design Engineer", category="Design",
         from_team="Mercedes", to_team="Ferrari", timeline="2026-07", season="2027",
         status="Confirmed", source=f"{THREAD}&start=840",
         notes="Six years at Mercedes before the move. Drop by mclaren_mircea 31 Jul 2026; "
               "independently corroborated by the 2026-08-05 community org-structure doc, which "
               f"places him at Ferrari under Head of Composite Design. Doc: {DOC_URL}"),
    dict(name="Oliver Rose", nationality="",
         role="Deputy Team Leader - Aerodynamics", category="Aerodynamics",
         from_team="Aston Martin", to_team="Racing Bulls", timeline="2026-06", season="2027",
         status="Confirmed", source=f"{THREAD}&start=840",
         notes="Was Principal Aerodynamicist at Aston Martin; joined VCARB in June 2026. Drop by "
               "lio007 2 Aug 2026, independently corroborated by the 2026-08-05 org-structure doc, "
               f"which lists him as Racing Bulls Deputy Team Leader in Aerodynamics. Doc: {DOC_URL}"),
    dict(name="Stephen Taylor", nationality="",
         role="Lead Composite Design Engineer", category="Design",
         from_team="Mercedes", to_team="Aston Martin", timeline="2026-08", season="2027",
         status="Rumored", source=f"{THREAD}&start=840",
         notes="Long-serving Mercedes lead composite designer. Reported 5 Aug 2026 by ralphster7, "
               "who also authors the community org-structure doc - and that doc still lists Taylor "
               "under Mercedes, so it corroborates nothing here. Forum-sourced, single source."),
    dict(name="Carlos Sanchez Martinez", nationality="Spanish",
         role="Unspecified engineering role", category="Technical",
         from_team="Aston Martin", to_team="Ferrari", timeline="2026-08", season="2027",
         status="Rumored", source=f"{THREAD}&start=840",
         notes="Drop by ScottR267 2 Aug 2026; role not stated. Absent from the 2026-08-05 "
               "org-structure doc, so no corroboration yet. Forum-sourced."),
    dict(name="Guillaume Catellani", nationality="French",
         role="Deputy Technical Director (departed)", category="Management",
         from_team="Racing Bulls", to_team="Departed", timeline="2026-04 → TBC", season="2026",
         status="Rumored", source=f"{THREAD}&start=825",
         notes="Announced as leaving alongside Andrea Landi's move to Red Bull; destination "
               "unknown. Drop by ralphster7 17 Apr 2026 (spelled 'Catelanni' in his org-structure "
               "doc's move list). Absent from the doc's Racing Bulls chart, consistent with a "
               "departure. Forum-sourced, single source."),
]


def main() -> None:
    with CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)

    promoted = 0
    for row in rows:
        entry = PROMOTE.get(row["name"])
        if entry and row["status"] == "Rumored":
            seat, user = entry
            row["status"] = "Confirmed"
            note = CORROB.format(seat=seat, user=user)
            row["notes"] = f"{row['notes'].rstrip().rstrip('.')}. {note}" if row["notes"].strip() else note
            promoted += 1

    existing = {(r["name"], r["to_team"]) for r in rows}
    added = [r for r in NEW_ROWS if (r["name"], r["to_team"]) not in existing]
    rows.extend(added)

    with CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"promoted to Confirmed : {promoted}")
    print(f"new rows appended     : {len(added)}")
    for r in added:
        print(f"    {r['name']:<26} {r['from_team']:<14} -> {r['to_team']:<14} [{r['status']}]")
    print(f"total rows            : {len(rows)}")


if __name__ == "__main__":
    main()
