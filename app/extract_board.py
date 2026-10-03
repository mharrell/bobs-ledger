"""Extract final board minions per player from a Power.log game range.

Pure stdlib. Canonical semantics (.claude/skills/hearth-board-extract):
track each entity's card id, controller, and LAST-KNOWN zone; report minions
still in zone=PLAY at the end of the range, one row per entity (duplicates
preserved — a board can hold two of a card), filtering
enchantment/token/trinket noise. Golden minions (_G) are real board minions,
not noise.

Zone-tracking rules the naive read gets wrong (the 2026-09-10 game: sold
minions stuck at PLAY, one of two same-card Fauna Whisperers invisible):
- A TAG_CHANGE whose bracket carries `zone=PLAY` may simultaneously write
  `tag=ZONE value=REMOVEDFROMGAME` — the bracket zone is STALE; the tag
  value wins. ZONE writes therefore parse BEFORE any bracket matcher, and
  TAG_CHANGE brackets never update the zone at all.
- Entities created mid-game carry their zone only in their FULL_ENTITY
  block's bare `tag=...` lines (no Entity= prefix); those attach to the
  entity the block is currently creating/updating.
- DebugPrintOptions re-prints stale brackets every event; the Power task
  stream only.
"""
import re
import sys
from collections import defaultdict

FULL = re.compile(r'FULL_ENTITY - Creating ID=(\d+) CardID=([A-Za-z0-9_]*)')
UPDATING = re.compile(r'FULL_ENTITY - Updating \[(.*)\] CardID=([A-Za-z0-9_]*)')
UPDATING_ID = re.compile(r'\bid=(\d+)')
SHOW = re.compile(r'SHOW_ENTITY - Updating Entity=(?:\[.*?\bid=(\d+).*?\]|(\d+)) '
                  r'CardID=([A-Za-z0-9_]*)')
# ZONE writes first — they are the authority (see docstring).
ZONE_ENT = re.compile(r'Entity=\[.*?id=(\d+).*?\] tag=ZONE value=(\w+)')
ZONE_PLAIN = re.compile(r'Entity=(\d+) tag=ZONE value=(\w+)')
CONTROLLER = re.compile(r'Entity=(?:\[.*?id=(\d+).*?\]|(\d+)) '
                        r'tag=CONTROLLER value=(\d+)')
STAT = re.compile(r'Entity=(?:\[.*?id=(\d+).*?\]|(\d+)) '
                  r'tag=(ATK|HEALTH) value=(-?\d+)')
# A bracket with zone + cardId + player — SHOW_ENTITY/UPDATING brackets and
# leftovers; NOT applied to TAG_CHANGE lines (stale bracket zones, see above).
INLINE = re.compile(r'id=(\d+) zone=(\w+) zonePos=\d+ cardId=([A-Za-z0-9_]+).*?player=(\d+)')
# A bare tag line inside a FULL_ENTITY/SHOW_ENTITY block (no Entity= prefix).
FULL_TAG = re.compile(r'^\s*tag=(\w+) value=(\S+)')

# Enchantment/token id tails (BG25_008e, ...e2, BG25_008t...). Golden minions
# (BG25_008_G, uppercase G) are real board minions, NOT noise — board_state.py's
# MINION_ONLY regex includes them too. Trailing digits are stripped before the
# tail check so e2/te3 variants match like e/te.
NOISE_TAILS = ('e', 't', 'd', 'te')


def is_noise(card):
    if card.startswith(('TB_BaconShop_', 'BG36_MidGameEffect_', 'BG36_Button_',
                        'BG30_Trinket_', 'BG32_MagicItem_', 'BG_ShopBuff',
                        'EBG_Spell_', 'BG20_GEM', 'BG_Spell_')):
        return True
    tail = re.sub(r'\d+$', '', card.split('_')[-1])
    return tail in NOISE_TAILS or tail.endswith(('e', 't'))


def extract_rows(path, start, end):
    """{player: [(cid, atk, health), ...]} for minions in PLAY at `end`."""
    card = {}
    player = {}
    zone = defaultdict(lambda: '?')
    atk = {}
    health = {}
    cur = None  # entity the current FULL_ENTITY/SHOW_ENTITY block describes

    with open(path, encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            if lineno < start:
                continue
            if lineno > end:
                break
            if 'DebugPrintPower' not in line:
                continue  # DebugPrintOptions re-prints stale brackets
            m = ZONE_ENT.search(line) or ZONE_PLAIN.search(line)
            if m:
                zone[int(m.group(1))] = m.group(2)
                cur = None
                continue
            m = FULL.search(line)
            if m:
                cur = int(m.group(1))
                if m.group(2) and not card.get(cur):
                    card[cur] = m.group(2)
                continue
            m = UPDATING.search(line) or SHOW.search(line)
            if m:
                if UPDATING.search(line):
                    eid = int(UPDATING_ID.search(m.group(1)).group(1))
                    cid = m.group(2)
                else:
                    eid, cid = (m.group(1) or m.group(2)), m.group(3)
                cur = int(eid)
                if cid:
                    card[cur] = cid  # SHOW/UPDATING fill UNKNOWN placeholders
                continue
            m = CONTROLLER.search(line)
            if m:
                player[int(m.group(1) or m.group(2))] = int(m.group(3))
                cur = None
                continue
            m = STAT.search(line)
            if m:
                eid = int(m.group(1) or m.group(2))
                (atk if m.group(3) == 'ATK' else health)[eid] = int(m.group(4))
                cur = None
                continue
            if 'TAG_CHANGE' in line or 'BLOCK_' in line or 'Choices' in line:
                cur = None
                continue
            m = INLINE.search(line)
            if m and 'TAG_CHANGE' not in line:
                eid = int(m.group(1))
                card[eid], player[eid], zone[eid] = \
                    m.group(3), int(m.group(4)), m.group(2)
                cur = None
                continue
            m = FULL_TAG.match(line.split(' - ', 1)[1] if ' - ' in line else '')
            if m and cur is not None:
                tag, val = m.group(1), m.group(2)
                if tag == 'ZONE':
                    zone[cur] = val
                elif tag == 'CONTROLLER':
                    player[cur] = int(val)
                elif tag == 'ATK' and val.lstrip('-').isdigit():
                    atk[cur] = int(val)
                elif tag == 'HEALTH' and val.lstrip('-').isdigit():
                    health[cur] = int(val)

    board = defaultdict(list)
    for eid, cid in card.items():
        if not cid.startswith(('BG', 'BGS_')):
            continue
        if is_noise(cid):
            continue
        if zone.get(eid) != 'PLAY':
            continue
        p = player.get(eid)
        if p is not None:
            board[p].append((cid, atk.get(eid), health.get(eid)))
    return board


def main():
    path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    board = extract_rows(path, start, end)
    for p in sorted(board):
        rows = sorted(board[p], key=lambda r: (r[0], r[1] or 0, r[2] or 0))
        print(f"Player {p}: {len(rows)} board minions")
        for cid, a, h in rows:
            stats = f" {a}/{h}" if a is not None and h is not None else ""
            print(f"   {cid}{stats}")


if __name__ == '__main__':
    main()
