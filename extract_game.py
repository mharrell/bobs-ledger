"""Extract per-game Battlegrounds data from a Power.log (stdlib only, no hslog).

hslog's EntityTreeExporter is built for constructed (2 players) and mangles
Battlegrounds' 8-player structure (it collapses all 7 opponents into the
"spectator" player). So we parse the raw log directly.

For each game this extracts all 8 players: hero card, hero name, account name
(friendly only), final placement, and final tech level. It also extracts the
move stream (purchases, sells, tier upgrades).

Usage:
    python extract_game.py <Power.log> [--games N] [--moves] [--compare]

The raw-log patterns we rely on (all from GameState.DebugPrintPower lines):

    TAG_CHANGE Entity=[entityName=<hero> id=<id> ... cardId=<card> player=<p>]
              tag=PLAYER_LEADERBOARD_PLACE value=<n>     # placement, last-wins
    TAG_CHANGE Entity=[... id=<id> ...] tag=PLAYER_TECH_LEVEL value=<n>  # tier
    TAG_CHANGE Entity=<account> tag=HERO_ENTITY value=<id>  # name -> hero (friendly)
    FULL_ENTITY - Creating ID=<id> CardID=<card>          # entity creation
"""
import re
import sys

# TAG_CHANGE with a full Entity=[...] block (has cardId + player).
ENTITY_TAG = re.compile(
    r"Entity=\[entityName=(.*?) id=(\d+) .*? cardId=(\w+) player=(\d+)\] "
    r"tag=(\w+) value=(\w+)"
)
# Entity=<account> tag=HERO_ENTITY value=<id>  (friendly name -> hero entity)
NAME_HERO = re.compile(r"Entity=([^ ]+) tag=HERO_ENTITY value=(\d+)")
# FULL_ENTITY - Creating ID=<id> CardID=<card>. CardID may be empty (enchantment
# entities are created with no card id and revealed later via SHOW_ENTITY), so
# \w* not \w+ — otherwise the block's tag lines get attributed to the previous
# entity.
FULL_ENTITY = re.compile(r"FULL_ENTITY - Creating ID=(\d+) CardID=(\w*)")
# Entity=<id> tag=ZONE value=<zone>  (plain form, no cardId/player)
ZONE_PLAIN = re.compile(r"Entity=(\d+) tag=ZONE value=(\w+)")

# A real hero card: BGxx_HERO_xxx or TB_BaconShop_HERO_xx, optionally with a
# _SKIN_* suffix (cosmetic variant, e.g. TB_BaconShop_HERO_70_SKIN_I). Excludes
# hero powers (_p/_p2/_pe) and placeholders (_PH, _KelThuzad).
HERO_CARD = re.compile(r"^(?:BG\d+_HERO_\d+|TB_BaconShop_HERO_\d+)(?:_SKIN_\w+)?$")

# A real minion/spell card (excludes internal entities like TB_BaconShop_* and
# BG30_Trinket_*).
MINION = re.compile(r"^(?:BG\d+_\d+|BGS_\d+|BG\d+_GS\d+)$")

# Log line timestamp, e.g. "D 21:41:45.4076558 ...".
TIMESTAMP = re.compile(r"^D (\d+:\d+:\d+\.\d+)")

# A tag line inside a FULL_ENTITY block, e.g. "tag=CONTROLLER value=13".
FULL_TAG = re.compile(r"tag=(\w+) value=(\w+)")


def split_game_chunks(lines):
    """Yield (start, end) line-index ranges, one per game.

    Game boundaries are CREATE_GAME lines from GameState.DebugPrintPower()
    (the duplicate PowerTaskList entries are ignored).
    """
    boundaries = [
        i for i, line in enumerate(lines)
        if "CREATE_GAME" in line and "GameState.DebugPrintPower" in line
    ]
    if not boundaries:
        return
    ends = boundaries[1:] + [len(lines)]
    for start, end in zip(boundaries, ends):
        yield start, end


def extract_game(lines):
    card = {}        # entity id -> card_id
    player = {}      # entity id -> player number (5=friendly, 13=spectator)
    zone = {}        # entity id -> zone name
    place = {}       # entity id -> final placement (last value wins)
    tech = {}        # entity id -> final tech level (last value wins)
    hero_name = {}   # entity id -> entityName (hero display name)
    hero_entity_tags = {}  # account name -> list of hero entity ids (HERO_ENTITY)

    for line in lines:
        m = ENTITY_TAG.search(line)
        if m:
            ename, eid, cid, p, tag, value = m.groups()
            eid = int(eid)
            p = int(p)
            card[eid] = cid
            player[eid] = p
            if ename:
                hero_name[eid] = ename
            if tag == "PLAYER_LEADERBOARD_PLACE":
                place[eid] = int(value)
            elif tag == "PLAYER_TECH_LEVEL":
                tech[eid] = int(value)
            elif tag == "ZONE":
                zone[eid] = value
            continue

        m = NAME_HERO.search(line)
        if m:
            name, eid = m.groups()
            hero_entity_tags.setdefault(name, []).append(int(eid))
            continue

        m = FULL_ENTITY.search(line)
        if m:
            eid, cid = m.groups()
            card[int(eid)] = cid
            continue

        m = ZONE_PLAIN.search(line)
        if m:
            zone[int(m.group(1))] = m.group(2)

    # Heroes = entities with a placement and a hero card id. The friendly hero
    # is re-created near the end of the game (for the final leaderboard) with a
    # fresh, higher entity id and a stale placement; keep the lowest entity id
    # (the original, live hero) per card id.
    heroes_by_card = {}
    for eid, p in place.items():
        cid = card.get(eid, "")
        if not HERO_CARD.match(cid):
            continue
        if cid not in heroes_by_card or eid < heroes_by_card[cid]["id"]:
            heroes_by_card[cid] = {
                "id": eid,
                "card": cid,
                "player": player.get(eid),
                "place": p,
                "tech": tech.get(eid),
                "hero_name": hero_name.get(eid),
            }

    heroes = sorted(heroes_by_card.values(), key=lambda h: h["place"])

    # Account name -> hero card. HERO_ENTITY points at each player's hero, but
    # also at the shared spectator hero (TB_BaconShop_HERO_PH, id varies per
    # game) and at re-created heroes. Resolve by matching the entity's card id
    # against the 8 real heroes.
    account = {}
    for name, eids in hero_entity_tags.items():
        for eid in eids:
            cid = card.get(eid, "")
            if cid in heroes_by_card:
                account[name] = cid
                break

    return {"heroes": heroes, "account": account}


def extract_moves(lines, friendly_player):
    """Extract the move stream.

    Returns (tier_reached, buys, sells):
      - tier_reached: hero card -> {tier: first timestamp} for all 8 players.
      - buys: list of (timestamp, minion card) for the friendly player.
      - sells: list of (timestamp, minion card) for the friendly player.

    The 7 opponents all share the "spectator" player number, so their
    individual buys/sells are not recoverable from the log; only tier timing is
    per-hero. Buys/sells are therefore friendly-only. Sells are approximated by
    a PLAY->GRAVEYARD zone change with DAMAGE=0 (a sold minion is undamaged; a
    combat death is not), which still double-counts a few deathrattle-resummon
    edge cases.
    """
    tier_reached = {}  # hero card -> {tier: timestamp}
    buys = []          # (timestamp, minion card)
    sells = []         # (timestamp, minion card)

    controller = {}     # entity id -> controller
    zone = {}           # entity id -> zone
    damage = {}         # entity id -> damage taken (0 = undamaged)
    current_entity = None  # entity id of the FULL_ENTITY block being read

    for line in lines:
        ts = TIMESTAMP.match(line)
        t = ts.group(1) if ts else "?"

        # TAG_CHANGE with a full Entity=[...] block.
        m = ENTITY_TAG.search(line)
        if m:
            ename, eid, cid, p, tag, value = m.groups()
            eid = int(eid)
            if tag == "PLAYER_TECH_LEVEL":
                if HERO_CARD.match(cid):
                    tier = int(value)
                    if tier >= 1:
                        tier_reached.setdefault(cid, {}).setdefault(tier, t)
            elif tag == "CONTROLLER":
                old = controller.get(eid)
                new = int(value)
                if old is not None and old != new and new == friendly_player:
                    if MINION.match(cid):
                        buys.append((t, cid))
                controller[eid] = new
            elif tag == "DAMAGE":
                damage[eid] = int(value)
            elif tag == "ZONE":
                old_zone = zone.get(eid)
                new_zone = value
                if old_zone == "PLAY" and new_zone == "GRAVEYARD":
                    # A sell leaves the minion undamaged; a combat death does not.
                    if (MINION.match(cid)
                            and controller.get(eid) == friendly_player
                            and damage.get(eid, 0) == 0):
                        sells.append((t, cid))
                zone[eid] = new_zone
            continue

        # FULL_ENTITY "Creating" line: start a new entity block.
        m = FULL_ENTITY.search(line)
        if m:
            current_entity = int(m.group(1))
            continue

        # FULL_ENTITY tag line (indented, no Entity=[...]): capture the initial
        # controller/zone so a later CONTROLLER change reads as a buy.
        if "Entity=[" not in line:
            m = FULL_TAG.search(line)
            if m and current_entity is not None:
                tag, value = m.groups()
                if tag == "CONTROLLER":
                    controller[current_entity] = int(value)
                elif tag == "ZONE":
                    zone[current_entity] = value

    return tier_reached, buys, sells


def _fmt_hero(h):
    name = h["hero_name"] or "?"
    tech = h["tech"] if h["tech"] is not None else "?"
    return (
        f"  place={h['place']} hero={h['card']} name={name!r} "
        f"tech={tech} player={h['player']}"
    )


def _fmt_tier_timing(hero, tier_reached):
    """Format a hero's tier timing as 't2=.. t3=.. ...' (seconds precision)."""
    tiers = tier_reached.get(hero["card"], {})
    parts = []
    for tier in sorted(tiers):
        parts.append(f"t{tier}={tiers[tier].split('.')[0]}")
    return " ".join(parts) if parts else "(no tier data)"


def _friendly_player(heroes):
    """The friendly player number: the one with the fewest heroes (1 vs 7).

    Returns None if no heroes are parsed yet (e.g. the live coach analyzing a
    game's very first lines, or end-of-game cleanup) — so callers don't crash on
    an empty selection.
    """
    from collections import Counter
    counts = Counter(h["player"] for h in heroes)
    if not counts:
        return None
    return min(counts, key=lambda p: counts[p])


def main():
    if len(sys.argv) < 2:
        print("usage: python extract_game.py <Power.log> [--games N] [--moves] [--compare]")
        return 1
    log_path = sys.argv[1]
    limit = None
    show_moves = "--moves" in sys.argv
    show_compare = "--compare" in sys.argv
    if "--games" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--games") + 1])

    print(f"Parsing {log_path} ...", file=sys.stderr)
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    chunks = list(split_game_chunks(lines))
    print(f"Games found: {len(chunks)}", file=sys.stderr)
    if limit:
        chunks = chunks[:limit]

    for idx, (start, end) in enumerate(chunks, 1):
        chunk = lines[start:end]
        game = extract_game(chunk)
        print(f"\n=== Game {idx} ===")
        for h in game["heroes"]:
            print(_fmt_hero(h))
        if game["account"]:
            print("  account -> hero:")
            for name, cid in game["account"].items():
                print(f"    {name!r} -> {cid}")

        if show_moves or show_compare:
            friendly = _friendly_player(game["heroes"])
            tier_reached, buys, sells = extract_moves(chunk, friendly)
            if show_moves:
                print("\n  Tier timing:")
                for h in game["heroes"]:
                    print(f"    place={h['place']} {h['hero_name']}: "
                          f"{_fmt_tier_timing(h, tier_reached)}")
                print(f"\n  Friendly moves (player={friendly}):")
                print(f"    buys ({len(buys)}): "
                      + ", ".join(f"{c}@{t.split('.')[0]}" for t, c in buys))
                print(f"    sells ({len(sells)}): "
                      + ", ".join(f"{c}@{t.split('.')[0]}" for t, c in sells))
            if show_compare:
                winner = game["heroes"][0]   # sorted by place ascending
                loser = game["heroes"][-1]
                print("\n  First vs last:")
                print(f"    Winner (place=1): {winner['hero_name']} ({winner['card']})")
                print(f"      {_fmt_tier_timing(winner, tier_reached)}")
                print(f"    Loser (place=8): {loser['hero_name']} ({loser['card']})")
                print(f"      {_fmt_tier_timing(loser, tier_reached)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
