#!/usr/bin/env python3
"""Parse a Power.log into the friendly player's per-turn actions.

Extracts, broken down by turn:
  - buys:     minions that entered the player's hand (from the tavern)
  - sells:    minions removed from the player's board (not combat)
  - triples:  minions combined into a golden (BACON_TRIPLED_BASE_MINION_ID)
  - refreshes: tavern board replacements

Usage:
    python player_actions.py <Power.log> [--games N]
"""
import re
import sys

from extract_game import split_game_chunks, extract_game, _friendly_player

# A real board minion (excludes enchantments, golden _G, trinkets).
MINION_ONLY = re.compile(r"^(?:BG\d+_\d+|BGS_\d+|BG_[A-Z]+_\d+)$")

# [Entity|mainEntity]=[entityName=X id=N zone=Z zonePos=P cardId=C player=P]
# mainEntity= appears in DebugPrintOptions (shop offers / hand display).
ENTITY = re.compile(
    r"(?:Entity|mainEntity)=\[entityName=(\S+) id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\w+) player=(\d+)"
)
# The real turn counter is NUM_TURNS_IN_PLAY (TURN is a different, unreliable
# counter). In Duos the game re-enters MAIN_READY with alternating values, so we
# take the max of consecutive values as the turn.
TURN = re.compile(r"Entity=GameEntity tag=NUM_TURNS_IN_PLAY value=(\d+)")
TRIPLE = re.compile(r"tag=BACON_TRIPLED_BASE_MINION_ID value=(\d+)")
# STEP marks the game phase. The shop phase (MAIN_ACTION) is where the player
# acts (buy/sell/refresh/upgrade/hero-power); MAIN_COMBAT is automatic.
STEP_RE = re.compile(r"Entity=GameEntity tag=STEP value=(\w+)")
SHOP_STEPS = {"MAIN_ACTION", "MAIN_START", "MAIN_READY", "MAIN_START_TRIGGERS"}
# A refresh is a BLOCK_START on the Refresh button (TB_BaconShop_8p_Reroll_Button).
REFRESH = re.compile(r"BLOCK_START BlockType=TRIGGER Entity=\[entityName=Refresh ")


def parse_actions(chunk, friendly):
    """Return a list of per-turn action dicts for the friendly player."""
    turns = []          # list of {turn, buys, sells, triples, refreshes}
    cur_turn = None
    step = None
    card = {}           # entity id -> card id
    player = {}         # entity id -> player number
    zone = {}           # entity id -> zone
    seen_triples = set()    # (entity, base_id) already counted

    def new_turn(n):
        return {"turn": n, "buys": [], "sells": [], "triples": [], "refreshes": 0}

    for line in chunk:
        m = TURN.search(line)
        if m:
            n = int(m.group(1))
            # New turn only when the counter increases (handles Duos alternation).
            if cur_turn is None or n > cur_turn:
                cur_turn = n
                turns.append(new_turn(n))
            continue

        m = STEP_RE.search(line)
        if m:
            step = m.group(1)
            continue

        m = REFRESH.search(line)
        if m and cur_turn is not None:
            turns[-1]["refreshes"] += 1
            continue

        m = ENTITY.search(line)
        if m:
            name, eid, z, pos, cid, p = (
                m.group(1), int(m.group(2)), m.group(3),
                m.group(4), m.group(5), int(m.group(6)),
            )
            if not MINION_ONLY.match(cid):
                continue
            old_zone = zone.get(eid)
            old_player = player.get(eid)
            zone[eid] = z
            player[eid] = p
            if cur_turn is None:
                continue

            # BUY: minion's controller becomes friendly (bought from the tavern)
            # and it's in HAND.
            if p == friendly and z == "HAND" and old_player != friendly:
                turns[-1]["buys"].append(cid)
            # SELL: friendly minion leaves PLAY during the shop phase (not combat).
            elif (p == friendly and old_zone == "PLAY"
                  and z in ("SETASIDE", "GRAVEYARD") and step in SHOP_STEPS):
                turns[-1]["sells"].append(cid)
            continue

        m = TRIPLE.search(line)
        if m and cur_turn is not None:
            base = m.group(1)
            if base != "0" and base not in turns[-1]["triples"]:
                turns[-1]["triples"].append(base)

    return turns


def main():
    if len(sys.argv) < 2:
        print("usage: python player_actions.py <Power.log> [--games N]")
        return 1
    log_path = sys.argv[1]
    limit = None
    if "--games" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--games") + 1])

    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if limit:
        chunks = chunks[:limit]

    for idx, (start, end) in enumerate(chunks, 1):
        chunk = lines[start:end]
        game = extract_game(chunk)
        friendly = _friendly_player(game["heroes"])
        print(f"\n=== Game {idx} (friendly player={friendly}) ===")
        for t in parse_actions(chunk, friendly):
            print(f"  Turn {t['turn']}: "
                  f"buy={t['buys']} sell={t['sells']} "
                  f"triple={t['triples']} refresh={t['refreshes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
