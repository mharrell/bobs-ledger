"""Extract final board minions per player from a Power.log game range.

Pure stdlib. Tracks each entity's card id, controller, and last-known zone.
Reports minions (cardID BG*/BGS_) left in zone=PLAY at the end of the range,
deduped per player, filtering enchantment/token/trinket noise.
"""
import re
import sys
from collections import defaultdict

INLINE = re.compile(r'id=(\d+) zone=(\w+) zonePos=\d+ cardId=([A-Za-z0-9_]+).*?player=(\d+)')
FULL = re.compile(r'Creating ID=(\d+).*?CardID=([A-Za-z0-9_]+)')
ZONE_ENT = re.compile(r'Entity=\[.*?id=(\d+).*?\] tag=ZONE value=(\w+)')
ZONE_PLAIN = re.compile(r'Entity=(\d+) tag=ZONE value=(\w+)')

NOISE_TAILS = ('e', 't', 'G', 'd', 'te', 'e2', 'e3', 't2', 't3', 't14', 't18', 't22', 'te2', 'te3')


def is_noise(card):
    if card.startswith(('TB_BaconShop_', 'BG36_MidGameEffect_', 'BG36_Button_',
                        'BG30_Trinket_', 'BG32_MagicItem_', 'BG_ShopBuff_',
                        'EBG_Spell_', 'BG20_GEM', 'BG_Spell_')):
        return True
    tail = card.split('_')[-1]
    if tail in NOISE_TAILS:
        return True
    return tail.endswith(('e', 't', 'G'))


def main():
    path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    card = {}
    player = {}
    zone = defaultdict(lambda: '?')

    with open(path, encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            if lineno < start:
                continue
            if lineno > end:
                break
            m = INLINE.search(line)
            if m:
                eid, z, cid, p = int(m.group(1)), m.group(2), m.group(3), int(m.group(4))
                card[eid], player[eid], zone[eid] = cid, p, z
                continue
            m = FULL.search(line)
            if m:
                eid, cid = int(m.group(1)), m.group(2)
                if eid not in card:
                    card[eid] = cid
                continue
            m = ZONE_ENT.search(line)
            if m:
                zone[int(m.group(1))] = m.group(2)
                continue
            m = ZONE_PLAIN.search(line)
            if m:
                zone[int(m.group(1))] = m.group(2)

    board = defaultdict(set)
    for eid, cid in card.items():
        if not cid.startswith(('BG', 'BGS_')):
            continue
        if is_noise(cid):
            continue
        if zone.get(eid) != 'PLAY':
            continue
        p = player.get(eid)
        if p is not None:
            board[p].add(cid)

    for p in sorted(board):
        print(f"Player {p}: {len(board[p])} board minions")
        for c in sorted(board[p]):
            print(f"   {c}")


if __name__ == '__main__':
    main()
