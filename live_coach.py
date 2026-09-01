"""Incremental live coach: maintains the parse as lines arrive.

The batch `coach.analyze(path, gi)` re-reads and re-parses the whole Power.log
(40-120 MB) on every buy phase (~2s), which makes the live overlay lag. This
module feeds lines into a persistent GameState + action tracker as they arrive,
and caches per-game data (heroes, bans, comps), so each buy-phase analysis is
fast (board + gold + sell from the current state, no re-parse).

Usage (from live.py):
    coach = LiveCoach()
    for line in new_lines: coach.feed(line)
    analysis = coach.analyze()   # fast, on each buy phase
"""
import json
import os
import re

from board_state import GameState
from extract_game import extract_game, _friendly_player
from tribes import normalize
from bans import bans_from_log, filter_comps_by_available_tribes, _load_card_races, _HERE
from meta import hero_power as _hero_power_text
from tribes import DISPLAY_TRIBES, normalize
from player_actions import (
    STEP_RE, _GS, ENTITY, MINION_ONLY, CHOICE,
    _load_bg_pool, _load_bg_minion_ids,
)
from value import sell_recommendation, shop_ranking, top_move, comp_target, target_state

_TRIGGER_KEYS = ("cast_spell", "play_elemental", "play_mech", "play_naga",
                 "play_tier3_or_lower", "discover")
_GAME_START = re.compile(r"GameState\.DebugPrintPower.*CREATE_GAME")
_SEED = re.compile(r"GAME_SEED value=(\d+)")
# A spell cast = a PLAY block on a non-minion card. Captures entityName so shop
# buttons (Refresh/Freeze/Tavern Tier/Drag To Buy/Dark Discovery) are excluded by
# name, matching the batch parser's spell heuristic.
_SPELL = re.compile(_GS + r"BlockType=PLAY Entity=\[entityName=([^]]+) cardId=(\w+)")
_SHOP_BUTTON_NAMES = ("Refresh", "Freeze", "Tavern Tier", "Drag To Buy",
                      "Dark Discovery")
# A tavern offer: a DebugPrintOptions POWER option whose mainEntity is a real
# card — minion or tavern spell (BG/BGS spell ids match MINION_ONLY too; the
# minion/spell split happens in shop_ranking, which has the spell DB). Captures
# cardId and the owning player, so the player's own minions (shown as sell
# options) are excluded from the shop.
# e.g. "option 4 type=POWER mainEntity=[entityName=X cardId=BG36_345 .. player=15]"
_SHOP_OPT = re.compile(r"DebugPrintOptions\(\).*?cardId=(\w+)[^\]]*player=(\d+)")
# A new options block starts (GameState). Options re-print after every game
# event; each block is the authoritative current shop.
_OPTIONS_HEADER = re.compile(r"GameState\.DebugPrintOptions\(\) -\s+id=\d+")


def _banned(allowed):
    # Unknown ban info (None) shows as no banned tribes, never "all banned".
    if not allowed:
        return []
    return [t for t in DISPLAY_TRIBES if t not in set(allowed)]


class _LiveActions:
    """Incrementally track per-turn trigger counts (spells, tribe plays).

    Plays are stored with their player number and filtered to the friendly
    player at scenario() time (the friendly number is only known once the hero
    selection is parsed). Spells are counted only during the buy phase.
    """

    def __init__(self):
        self.pool = _load_bg_pool()
        self.minion_ids = _load_bg_minion_ids()
        self.friendly = None
        self.turn = 0
        self.in_buying = False
        self.spells = 0
        self.discovers = 0
        self.plays = []  # (player, card) this turn
        self.zone = {}
        self.player = {}
        self.turn_spells = []
        self.turn_discovers = []
        self.turn_plays = []

    def feed(self, line):
        m = STEP_RE.search(line)
        if m:
            # Both GameState and PowerTaskList log tag=STEP lines; the PTL copy
            # arrives after GameState's MAIN_END and would spawn a spurious
            # turn. Only GameState steps delimit turns.
            if "PowerTaskList" in line:
                m = None
            if m and m.group(1) == "MAIN_ACTION" and not self.in_buying:
                # The first MAIN_ACTION of a game is a real buy phase.
                self._end_turn()
                self.turn += 1
                self.in_buying = True
            elif m and m.group(1) == "MAIN_END":
                self.in_buying = False
            return

        m = _SPELL.search(line)
        if m:
            ename, cid = m.group(1), m.group(2)
            # A spell cast: a PLAY on a non-minion, non-shop-button, non-hero-power
            # card during the buy phase (matches the batch parser's heuristic).
            if self.in_buying and cid not in self.minion_ids \
                    and not cid.startswith("TB_BaconShop_DragBuy") and "HERO" not in cid \
                    and not ename.startswith(_SHOP_BUTTON_NAMES):
                self.spells += 1
            return

        m = CHOICE.search(line)
        if m:
            self.discovers += 1  # a Discover pick (Hero/trinket/dark-gift pick)
            return

        m = ENTITY.search(line)
        if m:
            _name, eid, z, _pos, cid, p = m.groups()
            if not MINION_ONLY.match(cid):
                return
            eid, p = int(eid), int(p)
            old = self.zone.get(eid)
            self.zone[eid] = z
            self.player[eid] = p
            if z == "PLAY" and old == "HAND":
                self.plays.append((p, cid))

    def _end_turn(self):
        self.turn_spells.append(self.spells)
        self.turn_discovers.append(self.discovers)
        self.turn_plays.append(self.plays)
        self.spells = 0
        self.discovers = 0
        self.plays = []

    def scenario(self):
        maxes = {k: 0 for k in _TRIGGER_KEYS}
        totals = {k: 0 for k in _TRIGGER_KEYS}
        for spells, discovers, plays in zip(self.turn_spells, self.turn_discovers,
                                            self.turn_plays):
            totals["cast_spell"] += spells
            maxes["cast_spell"] = max(maxes["cast_spell"], spells)
            totals["discover"] += discovers
            maxes["discover"] = max(maxes["discover"], discovers)
            pe = pm = pn = pt = 0
            for p, cid in plays:
                if self.friendly is not None and p != self.friendly:
                    continue
                info = self.pool.get(cid)
                if not info:
                    continue
                tribe = normalize(info.get("tribe"))
                tier = info.get("tier")
                if tribe == "Elemental":
                    pe += 1
                elif tribe == "Mech":
                    pm += 1
                elif tribe == "Naga":
                    pn += 1
                if tier is not None and tier <= 3:
                    pt += 1
            for k, v in (("play_elemental", pe), ("play_mech", pm),
                         ("play_naga", pn), ("play_tier3_or_lower", pt)):
                totals[k] += v
                maxes[k] = max(maxes[k], v)
        out = {}
        for k in _TRIGGER_KEYS:
            out[k] = maxes[k]
            out[k + "_total"] = totals[k]
        out["turns"] = self.turn
        return out


class LiveCoach:
    """Feeds lines incrementally; analyze() is fast on each buy phase."""

    def __init__(self):
        self.gs = GameState()
        self.actions = _LiveActions()
        self.cur_lines = []
        self.shop_cards = []
        self._reset_meta()

    def _reset_meta(self):
        self.meta = None
        self.friendly = None
        self.hero_card = None
        self.hero_name = None
        self.account = None
        self.allowed = None
        self.playable = None

    def _reset(self):
        self.gs = GameState()
        self.actions = _LiveActions()
        self.cur_lines = []
        self.shop_cards = []
        self._reset_meta()

    def feed(self, line):
        if _GAME_START.search(line):
            self._reset()
        # The shop changes at a new buy phase, on a refresh (re-roll), or on a
        # buy; reset so the next DebugPrintOptions block rebuilds it from the
        # current offers. (Only actual PLAY actions for refresh/buy, not the
        # DebugPrintOptions buttons.)
        if "tag=STEP value=MAIN_ACTION" in line \
                or "BlockType=PLAY Entity=[entityName=Refresh " in line \
                or ("BlockType=PLAY Entity=[entityName=Drag To Buy " in line and "Target=" in line):
            self.shop_cards = []
        # The game re-prints ALL options after every event; each new options
        # block starts with "DebugPrintOptions() - id=N". Treat the shop as the
        # most recent block: reset on block start so stale generations
        # (including discover choices) don't accumulate in the ranking.
        if _OPTIONS_HEADER.search(line):
            self.shop_cards = []
        m = _SHOP_OPT.search(line)
        if m:
            cid, p = m.group(1), int(m.group(2))
            # Keep every card option, minions and tavern spells (shop offers are
            # owned by the tavern player; the friendly player's own board/hand
            # minions — and the spells they cast — are filtered in analyze()).
            if MINION_ONLY.match(cid) and "HERO" not in cid \
                    and all(cid != c for c, _ in self.shop_cards):
                self.shop_cards.append((p, cid))
            return
        self.gs.feed(line)
        self.actions.feed(line)
        self.cur_lines.append(line)

    def _ensure_meta(self):
        """Compute per-game data once heroes are parsed; retry until they are."""
        if self.friendly is not None or not self.cur_lines:
            return
        meta = extract_game(self.cur_lines)
        friendly = _friendly_player(meta["heroes"])
        if friendly is None:
            return  # no heroes parsed yet (very early / end-of-game); retry next analyze
        self.meta = meta
        self.friendly = friendly
        hero = next((h for h in meta["heroes"] if h["player"] == friendly), None)
        self.hero_card = hero["card"] if hero else None
        self.hero_name = hero["hero_name"] if hero else None
        self.account = next((n for n, c in meta["account"].items()
                             if c == self.hero_card), None)
        self.actions.friendly = self.friendly

        card_races = _load_card_races(os.path.join(_HERE, ".card_races.json"))
        seed_m = _SEED.search("".join(self.cur_lines))
        seed = seed_m.group(1) if seed_m else None
        # No seed match (or no pool minions yet) = no ban info: fail OPEN
        # (None), never "all tribes banned".
        allowed = None
        for g in bans_from_log(None, card_races, lines=self.cur_lines):
            if g["seed"] == seed:
                allowed = g["allowed"]
                break
        self.allowed = allowed
        with open(os.path.join(_HERE, "meta", "comps.json"), encoding="utf-8") as f:
            comps = json.load(f)
        self.playable = filter_comps_by_available_tribes(comps, card_races, allowed)

    def tavern_offers(self):
        """Minion card ids offered by the tavern right now — excludes the
        friendly player's own minions, which DebugPrintOptions lists as sell
        options (they arrive BEFORE the actual shop offers)."""
        return [c for p, c in self.shop_cards
                if self.friendly is None or p != self.friendly]

    def state_fingerprint(self):
        """A cheap fingerprint of everything the advice depends on.

        (gold, tier, board, tavern offers) — the monitor re-advises whenever
        this changes during a buy phase, so buys/rolls/plays/sells mid-turn
        update the advice instead of waiting for the next buy phase. None
        before the hero is parsed (nothing to fingerprint yet).
        """
        if self.friendly is None:
            return None
        board, _ = self.gs.final_board(self.friendly)
        return (
            self.gs.gold.get(self.account) if self.account else None,
            self.gs.hero_meta.get(self.hero_card, {}).get("tier"),
            tuple(sorted((m["card"], m.get("atk") or 0, m.get("health") or 0,
                          m.get("golden") or False) for m in board)),
            tuple(self.tavern_offers()),
        )

    def analyze(self):
        """Fast per-buy-phase analysis from the current incremental state."""
        self._ensure_meta()
        if self.friendly is None:
            return None  # no game/hero yet — nothing to analyze
        board, _ = self.gs.final_board(self.friendly)
        tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier")
        gold = self.gs.gold.get(self.account) if self.account else None
        scenario = self.actions.scenario()
        hero_power = _hero_power_text(self.hero_name)
        ranked = sell_recommendation(board, self.playable, self.allowed,
                                     scenario=scenario, hero_power=hero_power)
        # The shop = the DebugPrintOptions offers owned by anyone but the friendly
        # player (the player's own minions are shown as sell options, not offers).
        offer_ids = []
        seen = set()
        for p, c in self.shop_cards:
            if p != self.friendly and c not in seen:
                offer_ids.append(c)
                seen.add(c)
        shop = shop_ranking(offer_ids, self.playable, board,
                            self.allowed, hero_power=hero_power,
                            scenario=scenario) if offer_ids else []
        target = comp_target(board, self.playable)
        result = {
            "hero": self.hero_name,
            "tier": tier,
            "gold": gold,
            "board": board,
            "banned": _banned(self.allowed),
            "playable_comps": self.playable,
            "sell_rank": ranked,
            "shop_rank": shop,
            "buy_this": shop[0][0] if shop else None,
            "target_comp": target["name"] if target else None,
            "target_state": target_state(target, board),
            "scenario": scenario,
        }
        result["top_move"] = top_move(result)
        return result
