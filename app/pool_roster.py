#!/usr/bin/env python3
"""Mine the live Battlegrounds minion pool from the machine's own Power.logs.

`meta/minions.json` is a hand-refreshed snapshot (pasted from hsreplay, enriched
from hearthstonejson) and goes stale on every patch. But the game itself prints
an authoritative dump of its current pool: at the start of each game every
in-pool minion is created as a `FULL_ENTITY` block carrying

    ID=<n> CardID=<card_id>
      tag=TECH_LEVEL value=<n>            <- the tavern tier
      tag=ATK / tag=HEALTH value=<n>      <- base stats
      tag=CARDRACE value=<TRIBE>          <- one per tribe (compounds print several)
      tag=IS_BACON_POOL_MINION value=1    <- pool membership
      tag=BACON_SUBSET_<TRIBE> value=1    <- the per-card subset marker

So the pool can be read straight off the disk, offline, with no Cloudflare, no
hearthstonejson lag, and no manual paste — and it is *patch-proof*: new cards
show up the first time the player gets into a game on the new patch.

## Epochs (patch boundaries)

A patch changes the pool, so sessions are grouped into **content epochs**. The
newest session defines the current epoch: `_signature()` is the set of cards and
pure pool tribes it has that no older session has (on 2026-09-22 the signature
was the 20 new `ABERRATION` cards, which is exactly the 36.6.1 boundary). Any
older session whose pool contains a signature element is swept into the same
epoch; sessions before the boundary are history. A patch that only *removes*
cards and adds none yields an empty signature — then the epoch is just the
newest session and the removal shows up in the diff instead, which is reported
and must be read by a human.

## Coverage caveat (do not over-trust a small roster)

Each game only puts **5 of the ~10 tribes** in the pool (the rest are banned), so
one session observes only the tribes its lobbies happened to roll. A tribe
missing from the roster is therefore *untested*, not *absent* — absence has to
come from the official patch notes, which is what `meta/out_of_play.json` is
for. Mine more sessions to widen coverage; the roster grows monotonically within
an epoch.

Usage:
  python pool_roster.py                      # dry run: report the current epoch
  python pool_roster.py --apply              # write meta/pool_roster.json
  python pool_roster.py --apply --patch 36.6.1
  python pool_roster.py --all-sessions       # ignore epoch detection
  python pool_roster.py --diff               # show the diff against the saved roster
  python pool_roster.py --json               # dump the built roster
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

from tribes import ALL_MARKER, ALL_TRIBES, canon, parts, tribes_from_races

_HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER = os.path.join(_HERE, "meta", "pool_roster.json")
DEFAULT_LOG_DIR = r"C:\Program Files (x86)\Hearthstone\Logs"

#: entityName carries spaces ("Wrath Weaver"), so capture up to " id=<digits>".
NAME_RE = re.compile(
    r"entityName=(.+?) id=\d+ zone=\w+ zonePos=\d+ cardId=([A-Za-z0-9_]+)")
SEED_RE = re.compile(r"GAME_SEED value=(\d+)")
CARDID_RE = re.compile(r"CardID=([A-Za-z0-9_]+)")
CARD_TYPE_RE = re.compile(r"tag=CARDTYPE value=MINION")
TRIPLE_ID_RE = re.compile(r"tag=BACON_TRIPLE_UPGRADE_MINION_ID value=\d+")
RACE_RE = re.compile(r"tag=CARDRACE value=([A-Z]+)")
_TAG_RES = {
    "tier": re.compile(r"tag=TECH_LEVEL value=(-?\d+)"),
    "attack": re.compile(r"tag=ATK value=(-?\d+)"),
    "health": re.compile(r"tag=HEALTH value=(-?\d+)"),
}


def scan_log(path):
    """One Power.log -> {"games": int, "cards": {cid: card}, "names": {cid: name}}.

    Pool membership is read from the entity's own creation block (the run-walk
    mirrors `bans.bans_from_log`, which is validated by the live 5/5 ban gate):
    a `FULL_ENTITY`/`SHOW_ENTITY` header opens a segment, `tag=` lines join it,
    and any other line closes the run. Back-to-back pool definitions arrive with
    no separator, so each header starts its own segment.

    Stats and tier are taken from the FIRST segment that carries
    `IS_BACON_POOL_MINION` for a card id — that is the pool definition, before
    any buffs or board TAG_CHANGEs — so a later buffed copy can't overwrite the
    base stats.
    """
    names = {}
    cards = {}
    created = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    games = sum(1 for line in lines
                if "CREATE_GAME" in line and "GameState.DebugPrintPower" in line)
    for line in lines:
        for nm, cid in NAME_RE.findall(line):
            names.setdefault(cid, nm.strip())

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if "SHOW_ENTITY" not in line and "FULL_ENTITY" not in line:
            i += 1
            continue
        run = []
        j = i
        while j < n and ("tag=" in lines[j] or "SHOW_ENTITY" in lines[j]
                         or "FULL_ENTITY" in lines[j]):
            run.append(lines[j])
            j += 1

        segments = []
        cur_cid, cur_text = None, []
        for bl in run:
            if "FULL_ENTITY" in bl or "SHOW_ENTITY" in bl:
                if cur_cid is not None:
                    segments.append((cur_cid, cur_text))
                m = CARDID_RE.search(bl)
                cur_cid = m.group(1) if m else None
                cur_text = [bl]
            else:
                cur_text.append(bl)
        if cur_cid is not None:
            segments.append((cur_cid, cur_text))

        for cid, text in segments:
            body = "\n".join(text)
            if cid is None:
                continue
            # IS_BACON_POOL_MINION also rides on non-minion entities that the
            # pool machinery creates (tokens, enchantments, spell entities:
            # BG34_170e Volumized, BG31_890t Way of the Mage). They are not
            # buyable cards and they polluted the roster with tier-0 "minions"
            # until CARDTYPE was required.
            if not CARD_TYPE_RE.search(body):
                continue
            # Two admission signals, recorded SEPARATELY on purpose.
            #
            # `IS_BACON_POOL_MINION` is the pool. It is the authoritative answer
            # to "what is in the shop this patch" and it is what `cards` holds.
            #
            # `BACON_TRIPLE_UPGRADE_MINION_ID` (a minion's golden/triple-reward
            # id) catches a real buyable card the pool tag MISSES: 36.6.1's Dark
            # Paradox never carries the pool tag, because the game picks one of
            # its variants per game and materialises it through an evolution
            # creator (`CREATOR`, `AURA value=1`, `BACON_EVOLUTION_CARD_ID`).
            # But the same tag also rides on summoned TOKENS (Beetle, Aberrant
            # Tentacle, Microbot, Half-Shell), so a triple-only entity is NOT
            # proof of a pool minion and must not be mixed into `cards` — that
            # is how the roster grew tier-0 "minions" the first time round. It
            # goes in `created`, which the coach reads as "known card, not
            # necessarily buyable", and which a human reconciles.
            if cid in cards or cid in created:
                continue  # first (unbuffed) definition wins
            pooled = "BACON_POOL_MINION" in body
            if not pooled and not TRIPLE_ID_RE.search(body):
                continue
            races = [r for r in RACE_RE.findall(body) if r in ALL_TRIBES]
            card = {"races": sorted(set(races)),
                    "pool_src": "pool" if pooled else "triple"}
            for key, rx in _TAG_RES.items():
                m = rx.search(body)
                if m:
                    card[key] = int(m.group(1))
            (cards if pooled else created)[cid] = card
        i = j

    return {"games": games, "cards": cards, "created": created, "names": names}


def load_sessions(log_dir=DEFAULT_LOG_DIR):
    """All session logs on disk, oldest first, with their scan result."""
    out = []
    for path in glob.glob(os.path.join(log_dir, "Hearthstone_*", "Power.log")):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        out.append({"name": os.path.basename(os.path.dirname(path)),
                    "path": path, "mtime": mtime})
    out.sort(key=lambda s: s["mtime"])
    for s in out:
        s["scan"] = scan_log(s["path"])
    return out


def _signature(newest, older):
    """Cards + pure pool tribes the newest session has that no older one has."""
    old_cards = set()
    old_tribes = set()
    for s in older:
        old_cards |= set(s["scan"]["cards"])
        old_tribes |= pure_tribes(s["scan"]["cards"])
    new_cards = set(newest["scan"]["cards"]) - old_cards
    new_tribes = pure_tribes(newest["scan"]["cards"]) - old_tribes
    return new_cards, new_tribes


def pure_tribes(cards):
    """Tribes that appear as a PURE (single-tribe) pool card in `cards`.

    Keys off the resolved `tribe` field when present and falls back to the raw
    log races (a scan result has no `tribe` yet). Using the raw races was wrong
    after meta enrichment: `BG31_330 Ominous Seer` prints `NAGA` alone but is
    Demon/Naga, so a race-based reading kept reporting Naga as a tribe with a
    *pure* card in the pool — the exact thing rotation removes.
    """
    out = set()
    for card in cards.values():
        tribe = card.get("tribe") if "tribe" in card else \
            tribes_from_races(card.get("races") or [])
        p = parts(tribe)
        if len(p) == 1:
            out.add(p[0])
    return out


def current_epoch(sessions):
    """(epoch_sessions, signature) for the newest content generation.

    See the module docstring: the newest session's signature is what it has that
    no older session has; every older session holding a signature element joins
    the epoch. With an empty signature (a removal-only patch) the epoch is the
    newest session alone.
    """
    if not sessions:
        return [], (set(), set())
    newest, older = sessions[-1], sessions[:-1]
    sig_cards, sig_tribes = _signature(newest, older)
    if not sig_cards and not sig_tribes:
        return [newest], (sig_cards, sig_tribes)
    epoch = [s for s in sessions
             if s is newest
             or (set(s["scan"]["cards"]) & sig_cards)
             or (pure_tribes(s["scan"]["cards"]) & sig_tribes)]
    return epoch, (sig_cards, sig_tribes)


def enrich_from_meta(cards, meta_path=None):
    """Union each roster card's tribes with the curated meta DB's tribe.

    The log's pool block prints the card's own `CARDRACE` tags, but a COMPOUND
    card can reveal only one of them: `BG31_330 Ominous Seer` prints `NAGA`
    alone in the post-36.6.1 log even though it is Demon/Naga — which made the
    roster claim a *pure Naga* card sat in a pool Naga had been rotated out of,
    and tripped the out-of-play validator. `meta/minions.json` already carries
    the union across every log ever mined (`tribe_src: "log"`), so unioning is
    free, offline, and matches how the repo already resolves tribes
    (`parse_minions.refresh_tribes`).

    Union, never replace: a brand-new card is simply absent from the meta DB
    and keeps the log's answer, and a genuinely narrowed card is left for the
    human-audited `meta/tribe_overrides.json` to settle.

    Returns the number of cards whose tribe was widened.
    """
    path = meta_path or os.path.join(_HERE, "meta", "minions.json")
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return 0
    known = {m.get("id"): m.get("tribe") for m in meta if m.get("id")}
    widened = 0
    for cid, card in cards.items():
        meta_tribe = known.get(cid)
        if not meta_tribe:
            continue
        if meta_tribe == ALL_MARKER:
            # An Amalgam counts as EVERY tribe. Never expand it into a compound
            # list — the log prints no CARDRACE for some of them, and a compound
            # spelling would silently stop it matching every tribe fit term.
            if card.get("tribe") != ALL_MARKER:
                card["tribe"] = ALL_MARKER
                card["races"] = sorted(set(card.get("races") or []) | {"ALL"})
                card["tribe_src"] = "log+meta"
                widened += 1
            continue
        log_parts = set(parts(card.get("tribe")))
        meta_parts = set(parts(meta_tribe))
        if meta_parts - log_parts:
            card["tribe"] = "/".join(sorted(log_parts | meta_parts))
            card["tribe_src"] = "log+meta"
            widened += 1
    return widened


def build_roster(epoch, patch=None):
    """Merge epoch sessions into the roster document.

    Two card sets come out, deliberately unmixed (see `scan_log`):

    - `cards` — the POOL: what the game put in the shop this patch.
    - `created` — minions the game materialised through a creator/evolution
      that the pool tag misses. It contains real cards Dark Paradox-style AND
      summoned tokens, so it is a lead list for a human, never a pool.

    Cards that are already in `cards` are never re-listed in `created`.
    """
    cards = {}
    created = {}
    names = {}
    for s in epoch:
        names.update({k: v for k, v in s["scan"]["names"].items()
                      if k not in names})
        for cid, card in s["scan"]["cards"].items():
            if cid in cards:
                continue
            cards[cid] = card
        for cid, card in s["scan"].get("created", {}).items():
            if cid in created or cid in cards:
                continue
            created[cid] = card
    for cid, card in cards.items():
        card["name"] = names.get(cid)
        card["tribe"] = tribes_from_races(card.get("races") or [])
        card["tribe_src"] = "log" if card["tribe"] else None
    for cid, card in created.items():
        # Names/tier only. No tribe resolution and no meta enrichment: these
        # are a lead list, and dressing them up as curated cards is exactly how
        # a token gets mistaken for a pool minion.
        card["name"] = names.get(cid)
    widened = enrich_from_meta(cards)
    return {
        "patch": patch,
        "built": datetime.date.today().isoformat(),
        "sessions": [s["name"] for s in epoch],
        "games": sum(s["scan"]["games"] for s in epoch),
        "tribes_present": sorted(pure_tribes(cards)),
        "tribes_widened_from_meta": widened,
        "cards": dict(sorted(cards.items())),
        "created": dict(sorted(created.items())),
    }


def diff_rosters(old, new):
    """(added, removed, changed) card ids between two roster documents."""
    o = (old or {}).get("cards") or {}
    n = (new or {}).get("cards") or {}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = []
    for cid in sorted(set(o) & set(n)):
        fields = [f for f in ("tier", "attack", "health", "tribe")
                  if o[cid].get(f) != n[cid].get(f)]
        if fields:
            changed.append((cid, fields, o[cid], n[cid]))
    return added, removed, changed


def load_roster(path=ROSTER):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _label(cid, roster):
    card = (roster.get("cards") or {}).get(cid) or {}
    return f"{cid} {card.get('name') or '?'} (tier {card.get('tier')})"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs", default=DEFAULT_LOG_DIR)
    ap.add_argument("--patch", default=None,
                    help="patch label to stamp on the roster (e.g. 36.6.1)")
    ap.add_argument("--all-sessions", action="store_true",
                    help="skip epoch detection; mine every session on disk")
    ap.add_argument("--sessions", type=int, default=None, metavar="N",
                    help="union the newest N sessions (widen tribe coverage); "
                         "refuses to write if the union pulls an out-of-play "
                         "card back in, unless --force")
    ap.add_argument("--force", action="store_true",
                    help="with --sessions: write even when the union contains "
                         "cards the out-of-play registry says are removed")
    ap.add_argument("--apply", action="store_true",
                    help="write meta/pool_roster.json (default: dry run)")
    ap.add_argument("--diff", action="store_true",
                    help="diff the built roster against the saved one")
    ap.add_argument("--json", action="store_true", help="dump the built roster")
    args = ap.parse_args()

    sessions = load_sessions(args.logs)
    if not sessions:
        print(f"no Power.log sessions under {args.logs}")
        return 1

    if args.all_sessions:
        epoch, sig = sessions, (set(), set())
    elif args.sessions:
        epoch, sig = sessions[-args.sessions:], (set(), set())
    else:
        epoch, sig = current_epoch(sessions)

    print(f"{len(sessions)} session(s) on disk")
    for s in sessions:
        mark = "*" if s in epoch else " "
        print(f" {mark} {s['name']}  games={s['scan']['games']:2}  "
              f"pool_cards={len(s['scan']['cards']):3}")
    if not args.all_sessions:
        sig_cards, sig_tribes = sig
        print(f"\ncurrent epoch: {len(epoch)} session(s), signature "
              f"{len(sig_cards)} card(s) + {sorted(sig_tribes)} tribe(s)")
        if sig_cards:
            names = {}
            for s in epoch:
                names.update(s["scan"]["names"])
            for cid in sorted(sig_cards)[:8]:
                print(f"    new: {cid} {names.get(cid) or '?'}")
            if len(sig_cards) > 8:
                print(f"    ... and {len(sig_cards) - 8} more")
        if not sig_cards and not sig_tribes:
            print("    (no signature — newest session only; a removal-only "
                  "patch shows up as roster removals, review the diff)")

    roster = build_roster(epoch, args.patch)
    print(f"\nroster: {len(roster['cards'])} pool minions, "
          f"{roster['games']} game(s)")
    tiers = {}
    for card in roster["cards"].values():
        tiers[card.get("tier")] = tiers.get(card.get("tier"), 0) + 1
    print("  by tier: " + ", ".join(
        f"{k}:{v}" for k, v in sorted(tiers.items(),
                                      key=lambda kv: (kv[0] is None, kv[0]))))
    print("  tribes seen in pool: " + ", ".join(roster["tribes_present"]))
    untribed = [c for c, v in roster["cards"].items() if not v.get("tribe")]
    print(f"  untribed (neutral): {len(untribed)}")
    created = roster.get("created") or {}
    if created:
        print(f"  created by a creator/evolution (pool tag MISSED — leads, "
              f"not pool members): {len(created)}")
        for cid, c in list(created.items())[:12]:
            print(f"      {cid} {c.get('name') or '?'} (tier {c.get('tier')})")
    noname = [c for c, v in roster["cards"].items() if not v.get("name")]
    if noname:
        print(f"  WARN {len(noname)} card(s) with no name observed: "
              f"{noname[:6]}")

    saved = load_roster()
    if saved:
        added, removed, changed = diff_rosters(saved, roster)
        print(f"\nvs saved roster (patch {saved.get('patch')}, "
              f"built {saved.get('built')}): "
              f"+{len(added)} / -{len(removed)} / ~{len(changed)}")
        for cid in added[:12]:
            print(f"  + {_label(cid, roster)}")
        for cid in removed[:12]:
            print(f"  - {_label(cid, saved)}")
        for cid, fields, o, n in changed[:12]:
            print(f"  ~ {cid} {n.get('name') or o.get('name') or '?'}: "
                  + ", ".join(f"{f} {o.get(f)}->{n.get(f)}" for f in fields))
        if not (added or removed or changed):
            print("  (identical)")
    else:
        print("\nno saved roster yet")

    if args.json:
        print(json.dumps(roster, indent=2, ensure_ascii=False))

    stale = _out_of_play_cards(roster)
    if stale:
        print(f"\nWARN {len(stale)} card(s) in this roster are marked OUT OF "
              f"PLAY by meta/out_of_play.json:")
        for cid in stale[:10]:
            print(f"    {_label(cid, roster)}")
        if len(stale) > 10:
            print(f"    ... and {len(stale) - 10} more")
        print("  The epoch you mined probably straddles a patch boundary "
              "(an older session's pool dragged removed cards back in). Use the "
              "auto-detected epoch, or lower --sessions.")

    if args.apply and stale and not args.force:
        print("\nrefusing to write — pass --force to write anyway")
        return 1
    if args.apply:
        with open(ROSTER, "w", encoding="utf-8") as f:
            json.dump(roster, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"\nwrote {ROSTER}")
    else:
        print("\ndry run — pass --apply to write")
    return 0


def _out_of_play_cards(roster):
    """Roster card ids that `meta/out_of_play.json` says are removed.

    The guard for explicit multi-session mining: widening coverage with
    `--sessions N` can silently cross a patch boundary, and the cardinal sin
    there is resurrecting a removed card into the "current" pool. Fail-open if
    the registry or playable.py is unavailable — this is a safety net, not a
    dependency.
    """
    try:
        import playable
    except ImportError:  # pragma: no cover
        return []
    doc = playable.load_out_of_play()
    removed = {e.get("id") for e in (doc.get("cards") or {}).values()
               if e.get("id")}
    return sorted(removed & set(roster.get("cards") or {}))


if __name__ == "__main__":
    sys.exit(main())
