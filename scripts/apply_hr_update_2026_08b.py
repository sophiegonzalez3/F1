"""Second pass of the summer-break 2026 HR update: moves harvested from the doc.

scripts/apply_hr_update_2026_08.py handled the f1technical thread drops. This one
adds moves that only the community org-structure document carries, from two places:

  - its "LATEST MOVES" / "WATCH LIST" free-text blocks, which the thread never
    posted separately;
  - its own internal contradictions. The author builds the document team by team,
    so where one person is listed under two teams he has caught a transfer on one
    page and not yet the other. Gilmore, Sykes and Brice all surface that way.

Every row here is Rumored. The document's author (ralphster7) is also the thread's
main move-poster, so nothing in it is a second, independent source -- see
scripts/check_source_independence.py. Where the org chart happens to seat someone
at the destination too, that is the same author agreeing with himself and the note
says so.

Idempotent: re-running makes no further changes.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from f1lib.names import same_person  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "staff_moves.csv"
DOC = "https://docs.google.com/document/d/1eiZEmLfNBkGt4pWEjycdD7dZkN2Eb1tawQvfEQqY4v8/edit"

_SEEN = ("Listed in the community org-structure doc (posted 2026-08-05 to the "
         "f1technical 'Moving F1-Staff' thread, compiled from public LinkedIn "
         "profiles). ")
_SAME_AUTHOR = ("That doc's author is also the thread's main move-poster, so its "
                "org chart agreeing is not independent corroboration. ")


def row(name, role, category, frm, to, season, notes, nationality="",
        timeline="2026", status="Rumored"):
    return dict(name=name, nationality=nationality, role=role, category=category,
                from_team=frm, to_team=to, timeline=timeline, season=str(season),
                status=status, source=DOC, notes=notes)


NEW_ROWS = [
    # -- from the doc's LATEST MOVES block, corroborated by its own org chart --
    row("Matteo Sansavini", "Aero Project Leader", "Aerodynamics",
        "Aston Martin", "McLaren", 2027,
        _SEEN + "Was Aero Team Leader at Aston Martin. The doc's McLaren chart also "
        "seats him as an Aero Project Leader. " + _SAME_AUTHOR + "Date not stated."),
    row("Martin Wahl", "Performance Engineer (Perez)", "Technical",
        "Haas F1 Team", "Cadillac", 2026,
        _SEEN + "The doc's Cadillac race-team chart seats him as performance engineer "
        "alongside Carlo Pasetti on Perez's car. " + _SAME_AUTHOR
        + "Trackside role, so it bites from Cadillac's debut season."),
    row("Mark Green", "Aerodynamics Project Leader", "Aerodynamics",
        "Alpine", "Williams", 2027,
        _SEEN + "Was Senior Aerodynamicist at Alpine; the doc's Williams chart lists "
        "him among the Aero Project Leaders. " + _SAME_AUTHOR + "Date not stated."),
    row("Vasilis Tsinias", "Team Leader - Tyre Science", "Technical",
        "Alpine", "Haas F1 Team", 2027,
        _SEEN + "The doc contradicts itself on this one: its move list says the "
        "destination is TBC, while its Haas chart already seats him as Team Leader - "
        "Tyre Science. Recorded to Haas on the more specific of the two, but treat "
        "the destination as soft. " + _SAME_AUTHOR),
    row("Patrick Inzinger", "Unspecified engineering role", "Technical",
        "Racing Bulls", "Red Bull Racing", 2027,
        _SEEN + "Listed only as Racing Bulls to Red Bull, with no role or date. One "
        "of several sister-team promotions in this window (cf. Andrea Landi)."),
    row("Carine Criedlich", "Head of Race Strategy (departed)", "Sporting",
        "Haas F1 Team", "Departed", 2026,
        _SEEN + "Destination not stated. Trackside strategy role, so the gap opens "
        "in-season."),
    row("David Baker", "PLM Manager (retired)", "Technical",
        "Ferrari", "Departed", 2026,
        _SEEN + "Retired after 34 years at Ferrari."),
    row("John Lockwood", "Head of Composite Design", "Design",
        "Ferrari", "Ferrari Hypersail (non-F1)", 2026,
        _SEEN + "Moved off the F1 programme onto Ferrari's Hypersail sailing project "
        "- so the F1 team loses the seat even though the employer is unchanged. "
        "Recorded as a non-F1 destination, the same treatment as Aston Martin "
        "Performance Technologies."),

    # -- surfaced by the doc listing one person under two teams --
    row("Mark Gilmore", "Head of Aerodynamic R&D", "Aerodynamics",
        "Alpine", "Aston Martin", 2027,
        "Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
        "listed as Alpine's Head of Wind Tunnel Development AND Aston Martin's Head "
        "of Aerodynamic R&D. The author compiles team by team, so a double listing "
        "usually means a transfer caught on one page and not the other. Not "
        "separately reported in the thread - treat as a lead."),
    row("Nathan Sykes", "Chief Engineer - Methodology", "Technical",
        "Alpine", "Aston Martin", 2027,
        "Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
        "listed as Alpine's Chief Information Officer AND Aston Martin's Chief "
        "Engineer - Methodology. Not separately reported in the thread - treat as a "
        "lead."),
    row("Terry Brice", "Facilities Director", "Management",
        "Red Bull Racing", "Aston Martin", 2027,
        "Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
        "listed as Red Bull's Group Director, Infrastructure and Property AND Aston "
        "Martin's Facilities Director. The author separately flags his name, with no "
        "arrow, in the doc's move list - so he was aware of it. Treat as a lead."),

    # -- communications and media leadership --
    row("Benjamin Ippoliti", "Group Director, Communications", "Management",
        "Red Bull Racing", "Red Bull Racing", 2026,
        _SEEN + "Internal move up from Head of Marketing & Communications for Red "
        "Bull's corporate projects to the racing team's communications directorate; "
        "the doc's Red Bull chart seats him there. " + _SAME_AUTHOR),
    row("Alexandra Horton", "Head of Communications (promoted)", "Management",
        "Racing Bulls", "Racing Bulls", 2026,
        _SEEN + "Internal promotion, backfilling Fabiana Valenti. The doc's Racing "
        "Bulls chart seats her in the role. " + _SAME_AUTHOR),
    row("Fabiana Valenti", "Head of Communications", "Management",
        "Racing Bulls", "Racing Bulls", 2026,
        _SEEN + "Moved off the travelling communications role into a factory-based "
        "one; replaced by Alexandra Horton."),
    row("Silvia Hoffer Frangipane", "Head of Media", "Management",
        "Ferrari", "Ferrari Corporate (non-F1)", 2026,
        _SEEN + "Moved from the F1 team's media operation to Ferrari corporate, so "
        "the racing team loses the seat. Name spelled 'Frangipagne' in the source.",
        nationality="Italian"),
    row("Rebecca Banks", "Head of Media (departed)", "Management",
        "Williams", "Departed", 2026,
        _SEEN + "Recorded only as having left; no destination given."),

    # -- the doc's bare Red Bull "OUT" list --
    row("Joanna Fleet", "Unspecified (listed as departing)", "Technical",
        "Red Bull Racing", "Departed", 2026,
        _SEEN + "One of four names under a bare 'RED BULL / OUT' heading, with no "
        "role, date or destination attached. Logged for completeness; the role is "
        "genuinely unknown, not omitted."),
    row("Julia George", "Unspecified (listed as departing)", "Technical",
        "Red Bull Racing", "Departed", 2026,
        _SEEN + "One of four names under a bare 'RED BULL / OUT' heading, with no "
        "role, date or destination attached. Logged for completeness; the role is "
        "genuinely unknown, not omitted."),
    row("Simon Smith-Wright", "Unspecified (listed as departing)", "Technical",
        "Red Bull Racing", "Departed", 2026,
        _SEEN + "One of four names under a bare 'RED BULL / OUT' heading, with no "
        "role, date or destination attached. Logged for completeness; the role is "
        "genuinely unknown, not omitted."),
    row("Alice Hedworth", "Unspecified (listed as departing)", "Technical",
        "Red Bull Racing", "Departed", 2026,
        _SEEN + "One of four names under a bare 'RED BULL / OUT' heading, with no "
        "role, date or destination attached. Logged for completeness; the role is "
        "genuinely unknown, not omitted."),
]


def main() -> None:
    with CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)

    added = []
    for cand in NEW_ROWS:
        dupe = any(same_person(cand["name"], r["name"]) and r["to_team"] == cand["to_team"]
                   for r in rows)
        if not dupe:
            rows.append(cand)
            added.append(cand)

    with CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"new rows appended: {len(added)}")
    for r in added:
        print(f"    {r['name']:<26} {r['from_team']:<16} -> {r['to_team']:<32} [{r['status']}]")
    print(f"total rows       : {len(rows)}")


if __name__ == "__main__":
    main()
