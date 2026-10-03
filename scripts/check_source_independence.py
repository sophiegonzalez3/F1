"""Independence test for the community org-structure doc.

The doc was posted to the f1technical "Moving F1-Staff" thread on 2026-08-05 by the
user `ralphster7`, who is also the thread's most prolific poster of move drops. Our
verification rule promotes a Rumored move to Confirmed when a *second, independent*
source corroborates it. If the original drop and the doc are both ralphster7, they
are one source wearing two hats and the row must stay Rumored.

This script attributes every forum-sourced row in staff_moves.csv to the forum user
who actually posted it, so the promotion decision can be made per row instead of
in bulk.

Input: the scraped thread dump (JSON array of {start, user, text}) passed as argv[1].
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DOC_AUTHOR = "ralphster7"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s.lower())).strip()


def load_posts(path: Path) -> list[dict]:
    blob = json.loads(path.read_text(encoding="utf-8"))
    # The browser tool wraps results as [{type, text}]; `text` is our JSON array
    # double-encoded as a string, followed by a human-readable origin trailer.
    if blob and isinstance(blob[0], dict) and blob[0].get("type") == "text":
        inner, _ = json.JSONDecoder().raw_decode(blob[0]["text"])
        blob = json.loads(inner) if isinstance(inner, str) else inner
    for p in blob:
        p["norm"] = norm(p["text"])
    return blob


def main() -> None:
    posts = load_posts(Path(sys.argv[1]))
    mov = pd.read_csv(ROOT / "data" / "staff_moves.csv", encoding="utf-8")

    forum = mov[mov.source.astype(str).str.contains("f1technical", na=False)].copy()
    print(f"staff_moves.csv: {len(mov)} rows, {len(forum)} sourced to the f1technical thread")
    print(f"  of those, Rumored: {(forum.status == 'Rumored').sum()}")
    print(f"\nScraped {len(posts)} posts across thread pages 465-840.")
    print("Top posters:", ", ".join(f"{u} ({n})" for u, n in Counter(p["user"] for p in posts).most_common(6)))

    attrib: dict[str, set[str]] = defaultdict(set)
    unmatched = []
    for _, row in forum.iterrows():
        parts = norm(row["name"]).split()
        if not parts:
            continue
        surname = parts[-1]
        hits = [p for p in posts if re.search(rf"\b{re.escape(surname)}\b", p["norm"])]
        # Prefer posts that also carry the first name, when there are several.
        strict = [p for p in hits if re.search(rf"\b{re.escape(parts[0])}\b", p["norm"])]
        hits = strict or hits
        if not hits:
            unmatched.append(row["name"])
            continue
        for p in hits:
            attrib[row["name"]].add(p["user"])

    sole_author, independent, multi = [], [], []
    for _, row in forum.iterrows():
        users = attrib.get(row["name"])
        if not users:
            continue
        if users == {DOC_AUTHOR}:
            sole_author.append(row)
        elif DOC_AUTHOR in users:
            multi.append((row, users))
        else:
            independent.append((row, users))

    print(f"\n{'='*78}\nATTRIBUTION OF FORUM-SOURCED ROWS\n{'='*78}")
    print(f"  posted ONLY by {DOC_AUTHOR} (doc author)  : {len(sole_author):>4}  -> doc is NOT independent")
    print(f"  posted by {DOC_AUTHOR} AND others         : {len(multi):>4}  -> check per row")
    print(f"  posted only by OTHER users              : {len(independent):>4}  -> doc IS independent")
    print(f"  name not found in scraped posts         : {len(unmatched):>4}")

    print(f"\n-- Rumored rows the doc corroborates INDEPENDENTLY (safe to promote) --")
    n = 0
    for row, users in independent:
        if row["status"] == "Rumored":
            print(f"    {row['name']:<28} {str(row['from_team']):<16} -> {str(row['to_team']):<16} "
                  f"posted by: {', '.join(sorted(users))}")
            n += 1
    print(f"    ({n} rows)" if n else "    (none)")

    print(f"\n-- Rumored rows where {DOC_AUTHOR} is the ONLY forum source (keep Rumored) --")
    names = sorted(r["name"] for r in sole_author if r["status"] == "Rumored")
    for i in range(0, len(names), 3):
        print("    " + "".join(f"{x:<30}" for x in names[i:i + 3]))
    print(f"    ({len(names)} rows)")

    # The promotion set is the intersection: an independent forum poster made the
    # original drop AND the doc independently places the person at our destination.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from review_org_structure import same_person, surname_key  # noqa: E402

    org = pd.read_csv(ROOT / "data" / "org_structure.csv", encoding="utf-8")
    org = org[org.name.notna()]
    org_bucket: dict[str, list] = defaultdict(list)
    for _, r in org.iterrows():
        org_bucket[surname_key(r["name"])].append(r)

    print(f"\n{'='*78}\nPROMOTE TO CONFIRMED -- independent poster AND doc places them at our to_team\n{'='*78}")
    promote = []
    for row, users in independent:
        if row["status"] != "Rumored":
            continue
        hits = [r for r in org_bucket.get(surname_key(row["name"]), [])
                if same_person(row["name"], r["name"])]
        if any(r.team == row["to_team"] for r in hits):
            seat = next(r for r in hits if r.team == row["to_team"])
            promote.append((row, users, seat))
            print(f"    {row['name']:<26} -> {row['to_team']:<16} {str(seat.role)[:34]:<34} "
                  f"(drop by {', '.join(sorted(users))})")
    print(f"\n    {len(promote)} rows qualify.")


if __name__ == "__main__":
    main()
