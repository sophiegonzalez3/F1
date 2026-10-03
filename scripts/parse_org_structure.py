"""Parse the f1technical community org-structure document into data/org_structure.csv.

Source: a Google Doc compiled from public LinkedIn profiles by an f1technical.net
"Moving F1-Staff" contributor, posted to that thread on 2026-08-05. Raw export kept
at data/org_structure_raw.txt so re-parses are reproducible.

Document grammar (as written by its author):
    Mercedes                      -- team, a bare line after a "---" rule
    **Aerodynamics**              -- department
    - Role: Name                  -- person reporting into the department
    *Role:* Name                  -- sub-unit head; following "-" lines sit under them
      - Role: Name                -- extra indent, reports to the line above

Names carry the author's own confidence markers: a trailing "?" means unsure, a bare
"?" in the name slot means the seat is known but unfilled/unknown, "x" or "√" are
his private check marks. We keep those as flags rather than dropping the rows.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "org_structure_raw.txt"
OUT = ROOT / "data" / "org_structure.csv"

# Teams as the document titles them -> the TEAM_COLORS / staff_moves node names.
# Mercedes HPP and the engine arms are their own document sections but belong to
# the works team node, exactly as staff_moves.csv harmonises them.
TEAM_ALIASES = {
    "Mercedes": "Mercedes",
    "Mercedes HPP": "Mercedes",
    "Ferrari": "Ferrari",
    "Red Bull": "Red Bull Racing",
    "McLaren": "McLaren",
    "Racing Bulls": "Racing Bulls",
    "Audi": "Audi",
    "Alpine": "Alpine",
    "Williams": "Williams",
    "Haas": "Haas F1 Team",
    "Aston Martin": "Aston Martin",
    "Cadillac": "Cadillac",
}

# Section headers that are not org units.
NON_TEAM_SECTIONS = {"WATCH LIST", "LATEST MOVES", "END OF DOCUMENT", "RED BULL"}

# Department header -> canonical department, so Ferrari's "Design Office" and
# Mercedes' "Design" land in the same bucket for cross-team comparison.
DEPT_CANON = {
    "ownership": "Ownership",
    "bod": "Board",
    "board of director's": "Board",
    "board of directors": "Board",
    "executive team": "Executive",
    "executive leadership": "Executive",
    "executive management": "Executive",
    "executive": "Executive",
    "c suite": "C-Suite",
    "c-suite": "C-Suite",
    "c - suite (share some staff with red bull)": "C-Suite",
    "directors": "Executive",
    "design": "Design",
    "design office": "Design",
    "aerodynamics": "Aerodynamics",
    "vehicle performance": "Vehicle Performance",
    "research and development": "R&D",
    "race team": "Race Team",
    "operations": "Operations",
    "production": "Operations",
    "operations / production": "Operations",
    "production / operations": "Operations",
    "engine": "Power Unit",
    "engine (with ford)": "Power Unit",
    "engine / neuberg": "Power Unit",
    "engine:": "Power Unit",
    "electronics": "Electronics",
    "software": "Software & IT",
    "it & ai": "Software & IT",
    "it": "Software & IT",
    "non racing": "Non-Racing",
    "tpc": "Race Team",
    "heritage": "Heritage",
    "old guard": "Non-Racing",
    "uk": "Power Unit",
    "fuel (petronas)": "Power Unit",
    "technical team - usa, charlotte": "Engineering (US)",
    "managing director hpp": "Power Unit",
}

# Lines that are section subtitles, not people.
SUBTITLE_LINES = {"High Performance Powertrains"}

# Role keyword -> seniority band. Checked in order, first hit wins.
SENIORITY = [
    (r"\b(owner|chairman|chair)\b", 1),
    (r"\b(ceo|chief executive|managing director|team principal|president)\b", 1),
    (r"\bdeputy team principal\b", 2),
    (r"\b(chief \w+ officer|c[foti]o|general counsel|executive director|executive chairman)\b", 2),
    (r"\b(technical director|executive technical|chief technical officer)\b", 2),
    (r"\b(director|chief designer|chief engineer|chief aerodynamicist|chief mechanic|chief scientist|chief strategist)\b", 3),
    (r"\bdeputy chief\b", 3),
    (r"\bhead of\b", 4),
    (r"\b(deputy head|associate director|manager)\b", 4),
    (r"\b(principal|lead |leader|group leader|team leader|section leader)\b", 5),
    (r"\b(senior|snr)\b", 6),
]


def norm_name(name: str) -> str:
    """Casefold + strip accents so 'Frédéric Launoy' matches 'Frederic Launoy'."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def seniority(role: str) -> int:
    low = role.lower()
    for pattern, band in SENIORITY:
        if re.search(pattern, low):
            return band
    return 7


def split_name_role(text: str) -> tuple[str, str]:
    """Split an unlabelled entry into (name, role).

    Board lines read "Jörg Burzer (CTO, Mercedes - Benz)" -- the parenthetical is the
    role, and it may itself contain " - ", so parentheses win over the dash rule.
    Only a dash *outside* brackets marks "René Dias Torcato - head of test".
    """
    text = text.strip()
    m = re.fullmatch(r"([^(]+?)\s*\((.+)\)\s*", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    depth = 0
    for i in range(len(text) - 2):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        elif depth == 0 and text[i : i + 3] == " - ":
            return text[:i].strip(), text[i + 3 :].strip()
    return text, ""


def clean_person(raw: str) -> tuple[str, str, str]:
    """Split a person cell into (name, confidence, note)."""
    note_bits = []
    name = raw.strip()

    # "P = Micky Condolf" -- the author's shorthand for a performance engineer.
    name = re.sub(r"^P\s*=\s*", "", name)

    # The author's private markers.
    if name.endswith("√"):
        note_bits.append("author-verified")
        name = name[:-1].strip()
    if re.search(r"\bx\s*$", name) and len(name) > 2:
        note_bits.append("author-flagged (x)")
        name = re.sub(r"\bx\s*$", "", name).strip()

    confidence = "stated"
    if not name or name in {"?", "??", "xx", "x"}:
        return "", "vacant/unknown", "; ".join(note_bits)
    if name.endswith("?"):
        confidence = "uncertain"
        name = name.rstrip("? ").strip()

    # "Nicola Mosconi // Nicola Barriselli" -- author unsure which of two.
    if "//" in name:
        confidence = "uncertain"
        note_bits.append("document lists two candidates: " + name)
        name = name.split("//")[0].strip()

    # Bracketed names are the author's tentative entries.
    if name.startswith("[") and name.endswith("]"):
        confidence = "uncertain"
        name = name[1:-1].strip()

    name = re.sub(r"\s+", " ", name).strip(" .")
    return name, confidence, "; ".join(note_bits)


def parse() -> list[dict]:
    lines = RAW.read_text(encoding="utf-8").splitlines()
    rows: list[dict] = []

    team = dept = subunit = None
    prev = None  # last non-indented person, for "  - " children

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        stripped = line.strip()

        # Skip the document title.
        if stripped.startswith("# "):
            continue

        # Department header: **Aerodynamics**
        m = re.fullmatch(r"\*\*(.+?):?\*\*:?(.*)", stripped)
        if m:
            head = m.group(1).strip()
            trailing = m.group(2).strip()
            if head.upper() in NON_TEAM_SECTIONS:
                team = None  # WATCH LIST / LATEST MOVES handled separately
                dept = subunit = None
                continue
            key = head.lower().strip().rstrip(":")
            # "OWNERSHIP = AUDI AG, Volkswagen Group (75%) & QIA (25%)" carries the
            # value in the header itself rather than after the colon.
            if key.startswith("ownership"):
                inline = head.split("=", 1)[1].strip() if "=" in head else ""
                dept, subunit, prev = "Ownership", None, None
                if inline or trailing:
                    rows.append(dict(team=team, department="Ownership", subunit="",
                                     role="Ownership", name=(inline or trailing),
                                     seniority=1, confidence="stated", note="ownership line"))
                continue
            dept = DEPT_CANON.get(key, head.strip())
            subunit = None
            prev = None
            # "**Ownership:** Mercedes Benz Group (33.3%) ..." carries its value inline
            if trailing:
                rows.append(
                    dict(team=team, department=dept, subunit="", role=head.strip(),
                         name=trailing, seniority=1, confidence="stated", note="ownership line")
                )
            continue

        # Team header: a bare line, no bullet/asterisk, matching a known team.
        if stripped in TEAM_ALIASES and not line.startswith((" ", "-", "*")):
            team = TEAM_ALIASES[stripped]
            dept = subunit = None
            prev = None
            continue
        if stripped in NON_TEAM_SECTIONS:
            team = None
            continue

        if team is None:
            continue

        # Sub-unit head: *Head of Composite Design:* Chris St Leger Harris
        m = re.fullmatch(r"\*(.+?):?\*\s*(.*)", stripped)
        if m:
            role = m.group(1).strip().rstrip(":")
            name, confidence, note = clean_person(m.group(2))
            subunit = role
            prev = name
            rows.append(dict(team=team, department=dept or "Unassigned", subunit="",
                             role=role, name=name, seniority=seniority(role),
                             confidence=confidence, note=note))
            continue

        # Person line: "- Role: Name" or "  - Role: Name"
        m = re.fullmatch(r"-\s*(.+)", stripped)
        if m:
            body = m.group(1)
            indented = bool(re.match(r"^\s{2,}-", line))
            if ":" in body:
                role, _, person = body.partition(":")
                role, person = role.strip(), person.strip()
            else:
                # "- René Dias Torcato - head of test" style, or a bare name
                role, person = "", body.strip()
            name, confidence, note = clean_person(person)
            if not role and name:
                name, role = split_name_role(name)
            parent = prev if indented else (subunit or "")
            rows.append(dict(team=team, department=dept or "Unassigned",
                             subunit=subunit or "", role=role, name=name,
                             seniority=seniority(role), confidence=confidence,
                             note=(note + ("; reports to " + str(parent) if indented and parent else "")).strip("; ")))
            if not indented:
                prev = name
            continue

        # Bare name with no bullet: "Tim Graves?", "Marcio Pierobom"
        if not stripped.startswith(("*", "#")):
            if stripped in SUBTITLE_LINES:
                continue
            name, confidence, note = clean_person(stripped)
            role = ""
            if name:
                name, role = split_name_role(name)
            if name:
                rows.append(dict(team=team, department=dept or "Unassigned",
                                 subunit=subunit or "", role=role.strip(), name=name,
                                 seniority=seniority(role), confidence=confidence,
                                 note=(note + "; unstructured entry in source").strip("; ")))
    return rows


def main() -> None:
    rows = [r for r in parse() if r["team"]]
    for r in rows:
        r["name_key"] = norm_name(r["name"])
    fields = ["team", "department", "subunit", "role", "name", "name_key",
              "seniority", "confidence", "note"]
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    named = [r for r in rows if r["name"]]
    print(f"{len(rows)} rows -> {OUT.relative_to(ROOT)}  ({len(named)} named, {len(rows)-len(named)} vacant/unknown)")
    from collections import Counter
    for team, n in Counter(r["team"] for r in named).most_common():
        print(f"  {team:<18} {n:>4}")


if __name__ == "__main__":
    main()
