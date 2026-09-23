#!/usr/bin/env python3
"""Named queries over a Power.log, for agents that pay for output tokens.

The point of this tool is not capability — every query here is something one of
us already worked out by hand, usually with a throwaway script, sometimes twice
in the same session (four review subagents rebuilt the same forensics). The
point is that the ANSWER comes back in a bounded number of lines, because on a
token-billed workflow the expensive side is what the agent reads, not what the
machine computes. Compute is free; output is not.

Every query prints at most `--top` lines (default 25) and takes `--json` for the
full structured result. Nothing dumps a log.

Usage:
  python logquery.py <query> [args] [--game N] [--top N] [--json] [<log|--latest>]

  games                     one line per game: hero, placement, phases, bans
  actions    --game N       per buy phase: buys / sells / plays / rolls / levels
  board      --game N [--turn T]   board snapshot (end of turn T, else final)
  stats      --game N       per turn: HP, armor, effective HP, damage taken
  cap        --game N       BACON_COMBAT_DAMAGE_CAP series (turn -> cap)
  tags       --tag NAME     distinct values of one entity tag (+ sample entities)
  vanish     --game N       hand -> non-PLAY zone transitions (cast vs discard)
  unresolved --game N       card ids in the log that no meta DB knows
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import extract_game as eg  # noqa: E402
import meta  # noqa: E402
import player_actions as pa  # noqa: E402
from board_state import GameState  # noqa: E402
from tribes import canon  # noqa: E402

HS_LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"
STEP_TURN = re.compile(r"tag=STEP value=MAIN_ACTION")
HP_OR_ARMOR = re.compile(r"Entity=\[entityName=([^\]]*?) id=(\d+)[^\]]*?"
                         r"cardId=([A-Za-z0-9_]+)[^\]]*?\] tag=(HEALTH|ARMOR) "
                         r"value=(-?\d+)")
BARE_HP = re.compile(r"TAG_CHANGE Entity=(\d+) tag=(HEALTH|ARMOR) value=(-?\d+)")
CAP_TAG = re.compile(r"tag=BACON_COMBAT_DAMAGE_CAP value=(\d+)")
TAGVAL = re.compile(r"tag=(\w+) value=(\w+)")
CARDID = re.compile(r"cardId=([A-Za-z0-9_]+)", re.I)
#: NB the name group is `(.+?) id=` and NOT `([^\]]*?)`: entity names contain
#: brackets — `Secret Deity [DNT]`, `Discard Paired Cards Player Ench [DNT]` —
#: and a `[^\]]*` name group stops at the first `]`, so the whole match fails and
#: the entity is silently invisible. That is not hypothetical: it is why the
#: Deity's own entity never showed up in the first versions of the discard
#: probes, and why its `BACON_DEITY_SIGIL` samples read as a trinket.
BRACKET = re.compile(r"Entity=\[entityName=(.+?) id=(\d+) zone=(\w+) "
                     r"zonePos=(-?\d+)(?: cardId=([A-Za-z0-9_]+))?")
ZONE_IN_LINE = re.compile(r"tag=ZONE value=(\w+)")


def newest_log():
    logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


class Session:
    """One Power.log, split into games, with the friendly player resolved."""

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8", errors="replace") as f:
            self.lines = f.readlines()
        self.chunks = list(eg.split_game_chunks(self.lines))
        self._friendly = {}

    def game(self, index):
        """1-based game index -> (chunk, friendly_player, my_hero_dict)."""
        if not 1 <= index <= len(self.chunks):
            raise SystemExit(f"game {index} out of range 1..{len(self.chunks)}")
        lo, hi = self.chunks[index - 1]
        chunk = self.lines[lo:hi]
        info = eg.extract_game(chunk)
        friendly = eg._friendly_player(info["heroes"], info["choice_players"])
        mine = next((h for h in info["heroes"] if h["player"] == friendly), None)
        return chunk, friendly, mine

    def names(self):
        return dict(_NAMES)


def _load_names():
    names = {}
    for f, key in (("minions.json", "id"), ("tavern_spells.json", "id"),
                   ("trinkets.json", "id")):
        for row in meta._raw(f) or []:
            if row.get(key) and row.get("name"):
                names.setdefault(row[key], row["name"])
    for row in meta._raw("heroes.json") or []:
        names.setdefault(row.get("name"), row.get("name"))
    return names


_NAMES = _load_names()


def _hero_label(hero):
    if not hero:
        return "?"
    return f"{hero.get('hero_name') or hero.get('card')} (#{hero.get('place')})"


# ---------------------------------------------------------------- queries

def q_games(sess, args):
    out = []
    for i in range(1, len(sess.chunks) + 1):
        chunk, friendly, mine = sess.game(i)
        phases = len(_phases(chunk))
        unresolved = _unresolved_ids(chunk)
        out.append(OrderedDict(
            game=i, hero=(mine or {}).get("hero_name") or (mine or {}).get("card"),
            place=(mine or {}).get("place"), tier=(mine or {}).get("tech"),
            phases=phases, unresolved=len(unresolved),
            top_unresolved=[u[0] for u in unresolved[:4]]))
    return out


def _phases(chunk):
    import replay_review
    return replay_review._phases(chunk)


def q_actions(sess, args):
    chunk, friendly, mine = sess.game(args.game or 1)
    hero_card = (mine or {}).get("card")
    try:
        actions = pa.parse_actions(chunk, friendly, hero_card)
    except Exception as exc:  # parser is best-effort on odd logs
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    rows = OrderedDict()
    for a in actions:
        t = getattr(a, "turn", None) or (a.get("turn") if isinstance(a, dict) else None)
        kind = getattr(a, "kind", None) or (a.get("kind") if isinstance(a, dict) else None)
        if t is None or kind is None:
            continue
        r = rows.setdefault(t, Counter())
        r[kind] += 1
    return [OrderedDict(turn=t, **{k: v for k, v in sorted(c.items())})
            for t, c in sorted(rows.items())]


def q_board(sess, args):
    chunk, friendly, mine = sess.game(args.game or 1)
    gs = GameState()
    target_turn = args.turn
    turn = 0
    last = None
    for line in chunk:
        if "GameState.DebugPrintPower" in line and STEP_TURN.search(line):
            turn += 1
            if target_turn and turn > target_turn:
                break
        gs.feed(line)
        if target_turn and turn == target_turn:
            last = True
    board = gs.final_board if (not target_turn and gs.final_board) else gs.board
    out = []
    for m in board or []:
        if not isinstance(m, dict):
            continue
        out.append(OrderedDict(
            card=m.get("card"), name=_NAMES.get(m.get("card")) or m.get("name"),
            atk=m.get("atk"), hp=m.get("health") or m.get("hp"),
            tribe=m.get("tribe"), golden=bool(m.get("golden"))))
    return out


def q_stats(sess, args):
    """Per-turn HP / armor / effective HP and the damage taken that turn.

    Reads the friendly hero's own HEALTH and ARMOR writes directly rather than
    going through the live coach: last write in a turn is the post-combat value,
    so damage = previous turn's effective HP minus this turn's.
    """
    chunk, friendly, mine = sess.game(args.game or 1)
    hero_card = (mine or {}).get("card")
    if not hero_card:
        return []
    turn = 0
    per_turn = OrderedDict()
    for line in chunk:
        if "GameState.DebugPrintPower" in line and STEP_TURN.search(line):
            turn += 1
        m = HP_OR_ARMOR.search(line)
        if m and m.group(3) == hero_card:
            per_turn.setdefault(turn, {})[m.group(4).lower()] = int(m.group(5))
    rows, prev = [], None
    hp = armor = None
    for t, vals in per_turn.items():
        hp = vals.get("health", hp)
        armor = vals.get("armor", armor)
        eff = (hp or 0) + (armor or 0)
        rows.append(OrderedDict(turn=t, hp=hp, armor=armor, eff=eff,
                                took=None if prev is None else prev - eff))
        prev = eff
    return rows


def q_cap(sess, args):
    chunk, _friendly, _mine = sess.game(args.game or 1)
    turn, seen = 0, []
    for line in chunk:
        if "GameState.DebugPrintPower" not in line:
            continue
        if STEP_TURN.search(line):
            turn += 1
        m = CAP_TAG.search(line)
        if m:
            v = int(m.group(1))
            if not seen or seen[-1][1] != v:
                seen.append((turn, v))
    return [OrderedDict(turn=t, cap=v) for t, v in seen]


def q_tags(sess, args):
    """Distinct values of one tag, with up to 3 entities it rides on.

    Samples are collected from the most recent bracketed entity seen, not from
    the tag's own line, because most tag writes are continuation lines inside a
    block (the Deity's `BACON_DEITY_SIGIL` lines carry no entity at all). And
    they are a LIST, because a tag can ride on several entities: reporting only
    the last one showed "Greater Trinket" for the Deity's sigil, which is
    misleading rather than wrong.
    """
    if not args.tag:
        raise SystemExit("tags needs --tag NAME")
    pat = re.compile(r"tag=" + re.escape(args.tag) + r" value=(\w+)")
    vals, ents = Counter(), {}
    games = [args.game] if args.game else range(1, len(sess.chunks) + 1)
    for g in games:
        chunk, _f, _m = sess.game(g)
        last = None
        for line in chunk:
            if "GameState.DebugPrintPower" not in line:
                continue
            b = BRACKET.search(line)
            if b:
                last = b.group(1) or b.group(5)
            m = pat.search(line)
            if not m:
                continue
            vals[m.group(1)] += 1
            if last:
                ents.setdefault(m.group(1), [])
                if last not in ents[m.group(1)] and len(ents[m.group(1)]) < 3:
                    ents[m.group(1)].append(last)
    return [OrderedDict(value=v, count=c,
                        samples=ents.get(v, []), sample=(ents.get(v) or [""])[0])
            for v, c in sorted(vals.items(), key=lambda kv: -kv[1])]


def q_vanish(sess, args):
    """Cards that left HAND for somewhere other than PLAY.

    Deliberately reports the ambiguity rather than hiding it: a CAST spell also
    ends in GRAVEYARD, so this is a candidate list, not a discard count.
    """
    chunk, friendly, _mine = sess.game(args.game or 1)
    zone, card, name, owner = {}, {}, {}, {}
    out = []
    for line in chunk:
        if "GameState.DebugPrintPower" not in line:
            continue
        b = BRACKET.search(line)
        if b:
            nm, eid, _z, _p, cid = b.groups()
            eid = int(eid)
            if nm:
                name[eid] = nm
            if cid:
                card[eid] = cid
            z = ZONE_IN_LINE.search(line)
            if z:
                if zone.get(eid) == "HAND" and z.group(1) not in ("HAND", "PLAY"):
                    out.append(OrderedDict(
                        card=card.get(eid), name=name.get(eid),
                        to=z.group(1), player=owner.get(eid)))
                zone[eid] = z.group(1)
            continue
        b2 = re.search(r"TAG_CHANGE Entity=(\d+) tag=(\w+) value=(\w+)", line)
        if b2:
            eid, tag, val = int(b2.group(1)), b2.group(2), b2.group(3)
            owner.setdefault(eid, None)
            if tag == "ZONE":
                if zone.get(eid) == "HAND" and val not in ("HAND", "PLAY"):
                    out.append(OrderedDict(card=card.get(eid),
                                           name=name.get(eid), to=val,
                                           player=owner.get(eid)))
                zone[eid] = val
    return out


def _meta_ids():
    ids = set()
    for f, key in (("minions.json", "id"), ("tavern_spells.json", "id"),
                   ("trinkets.json", "id"), ("comps.json", None)):
        for row in meta._raw(f) or []:
            if not isinstance(row, dict):
                continue
            if key and row.get(key):
                ids.add(row[key])
            for cid in row.get("core", []) + row.get("addons", []):
                ids.add(cid)
    return ids


#: CARDTYPEs that represent a card a player can see and the coach might name.
#: Enchantments and internal tokens are excluded on purpose: the first version of
#: this query reported 169 "unresolved" ids for a single game, and all but a
#: handful were `_e` enchantments, `_G` goldens and `TB_BaconShop_*` machinery.
#: A pre-flight that buries four real gaps under 165 non-cards is not a
#: pre-flight.
_DISPLAYABLE = {"MINION", "BATTLEGROUND_SPELL", "SPELL", "WEAPON"}
_CARD_TYPE_LINE = re.compile(r"tag=CARDTYPE value=(\w+)")
#: Summoned tokens and per-card variant objects: real minion ids never end in
#: `t`, and a `t`/`t2` suffix on an id whose base IS in the DB is that card's
#: token (BG31_880t is Alliance Flag's token, BG36_341t2 a Tier-2 variant).
#: Real tavern SPELLS do end in `t` themselves (BG36_301t Sludge Corrosion), so
#: the suffix is only disqualifying when the trimmed base is already known.
_TOKEN_SUFFIX = re.compile(r"t\d*$")
#: Entity ids that are game machinery rather than cards: `BG_OldGod` is the
#: Deity itself, `*MidGameEffect*` are internal effect objects, `EBG_*` are
#: event/brawl cards, `*_HERO_<n>p*` are hero-POWER variants (the coach reads
#: hero powers by name from heroes.json), `*_GEM*` are Blood Gem tokens and
#: `*Quest*` are quest objects.
#:
#: Deliberately NOT excluded: `BG31_893` ("Gem Day", a real SPELL with no
#: TECH_LEVEL or COST in the log, so probably generated rather than shop-bought).
#: It is a genuine unknown and the pre-flight is supposed to surface it.
_NON_CARD = re.compile(r"(MidGameEffect|OldGod|^EBG_|_HERO_\d+p|_GEM|Quest)",
                       re.I)


def _plausible_card(cid, ctype, known):
    """Could a player see this as a card the coach might name?

    Four exclusions, each earned by watching the query be useless at the
    previous setting: `TB_*` Battlegrounds machinery (`TB_Baconups_079`,
    `TB_BaconShop_CheckTriples`), summoned MINION tokens (`BGS_115t`), a
    `t`/`t2` variant whose base card IS known, and non-card entities. The count
    went 169 -> 27 -> 19 across three passes on one game; a pre-flight that
    buries four real gaps under 165 non-cards is not a pre-flight.
    """
    if _NON_CARD.search(cid):
        return False
    if cid.upper().startswith("TB_"):
        return False
    if ctype == "MINION" and _TOKEN_SUFFIX.search(cid):
        return False
    m = _TOKEN_SUFFIX.search(cid)
    if m and cid[:m.start()] in known:
        return False
    return ctype in _DISPLAYABLE


def _unresolved_ids(chunk):
    """Real cards in this game that no meta DB knows (the review pre-flight)."""
    known = _meta_ids()
    seen, ctype, cur = Counter(), {}, None
    for line in chunk:
        if "DebugPrintPower" not in line:
            continue
        if "FULL_ENTITY" in line or "SHOW_ENTITY" in line:
            m = CARDID.search(line)
            cur = m.group(1) if m else None
            # Count the header id too. A card that only ever appears in its
            # creation block (never in a bracketed TAG_CHANGE) would otherwise
            # be invisible here — a test caught exactly that.
            if cur and cur not in known and not (
                    cur.endswith("_G") and cur[:-2] in known):
                seen[cur] += 1
            continue
        cm = _CARD_TYPE_LINE.search(line)
        if cm and cur:
            ctype.setdefault(cur, cm.group(1))
        for cid in CARDID.findall(line):
            if cid in known:
                continue
            if cid.endswith("_G") and cid[:-2] in known:
                continue  # a golden of a known card
            seen[cid] += 1
    real = {c: n for c, n in seen.items()
            if _plausible_card(c, ctype.get(c), known)}
    return Counter(real).most_common()




def q_unresolved(sess, args):
    chunk, _f, _m = sess.game(args.game or 1)
    return [OrderedDict(card=c, hits=n) for c, n in _unresolved_ids(chunk)]


QUERIES = OrderedDict([
    ("games", q_games), ("actions", q_actions), ("board", q_board),
    ("stats", q_stats), ("cap", q_cap), ("tags", q_tags),
    ("vanish", q_vanish), ("unresolved", q_unresolved),
])


def _render(query, rows, names):
    """Bounded human view. Never more than one line per row, `--top` rows."""
    if not rows:
        return "  (nothing)"
    if query == "games":
        return "\n".join(
            f"  g{r['game']} {str(r['hero'])[:22]:22} place={r['place']} "
            f"tier={r['tier']} phases={r['phases']} unresolved={r['unresolved']}"
            for r in rows)
    if query == "tags":
        return "\n".join(f"  {r['value']:>6} x{r['count']:<5} {r['sample'] or ''}"
                         for r in rows)
    if query == "vanish":
        return "\n".join(f"  {str(r['name'])[:24]:24} {r['card']:14} -> {r['to']}"
                         for r in rows)
    if query == "unresolved":
        return "\n".join(f"  {r['card']:16} x{r['hits']}" for r in rows)
    return "\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", choices=list(QUERIES))
    ap.add_argument("log", nargs="?", default=None)
    ap.add_argument("--game", type=int, default=None)
    ap.add_argument("--turn", type=int, default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = args.log if args.log and args.log != "--latest" else newest_log()
    if not path or not os.path.exists(path):
        raise SystemExit("no Power.log found (pass a path)")
    sess = Session(path)
    rows = QUERIES[args.query](sess, args)
    if args.json:
        print(json.dumps({"log": sess.name, "query": args.query, "rows": rows},
                         ensure_ascii=False))
        return 0
    shown = rows[:args.top]
    print(f"{sess.name}  {args.query}  ({len(rows)} row(s)"
          + (f", showing {len(shown)}" if len(rows) > len(shown) else "") + ")")
    print(_render(args.query, shown, _NAMES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
