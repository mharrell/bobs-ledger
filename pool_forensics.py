#!/usr/bin/env python3
"""Pool-estimator forensics: pin the log mechanics bg_pool_estimator.py assumes.

Phase 0 of card availability (analysis/pool_availability.md has the full
write-up). Answers, from real logs, the four open questions:

  1. BURST SHAPE   Each combat window stages BOTH boards as fresh entities
                   under the shared combat-slot controller: first OUR board,
                   then the opponent's (final duel stages only the opponent's).
                   The staging marker is tag=CREATOR pointing at the persistent
                   TB_BaconShop_8P_PlayerE enchantment entity — combat summons,
                   shop offers, and heroes/hero-powers/trinkets have other (or
                   no) creators. Goldens arrive with a _G card id AND
                   PREMIUM=1. Hand-carried minions surface as SHOW_ENTITY.
  2. ELIMINATION   There is NO elimination tag. PLAYSTATE is game-end only
                   (with transient LOSING blips mid-combat); BACON_DIED_LAST_
                   COMBAT is a per-MINION flag, not per-player. A dead seat is
                   only visible indirectly: it stops being paired and its
                   leaderboard place freezes.
  3. SEAT BRIDGE   BACON_CURRENT_COMBAT_PLAYER_ID seats (1..8, 0 = slot
                   cleared after the fight) are the stable per-player key;
                   opponents' hero entities are re-created under the combat
                   slot every round, so their player numbers are NOT stable.
                   The BACON row itself carries the account name -> hero card
                   (via extract_game's HERO_ENTITY map). The friendly seat
                   equalled the friendly player number in both observed games.
  4. CONTROLLER VARIANCE   Real: game 1 used friendly=1 / combat-slot=9,
                   game 2 used 5/13. The blueprint's hardcoded 1/9 are one
                   session's values; resolve dynamically (as our parsers do).

Usage:
  python pool_forensics.py --latest [--game N] [--bursts] [--elim] [--tags]
  python pool_forensics.py <Power.log> [game_index] [--bursts] [--elim] [--tags]

GameState lines only (PowerTaskList duplicates every write). Reuses
extract_game's regexes/parsers and replay_review._phases for turn windows.
"""
import glob
import os
import re
import sys
from collections import Counter, defaultdict

from config import HS_LOG_GLOB
from extract_game import (
    split_game_chunks, extract_game, _friendly_player,
    MINION_ID, FULL_ENTITY, FULL_ENTITY_UPDATING, UPDATING_ENTITY_ID,
    ENTITY_TAG, TIMESTAMP, FULL_TAG,
)
from replay_review import _phases
from value import _load_bg_names

GS = "GameState.DebugPrintPower()"
SEAT = re.compile(r"TAG_CHANGE Entity=(.+?) tag=BACON_CURRENT_COMBAT_PLAYER_ID value=(\d+)")
NEXT_OPP = re.compile(r"TAG_CHANGE Entity=.+? tag=NEXT_OPPONENT_PLAYER_ID value=(\d+)")
# TAG_CHANGE with a bare-name entity (account form): Entity=Name#1234 tag=X value=Y
NAME_TAG = re.compile(r"TAG_CHANGE Entity=(\S+) tag=(\w+) value=(\w+)")
SHOW_ENTITY = re.compile(r"SHOW_ENTITY - Updating Entity=\[.*?\bid=(\d+).*?\] CardID=(\w*)")
ELIMISH = re.compile(r"ELIMIN|ALIVE|DEAD|DEATH|BUST|QUIT|KNOCK|PLAYSTATE|FATIGUE", re.I)
PREMIUM_GOLDEN = 1


def _card_of(ent):
    return ent.get("card", "")


def _ts_s(ts):
    """'12:53:30.4550317' -> seconds since midnight (float)."""
    try:
        h, m, rest = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    except (ValueError, AttributeError):
        return None




def _is_minion(ent):
    return ent.get("cardtype") == "MINION" or (
        _card_of(ent) and MINION_ID.match(_card_of(ent))
        and ent.get("cardtype") not in ("HERO", "HERO_POWER", "TRINKET"))


def forensics(chunk, names, game_index=1, want_bursts=False, want_elim=False,
              want_tags=False):
    """Walk one game chunk; print the forensic report."""
    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    phases = _phases(chunk)
    # Window index for a line: (kind, turn). kind: buy/combat. Combat of turn t
    # runs from buy t's MAIN_END to buy t+1's MAIN_ACTION.
    win_of_line = {}
    for t, (lo, hi) in enumerate(phases, 1):
        for i in range(lo, (hi if hi is not None else len(chunk))):
            win_of_line[i] = ("buy", t)
    for t, (lo, hi) in enumerate(phases, 1):
        nxt = phases[t][0] if t < len(phases) else len(chunk)
        if hi is not None:
            for i in range(hi, nxt):
                win_of_line[i] = ("combat", t)

    # --- single pass: entities, seats, next-opponent, place history, vocab ---
    ent = {}            # eid -> {card, controller, zone, premium, cardtype, creator}
    cur = None          # eid of the FULL_ENTITY block being read
    seats = []          # (line, ts, entity_str, value)
    next_opps = []      # (line, ts, value)
    place_hist = defaultdict(list)   # eid -> [(line, ts, value)]
    tag_vocab = Counter()
    elim_tags = defaultdict(list)    # tag -> sample (ts, value)
    creations = []      # (line, ts, eid, win)
    shows = []          # (line, ts, eid, card, win)
    acct_tags = defaultdict(list)    # account -> [(ts, tag, value)]
    SHOP_ENCHANT = "TB_BaconShop_8P_PlayerE"   # board-load staging entity

    for i, line in enumerate(chunk):
        if GS not in line:
            continue
        win = win_of_line.get(i)
        ts_m = TIMESTAMP.match(line)
        ts = ts_m.group(1) if ts_m else "?"

        m = FULL_ENTITY.search(line)
        if m and "Updating" not in line:
            cur = int(m.group(1))
            ent.setdefault(cur, {})["card"] = m.group(2)
            creations.append((i, ts, cur, win))
            continue
        m = FULL_ENTITY_UPDATING.search(line)
        if m:
            idm = UPDATING_ENTITY_ID.search(m.group(1))
            if idm:
                cur = int(idm.group(1))
                ent.setdefault(cur, {})["card"] = m.group(2)
            continue
        m = SHOW_ENTITY.search(line)
        if m:
            eid, cid = int(m.group(1)), m.group(2)
            if cid:
                ent.setdefault(eid, {})["card"] = cid
                shows.append((i, ts, eid, cid, win))
            continue

        m = ENTITY_TAG.search(line)
        if m:
            ename, eid, cid, p, tag, value = m.groups()
            eid = int(eid)
            e = ent.setdefault(eid, {})
            if cid:
                e["card"] = cid
            if tag in ("CONTROLLER", "ZONE", "PREMIUM", "CARDTYPE"):
                e[tag.lower()] = value
            elif tag == "PLAYER_LEADERBOARD_PLACE":
                place_hist[eid].append((i, ts, int(value)))
            tag_vocab[tag] += 1
            if ELIMISH.search(tag):
                elim_tags[tag].append((ts, value))
            cur = None
            continue

        m = SEAT.search(line)
        if m:
            seats.append((i, ts, m.group(1), int(m.group(2)),
                          (win_of_line.get(i) or ("?", 0))[1]))
            cur = None
            continue
        m = NEXT_OPP.search(line)
        if m:
            next_opps.append((i, ts, int(m.group(1)),
                              (win_of_line.get(i) or ("?", 0))[1]))
            cur = None
            continue

        m = NAME_TAG.search(line)
        if m:
            tag_vocab[m.group(2)] += 1
            acct_tags[m.group(1)].append((ts, m.group(2), m.group(3)))
            if ELIMISH.search(m.group(2)):
                elim_tags[m.group(2)].append((ts, m.group(3)))

        # tag lines inside an entity block (no Entity= / no TAG_CHANGE head)
        if "TAG_CHANGE" not in line and "Creating" not in line \
                and "Updating" not in line:
            m = FULL_TAG.search(line)
            if m and cur is not None:
                tag, value = m.groups()
                if tag in ("CONTROLLER", "ZONE", "PREMIUM", "CARDTYPE",
                           "CREATOR", "ZONE_POSITION"):
                    ent[cur][tag.lower() if tag != "ZONE_POSITION"
                             else "zonepos"] = value
                tag_vocab[tag] += 1
                if ELIMISH.search(tag):
                    elim_tags[tag].append((ts, value))

    # --- controllers: friendly vs combat slot vs shop ---
    # hero entity player numbers (heroes keep their player number all game;
    # the combat slot re-uses one shared non-friendly number for minions).
    by_ctrl = defaultdict(lambda: Counter())   # (kind, ctrl) -> minion cards
    for line, ts, eid, win in creations:
        e = ent.get(eid, {})
        if not _is_minion(e):
            continue
        ctrl = e.get("controller")
        if ctrl is None:
            continue
        kind, t = win if win else ("?", 0)
        by_ctrl[(kind, int(ctrl))][e["card"]] += 1

    non_friendly = Counter()
    for (kind, ctrl), cards in by_ctrl.items():
        if ctrl != friendly:
            non_friendly[ctrl] += sum(cards.values())
    combat_slot = non_friendly.most_common(1)[0][0] if non_friendly else None

    # The board-load staging entity: opponent board copies are CREATED by it
    # (tag=CREATOR), combat summons are created by other minions. Resolve its
    # entity id(s) from any line carrying its card id.
    shop_ids = set()
    for eid, e in ent.items():
        if e.get("card") == SHOP_ENCHANT:
            shop_ids.add(eid)
    if not shop_ids:
        for i, line in enumerate(chunk):
            if GS in line and SHOP_ENCHANT in line:
                m = re.search(r"\bid=(\d+)", line)
                if m:
                    shop_ids.add(int(m.group(1)))

    # --- bursts: per-turn combat-window entity creations ---
    # Boundary rule under test: board load = combat-slot creations whose
    # CREATOR is the BaconShop8PlayerEnchant staging entity. Everything else
    # (minions summoned mid-fight, trinkets re-listed, heroes re-created)
    # must fall outside "load".
    bursts = defaultdict(lambda: {"load": [], "load_goldens": 0,
                                  "summons": 0, "others": [],
                                  "shows": [], "first": None, "last": None,
                                  "pre_first": None})
    buy_loads = defaultdict(lambda: {"minions": [], "first": None})
    for line, ts, eid, win in creations:
        e = ent.get(eid, {})
        creator = e.get("creator")
        is_staged = (creator and int(creator) in shop_ids
                     and e.get("cardtype") == "MINION"
                     and e.get("controller") == str(combat_slot))
        if not win:
            continue
        if win[0] == "buy":
            if is_staged:
                bb = buy_loads[win[1]]
                if bb["first"] is None:
                    bb["first"] = ts
                bb["minions"].append((_ts_s(ts), eid, _card_of(e),
                                      e.get("zonepos", "")))
            continue
        b = bursts[win[1]]
        if b["first"] is None:
            b["first"] = (ts, line, chunk[line - 1].strip() if line else "")
        b["last"] = (ts, line)
        if is_staged:
            b["load"].append((_ts_s(ts), eid, _card_of(e),
                              e.get("zonepos", "")))
            if e.get("premium") == str(PREMIUM_GOLDEN):
                b["load_goldens"] += 1
        elif e.get("cardtype") == "MINION" \
                and e.get("controller") == str(combat_slot):
            b["summons"] += 1
            b["others"].append((_card_of(e), "summon", creator))
        else:
            b["others"].append((_card_of(e), e.get("cardtype", "?"), creator))
    for line, ts, eid, cid, win in shows:
        if not win or win[0] != "combat":
            continue
        e = ent.get(eid, {})
        if e.get("controller") == str(combat_slot) and MINION_ID.match(cid):
            bursts[win[1]]["shows"].append((cid, eid))

    # --- seats: value vs hero player number (the bridge test) ---
    acct_hero = game.get("account", {})     # account name -> hero card id
    hero_player = {h["card"]: h["player"] for h in game["heroes"]}
    seat_rows = []
    for line, ts, estr, seat, rnd in seats:
        name = estr[1:-1] if estr.startswith("[") else estr
        hero_card = acct_hero.get(name)
        pnum = hero_player.get(hero_card)
        seat_rows.append((ts, name, seat, hero_card, pnum, rnd))

    # --- report ---
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    print(f"\n=== Game {game_index}  hero={hero['hero_name'] if hero else '?'}"
          f"  turns={len(phases)} ===")
    shop_ctrls = Counter()
    for (kind, ctrl), cards in by_ctrl.items():
        if kind == "buy":
            shop_ctrls[ctrl] += sum(cards.values())
    print(f"players: friendly={friendly}  combat_slot={combat_slot}  "
          f"shop minions by controller={dict(shop_ctrls)}")
    print(f"non-friendly minion controllers (combat windows): "
          f"{dict(non_friendly)}")

    print(f"seat tags ({len(seats)}):  [value == player number? => bridge]")
    for ts, name, seat, hc, pn, rnd in seat_rows:
        match = "OK" if pn == seat else ("MAP-NEEDED" if pn else "?")
        print(f"  r{rnd:<3} {ts} {name[:24]:24} seat={seat:<3} "
              f"hero={hc} player={pn} {match}")
    print(f"next-opponent tags: {len(next_opps)} "
          f"(values {sorted({v for _, _, v, _ in next_opps})})")

    print(f"combat bursts ({len(bursts)}) — load rule: "
          f"CREATOR in {sorted(shop_ids)} + CARDTYPE=MINION:")
    for t in sorted(bursts):
        b = bursts[t]
        first_ts, first_line, pre = b["first"] or ("?", 0, "")
        span = ""
        if b["last"]:
            span = f"..{b['last'][0]}"
        print(f"  r{t:<3} load={len(b['load']):<2} goldens={b['load_goldens']:<2}"
              f" summons={b['summons']:<3}"
              f" shows(hand)={len(b['shows'])}"
              f"  @{first_ts}{span}")
        if want_bursts:
            base = _ts_s(first_ts) or 0.0
            labelled = [f"{names.get(c, c)}@pos{pos or '?'}"
                        f"+{(_ts_s(ts) or base) - base:.2f}s"
                        for ts, _eid, c, pos in b["load"]]
            print(f"        board-load: {labelled}")
            if b["others"]:
                oth = [f"{names.get(c, c)}({k},cr={cr})"
                       for c, k, cr in b["others"][:12]]
                print(f"        non-load creations: {oth}")
            print(f"        pre-first line: {pre[:110]}")
    if buy_loads:
        print("buy-phase staged board loads (scout / shop-side staging):")
        for t in sorted(buy_loads):
            bb = buy_loads[t]
            print(f"  buy t{t:<3} staged={len(bb['minions']):<3} "
                  f"@{bb['first']}")
            if want_bursts:
                bbase = _ts_s(bb["first"]) or 0.0
                print(f"        {[f'{names.get(c, c)}@pos{pos or "?"}'
                                  f'+{(_s or bbase) - bbase:.2f}s'
                                  for _s, _e, c, pos in bb['minions']]}")

    # --- elimination inference: seat pairing-absence vs place changes ---
    # No elimination tag exists in the vocabulary; a dead seat simply stops
    # being paired. Table: per seat, the rounds it was paired, and whether its
    # final place explains the absence (place freezes at death).
    pair_rounds = defaultdict(list)
    for ts, name, seat, hc, pn, rnd in seat_rows:
        if seat and rnd:
            pair_rounds[seat].append(rnd)
    print("seat pairing coverage (elimination inference):")
    seat_name = {}
    for ts, name, seat, hc, pn, rnd in seat_rows:
        if seat and name != "Bartender Bob":
            seat_name.setdefault(seat, (name, hc))
    for seat in sorted(pair_rounds):
        name, hc = seat_name.get(seat, ("?", "?"))
        rounds = pair_rounds[seat]
        print(f"  seat {seat:<2} {name[:20]:20} hero={hc} "
              f"paired in rounds {sorted(set(rounds))}")

    # --- per-account histories: the elimination hunt ---
    # Opponent hero entities are re-created every combat (controller = combat
    # slot), so any stable per-player flag must live on the ACCOUNT entity —
    # the same entity BACON_CURRENT_COMBAT_PLAYER_ID is written to. Dump every
    # tag each opponent account ever received.
    print("opponent accounts (seat via seat tags; tags from account entities):")
    seen_acct = set()
    for ts, name, seat, hc, pn, rnd in reversed(seat_rows):
        if seat == 0 or name == "UNKNOWN HUMAN PLAYER" or name in seen_acct:
            continue
        seen_acct.add(name)
        tags = acct_tags.get(name, [])
        if not tags:
            continue
        vocab = {}
        for _t, tag, val in tags:
            vocab[tag] = val
        print(f"  {name[:22]:22} seat={seat:<3} hero={hc}")
        for tag, val in sorted(vocab.items()):
            print(f"      {tag}={val}")
        if want_elim:
            for t2, tag, val in tags:
                if ELIMISH.search(tag):
                    print(f"      ... {tag}={val} @ {t2}")

    if want_tags:
        print(f"tag vocabulary ({len(tag_vocab)} distinct):")
        for tag, n in sorted(tag_vocab.items()):
            print(f"  {tag} x{n}")
    print("elimination-ish tags seen (any entity):")
    for tag, samples in sorted(elim_tags.items()):
        vals = Counter(v for _, v in samples)
        print(f"  {tag} x{len(samples)} values={dict(vals)}")

    # --- place timeline: when did the lobby shrink? ---
    # Use only live hero entities (lowest eid per card id — the re-created
    # final-leaderboard copies carry stale places). Initial hero-select
    # assignment noise (all 8 heroes flip 1..8 within a second) is trimmed.
    live = {h["card"]: h for h in game["heroes"] if h["player"] == friendly
            or h["card"] in hero_player}
    events = []
    for card, h in live.items():
        for line, ts, val in place_hist.get(h["id"], []):
            events.append((ts, line, card, val))
    events.sort()
    if events:
        print(f"place changes: {len(events)} "
              f"(first at {events[0][0]}, last at {events[-1][0]})")
        if want_elim:
            for ts, line, card, val in events:
                print(f"  {ts} {card} -> place {val}")
    return {"friendly": friendly, "combat_slot": combat_slot,
            "shop": dict(shop_ctrls), "bursts": len(bursts),
            "seat_bridge": [("OK" if pn == s else "MAP-NEEDED")
                            for _, _, s, _, pn, _ in seat_rows]}


def main():
    argv = sys.argv[1:]
    want_bursts = "--bursts" in argv
    want_elim = "--elim" in argv
    want_tags = "--tags" in argv
    only_game = None
    if "--game" in argv:
        i = argv.index("--game")
        only_game = int(argv[i + 1])
        del argv[i:i + 2]
    argv = [a for a in argv if not a.startswith("--")]
    if argv:
        path = argv[0]
        if len(argv) > 1 and only_game is None:
            only_game = int(argv[1])
    else:
        logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime,
                      reverse=True)
        if not logs:
            print("no session log found")
            return 1
        path = logs[0]

    names = _load_bg_names()
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    print(f"pool forensics — {os.path.basename(os.path.dirname(path))}  "
          f"games={len(chunks)}")

    summary = []
    for idx, (s, e) in enumerate(chunks, 1):
        if only_game and idx != only_game:
            continue
        summary.append(forensics(lines[s:e], names, idx, want_bursts,
                                 want_elim, want_tags))

    if len(summary) > 1:
        print("\n=== session summary (controller variance / bridge) ===")
        for i, r in enumerate(summary, 1):
            bridge = Counter(r["seat_bridge"])
            print(f"  game {i}: friendly={r['friendly']} "
                  f"combat_slot={r['combat_slot']} shop={r['shop']} "
                  f"bursts={r['bursts']} seat-bridge={dict(bridge)}")


if __name__ == "__main__":
    sys.exit(main())
