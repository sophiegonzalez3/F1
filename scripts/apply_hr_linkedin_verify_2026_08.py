"""Apply the LinkedIn / press verification pass over data/staff_moves.csv.

Method note. LinkedIn returns HTTP 999 to any direct fetch and the logged-in
browser path was unavailable, so nothing here comes from reading a profile page.
What IS reliable is a profile's *title tag* as indexed by search engines --
"Name - Company | LinkedIn" or "Name - Job Title" -- which is the person's own
headline, plus ordinary press. The search tool's AI summary is NOT reliable: it
claimed Mark Gilmore was joining Cadillac as "Aerodynamics Department Manager",
which is the title we already hold for Simon Hine, so it was conflating two of the
200+ Mark Gilmores. Only headlines and named press articles are used below.

A headline that names the OLD employer is evidence against a move, but weak
evidence -- search indexes lag and plenty of people never update their profile.
So contradicted rows are annotated and held at Rumored rather than deleted. The
one deletion is a row where the supposed press coverage turned out to be about a
different person entirely.
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

GPFANS = ("https://www.gpfans.com/en/f1-news/1088704/"
          "ferrari-poach-mercedes-f1-engineer-luciano-nicomede-double-signing-aston-martin/")
WILLIAMS = ("https://www.williamsf1.com/articles/01c3bcdc-41aa-40ec-b866-fb279d8d0000/"
            "williams-racing-unveils-new-top-technical-talent")
F1COM_26 = ("https://www.formula1.com/en/latest/article/"
            "former-alpine-tech-chief-matt-harman-heads-bumper-list-of-26-williams-hires."
            "41ymWaiX90AmjoScccl2lv")

# name -> field updates. Applied to the row matching that person.
UPDATES: dict[str, dict] = {
    "Carlos Sanchez Martinez": dict(
        role="Chassis Stress Engineering Specialist",
        status="Confirmed",
        source=GPFANS,
        timeline="2026-07",
        notes="Eight years at Aston Martin, joining as a junior stress engineer when the "
              "team was Racing Point in 2019 and promoted to stress engineer in 2022. "
              "Moves into the chassis structure under technical director Loic Serra. "
              "Confirmed by GPFans (4 Aug 2026) and by his own LinkedIn headline, which "
              "now reads Ferrari -- independent of the f1technical drop by ScottR267 and "
              "of the community org-structure doc, which does not list him at all."),
    "Luciano Nicomede": dict(
        role="Senior Chassis Composite Designer",
        source=GPFANS,
        notes="At Mercedes since 2020. Announced it himself: \"I'm happy to share that "
              "I've started a new role as a Senior Chassis Composite Designer at "
              "Scuderia Ferrari HP.\" Reported by GPFans (4 Aug 2026) as one half of a "
              "double signing with Carlos Sanchez Martinez. Press confirmation now "
              "supersedes the original forum drop by mclaren_mircea; the community "
              "org-structure doc also seats him at Ferrari. Role corrected from "
              "'Senior Composite Design Engineer' to the title he uses himself."),
    "Adam Kenyon": dict(
        source=WILLIAMS,
        notes="Internal promotion, April 2024. Confirmed by Williams' own technical-"
              "recruitment announcement (27 Jun 2024), which lists him as Head of "
              "Aerodynamics promoted from within -- a first-party source, so this no "
              "longer rests on the f1technical thread or the org-structure doc."),

    # -- LinkedIn headline still shows the ORIGIN team: held at Rumored --
    "Vasilis Tsinias": dict(
        notes="Recorded from the community org-structure doc, whose Haas chart seats him "
              "as Team Leader - Tyre Science while its own move list says the destination "
              "is TBC. Verification makes this weaker still: his LinkedIn headline reads "
              "'Vasilis Tsinias - Alpine Formula One Team', and his documented history is "
              "Alpine throughout (Senior Tyre Performance Engineer 2016-18, then Tyre "
              "Performance Section Leader). Treat the Haas destination as unsupported "
              "until a second source appears."),
    "Mark Gilmore": dict(
        notes="Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
              "listed as Alpine's Head of Wind Tunnel Development AND Aston Martin's Head "
              "of Aerodynamic R&D. Verification does not support the Aston Martin end -- "
              "his LinkedIn headline still reads 'Mark Gilmore - Alpine Formula One Team' "
              "and no press covers a move. Held as a lead only."),
    "Terry Brice": dict(
        notes="Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
              "listed as Red Bull's Group Director, Infrastructure and Property AND Aston "
              "Martin's Facilities Director. Verification does not support the Aston "
              "Martin end -- his LinkedIn headline still reads 'Group Director of "
              "Infrastructure & Property', the Red Bull title. Held as a lead only."),
    "Nathan Sykes": dict(
        notes="Surfaced by an internal contradiction in the 2026-08-05 org-structure doc: "
              "listed as Alpine's Chief Information Officer AND Aston Martin's Chief "
              "Engineer - Methodology. Evidence is genuinely mixed: his LinkedIn places "
              "him at Towcester, next to Aston Martin's Silverstone base, and a since-"
              "deleted SI.com piece was headlined on Aston Martin hiring an Alpine "
              "advisor -- but directory listings still carry his Alpine title (IT, "
              "Business Systems and Data Science Director). Note also that the two roles "
              "are an odd pairing for one person. Best supported of the three duplicate-"
              "derived leads, still short of confirmation."),
}

# Rows whose basis did not survive checking.
REMOVE = {
    "Matteo Sansavini": (
        "recorded as Aston Martin -> McLaren from the org-structure doc's move list. "
        "His own LinkedIn headline reads 'Matteo Sansavini - Aston Martin F1 Team' and "
        "directory listings give him as Aston Martin Aero Group Leader. The press stories "
        "that look like corroboration ('McLaren lands senior Aston F1 aerodynamicist') "
        "are from March 2023 and are about Mariano Alperin, a different person. His "
        "McLaren spell was 2013. The doc appears to have conflated the two."),
}

# Found while verifying, not previously tracked.
ADD = [
    dict(name="Sorin Cheran", nationality="Romanian",
         role="Chief Information and Analytics Officer", category="Management",
         from_team="Hewlett Packard Enterprise", to_team="Williams",
         timeline="2024-06", season="2025", status="Confirmed", source=WILLIAMS,
         notes="Named in Williams' own technical-recruitment announcement (27 Jun 2024) "
               "alongside Harman, Molina, Winstanley, Moncade and Frith, all of whom we "
               "already track. Missed until now because he joined from outside F1 "
               "(Hewlett Packard Enterprise), so he never appeared in the f1technical "
               f"sweep. Part of the same 26-hire wave: {F1COM_26}"),
]


def main() -> None:
    with CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)

    kept, removed = [], []
    for r in rows:
        hit = next((n for n in REMOVE if same_person(n, r["name"])), None)
        if hit and r["to_team"] == "McLaren":
            removed.append((r, REMOVE[hit]))
            continue
        kept.append(r)
    rows = kept

    updated = []
    for r in rows:
        for name, fieldmap in UPDATES.items():
            if same_person(name, r["name"]) and (
                    name != "Adam Kenyon" or r["to_team"] == "Williams"):
                before = r["status"]
                r.update(fieldmap)
                updated.append((r["name"], before, r["status"]))
                break

    existing = {(r["name"], r["to_team"]) for r in rows}
    added = [a for a in ADD if (a["name"], a["to_team"]) not in existing]
    rows.extend(added)

    with CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"removed : {len(removed)}")
    for r, why in removed:
        print(f"    {r['name']} ({r['from_team']} -> {r['to_team']}) -- {why[:90]}...")
    print(f"updated : {len(updated)}")
    for n, b, a in updated:
        print(f"    {n:<26} {b} -> {a}")
    print(f"added   : {len(added)}")
    for a in added:
        print(f"    {a['name']:<26} {a['from_team']} -> {a['to_team']} [{a['status']}]")
    print(f"total rows: {len(rows)}")


if __name__ == "__main__":
    main()
