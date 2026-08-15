#!/usr/bin/env python3
"""
verify_sets.py — independently recompute a day's sets.

The point of this file is that nobody has to trust the app, including the man who
built it. Take the arrival log from the Checkins sheet and the row the app wrote
into Formations, run them through here, and confirm the sets that appeared on the
pitch are the only sets that could have appeared.

Usage
-----
    python verify_sets.py arrivals.csv --rule spread --set-size 5 \
        --max-sets 8 --sets-on-pitch 2 --expect-seed 4f2a9c...

For a redraw, add the nonce and the latecomer window from the same Formations row:

    python verify_sets.py arrivals.csv --rule spread --nonce A1B2C3D4E5 \
        --late-window 10 --cutoff 2026-08-15T09:00:00.000Z --expect-seed ...

arrivals.csv needs two columns, in the form the Checkins sheet stores them:

    player_id,ts_iso
    PA1B2C3D4,2026-08-15T08:58:12.114Z
    P9F8E7D6C,2026-08-15T09:01:44.902Z

Export every arrival for the day, including the late ones. Give --cutoff and
--late-window and this tool applies the same filter the backend applied. Rows for
anyone who left or was taken off must be dropped first, as the backend drops them.

Every argument you need is written in the Formations row for that draw: rule,
nonce, late_window_min, set_size, max_sets and sets_on_pitch. That is the whole
point of recording them. You should never have to remember what the settings were.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone

MASK = 0xFFFFFFFF

Entry = tuple[str, str]


# ---------------------------------------------------------------------------
# The generator, ported bit for bit from Code.gs
# ---------------------------------------------------------------------------

def imul(a: int, b: int) -> int:
    """Math.imul: 32-bit multiply, keeping the low 32 bits."""
    return (a * b) & MASK


def mulberry32(seed: int):
    """Bit-for-bit port of the mulberry32 generator used in Code.gs."""
    a = seed & MASK

    def rnd() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & MASK
        t = imul(a ^ (a >> 15), (1 | a) & MASK)
        t = ((t + imul(t ^ (t >> 7), (61 | t) & MASK)) & MASK) ^ t
        return ((t ^ (t >> 14)) & MASK) / 4294967296.0

    return rnd


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_from(entries: list[Entry], nonce: str = "") -> tuple[str, str]:
    """
    Canonical string and seed.

    The canonical string is the arrival log and nothing else, unchanged since the
    first version, so every draw ever recorded still reproduces. A redraw nonce is
    stirred in afterwards rather than folded into the canonical string, for that
    same reason.
    """
    canonical = "|".join(f"{pid}@{ts}" for pid, ts in entries)
    base = sha(canonical)
    return canonical, (sha(f"{base}|nonce|{nonce}") if nonce else base)


def seeded_shuffle(items: list, seed_hex: str) -> list:
    """Fisher-Yates, descending, matching seededShuffle_ in Code.gs."""
    rnd = mulberry32(int(seed_hex[:8], 16))
    arr = list(items)
    for i in range(len(arr) - 1, 0, -1):
        j = int(rnd() * (i + 1))
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def arrival_order(row: Entry):
    """Timestamp first, player id as the tie-break. Same rule as the backend."""
    return (row[1], row[0])


# ---------------------------------------------------------------------------
# The three draw rules. These mirror DRAW_RULES in Code.gs exactly.
# Each takes the chosen players in arrival order and returns a list of sets.
# ---------------------------------------------------------------------------

def rule_banded(chosen: list[Entry], set_size: int, sets_on_pitch: int,
                seed_hex: str) -> list[list[Entry]]:
    """
    The original rule. Bands of set_size * sets_on_pitch, each shuffled whole.
    Frozen: every draw already in Formations was produced by this.
    """
    band = set_size * sets_on_pitch
    sets: list[list[Entry]] = []
    sets_done = 0
    for start in range(0, len(chosen), band):
        group = chosen[start:start + band]
        mixed = seeded_shuffle(group, sha(f"{seed_hex}|band{start // band}"))
        for i, p in enumerate(mixed):
            idx = sets_done + i // set_size
            while len(sets) <= idx:
                sets.append([])
            sets[idx].append(p)
        sets_done += -(-len(mixed) // set_size)
    return sets


def rule_spread(chosen: list[Entry], set_size: int, sets_on_pitch: int,
                seed_hex: str) -> list[list[Entry]]:
    """
    Bands unchanged, so arrival fairness is unchanged. Inside a band, arrivals are
    dealt in strata of sets_on_pitch, one player per set, so men who arrive one
    after another cannot share a set. A tail too short to fill sets_on_pitch sets
    is absorbed into the band before it. Slot order is shuffled separately, so
    slot 01 is not always an early arrival.
    """
    band = set_size * sets_on_pitch
    bounds = [[s, min(s + band, len(chosen))] for s in range(0, len(chosen), band)]
    # Never merge down to a single band: that would widen the OPENING band and let
    # an early arrival be dealt into a set that goes on second. Keeping three bands
    # confines the merge to the closing rotations.
    if len(bounds) > 2 and (bounds[-1][1] - bounds[-1][0]) // set_size < sets_on_pitch:
        bounds[-2][1] = bounds[-1][1]
        bounds.pop()

    sets: list[list[Entry]] = []
    for b, (lo, hi) in enumerate(bounds):
        group = chosen[lo:hi]
        k = -(-len(group) // set_size)               # sets this band produces
        base = len(sets)
        sets.extend([] for _ in range(k))
        stratum = 0
        for j in range(0, len(group), k):
            layer = seeded_shuffle(group[j:j + k], sha(f"{seed_hex}|spread{b}|s{stratum}"))
            for i, p in enumerate(layer):
                sets[base + i].append(p)
            stratum += 1
    return [seeded_shuffle(m, sha(f"{seed_hex}|slot{i}")) for i, m in enumerate(sets)]


def rule_open(chosen: list[Entry], set_size: int, sets_on_pitch: int,
              seed_hex: str) -> list[list[Entry]]:
    """
    The first sets_on_pitch arrivals are guaranteed a place in the sets that start.
    Everyone else is randomised across every set regardless of arrival time.
    """
    count = len(chosen) // set_size
    sets: list[list[Entry]] = [[] for _ in range(count)]
    head = min(sets_on_pitch, count)
    for h in range(head):
        sets[h].append(chosen[h])
    rest = seeded_shuffle(chosen[head:], sha(f"{seed_hex}|open"))
    k = 0
    for s in range(count):
        while len(sets[s]) < set_size:
            sets[s].append(rest[k])
            k += 1
    return sets


DRAW_RULES = {"banded": rule_banded, "spread": rule_spread, "open": rule_open}


# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime:
    t = s.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def form_sets(entries: list[Entry], set_size: int, max_sets: int,
              sets_on_pitch: int = 2, rule: str = "spread",
              nonce: str = "") -> dict:
    """Whether you play is settled by arrival order. The rule decides only the mix."""
    if rule not in DRAW_RULES:
        raise ValueError(f"{rule!r} is not a rule. Use one of: {', '.join(DRAW_RULES)}")

    pool = sorted(entries, key=arrival_order)
    capacity = set_size * max_sets
    playable = min((len(pool) // set_size) * set_size, capacity)

    if playable < set_size:
        return {"sets": {}, "waiting": pool, "seed": None, "canonical": None,
                "reason": f"only {len(pool)} present, a set needs {set_size}"}

    chosen, waiting = pool[:playable], pool[playable:]
    canonical, seed_hex = seed_from(chosen, nonce)
    drawn = DRAW_RULES[rule](chosen, set_size, sets_on_pitch, seed_hex)

    return {"sets": {i + 1: [pid for pid, _ in s] for i, s in enumerate(drawn)},
            "waiting": waiting, "seed": seed_hex, "canonical": canonical,
            "reason": None, "band": set_size * sets_on_pitch, "rule": rule}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Recompute a day's sets from the arrival log. "
                    "Every setting below is written in the Formations row for that draw.")
    ap.add_argument("csv_path", help="CSV with player_id,ts_iso")
    ap.add_argument("--rule", default="spread", choices=sorted(DRAW_RULES),
                    help="Which rule drew it. Read it off the Formations row.")
    ap.add_argument("--set-size", type=int, default=6)
    ap.add_argument("--max-sets", type=int, default=8)
    ap.add_argument("--sets-on-pitch", type=int, default=2)
    ap.add_argument("--nonce", default="",
                    help="Redraw nonce from the Formations row. Omit for a cutoff draw.")
    ap.add_argument("--late-window", default="0",
                    help="Minutes after the cutoff that were admitted, or 'all'. "
                         "Needs --cutoff to have any effect.")
    ap.add_argument("--cutoff", default="",
                    help="Cutoff instant in ISO form, so --late-window can be applied.")
    ap.add_argument("--expect-seed", help="Seed printed by the app, to compare against")
    args = ap.parse_args()

    with open(args.csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    try:
        entries = [(r["player_id"].strip(), r["ts_iso"].strip()) for r in rows]
    except KeyError:
        print("The CSV needs player_id and ts_iso columns.", file=sys.stderr)
        return 2

    dropped = 0
    if args.cutoff:
        cut = parse_iso(args.cutoff)
        win = args.late_window.strip().lower()
        if win in ("all", "everyone", "infinity"):
            limit = None
        else:
            if not win.isdigit():
                print("--late-window must be a whole number of minutes, or 'all'.",
                      file=sys.stderr)
                return 2
            limit = cut.timestamp() + int(win) * 60
        if limit is not None:
            before = len(entries)
            entries = [e for e in entries if parse_iso(e[1]).timestamp() < limit]
            dropped = before - len(entries)
    elif args.late_window not in ("0", ""):
        print("--late-window needs --cutoff to mean anything.", file=sys.stderr)
        return 2

    result = form_sets(entries, args.set_size, args.max_sets,
                       args.sets_on_pitch, args.rule, args.nonce)

    print(f"rule           {args.rule}")
    print(f"present        {len(entries)}" + (f"  ({dropped} outside the window)" if dropped else ""))
    print(f"set size       {args.set_size}   max sets {args.max_sets}   on pitch {args.sets_on_pitch}")
    if args.nonce:
        print(f"nonce          {args.nonce}")
    if result["reason"]:
        print(f"no draw        {result['reason']}")
        return 0

    print(f"seed           {result['seed']}")
    for set_no, members in sorted(result["sets"].items()):
        letter = chr(64 + set_no)
        print(f"set {letter}          {', '.join(members)}")
    if result["waiting"]:
        print(f"waiting        {', '.join(pid for pid, _ in result['waiting'])}")

    if args.expect_seed:
        match = result["seed"].startswith(args.expect_seed.strip().lower())
        print(f"seed match     {'yes' if match else 'NO — the log and the draw disagree'}")
        return 0 if match else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
