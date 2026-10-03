"""Cross-check the community org-structure doc against our data/staff_moves.csv.

Four questions, in the order they matter:
  1. Where does the doc place people we already track? Agreement is corroboration
     (it is independent LinkedIn-derived evidence); disagreement is a staleness flag
     on one side or the other.
  2. Who appears under two different teams inside the doc itself? The author builds
     it team-by-team, so a duplicate is almost always a move he caught on one page
     and not the other -- free signal.
  3. Which of the doc's own "LATEST MOVES" / "WATCH LIST" entries are missing from
     our CSV?
  4. How much of each team's org chart is churn we have on record?
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")  # the doc carries accents and the author's √ marks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "org_structure_raw.txt"

# Team names as the doc's free-text sections write them -> our node names.
MOVE_TEAM_ALIASES = {
    "sauber": "Audi", "audi": "Audi", "hinwil": "Audi",
    "mercedes": "Mercedes", "mercedes hpp": "Mercedes", "merc": "Mercedes",
    "ferrari": "Ferrari",
    "red bull": "Red Bull Racing", "rbr": "Red Bull Racing", "red bull racing": "Red Bull Racing",
    "racing bulls": "Racing Bulls", "vcarb": "Racing Bulls", "rb": "Racing Bulls",
    "mclaren": "McLaren",
    "alpine": "Alpine", "renault": "Alpine", "enstone": "Alpine",
    "williams": "Williams",
    "haas": "Haas F1 Team",
    "aston martin": "Aston Martin", "aston": "Aston Martin",
    "cadillac": "Cadillac",
    "fia": "FIA",
}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# Nicknames that a prefix test cannot bridge.
NICKNAMES = {
    "nick": "nicholas", "nic": "nicholas", "mike": "michael", "mick": "michael",
    "bob": "robert", "rob": "robert", "bill": "william", "will": "william",
    "dick": "richard", "rick": "richard", "jim": "james", "jack": "john",
    "tony": "anthony", "ted": "edward", "ed": "edward", "sam": "samuel",
    "alex": "alexander", "chris": "christopher", "dan": "daniel", "matt": "matthew",
    "pete": "peter", "steve": "stephen", "tom": "thomas", "greg": "gregory",
    "andy": "andrew", "ben": "benjamin", "gary": "gareth", "joe": "joseph",
}


def surname_key(name: str) -> str:
    """Last token + first initial. Deliberately loose -- see `same_person` for the
    precision test; this is only a cheap bucketing key."""
    parts = norm(name).split()
    if not parts:
        return ""
    return f"{parts[-1]}|{parts[0][0]}" if len(parts) > 1 else parts[-1]


def _canon_first(first: str) -> str:
    return NICKNAMES.get(first, first)


def same_person(a: str, b: str) -> bool:
    """Precision test on top of the surname bucket.

    'Steve Booth'/'Steven Booth' and 'Oliver R.'/'Oliver Rose' are the same person;
    'Alex Chan'/'Alan Chan' and 'James Williams'/'Jason Williams' are not. Requires
    the surnames to match and the first names to be equal, a nickname pair, an
    initial, or a genuine prefix of one another.
    """
    pa, pb = norm(a).split(), norm(b).split()
    if not pa or not pb or pa[-1] != pb[-1]:
        return False
    if len(pa) == 1 or len(pb) == 1:
        return True
    fa, fb = _canon_first(pa[0]), _canon_first(pb[0])
    if fa == fb:
        return True
    if len(fa) == 1 or len(fb) == 1:
        return fa[0] == fb[0]
    short, long_ = sorted((fa, fb), key=len)
    return len(short) >= 3 and long_.startswith(short)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    org = pd.read_csv(ROOT / "data" / "org_structure.csv", encoding="utf-8")
    org = org[org.name.notna() & (org.department != "Ownership")].copy()
    org["skey"] = org.name.map(surname_key)

    mov = pd.read_csv(ROOT / "data" / "staff_moves.csv", encoding="utf-8")
    mov["skey"] = mov.name.map(surname_key)
    return org, mov


def section(title: str) -> str:
    """Pull a trailing free-text block ('WATCH LIST' / 'LATEST MOVES') from the raw doc."""
    text = RAW.read_text(encoding="utf-8")
    m = re.search(rf"\*\*{title}\*\*(.*?)(?=\n---|\*\*END OF DOCUMENT\*\*)", text, re.S)
    return m.group(1).strip() if m else ""


def report_placement(org: pd.DataFrame, mov: pd.DataFrame) -> None:
    """Q1: does the doc place our tracked movers where we say they went?"""
    bucket = defaultdict(list)
    for _, r in org.iterrows():
        bucket[r.skey].append(r)

    agree, disagree, absent = [], [], []
    for _, m in mov.iterrows():
        hits = [r for r in bucket.get(m.skey, []) if same_person(m["name"], r["name"])]
        if not hits:
            absent.append(m)
            continue
        teams = {r.team for r in hits}
        if m.to_team in teams:
            agree.append(m)
        elif m.from_team in teams:
            disagree.append((m, teams))
        else:
            disagree.append((m, teams))

    print(f"\n{'='*78}\n1. PLACEMENT CHECK -- our {len(mov)} tracked moves vs the doc's org chart\n{'='*78}")
    print(f"  doc places them at our destination : {len(agree):>4}   (independent corroboration)")
    print(f"  doc places them somewhere else     : {len(disagree):>4}   (staleness on one side)")
    print(f"  not named anywhere in the doc      : {len(absent):>4}")

    print("\n  -- CORROBORATED, currently Rumored in our CSV (candidates to promote) --")
    n = 0
    for m in agree:
        if m.status == "Rumored":
            print(f"    {m['name']:<28} {str(m.from_team):<16} -> {m.to_team:<16} {str(m.role)[:38]}")
            n += 1
    if not n:
        print("    (none)")

    print("\n  -- DISAGREEMENTS (doc still lists them elsewhere) --")
    for m, teams in disagree:
        where = ", ".join(sorted(teams))
        print(f"    {m['name']:<28} we: {str(m.from_team):<14} -> {m.to_team:<14} | doc: {where}  [{m.status}]")


def report_duplicates(org: pd.DataFrame) -> None:
    """Q2: same person under two teams inside the doc = an in-flight move."""
    print(f"\n{'='*78}\n2. INTERNAL DUPLICATES -- one person, two teams in the same document\n{'='*78}")
    dupes = []
    for skey, grp in org.groupby("skey"):
        # A surname bucket can hold several distinct people (three Williamses across
        # three teams); split it into same_person clusters before calling anything a
        # duplicate.
        clusters: list[list] = []
        for _, r in grp.iterrows():
            for c in clusters:
                if same_person(c[0]["name"], r["name"]):
                    c.append(r)
                    break
            else:
                clusters.append([r])
        for c in clusters:
            teams = sorted({r.team for r in c})
            if len(teams) > 1:
                dupes.append((skey, pd.DataFrame(c), teams))
    print(f"  {len(dupes)} people appear under more than one team\n")
    for _skey, grp, teams in sorted(dupes, key=lambda d: d[1].name.iloc[0]):
        name = grp.name.iloc[0]
        print(f"    {name}")
        for _, r in grp.iterrows():
            print(f"        {r.team:<17} {r.department:<20} {str(r.role)[:46]}")


def report_freetext(mov: pd.DataFrame) -> None:
    """Q3: the doc's own move lists vs our CSV."""
    # Match by scanning each line for any tracked person's name rather than trying to
    # parse a name out of the front of it -- these lines have no consistent shape
    # ("Gavin Bonney Head of ... [Aston Martin] -> ...", "Joanna Fleet OUT").
    tracked = [(norm(n), norm(n).split()) for n in mov["name"].unique() if norm(n)]
    for title in ("WATCH LIST", "LATEST MOVES"):
        body = section(title)
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("**")]
        missing = []
        for l in lines:
            nl = norm(l)
            hit = any(full in nl for full, _ in tracked)
            if not hit:
                # Fall back to surname + first initial, to survive the doc's spelling
                # drift ("Tomazewski" vs "Tomaszewski", "Passetti" vs "Pasetti").
                toks = nl.split()
                hit = any(p[-1] in toks and p[0][0] in {t[0] for t in toks}
                          for _, p in tracked if len(p) > 1)
            if not hit:
                missing.append(l)
        have = len(lines) - len(missing)
        print(f"\n{'='*78}\n3{'a' if title=='WATCH LIST' else 'b'}. {title} -- {len(lines)} entries, "
              f"{have} already tracked, {len(missing)} NOT in staff_moves.csv\n{'='*78}")
        for l in missing:
            print(f"    {l}")


def report_coverage(org: pd.DataFrame, mov: pd.DataFrame) -> None:
    """Q4: how much of each roster is churn we already have on record?"""
    print(f"\n{'='*78}\n4. COVERAGE -- named people per team, and how many we track a move for\n{'='*78}")
    known = set(mov.skey)
    print(f"  {'team':<18} {'named':>6} {'tracked':>8} {'%':>6}   {'unnamed seats':>14}")
    for team, grp in org.groupby("team"):
        named = grp[grp.name != ""]
        hit = named[named.skey.isin(known)]
        vac = (grp.confidence == "vacant/unknown").sum()
        unsure = (grp.confidence == "uncertain").sum()
        print(f"  {team:<18} {len(named):>6} {len(hit):>8} {100*len(hit)/max(len(named),1):>5.1f}%   "
              f"{vac:>4} vacant, {unsure:>3} uncertain")


def main() -> None:
    org, mov = load()
    report_placement(org, mov)
    report_duplicates(org)
    report_freetext(mov)
    report_coverage(org, mov)


if __name__ == "__main__":
    main()
