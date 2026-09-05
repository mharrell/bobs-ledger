"""Reconstruct the board state (minions + stats) from a Power.log.

Phase 2 of the coach: turn the raw log into a queryable game-state model.
Tracks every entity's card id, controller, zone, and combat stats, then
snapshots the board (minions in ZONE=PLAY) at any point.

Known limitation (see analysis/BG_LOG_STRUCTURE.md): the 7 opponents all share
the "spectator" player number, so their minions are indistinguishable by
controller. The friendly board is fully reconstructable; opponents' boards are
only recoverable as a combined pool.

Hero/account/friendly-player detection is delegated to `extract_game.py`
(which already handles the re-created-hero and hero-selection-screen quirks);
this module is purely the entity/board tracker.

Usage:
    python board_state.py <Power.log> [--games N]
"""
import re
import sys
from collections import defaultdict

from extract_game import (
    ENTITY_TAG, FULL_ENTITY, FULL_ENTITY_UPDATING, FULL_TAG, NAME_HERO,
    ZONE_PLAIN, UPDATING_ENTITY_ID, HERO_CARD, TIMESTAMP, split_game_chunks,
    extract_game, _friendly_player,
)

# A real board minion: BGxx_NNN, BGxx_SETCODE_NNN (e.g. Drakkari = BG26_ICC_901),
# BGS_NNN (legacy), or BG_XXX_NNN (reprints, e.g. Brann = BG_LOE_077). BGS_ is
# used by both minions and spells, so the cardtype filter (not this regex) does
# the minion/spell split. Excludes enchantments (BGxx_NNNx) and trinkets. Golden
# cards (BGxx_NNN_G) ARE matched; _minion strips the _G and sets a `golden` flag.
# Heroes (HERO) match the set-code branch but are filtered by the cardtype check.
MINION_ONLY = re.compile(r"^(?:BG\d+_\d+|BG\d+_[A-Z]+_\d+|BGS_\d+|BG_[A-Z]+_\d+)(_G)?$")

# Boolean combat keywords worth reporting on a board.
KEYWORDS = ("TAUNT", "DIVINE_SHIELD", "REBORN", "WINDFURY", "POISONOUS",
            "VENOMOUS", "STEALTH", "LIFESTEAL", "DEATHRATTLE", "BATTLECRY")

# Plain Entity=<name> tag=<tag> value=<value> (account entity, e.g. gold).
NAME_TAG = re.compile(r"Entity=([^ ]+) tag=(\w+) value=(\w+)")

# SHOW_ENTITY - Updating Entity=<id> CardID=<card> (plain form).
SHOW_ENTITY = re.compile(r"SHOW_ENTITY - Updating Entity=(\d+) CardID=(\w+)")


class GameState:
    """Tracks the evolving state of one Battlegrounds game from raw log lines."""

    def __init__(self):
        self.card = {}          # entity id -> card id
        self.player = {}        # entity id -> player number
        self.zone = {}          # entity id -> zone
        self.zone_pos = {}      # entity id -> ZONE_POSITION
        self.cardtype = {}      # entity id -> CARDTYPE
        self.atk = {}           # entity id -> attack
        self.health = {}        # entity id -> health
        self.tribe = {}         # entity id -> CARDRACE
        self.tier = {}          # entity id -> TECH_LEVEL (minion tier)
        self.keywords = defaultdict(set)  # entity id -> set of keywords
        self.gold_max = {}      # account -> RESOURCES (this turn's purse)
        self.gold_used = {}     # account -> RESOURCES_USED (spent this turn)
        self.gold_temp = {}     # account -> TEMP_RESOURCES (hero-power gold)
        self.gold = {}          # account -> available gold (purse - spent)
        self.hero_meta = defaultdict(dict)  # hero card -> {tier, armor}
        self.hero_stat_log = []  # (card, tag, value) hero ARMOR/HEALTH writes
        self.snapshots = []     # board snapshots, one per minion entering PLAY
        self.current_entity = None
        self._game_ended = False  # set on PLAYSTATE=WON/LOST; stops snapshots
        self._post_game = set()   # entity ids created after game end (re-created)

    def _set_gold(self, name):
        """Available gold = this turn's purse minus what's already spent.

        RESOURCES alone is the full allotment and never changes mid-turn; the
        game tracks spending in RESOURCES_USED. Subtracting it is what makes
        mid-turn advice judge affordability against gold the player actually
        has (the 2026-09-03 "coach doesn't understand gold" complaint).
        """
        self.gold[name] = max(
            0,
            (self.gold_max.get(name) or 0)
            + (self.gold_temp.get(name) or 0)
            - (self.gold_used.get(name) or 0),
        )

    def feed(self, line):
        m = ENTITY_TAG.search(line)
        if m:
            ename, eid, cid, p, tag, value = m.groups()
            eid = int(eid)
            self.card[eid] = cid
            self.player[eid] = int(p)
            self._apply(eid, tag, value)
            return

        m = NAME_HERO.search(line)
        if m:
            # account name -> hero entity; not needed for the board, skip.
            return

        m = NAME_TAG.search(line)
        if m:
            name, tag, value = m.groups()
            if tag == "RESOURCES":
                self.gold_max[name] = int(value)
                self._set_gold(name)
            elif tag == "RESOURCES_USED":
                self.gold_used[name] = int(value)
                self._set_gold(name)
            elif tag == "TEMP_RESOURCES":
                # Hero powers grant temp gold this turn; it is spendable.
                self.gold_temp[name] = int(value)
                self._set_gold(name)
            elif tag == "PLAYSTATE" and value in ("WON", "LOST"):
                # Game over: the end-of-game cleanup re-creates minions as
                # enchantments for the leaderboard, so stop snapshotting here.
                self._game_ended = True
            return

        m = SHOW_ENTITY.search(line)
        if m:
            self.card[int(m.group(1))] = m.group(2)
            return

        m = FULL_ENTITY.search(line)
        if m:
            self.current_entity = int(m.group(1))
            self.card[self.current_entity] = m.group(2)
            if self._game_ended:
                self._post_game.add(self.current_entity)
            return

        m = FULL_ENTITY_UPDATING.search(line)
        if m:
            # PowerTaskList re-describes an existing entity (same id); retarget
            # current_entity so its tag lines land on it instead of corrupting
            # the previous Creating entity.
            inner = UPDATING_ENTITY_ID.search(m.group(1))
            if inner:
                self.current_entity = int(inner.group(1))
                if m.group(2):
                    self.card[self.current_entity] = m.group(2)
                if self._game_ended:
                    self._post_game.add(self.current_entity)
            return

        if "Entity=[" not in line:
            m = FULL_TAG.search(line)
            if m and self.current_entity is not None:
                tag, value = m.groups()
                self._apply(self.current_entity, tag, value)
            return

        m = ZONE_PLAIN.search(line)
        if m:
            self.zone[int(m.group(1))] = m.group(2)

    def _apply(self, eid, tag, value):
        if tag == "ZONE":
            old = self.zone.get(eid)
            self.zone[eid] = value
            # A minion played from hand is a board change; snapshot the board so
            # the "final board" can be read back before the end-of-game cleanup.
            # Only HAND->PLAY (shop-phase plays) is snapshotted — combat summons
            # (SETASIDE/GRAVEYARD->PLAY) are transient and would pollute the
            # board with deathrattle copies that die the same turn.
            if value == "PLAY" and old == "HAND" and not self._game_ended:
                if MINION_ONLY.match(self.card.get(eid, "")):
                    self._record_snapshot()
            # A minion LEAVING PLAY also snapshots: combat deaths are the
            # first reliable point where BOTH boards are fully set (the
            # opponent's combat minions often enter from SETASIDE, which
            # never snapshotting would miss them entirely — the scout's
            # per-turn capture depends on this, 2026-09-04 Holmes game).
            elif (old == "PLAY" and value != "PLAY"
                  and not self._game_ended
                  and MINION_ONLY.match(self.card.get(eid, ""))):
                self._record_snapshot()
        elif tag == "ZONE_POSITION":
            self.zone_pos[eid] = int(value)
        elif tag in ("CONTROLLER", "PLAYER"):
            # FULL_ENTITY blocks assign ownership via CONTROLLER (a
            # TAG_CHANGE carries it in the Entity=[...player=N] header) —
            # without this, combat-created minions have player None and the
            # friendly/opponent split (and the scout) can't tell sides.
            self.player[eid] = int(value)
        elif tag == "CARDTYPE":
            self.cardtype[eid] = value
        elif tag == "ATK":
            self.atk[eid] = int(value)
        elif tag == "HEALTH":
            self.health[eid] = int(value)
            cid = self.card.get(eid, "")
            if HERO_CARD.match(cid):
                # The friendly hero's health — the dying-vs-leveling signal.
                self.hero_meta[cid]["health"] = int(value)
                self.hero_stat_log.append((cid, "HEALTH", int(value)))
        elif tag == "CARDRACE":
            self.tribe[eid] = value
        elif tag == "TECH_LEVEL":
            self.tier[eid] = int(value)
        elif tag == "PLAYER_TECH_LEVEL":
            cid = self.card.get(eid, "")
            if HERO_CARD.match(cid):
                self.hero_meta[cid]["tier"] = int(value)
        elif tag == "ARMOR":
            cid = self.card.get(eid, "")
            if HERO_CARD.match(cid):
                self.hero_meta[cid]["armor"] = int(value)
                self.hero_stat_log.append((cid, "ARMOR", int(value)))
        elif tag in KEYWORDS:
            if value == "1":
                self.keywords[eid].add(tag)
            else:
                self.keywords[eid].discard(tag)

    def _minion(self, eid, cid):
        golden = cid.endswith("_G")
        if golden:
            cid = cid[:-2]  # strip the _G suffix -> base card id
        return {
            "card": cid,
            "golden": golden,
            "player": self.player.get(eid),
            "atk": self.atk.get(eid),
            "health": self.health.get(eid),
            "tribe": self.tribe.get(eid),
            "tier": self.tier.get(eid),
            "pos": self.zone_pos.get(eid),
            "keywords": sorted(self.keywords.get(eid, ())),
        }

    def _record_snapshot(self):
        """Record the current board (minions in PLAY, cardtype=MINION).

        Stats are frozen at snapshot time so the opponent board (which is moved
        to REMOVEDFROMGAME and reset to base at game end) keeps its buffed
        stats. The friendly board is read from the re-created entities in PLAY
        at game end instead.
        """
        board = []
        for eid, cid in self.card.items():
            if not MINION_ONLY.match(cid):
                continue
            ct = self.cardtype.get(eid)
            if ct is not None and ct != "MINION":
                continue
            if self.zone.get(eid) != "PLAY":
                continue
            board.append(self._minion(eid, cid))
        self.snapshots.append(board)

    def final_board(self, friendly_player):
        """The final board, split friendly vs opponents.

        Friendly board: minions in PLAY at game end (re-created entities with
        buffed stats). Opponent board: the last snapshot (during the game),
        since the opponents' minions are moved to REMOVEDFROMGAME and reset to
        base at game end.
        """
        friendly_board, _ = self.board(friendly_player)
        opponent_board = []
        for board in reversed(self.snapshots):
            ob = [m for m in board if m["player"] != friendly_player]
            if ob:
                ob.sort(key=lambda m: m["card"])
                opponent_board = ob
                break
        return friendly_board, opponent_board

    def board(self, friendly_player):
        """Minions currently in ZONE=PLAY, split friendly vs opponents."""
        friendly_board, opponent_board = [], []
        for eid, cid in self.card.items():
            if not MINION_ONLY.match(cid):
                continue
            ct = self.cardtype.get(eid)
            if ct is not None and ct != "MINION":
                continue
            if self.zone.get(eid) != "PLAY":
                continue
            m = self._minion(eid, cid)
            if self.player.get(eid) == friendly_player:
                friendly_board.append(m)
            else:
                opponent_board.append(m)
        friendly_board.sort(key=lambda m: (m["pos"] is None, m["pos"] or 0))
        opponent_board.sort(key=lambda m: m["card"])
        return friendly_board, opponent_board

    def hand(self, friendly_player):
        """Cards in ZONE=HAND (bought, not yet played/cast), friendly only.

        Minions AND tavern spells: casting a spell from hand is free, and a
        minion stuck in hand (full board) plays free — both are decisions the
        coach must see. Each entry carries "type" ("minion"/"spell"); spell
        filtering (real tavern spells vs generated junk) happens upstream
        where the spell DB lives.
        """
        hand = []
        for eid, cid in self.card.items():
            if not MINION_ONLY.match(cid):
                continue
            ct = self.cardtype.get(eid)
            if ct not in ("MINION", "SPELL"):
                continue
            if self.zone.get(eid) != "HAND":
                continue
            if self.player.get(eid) != friendly_player:
                continue
            m = self._minion(eid, cid)
            m["type"] = "spell" if ct == "SPELL" else "minion"
            hand.append(m)
        hand.sort(key=lambda m: (m["pos"] is None, m["pos"] or 0))
        return hand


def _fmt_minion(m):
    parts = [m["card"]]
    if m["tribe"]:
        parts.append(m["tribe"])
    if m["tier"] is not None:
        parts.append(f"t{m['tier']}")
    atk = m["atk"] if m["atk"] is not None else "?"
    hp = m["health"] if m["health"] is not None else "?"
    parts.append(f"{atk}/{hp}")
    if m["keywords"]:
        parts.append(",".join(m["keywords"]))
    return "  ".join(parts)


def main():
    if len(sys.argv) < 2:
        print("usage: python board_state.py <Power.log> [--games N]")
        return 1
    log_path = sys.argv[1]
    limit = None
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
        friendly = _friendly_player(game["heroes"])

        friendly_hero = None
        for h in game["heroes"]:
            if h["player"] == friendly:
                friendly_hero = h["card"]
                break
        friendly_account = None
        for name, cid in game["account"].items():
            if cid == friendly_hero:
                friendly_account = name
                break

        gs = GameState()
        for line in chunk:
            gs.feed(line)

        friendly_board, opponent_board = gs.final_board(friendly)
        hand = gs.hand(friendly)
        meta = gs.hero_meta.get(friendly_hero, {}) if friendly_hero else {}
        tier = meta.get("tier")
        armor = meta.get("armor")
        gold = gs.gold.get(friendly_account) if friendly_account else None

        print(f"\n=== Game {idx} ===")
        print(f"Friendly: {friendly_account or '?'} (player={friendly}) "
              f"tier={tier if tier is not None else '?'} "
              f"gold={gold if gold is not None else '?'} "
              f"armor={armor if armor is not None else '?'}")
        print(f"  Board ({len(friendly_board)}):")
        for m in friendly_board:
            print(f"    {_fmt_minion(m)}")
        if hand:
            print(f"  Hand ({len(hand)}):")
            for m in hand:
                print(f"    {_fmt_minion(m)}")
        print(f"  Opponents (combined, {len(opponent_board)} minions):")
        for m in opponent_board:
            print(f"    {_fmt_minion(m)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
