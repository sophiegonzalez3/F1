"""
F1 Dashboard – shared beginner glossary
=======================================
One place that defines every piece of F1 jargon the dashboard uses, written
for someone who has *never watched a race*. `gloss()` wraps a word in a
dotted-underline hover (built on components.tip, so it works on Safari and
touch too) that shows the plain-English definition.

Usage — splice the returned [span, tooltip] pair into any children list, the
same way `tip()` is used:

    html.P(["The ", *gloss("undercut"), " is when a driver pits early…"])

Convention: gloss the *first* occurrence of a term in a given card or intro,
not every occurrence — enough to teach, not so much it clutters. Experts just
ignore the underline; newcomers hover the one term they don't know.
"""
from __future__ import annotations

from f1lib.components import tip

# ── The glossary ─────────────────────────────────────────────
# Keys are lower-case slugs; look-up in gloss() is case-insensitive and also
# tolerates the spelled-out term (spaces → the key). Definitions assume zero
# prior knowledge and stay to ~1-2 sentences so the hover card stays readable.
GLOSSARY: dict[str, str] = {
    # — Weekend structure —
    "grand prix": "A single race event — one round of the championship, held "
        "at one circuit over a weekend. There are ~24 per season.",
    "practice": "Non-scored sessions (FP1, FP2, FP3) before qualifying where "
        "teams try setups and tyres. Nothing here counts for points.",
    "qualifying": "The Saturday session that sets the starting order for the "
        "race. Whoever sets the fastest single lap starts at the very front.",
    "pole position": "The very first spot on the starting grid, earned by "
        "setting the fastest lap in qualifying. The best place to start from.",
    "grid": "The starting layout of the race — cars lined up two-by-two in the "
        "order they qualified, fastest at the front.",
    "sprint": "A short race (about a third of the normal distance) held on some "
        "weekends. It awards a few points but is separate from the main race.",
    "formation lap": "One slow lap the whole field drives before the race "
        "starts, to warm up tyres and brakes. The race begins when it ends.",
    "parc ferme": "A rule state after qualifying starts where teams may no "
        "longer change the car's setup — what you qualify with, you race with.",
    "chequered flag": "The black-and-white flag waved to signal the end of a "
        "session or race.",

    # — Cars, teams, people —
    "constructor": "A team (e.g. Ferrari, McLaren). Each enters two cars. The "
        "Constructors' Championship is the title for teams, not drivers.",
    "teammate": "The other driver in the same team, driving identical "
        "machinery — the fairest yardstick for how good a driver really is.",
    "power unit": "The modern F1 engine: a turbo-hybrid combining a petrol "
        "engine with electric-recovery motors. Often shortened to 'PU'.",
    "power unit penalty": "A grid-place drop given when a team fits more engine "
        "parts than the season allowance — an aging-engine tax, not misbehaviour.",
    "gearbox": "The transmission that sends engine power to the rear wheels. "
        "Like the engine it's rationed: each driver gets a fixed number per "
        "season, and fitting extra ones brings a grid penalty.",

    # — Timing & pace —
    "lap time": "How long a driver takes to complete one full lap of the "
        "circuit, measured to the thousandth of a second.",
    "sector": "Each lap is split into three timed parts (Sector 1/2/3), so you "
        "can see which part of the track a driver gains or loses time in.",
    "one-lap pace": "How fast a car is over a SINGLE flat-out lap — low fuel, "
        "fresh tyres, maximum attack. This is qualifying speed, and it is not "
        "the same thing as race pace: a car can be quick here and fall away on "
        "Sunday.",
    "race pace": "How fast a car is over MANY laps in a row on a heavy fuel "
        "load and wearing tyres — measured as the median of clean green-flag "
        "laps, corrected for fuel burn and track evolution. The thing that "
        "actually wins races, and often a different pecking order from "
        "one-lap pace.",
    "stint pace": "Race pace narrowed to one continuous run on one tyre "
        "compound — it separates 'this car is quick' from 'this car is quick "
        "on this particular tyre'.",
    "median lap": "The middle lap time of a run: half the laps are faster, "
        "half slower. Used instead of the average because one traffic lap or "
        "one mistake can't drag it around — the honest read of sustained pace.",
    "field median": "The middle car in the field that day. Expressing a gap "
        "against it (rather than against the fastest car) means one team's bad "
        "weekend doesn't shift everyone else's number — so a line that moves "
        "is a team that actually moved.",
    "session normalisation": "Correcting lap times for WHICH qualifying "
        "segment they were set in. The track rubbers in and speeds up through "
        "Q1→Q2→Q3, so comparing a Q1 lap directly against a Q3 pole flatters "
        "the pole. Normalising puts every car on the same track state.",
    "gap": "The time difference between two cars or laps, in seconds. A '0.3s "
        "gap' means one is three-tenths of a second ahead of the other.",
    "delta": "The running time difference versus a reference (a rival, or the "
        "driver's own best lap). Negative = ahead/faster, positive = behind.",
    "gap to the field": "A lap expressed as its distance from the typical lap "
        "of everyone on track that day — this cancels out a drying/rubbering "
        "track so laps from different moments can be compared fairly.",

    # — Tyres —
    "compound": "The rubber recipe of a tyre. Softer compounds grip more but "
        "wear out faster; harder ones last longer but are slower. Colour-coded.",
    "soft": "The fastest, quickest-wearing dry tyre (red-marked). Great for one "
        "flat-out lap, but fades soonest over a long run.",
    "medium": "The balanced dry tyre (yellow-marked) — a compromise between the "
        "soft's speed and the hard's longevity.",
    "hard": "The most durable, slowest dry tyre (white-marked). Slower per lap "
        "but can run far longer before it needs replacing.",
    "stint": "A continuous run of laps on one set of tyres, between two pit "
        "stops (or between the start/finish and a stop).",
    "degradation": "How much a tyre slows down as it wears and overheats during "
        "a stint. Often shortened to 'deg'. High deg = pace drops off quickly.",
    "pit stop": "A stop in the team's garage area where mechanics change all "
        "four tyres (and fix issues) in ~2-3 seconds. Costs ~20s of race time.",
    "tyre allocation": "The fixed set of tyres each driver is given for a "
        "weekend by the sole supplier — they must manage that limited stock.",

    # — Strategy —
    "undercut": "Pitting for fresh tyres *before* a rival, using the instant "
        "pace of new rubber to jump ahead of them once they later stop.",
    "overcut": "The opposite of an undercut: staying out on older tyres while a "
        "rival pits, banking on clear track to leapfrog them at your own stop.",
    "safety car": "A course car that leads the field slowly when the track is "
        "unsafe (a crash). It bunches everyone up and often reshuffles strategy.",
    "drs": "Drag Reduction System — a flap on the rear wing a chasing driver "
        "can open in marked zones for a straight-line speed boost, to aid "
        "overtaking.",
    "dirty air": "The turbulent air behind a car. It robs the following car of "
        "downforce and grip, making it hard to stay close enough to overtake.",
    "sandbagging": "Deliberately running slower than you can in practice, to "
        "hide your true pace from rivals. A tactic the dashboard tries to catch.",
    "quali sim": "A 'qualifying simulation' — a practice lap run in full "
        "qualifying trim (low fuel, fresh softs) to preview one-lap pace.",
    "dnf": "Did Not Finish — a car that retired from the race, usually from a "
        "crash or mechanical failure.",
    "fuel load": "How much fuel is on board. A full tank makes the car heavier "
        "and slower early in a race; it lightens and speeds up as fuel burns.",

    # — Championship —
    "points": "Scored by the top 10 finishers (25 for a win, down to 1 for "
        "10th). They accumulate all season to decide both championships.",
    "podium": "The top-three finish (1st, 2nd, 3rd) — the drivers who stand on "
        "the raised platform for trophies after the race.",
    "wdc": "World Drivers' Championship — the season-long title for the "
        "individual driver with the most points.",
    "wcc": "World Constructors' Championship — the season-long title for the "
        "team whose two cars together score the most points.",
}

# Aliases → canonical key, so common spellings/abbreviations resolve.
_ALIASES: dict[str, str] = {
    "deg": "degradation",
    "pu": "power unit",
    "pu penalty": "power unit penalty",
    "quali": "qualifying",
    "poles": "pole position",
    "pole": "pole position",
    "stints": "stint",
    "compounds": "compound",
    "undercutting": "undercut",
    "pit": "pit stop",
    "pit-stop": "pit stop",
    "pitstop": "pit stop",
    "one lap pace": "one-lap pace",
    "one-lap": "one-lap pace",
    "long run": "race pace",
    "long-run pace": "race pace",
    "race-pace": "race pace",
    "stint-pace": "stint pace",
    "median lap time": "median lap",
    "field-median": "field median",
    "constructors": "constructor",
    "teammates": "teammate",
    "power-unit": "power unit",
    "parc fermé": "parc ferme",
    "safety-car": "safety car",
    "did not finish": "dnf",
}


def _resolve(term: str) -> str | None:
    """Map a term (any case, spaces or hyphens) to its glossary definition."""
    key = term.strip().lower()
    key = _ALIASES.get(key, key)
    return GLOSSARY.get(key)


def gloss(term: str, display: str | None = None, placement: str = "bottom"):
    """Wrap `term` in a dotted-underline hover carrying its plain-English
    definition. `display` overrides the visible text (e.g. show "qualifying
    simulation" but key on "quali sim"). Returns [span, tooltip] — splice both
    into the parent's children, exactly like `tip()`.

    If the term isn't in the glossary the text is returned verbatim (as a bare
    span, no underline) so a typo degrades gracefully instead of crashing."""
    text = display if display is not None else term
    definition = _resolve(term)
    if definition is None:
        from dash import html
        return [html.Span(text)]
    return tip(text, definition, placement=placement,
               style={"cursor": "help", "borderBottom": "1px dotted currentColor",
                      "textDecoration": "none"})
