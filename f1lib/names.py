"""Person-name matching shared by the org-structure tooling.

Two sources name the same people differently: data/staff_moves.csv follows the
press ("Steve Booth", "Jan Tomaszewski"), while the community org-structure doc
follows LinkedIn and the author's shorthand ("Steven Booth", "Jan Tomazewski",
"Oliver R."). Matching on the full string loses those; matching on surname alone
merges the three unrelated Williamses sitting at three different teams.

So: `surname_key` is a cheap bucketing key, and `same_person` is the precision
test applied inside a bucket.
"""

from __future__ import annotations

import re
import unicodedata

# Nicknames a prefix test cannot bridge.
NICKNAMES = {
    "nick": "nicholas", "nic": "nicholas", "mike": "michael", "mick": "michael",
    "bob": "robert", "rob": "robert", "bill": "william", "will": "william",
    "dick": "richard", "rick": "richard", "jim": "james", "jack": "john",
    "tony": "anthony", "ted": "edward", "ed": "edward", "sam": "samuel",
    "alex": "alexander", "chris": "christopher", "dan": "daniel", "matt": "matthew",
    "pete": "peter", "steve": "stephen", "tom": "thomas", "greg": "gregory",
    "andy": "andrew", "ben": "benjamin", "gary": "gareth", "joe": "joseph",
}


def norm(name: str) -> str:
    """Casefold, strip accents and punctuation: 'Frédéric Launoy' -> 'frederic launoy'."""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s.lower())).strip()


def surname_key(name: str) -> str:
    """Bucketing key only — deliberately loose. Pair with `same_person`."""
    parts = norm(name).split()
    if not parts:
        return ""
    return f"{parts[-1]}|{parts[0][0]}" if len(parts) > 1 else parts[-1]


def _canon_first(first: str) -> str:
    return NICKNAMES.get(first, first)


def same_person(a: str, b: str) -> bool:
    """Whether two spellings denote one person.

    Surnames must match, and first names must be equal, a known nickname pair, a
    matching initial, or a genuine prefix of one another. That keeps
    'Steve/Steven Booth' and 'Oliver R./Oliver Rose' together while holding
    'Alex Chan'/'Alan Chan' and 'James/Jason Williams' apart.
    """
    pa, pb = norm(a).split(), norm(b).split()
    if not pa or not pb or pa[-1] != pb[-1]:
        return False
    if len(pa) == 1 or len(pb) == 1:  # mononym in one source
        return True
    fa, fb = _canon_first(pa[0]), _canon_first(pb[0])
    if fa == fb:
        return True
    if len(fa) == 1 or len(fb) == 1:  # "Oliver R." style initial
        return fa[0] == fb[0]
    short, long_ = sorted((fa, fb), key=len)
    return len(short) >= 3 and long_.startswith(short)
