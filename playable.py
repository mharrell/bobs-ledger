#!/usr/bin/env python3
"""Out-of-play enforcement: what must never be recommended.

`meta/out_of_play.json` is the registry (official patch notes, validated against
the log-mined pool): tribes rotated out of the minion pool, and the cards
removed from it. This module is the single place the coach asks "can this still
be bought / played / built toward?".

## The one rule that matters (log-verified)

A card is out of play by TRIBE only when **every** tribe it belongs to is out.
The game's own pool dump proves it: post-36.6.1 (Naga rotated out) a game whose
allowed tribes included Demon still had `BG31_330 Ominous Seer` — a Demon/Naga
compound — sitting in the pool. Naga-only cards are gone; Naga-*touched* cards
are not. Treating a compound as out because one of its tribes is out would drop
playable cards, and treating a pure Naga card as in because "the tribe list
mentions Naga" would recommend cards that no longer exist in any shop.

## Roster cross-check

`meta/pool_roster.json` (see `pool_roster.py`) is what the game actually put in
the pool in the mined sessions. The two are deliberately separate: the registry
says what the patch notes removed, the roster says what was observed. `validate()`
reports every disagreement instead of hiding it, because a disagreement is
information — either the official list is wrong, the roster is under-covered
(one session only rolls 5 of the tribes), or a card name was reused for a new
card.

Usage:
  python playable.py                 # registry + roster validation report
  python playable.py --json          # machine-readable
"""
import argparse
import json
import os
import sys

from tribes import ALL_TRIBES, canon, normalize, parts

_HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(_HERE, "meta")
OUT_OF_PLAY = os.path.join(META, "out_of_play.json")
ROSTER = os.path.join(META, "pool_roster.json")


def load_out_of_play(path=OUT_OF_PLAY):
    """The registry document, or an empty one when the file is absent."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"patch": None, "tribes": {}, "cards": {}, "heroes": {}}


def load_roster(path=ROSTER):
    """The log-mined pool roster, or None when it has not been built."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class OutOfPlay:
    """Answer "is this still in play?" for cards, names and tribes.

    Lookup is by card id first (exact, patch-proof) and by name second (the
    patch notes speak in names, and some entries never had an id in the meta
    DB). A name-only match is reported with `by_name=True` so callers can be
    more careful with it.
    """

    def __init__(self, doc=None, roster=None):
        self.doc = doc if doc is not None else load_out_of_play()
        self.roster = roster if roster is not None else load_roster()
        self.tribes = {canon(t): v
                       for t, v in (self.doc.get("tribes") or {}).items()}
        self._by_id = {}
        self._by_name = {}
        for key, entry in (self.doc.get("cards") or {}).items():
            cid = entry.get("id") or (key if not key.startswith("name:") else None)
            if cid:
                self._by_id[cid] = entry
            name = (entry.get("name") or "").lower()
            if name:
                self._by_name.setdefault(name, entry)

    # -- tribes ------------------------------------------------------------
    def tribes_out(self):
        return set(self.tribes)

    def tribe_is_out(self, tribe):
        """Is EVERY part of `tribe` out of play? (see the module docstring)

        None/empty/unknown tribes are never out — fail open, and never let an
        unknown tribe read as "everything is out".
        """
        parts_ = [p for p in (tribe or [])] if isinstance(tribe, list) \
            else parts(tribe)
        if not parts_:
            return False
        out = self.tribes_out()
        if not out:
            return False
        return all(p in out for p in parts_)

    def tribe_note(self, tribe):
        """The registry's explanation for a tribe being out, or None."""
        for part in (parts(tribe) or []):
            entry = self.tribes.get(part)
            if entry:
                return f"{part} is out of play ({entry.get('reason')}, " \
                       f"{entry.get('patch')})"
        return None

    # -- cards -------------------------------------------------------------
    def entry(self, card_id=None, name=None):
        """The registry entry for a card, or None."""
        if card_id and card_id in self._by_id:
            return self._by_id[card_id]
        if name and name.strip().lower() in self._by_name:
            return self._by_name[name.strip().lower()]
        return None

    def reason(self, card_id=None, name=None, tribe=None):
        """Why this card/name/tribe is out of play, or None when it is in play.

        The single question the coach needs: a truthy answer is the text to show
        the player, so it reads as an explanation rather than a boolean code.
        """
        e = self.entry(card_id, name)
        if e:
            return (f"out of play: {e.get('name')} was "
                    f"{e.get('reason')} in {e.get('patch')}")
        if self.tribe_is_out(tribe):
            return self.tribe_note(tribe)
        return None

    def is_out(self, card_id=None, name=None, tribe=None):
        return self.reason(card_id, name, tribe) is not None

    def in_pool(self, card_id):
        """Was this card observed in the mined pool? None when no roster."""
        if not self.roster:
            return None
        return card_id in (self.roster.get("cards") or {})

    # -- bulk filtering ----------------------------------------------------
    def filter_cards(self, rows, idkey="id", namekey="name", tribekey="tribe"):
        """Split `rows` into (kept, dropped).

        `kept` is the playable rows; `dropped` is [(row, reason)] so the caller
        can show the player why a card vanished from the offering (the meta DB
        rows use id/name/tribe, which is the default key set).
        """
        kept, dropped = [], []
        for row in rows:
            ident = row.get(idkey) if isinstance(row, dict) else None
            nm = row.get(namekey) if isinstance(row, dict) else None
            tr = row.get(tribekey) if isinstance(row, dict) else None
            why = self.reason(ident, nm, tr)
            (dropped if why else kept).append(
                (row, why) if why else row)
        return kept, dropped

    def filter_comps(self, comps):
        """Drop comps that are out of play; return (playable, dropped).

        A comp is dropped when its own tribe is out of play, or when every core
        card is out of play (the same shape as `bans.filter_comps_by_available_tribes`:
        unknown/untribed cards fail open so a comp is never wrongly dropped).
        """
        playable, dropped = {}, []
        for slug, comp in comps.items():
            why = None
            if self.tribe_is_out(comp.get("tribe")):
                why = self.tribe_note(comp.get("tribe"))
            else:
                core = comp.get("core") or []
                if core:
                    reasons = [self.reason(cid) for cid in core]
                    if all(reasons):
                        why = reasons[0]
                else:
                    why = None
            if why:
                dropped.append((slug, why))
            else:
                playable[slug] = comp
        return playable, dropped


_ENFORCE_CACHE = None
_ENFORCE_MISS = object()


def enforcement():
    """The process-wide `OutOfPlay`, or None when enforcement is switched off.

    Set `HEARTH_OUT_OF_PLAY=0` to disable (same shape as `HEARTH_TELEMETRY=0`).
    That matters for `replay_review.py`: it replays an OLD log through the
    CURRENT meta, and a pre-rotation game legitimately contains Naga shops and
    Naga comps. Judging that game against today's out-of-play list would report
    phantom "coach bugs" — so a historical review turns enforcement off and
    reviews the game under the rules it was actually played with.
    """
    global _ENFORCE_CACHE
    if os.environ.get("HEARTH_OUT_OF_PLAY", "1").strip().lower() in (
            "0", "false", "no", "off"):
        return None
    if _ENFORCE_CACHE is None:
        _ENFORCE_CACHE = OutOfPlay()
    return _ENFORCE_CACHE


def out_of_play_reason(card_id=None, name=None, tribe=None):
    """Convenience wrapper: out-of-play text for a card, or None. Fail-open."""
    oop = enforcement()
    if oop is None:
        return None
    return oop.reason(card_id, name, tribe)


def validate(out_of_play=None, roster=None):
    """Cross-check the registry against the log-mined roster.

    Returns a list of human-readable conflict strings (empty = consistent).
    A conflict is NOT automatically a registry bug: it is a thing to go look at.
    """
    oop = out_of_play if isinstance(out_of_play, OutOfPlay) \
        else OutOfPlay(out_of_play, roster)
    roster = oop.roster
    problems = []
    if not roster:
        problems.append("no meta/pool_roster.json — run `python pool_roster.py "
                        "--apply` to build it (nothing to validate against)")
        return problems

    cards = roster.get("cards") or {}
    for cid, entry in (oop.doc.get("cards") or {}).items():
        ident = entry.get("id") or (None if cid.startswith("name:") else cid)
        if ident and ident in cards:
            problems.append(
                f"{ident} {entry.get('name')} is marked out of play "
                f"({entry.get('reason')}) but the roster has it in the pool "
                f"(tier {cards[ident].get('tier')}, {cards[ident].get('tribe')})")

    for tribe in oop.tribes_out():
        pure = [cid for cid, c in cards.items()
                if (c.get("tribe") or "") == tribe]
        if pure:
            problems.append(
                f"tribe {tribe} is marked out of play but {len(pure)} pure "
                f"{tribe} card(s) are in the pool: {sorted(pure)[:6]}")

    # Cards the patch says came back must not still be marked out.
    for hist in oop.doc.get("history") or []:
        for name in hist.get("returning") or []:
            entry = oop.entry(name=name)
            if entry:
                problems.append(
                    f"{name} is listed as returning in {hist.get('patch')} but "
                    f"is still marked out of play ({entry.get('reason')})")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    oop = OutOfPlay()
    doc = oop.doc
    problems = validate(oop)

    if args.json:
        print(json.dumps({
            "patch": doc.get("patch"),
            "tribes_out": sorted(oop.tribes_out()),
            "cards_out": len(doc.get("cards") or {}),
            "roster_patch": (oop.roster or {}).get("patch"),
            "roster_cards": len((oop.roster or {}).get("cards") or {}),
            "problems": problems,
        }, indent=2))
        return 0

    print(f"out-of-play registry: patch {doc.get('patch')} "
          f"(updated {doc.get('updated')})")
    print(f"  tribes out : {sorted(oop.tribes_out()) or '—'}")
    kinds = {}
    for entry in (doc.get("cards") or {}).values():
        kinds[entry.get("kind")] = kinds.get(entry.get("kind"), 0) + 1
    print(f"  cards out  : {len(doc.get('cards') or {})} "
          f"({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    for name, entry in sorted(oop.tribes.items()):
        print(f"    {name}: {entry.get('reason')} ({entry.get('patch')})")
    noid = [e.get("name") for e in (doc.get("cards") or {}).values()
            if not e.get("id")]
    if noid:
        print(f"  name-only entries (no card id): {noid}")

    roster = oop.roster
    if roster:
        print(f"\nroster: patch {roster.get('patch')}, "
              f"{len(roster.get('cards') or {})} pool minions from "
              f"{len(roster.get('sessions') or [])} session(s), "
              f"built {roster.get('built')}")
        print(f"  tribes in pool: {', '.join(roster.get('tribes_present') or [])}")
    else:
        print("\nroster: (none built yet)")

    print(f"\nvalidation: {len(problems)} conflict(s)")
    for p in problems:
        print(f"  ! {p}")
    if not problems:
        print("  registry and roster agree — every removed card is absent from "
              "the pool, and no out-of-play tribe has pure cards in it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
