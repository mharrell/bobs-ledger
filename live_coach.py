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
from extract_game import extract_game, _friendly_player, MINION_ID
from tribes import normalize
from bans import bans_from_log, filter_comps_by_available_tribes, _load_card_races, _HERE
import meta
import pool
from meta import hero_power as _hero_power_text
from tribes import DISPLAY_TRIBES, normalize
from player_actions import (
    STEP_RE, _GS, ENTITY, CHOICE,
    _load_bg_pool, _load_bg_minion_ids,
)
from choices import _CHOICE_HEADER, _CHOICE_OPT, _CHOICE_SOURCE, _CHOSEN, choice_kind, rank_choices
from value import (
    comp_cards, comp_progress, sell_recommendation, shop_ranking, top_move,
    comp_target, target_state, hand_plan, _load_spell_db, _core_hits,
    situation_line, sticky_comp_target, combat_forecast,
)

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
# card — minion or tavern spell (BG/BGS spell ids match MINION_ID too; the
# minion/spell split happens in shop_ranking, which has the spell DB). Captures
# the entity id (for exact COST pricing) and the owning player, so the player's
# own minions (shown as sell options) are excluded from the shop.
# e.g. "option 4 type=POWER mainEntity=[entityName=X id=12023 zone=PLAY
#       zonePos=1 cardId=BG36_345 .. player=15]"
_SHOP_OPT = re.compile(
    r"DebugPrintOptions\(\).*?id=(\d+)[^\]]*cardId=(\w+)[^\]]*player=(\d+)")
# The zone layer: shop offers tracked from ENTITY WRITES, not options blocks.
# During a mid-phase roll/buy storm the client barely re-prints options (the
# 2026-09-10 game's t13: 9 rolls, 2 block headers in 4.6s) and the next
# Refresh/Drag To Buy resets the buffered block before the deferred commit
# can fire — so between actions the coach's shop was blank (the lobby's only
# Felfire Conjurer sat in the shop at 23:27:30 with the coach structurally
# unable to see it). The writes themselves are reliable: every offer gets
# HAS_DRAG_TO_BUY=1 (minions and tavern spells), and leaves the shop via
# ZONE REMOVEDFROMGAME (replaced/re-rolled) or ZONE HAND (bought — GRAVEYARD
# for a bought-then-cast spell). GameState lines only: the PowerTaskList
# copies duplicate every write for no signal.
_POWER = r"GameState\.DebugPrintPower\(\) - "
_CREATE = re.compile(_POWER + r"\s*FULL_ENTITY - Creating ID=(\d+) CardID=(\w+)")
_SHOW_ENT = re.compile(_POWER + r"\s*SHOW_ENTITY - Updating Entity=(\d+) CardID=(\w+)")
_ENT_UPD = re.compile(
    _POWER + r"\s*FULL_ENTITY - Updating \[[^\]]*?id=(\d+)[^\]]*\] CardID=(\w+)")
# A TAG_CHANGE naming an entity — bracketed (id inside) or bare Entity=<id>.
_ENT_REF = re.compile(
    r"TAG_CHANGE Entity=(?:\[[^\]]*?id=(\d+)[^\]]*\]|(\d+)) tag=(\w+) value=(\S+)")
# A SHOP block carries the tavern buttons as options (Refresh / Freeze /
# Drag To Sell / Drag To Buy — all TB_BaconShop_* card ids). Other options
# blocks share the wire format: a Murloc Holmes discovery block offered the
# shop's own Waverider as a choice (2026-09-05) and the old parse swallowed
# it as the whole shop — the Tavern box showed one card at a wrong price.
# Only blocks with a button option commit as the shop.
_SHOP_BUTTON_OPT = re.compile(
    r"GameState\.DebugPrintOptions\(\) -\s+option \d+ type=POWER "
    r"mainEntity=\[[^\]]*cardId=TB_BaconShop_?(?:8p_Reroll_Button|"
    r"LockAll_Button|DragSell|DragBuy|TechUp)")
# A new options block starts (GameState). Options re-print after every game
# event; each block is the authoritative current shop.
_OPTIONS_HEADER = re.compile(r"GameState\.DebugPrintOptions\(\) -\s+id=\d+")
# A board-minion ACTIVATION option: "option 7 type=POWER mainEntity=[...
# zone=PLAY ... cardId=X player=F] error=NONE" — error=NONE means the
# activation is usable RIGHT NOW (the game re-prints options after every
# action, so exhaustion shows up as REQ_NOT_EXHAUSTED_ACTIVATE /
# REQ_ENOUGH_MANA). Zone=PLAY only: a POWER option on a HAND minion is the
# play action, not an activation. Owned by the friendly player (shop copies
# of the same card belong to the tavern/opponent).
_ACT_OPT = re.compile(
    r"GameState\.DebugPrintOptions\(\) -\s+option \d+ type=POWER "
    r"mainEntity=\[entityName=[^\]]*zone=(\w+)[^\]]*cardId=(\w+)"
    r"[^\]]*player=(\d+)\] error=(\w+)")
# The tavern upgrade button: "Tavern Tier N" (TechUp0N = upgrade TO tier N).
# Its COST tag is the REAL upgrade price this turn — BG prices start at
# (target+3) gold and drop 1 at the start of each round you wait, so the old
# tier+1 model was wrong every turn (2026-09-03: turn-1 "level + buy" with 3
# gold is impossible; the turn-1 button costs 5).
# e.g. "TAG_CHANGE Entity=[entityName=Tavern Tier 3 id=1013 ...
#       cardId=TB_BaconShopTechUp03_Button player=7] tag=COST value=6"
_TECHUP = re.compile(r"entityName=Tavern Tier (\d+) id=(\d+)[^\]]*player=(\d+)")
_TECHUP_TAG = re.compile(r"tag=(ZONE|COST|TECH_LEVEL) value=(\S+)")
# The buy-phase scout: the pairing announced on the friendly hero (or the
# account entity) names the player of the fight after this shopping phase.
# e.g. "TAG_CHANGE Entity=[entityName=Guff Runetotem id=117 zone=PLAY
#       zonePos=0 cardId=BG20_HERO_242 player=3] tag=NEXT_OPPONENT_PLAYER_ID value=4"
# and the bare form "TAG_CHANGE Entity=<account> tag=NEXT_OPPONENT_PLAYER_ID value=1"
_NEXT_OPP = re.compile(
    r"TAG_CHANGE Entity=(?:\[entityName=[^\]]*? cardId=(\S+)"
    r"[^\]]*?player=(\d+)\]|(\S+)) tag=NEXT_OPPONENT_PLAYER_ID value=(\d+)")


def _banned(allowed):
    # Unknown ban info (None) shows as no banned tribes, never "all banned"
    # (the old code listed all 10 for None — the 2026-09-04 Guff overlay).
    if not allowed:
        return []
    return [t for t in DISPLAY_TRIBES if t not in set(allowed)]


def _median(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


_BASELINE = None


def _load_baseline():
    """meta/turn_baseline.json — corpus median board stats by turn
    (built by build_baseline.py from our own Power.log corpus)."""
    global _BASELINE
    if _BASELINE is None:
        try:
            with open(os.path.join(_HERE, "meta", "turn_baseline.json"),
                      encoding="utf-8") as f:
                _BASELINE = json.load(f)
        except OSError:
            _BASELINE = {}
    return _BASELINE


def _baseline_opp(turn):
    """Corpus median of the opponent boards fought at this turn (gate 3) —
    the "what does a board at turn N look like" prior."""
    data = (_load_baseline().get("opp") or {})
    if not data:
        return None
    for t in range(turn, -1, -1):
        rec = data.get(str(t)) or data.get(t)
        if rec:
            return rec.get("med")
    return None


def _estimate_board(snapshots, friendly, lookback=8):
    """The strongest recent snapshot of the friendly board.

    The estimate runs during the combat-teardown window (the real board is
    empty until the game re-adds it after the next shop prints). The LAST
    snapshot is the fight's END state — a won-but-costly fight shows the
    depleted remnant (2026-09-07 Tickatus game: the overlay read 'you 90'
    mid-turn on a 300-stat board — the player's 'my guys evaporated'
    report). The fullest recent snapshot is the buy-phase board: deaths
    only remove minions, so the pre-fight board is the high-water mark
    (a token-summon moment can briefly exceed it; acceptable for a
    transient estimate — the real board re-advises when it lands).
    """
    if not snapshots:
        return []
    recent = snapshots[-lookback:]

    def friendly_minions(snap):
        return [m for m in snap if m["player"] == friendly]

    best = max(recent, key=lambda snap: sum(
        (m.get("atk") or 0) + (m.get("health") or 0)
        for m in friendly_minions(snap)))
    return friendly_minions(best)


def _recent_acquisitions(plays, buys, last_plays, last_buys, friendly):
    """The last turn or two of friendly acquisitions, per-cid copies =
    max(#buys, #plays). A copy bought and then played is ONE acquisition,
    but the raw plays+buys sum counted it twice (2026-09-05 Holmes game:
    one bought-and-played Deathstrider read as 2 recent hits and "pivoted"
    the coach to Beasts over a six-naga board). Generated or discovered
    copies (played, never bought) still count via plays."""
    pl = [cid for p, cid in list(plays) + list(last_plays)
          if p == friendly]
    by = [cid for p, cid in list(buys) + list(last_buys)
          if p == friendly]
    copies = {}
    for cid in set(pl) | set(by):
        copies[cid] = max(by.count(cid), pl.count(cid))
    return [cid for cid, n in copies.items() for _ in range(n)]


def shop_cost_map(gs, offer_ids, eids=None):
    """Live COST-tag values for the shop offers, per entity.

    NOTE (2026-09-06): MINION tag=479 values are stale legacy tier costs —
    the patch prices ALL minions at a flat 3 (log ground truth: Buzzing
    Vermin/Decoy Conjurer charged RESOURCES_USED=3 with tags saying 1), so
    downstream consumers apply this map to SPELLS only. Kept for spell
    pricing (spells carry real per-spell COST tags) and for debugging.

    `eids` (shop card id -> offer entity id) prices the CURRENT shop's own
    entities — the 2026-09-05 Holmes game showed why: a discovery-pool
    Waverider carried COST 31 in SETASIDE, and card-id-keyed "later write
    wins" priced the shop's Waverider 31g. With entity ids, the shop's
    exact entity wins; the card-id scan (later entity wins, golden _G keeps
    its own COST and also maps the plain id) remains the fallback for ids
    the shop block didn't carry."""
    exact = {}
    if eids:
        for c in offer_ids:
            eid = eids.get(c)
            if eid is not None and gs.cost.get(eid) is not None:
                exact[c] = gs.cost[eid]
    cost_by_cid = {}
    for eid in sorted(gs.cost):
        cid = gs.card.get(eid)
        cost = gs.cost.get(eid)
        if cid and cost is not None:
            cost_by_cid[cid] = cost
            if cid.endswith("_G"):
                cost_by_cid.setdefault(cid[:-2], cost)
    cost_by_cid.update(exact)  # the shop's own entities win
    return {c: cost_by_cid[c] for c in offer_ids if c in cost_by_cid}


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
        self.buys = []   # (player, card) entering HAND this turn
        self.zone = {}
        self.player = {}
        self.turn_spells = []
        self.turn_discovers = []
        self.turn_plays = []
        self.turn_buys = []

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
            if not MINION_ID.match(cid):
                return
            eid, p = int(eid), int(p)
            old = self.zone.get(eid)
            self.zone[eid] = z
            self.player[eid] = p
            if z == "PLAY" and old == "HAND":
                self.plays.append((p, cid))
            # An acquisition: a minion entering HAND (a buy from the tavern,
            # or a generated copy). Buying IS intention — the comp-evidence
            # contract used plays only, so a beasts build whose pieces sat in
            # hand (full board) or a bought-but-uncast spell was invisible
            # (the 2026-09-04 beasts game stayed comp-agnostic until t11).
            elif z == "HAND" and old != "HAND":
                self.buys.append((p, cid))

    def _end_turn(self):
        self.turn_spells.append(self.spells)
        self.turn_discovers.append(self.discovers)
        self.turn_plays.append(self.plays)
        self.turn_buys.append(self.buys)
        self.spells = 0
        self.discovers = 0
        self.plays = []
        self.buys = []

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


# Per-game state defaults — the single source of truth for __init__ AND
# _reset(). The two were previously hand-synced lists: a field added to one
# and not the other was a latent cross-game contamination bug (the previous
# game's value silently carried into the new one). Callable values are
# factories (fresh list/dict/set per game); plain values are immutable.
_GAME_DEFAULTS = {
    "cur_lines": list,
    "shop_cards": list,
    "shop_eids": dict,       # shop card id -> offer entity id (exact pricing)
    "_sticky_target": None,  # last shown comp, for sticky same-tribe direction
    "_pending_shop": list,   # offers buffered for the open options block
    "_pending_is_shop": False,  # the open block carries a tavern button
    "_ent_cid": dict,        # zone layer: entity id -> card id
    "_ent_ctl": dict,        # zone layer: entity id -> controller player
    "_zone_shop": dict,      # zone layer: entity id -> card id now offered
    "_zone_shop_p": dict,    # zone layer: entity id -> controller player
    "_zone_gone": set,       # zone layer: eids removed from the shop this phase
    "activations": list,     # board card ids with a usable Activate right now
    "_pending_activations": list,  # buffered for the open options block
    "choice": None,          # pending pick: {'kind','source','options','picked'}
    "techup": dict,          # TechUp button id -> {tier, player, cost, zone}
    "_last_tier": None,
    "_tier_seen_turn": None,  # turn the current tier was reached
    "_armor_hist": dict,     # turn -> {af, al, hf, hl} first/last armor+HP
    "_stat_seen": 0,         # hero_stat_log entries already drained
    "_stat_pending": list,   # (turn, cid, tag, value) before hero parse
    "next_opponent": None,   # announced NEXT_OPPONENT_PLAYER_ID
    "_pair_cand": None,      # pairing announced during the open buy phase
    "_pairing": dict,        # turn -> opponent id announced for its fight
    "_snap_by_turn": dict,   # turn -> [(player, stat_total), ...] snapshots
    "_resolved": set,        # turns already committed to the lobby stats
    "_opp_boards": dict,     # player id -> {"stats", "n", "turn"} last-known
    "_lobby_stats": list,    # stats of every opponent board we fought
    "_snap_seen": 0,         # snapshots already buffered
    "_shop_seen": dict,      # shop minion cid -> turn last offered (hunt evidence)
    "_shop_seen_eids": set,  # offer entity ids already recorded in _shop_seen
    "_phase": "buy",         # buy phase vs combat window (GameState STEP)
    "_bans_ready": False,
    "tribes_detecting": False,  # 5/5 ban set not confirmed yet (window state)
    "tribes_seen": 0,        # pure tribes the pool reveal has shown so far
    "_card_races": None,
    "_seed": None,
    "_comps": None,
}


class LiveCoach:
    """Feeds lines incrementally; analyze() is fast on each buy phase."""

    def __init__(self):
        self.gs = GameState()
        self.actions = _LiveActions()
        self.game_no = 0    # bumped by _reset() on each CREATE_GAME
        self._init_game_state()
        self._reset_meta()

    def _init_game_state(self):
        """Restore every per-game attribute from _GAME_DEFAULTS."""
        for name, default in _GAME_DEFAULTS.items():
            setattr(self, name, default() if callable(default) else default)

    def _reset_meta(self):
        self.meta = None
        self.friendly = None
        self.hero_card = None
        self.hero_name = None
        self.account = None
        self.allowed = None
        self.playable = None
        self.game_comps = None   # the comps panel's game-level list

    def _reset(self):
        self.gs = GameState()
        self.actions = _LiveActions()
        self.game_no += 1
        self._init_game_state()
        self._reset_meta()

    def feed(self, line):
        if _GAME_START.search(line):
            self._reset()
        # Phase tracking (GameState lines only — the PowerTaskList copies
        # arrive after and would flip the phase late): the window between
        # MAIN_END and the next MAIN_ACTION is combat. Snapshots captured
        # there are the real fight boards; buy-phase snapshots are shop plays
        # and the previous fight's teardown remnants, which must never be
        # committed as "the board we fought".
        if "GameState." in line:
            if "tag=STEP value=MAIN_END" in line:
                # The BUY-phase MAIN_END (the second one closes combat): the
                # pairing in force is the fight that follows. The tag only
                # logs on CHANGE — a same-player rematch never re-announces —
                # so the announced value persists until the next one.
                if self._phase == "buy":
                    self._pairing[self.actions.turn] = self._pair_cand
                self._phase = "combat"
            elif "tag=STEP value=MAIN_ACTION" in line:
                self._phase = "buy"
        # The shop changes at a new buy phase, on a refresh (re-roll), or on a
        # buy; reset so the next DebugPrintOptions block rebuilds it from the
        # current offers. (Only actual PLAY actions for refresh/buy, not the
        # DebugPrintOptions buttons.) Mid-phase, the zone layer below keeps
        # shop_cards populated between actions — the options block only
        # reliably commits at phase start (see the zone-layer regex comment).
        if "tag=STEP value=MAIN_ACTION" in line \
                or "BlockType=PLAY Entity=[entityName=Refresh " in line \
                or ("BlockType=PLAY Entity=[entityName=Drag To Buy " in line and "Target=" in line):
            # The action acted on the shop the open block describes — commit
            # it (and mirror it into the zone layer) before the wipe, or a
            # buy/roll that follows a block with no trailing header (the
            # mid-phase norm) would drop its offers entirely.
            self._flush_shop_block()
            self.shop_cards = []
            self.shop_eids = {}
            self._pending_shop = []
            self._pending_is_shop = False
            self._pending_activations = []
            if "MAIN_ACTION" in line:
                # Phase start: a fresh table — the phase's options block
                # re-mirrors every offer (frozen ones included, which get no
                # new HAS_DRAG_TO_BUY write). Mid-phase resets (Refresh / buy)
                # keep the table: the roll's own REMOVEDFROMGAME writes prune
                # it, and the new generation's HAS_DRAG_TO_BUY writes refill it.
                self._zone_shop = {}
                self._zone_shop_p = {}
                self._zone_gone = set()
            elif "Refresh" not in line:
                # Drag To Buy: drop the bought offer now (its ZONE HAND write
                # follows in the same block and would prune it anyway).
                mt = re.search(r"Target=\[[^\]]*?id=(\d+)", line)
                if mt:
                    self._zone_gone.add(int(mt.group(1)))
                    self._zone_shop.pop(int(mt.group(1)), None)
                    self._zone_shop_p.pop(int(mt.group(1)), None)
            self._zone_commit()
        # Zone layer: track entity card ids, controllers, and shop membership
        # from tag writes so the shop state is correct at ANY moment, not just
        # right after an options block commits.
        m = _ENT_REF.search(line)
        if m:
            eid = int(m.group(1) or m.group(2))
            tag, val = m.group(3), m.group(4)
            if tag == "HAS_DRAG_TO_BUY" and val == "1":
                cid = self._ent_cid.get(eid)
                # HAS_DRAG_TO_BUY=1 also lands on the friendly player's own
                # board minions (drag-to-sell) and hand cards (drag-to-play);
                # controller is the discriminator — offers belong to the
                # tavern player (9/14/15... per game), never to us.
                ctl = self._ent_ctl.get(eid)
                if cid and MINION_ID.match(cid) and "HERO" not in cid \
                        and (self.friendly is None or ctl != self.friendly):
                    self._zone_shop[eid] = cid
                    self._zone_shop_p[eid] = ctl
                    self._zone_commit()
            elif tag == "CONTROLLER":
                self._ent_ctl[eid] = int(val)
                if eid in self._zone_shop:
                    if self.friendly is not None \
                            and int(val) == self.friendly:
                        # an own-card controller surfacing late: evict
                        del self._zone_shop[eid]
                        del self._zone_shop_p[eid]
                    else:
                        self._zone_shop_p[eid] = int(val)
            elif tag == "ZONE" and val in ("REMOVEDFROMGAME", "GRAVEYARD",
                                           "HAND"):
                # Record the removal even if the table hasn't learned this
                # eid yet — the phase's options block may still be unflushed
                # and would otherwise re-add the dead offer at commit.
                self._zone_gone.add(eid)
                if eid in self._zone_shop:
                    del self._zone_shop[eid]
                    del self._zone_shop_p[eid]
                self._zone_commit()
        if "GameState." in line:
            for cre in (_CREATE, _SHOW_ENT, _ENT_UPD):
                cm = cre.search(line)
                if cm:
                    self._ent_cid[int(cm.group(1))] = cm.group(2)
                    break
        # The game re-prints ALL options after every event; each new options
        # block starts with "DebugPrintOptions() - id=N". Offers BUFFER per
        # block and commit only when the block carries a tavern button —
        # discovery/choice blocks share the options format and must not
        # replace the shop (see _SHOP_BUTTON_OPT).
        if _OPTIONS_HEADER.search(line):
            self._flush_shop_block()
            self._pending_shop = []
            self._pending_is_shop = False
            self._pending_activations = []
        if _SHOP_BUTTON_OPT.search(line):
            self._pending_is_shop = True
        m = _ACT_OPT.search(line)
        if m:
            zone, cid, p, err = m.group(1), m.group(2), int(m.group(3)), \
                m.group(4)
            if (zone == "PLAY" and err == "NONE"
                    and self.friendly is not None and p == self.friendly
                    and cid not in self._pending_activations):
                self._pending_activations.append(cid)
        # The pending pick (hero / trinket / discover): a choice block opens,
        # then the player's SendChoices resolves it. Track but fall through —
        # actions.feed counts SendChoices for the discover trigger counts.
        if "GameState.DebugPrintEntityChoices" in line:
            m = _CHOICE_HEADER.search(line)
            if m:
                self.choice = {"ctype": m.group(3), "source": None,
                               "options": [], "picked": None}
            elif self.choice is not None:
                ms = _CHOICE_SOURCE.search(line)
                if ms:
                    self.choice["source"] = ms.group(1)
                else:
                    mo = _CHOICE_OPT.search(line)
                    if mo and all(mo.group(2) != c
                                  for _n, c in self.choice["options"]):
                        self.choice["options"].append((mo.group(1), mo.group(2)))
        m = _CHOSEN.search(line)
        if m and self.choice is not None:
            self.choice["picked"] = m.group(1)
        m = _SHOP_OPT.search(line)
        if m:
            eid, cid, p = int(m.group(1)), m.group(2), int(m.group(3))
            # Keep every card option, minions and tavern spells (shop offers are
            # owned by the tavern player; the friendly player's own board/hand
            # minions — and the spells they cast — are filtered in analyze()).
            if MINION_ID.match(cid) and "HERO" not in cid \
                    and all(cid != c for _e, c, _p in self._pending_shop):
                self._pending_shop.append((p, cid, eid))
            return
        # The tavern upgrade button's live price (see _TECHUP above). GameState
        # lines only: the PowerTaskList copies carry the same values, and the
        # end-of-turn teardown writes (COST 0 / prices after ZONE left PLAY)
        # must not pollute the record.
        if "TechUp" in line and "GameState" in line:
            self._feed_techup(line)
        self.gs.feed(line)
        self.actions.feed(line)
        self.cur_lines.append(line)
        # A turn boundary closes the previous combat. The pairing itself is
        # written when the buy phase closes (see the phase tracker above):
        # the fight belongs to the opponent announced while that buy phase
        # was open, persisted across turns because the tag only logs on
        # change. The BOARDS resolve lazily in _resolve_boards — the
        # friendly player id is only known once the hero parses, which may
        # be after the combat snapshots arrived (the 2026-09-04 Holmes
        # game captured nothing live for exactly this reason).
        # The buy-phase preview: NEXT_OPPONENT_PLAYER_ID on the friendly
        # hero (or the account entity) names the player of the fight after
        # this shopping phase; during combat it names the NEXT turn's fight.
        m = _NEXT_OPP.search(line)
        # Each alternative must actually IDENTIFY the friendly player: an
        # unbracketed entity leaves groups 1/2 None, and None == None (hero
        # not parsed yet) once passed the guard for every announcement.
        if m and ((m.group(1) is not None and m.group(1) == self.hero_card)
                  or (m.group(2) is not None
                      and m.group(2) == str(self.friendly))
                  or (m.group(3) is not None
                      and m.group(3) == self.account)):
            self.next_opponent = int(m.group(4)) or None
            # _pair_cand mirrors the tag value in force at all times (the
            # combat announcement of the NEXT fight is what pairs that fight
            # when its buy phase never re-announces — the tag only logs on
            # change); the pairing snapshot happens when the buy phase ends.
            self._pair_cand = self.next_opponent
        # Armor flow (Q0): stamp every friendly-hero ARMOR/HEALTH write with
        # the turn it arrived in, keeping first/last per turn — combat
        # damage = first minus last (the buy-phase state vs post-combat).
        if len(self.gs.hero_stat_log) > self._stat_seen:
            new = [(self.actions.turn, cid, tag, val)
                   for cid, tag, val in self.gs.hero_stat_log[self._stat_seen:]]
            self._stat_seen = len(self.gs.hero_stat_log)
            if self.hero_card:
                self._drain_stats(new)
            else:
                self._stat_pending.extend(new)  # drained once the hero parses
        # Scout: buffer the board snapshots PER TURN (player id + stat
        # totals; the opponent-side id is DYNAMIC per game — 11 in one game,
        # 13 in another — so the != friendly filter at resolve time is what
        # identifies it). Each snapshot carries the phase it was captured in
        # so the resolver can keep only real fight boards. Snapshots fire on
        # plays AND combat deaths, so a turn accumulates several.
        if len(self.gs.snapshots) > self._snap_seen:
            new = self.gs.snapshots[self._snap_seen:]
            self._snap_seen = len(self.gs.snapshots)
            for snap in new:
                self._snap_by_turn.setdefault(self.actions.turn, []).append({
                    "phase": self._phase,
                    "minions": [(m["player"],
                                 (m.get("atk") or 0) + (m.get("health") or 0))
                                for m in snap],
                })
        # Track when the friendly's tier changed, for the upgrade-price
        # fallback (the price drops 1 per turn you stay at a tier).
        if self.hero_card:
            tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier")
            if tier and tier != self._last_tier:
                if self._last_tier is not None:
                    self._tier_seen_turn = self.actions.turn
                self._last_tier = tier

    def _drain_stats(self, entries):
        """Record hero ARMOR/HEALTH/DAMAGE writes into the per-turn
        first/last history. A turn's record starts seeded with the previous
        turn's ending values (an armor-only combat still knows the health).
        DAMAGE: the current season logs hero damage as a DAMAGE tag with
        HEALTH staying at base — the series must use true HP (HEALTH -
        DAMAGE) or every loss streak reads zero (2026-09-08 Guff session:
        11 damage invisible all game)."""
        for turn, cid, tag, value in entries:
            if self.hero_card and cid != self.hero_card:
                continue
            v = int(value)
            rec = self._armor_hist.get(turn)
            if rec is None:
                prev = self._armor_hist.get(turn - 1) or {}
                rec = {"af": prev.get("al"), "hf": prev.get("hl"),
                       "df": prev.get("dl")}
                rec["al"] = rec["af"]
                rec["hl"] = rec["hf"]
                rec["dl"] = rec["df"]
                self._armor_hist[turn] = rec
            if tag == "ARMOR":
                rec["al"] = v
            elif tag == "DAMAGE":
                rec["dl"] = v
            else:
                rec["hl"] = v  # last write wins

    def _resolve_boards(self):
        """Commit buffered combat snapshots to the lobby scout (gates 3+4).

        Deferred until the friendly player id is known AND the turn's fight
        is over: only turns strictly before the current one are resolved, so
        a turn can never be marked from its own still-empty buy-phase data
        (the 2026-09-04 Guff game committed a 6-stat teardown remnant of the
        previous fight as the fought board and skipped every real fight).
        Within a completed turn, the COMBAT-phase snapshot with the MOST
        opponent presence is the board we fought — combat reveals their
        board progressively and deaths empty it toward the end, so the
        fullest view is the honest estimate. Buy-phase snapshots (shop plays
        and the previous fight's teardown remnants, which share the dynamic
        opponent-side id) are never committed. Credited to the pairing
        announced for that turn."""
        if self.friendly is None:
            return
        for t in sorted(self._snap_by_turn):
            if t < 1 or t >= self.actions.turn or t in self._resolved:
                continue
            snaps = [s for s in self._snap_by_turn[t]
                     if s.get("phase") == "combat"]
            if not snaps:
                snaps = self._snap_by_turn[t]
            self._resolved.add(t)
            best = None
            for snap in snaps:
                opp = [(p, s) for p, s in snap.get("minions", [])
                       if p not in (self.friendly, None)]
                stats = sum(s for _p, s in opp)
                if best is None or stats > best[0]:
                    best = (stats, len(opp))
            pid = self._pairing.get(t)
            if best and best[0] > 0 and pid is not None:
                rec = {"stats": best[0], "n": best[1], "turn": t}
                self._opp_boards[pid] = rec
                self._lobby_stats.append(rec)

    def _fresh_opp_stats(self, turn):
        """The next opponent's last-known board stats, if fresh enough."""
        rec = self._opp_boards.get(self.next_opponent)
        if rec and rec.get("turn", -99) >= turn - 2:
            return rec.get("stats")
        return None

    def _feed_techup(self, line):
        """Track the tavern upgrade button's live cost (see _TECHUP above)."""
        m = _TECHUP.search(line)
        if not m:
            return
        tgt, eid, p = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rec = self.techup.setdefault(eid, {"tier": tgt, "player": p,
                                           "cost": None, "zone": "PLAY"})
        rec["tier"], rec["player"] = tgt, p
        tm = _TECHUP_TAG.search(line)
        if not tm:
            return
        tag, value = tm.group(1), tm.group(2)
        if tag == "COST":
            # Death/teardown writes cost 0 or land after the button left PLAY;
            # only a positive cost on a live button is the real price.
            if rec["zone"] == "PLAY" and value.isdigit() and int(value) > 0:
                rec["cost"] = int(value)
        elif tag == "ZONE":
            rec["zone"] = value

    def _ensure_meta(self):
        """Compute per-game data once heroes are parsed; retry until they are."""
        if self.friendly is not None or not self.cur_lines:
            return
        game = extract_game(self.cur_lines)
        friendly = _friendly_player(game["heroes"])
        if friendly is None:
            return  # no heroes parsed yet (very early / end-of-game); retry next analyze
        self.meta = game
        self.friendly = friendly
        hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
        self.hero_card = hero["card"] if hero else None
        self.hero_name = hero["hero_name"] if hero else None
        self.account = next((n for n, c in game["account"].items()
                             if c == self.hero_card), None)
        self.actions.friendly = self.friendly
        if self._stat_pending:
            self._drain_stats(self._stat_pending)
            self._stat_pending = []
        # The current tier was set at game setup (before turn 1) — the
        # upgrade-price fallback counts turns at the tier from there.
        if self._last_tier is None:
            self._last_tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier")
            self._tier_seen_turn = 0

        card_races = _load_card_races(os.path.join(_HERE, ".card_races.json"))
        self._card_races = card_races
        seed_m = _SEED.search("".join(self.cur_lines))
        self._seed = seed_m.group(1) if seed_m else None
        self._comps = meta.comps()
        self._refresh_bans()

    def _refresh_bans(self):
        """Family-ban info, retried until the pool reveal is complete.

        bans_from_log derives allowed tribes from the pool minions seen so
        far (a tribe only counts once it has 3+ DISTINCT pure pool minions —
        effect-summoned singletons of banned tribes mid-game must not pad
        the count), and the pool streams in gradually with the shop rolls
        (2026-09-10 log: first pure tribe at ~50s, the fifth at ~3.5min —
        turn 3-5), so a partial set (one tribe's minions) once froze 9
        banned tribes in the UI for a whole game (2026-09-03 screenshot).
        The real family ban is 5 allowed / 5 banned, so only a 5-tribe set
        is accepted; until then allowed stays None and this re-runs on each
        analyze. More than 5 seen = not a 5/5 ban mode — fail open
        permanently.

        The advisory list (`self.playable`) is evidence-only during that
        window: comps whose tribe the pool has CONFIRMED (a counted pure
        tribe is definitely in this lobby). Fail-open instead (every comp
        playable) made the coach aim at banned-tribe comps for the first
        3 turns. Unseen tribes' comps stay out of it — they might be
        banned — and confirmed comps carry no _blocked_core marks, since
        a hybrid piece of an unseen tribe isn't known-banned, just not
        yet sampled.

        The comps PANEL (`self.game_comps`) is a second, game-level list
        (2026-09-11 ask): every comp stays listed until the bans land,
        because the player reads it on turn 1 to see what this game might
        allow — the evidence-only panel read as if the board picked the
        list. Each row carries _tribe_confirmed (its tribe in the
        confirmed set?) so the UI dims the could-still-be-banned ones
        instead of hiding them.
        """
        if self._bans_ready or self._comps is None or not self.cur_lines:
            return
        allowed = None
        observed = {}
        if self._seed is not None:
            for g in bans_from_log(None, self._card_races,
                                   lines=self.cur_lines):
                if g["seed"] == self._seed:
                    allowed = g["allowed"]
                    observed = g.get("races") or {}
                    break
        if observed:
            # The log's own CARDRACE tags (see bans_from_log): patch-proof
            # tribes for the comp filter too, not just the 5-tribe gate —
            # the upstream cache lags the patch, and core cards unknown to
            # it would otherwise fail open and never show their ban mark.
            self._card_races = {**self._card_races, **observed}
        if allowed is not None and len(allowed) > 5:
            self.allowed = None  # not a 5/5 ban mode
            self._bans_ready = True
        elif allowed and len(allowed) == 5:
            self.allowed = allowed
            self._bans_ready = True
        else:
            self.allowed = None  # still streaming — retry next analyze
        self.tribes_seen = len(allowed) if allowed else 0
        self.tribes_detecting = not self._bans_ready
        if self._bans_ready:
            self.playable = filter_comps_by_available_tribes(
                self._comps, self._card_races, self.allowed)
            self.game_comps = self.playable
        else:
            # Detection window. confirmed-set membership, not is_banned():
            # that fail-opens on an empty set, but here an empty set means
            # "nothing confirmed YET", not "no ban info" — with it the
            # window played fail-open (2026-09-10 replay: seen=0 ->
            # n_playable=21).
            confirmed = set(allowed or ())

            def window_ok(tribe):
                norm = normalize(tribe)
                return bool(norm and
                            set(norm.split("/")) & confirmed)

            self.playable = {slug: comp for slug, comp in self._comps.items()
                             if window_ok(comp.get("tribe"))}
            # The panel keeps the full game-level list; copies, because the
            # meta comp dicts are shared and _tribe_confirmed is per-game.
            self.game_comps = {
                slug: dict(comp, _tribe_confirmed=window_ok(comp.get("tribe")))
                for slug, comp in self._comps.items()}

    def ensure_meta(self):
        """Retry the hero parse from outside analyze().

        The monitor's fingerprint gate can't fire while friendly is None
        (None == None), and analyze() — which does this parse — is only called
        on a fingerprint change, so a game that starts with the monitor already
        running would deadlock at None forever. Calling this each tick breaks
        the cycle: the parse lands, the fingerprint becomes non-None, and the
        next tick differs from the last state and advises.
        """
        self._ensure_meta()

    def _zone_commit(self):
        """Rebuild shop_cards from the zone layer — the single source of
        truth for the shop. Keeps it correct between mid-phase actions,
        where options blocks don't re-print reliably (see the zone-layer
        regex comment); options blocks merge into the table on flush."""
        self.shop_cards = [(self._zone_shop_p.get(eid), cid)
                           for eid, cid in self._zone_shop.items()]
        self.shop_eids = {cid: eid for eid, cid in self._zone_shop.items()}
        # Shop sightings (hunt evidence for value._hunt_check): a NEW offer
        # eid is a shop generation showing this card. Recorded here, at feed
        # time — the replay harness builds a fresh coach per phase, so
        # analyze()-time recording would only ever see the current shop.
        for eid, cid in self._zone_shop.items():
            if eid not in self._shop_seen_eids:
                self._shop_seen_eids.add(eid)
                self._shop_seen[cid] = self.actions.turn

    def _flush_shop_block(self):
        """Merge the buffered options block into the zone shop — only if it
        carried a tavern button (a real shop block; discovery/choice blocks
        share the format and must not replace the shop). Sell options (the
        player's own minions, player==friendly) are NOT offers and never
        enter the table; nor do offers already removed this phase (_zone_gone
        — the 2026-09-10 storm blocks re-list stale copies). The buffer
        itself is cleared by the next block header / new-phase reset, never
        here — tavern_offers polls mid-block, and clearing would orphan
        offers that arrive after this flush."""
        if self._pending_is_shop and self._pending_shop:
            for p, c, e in self._pending_shop:
                if e and MINION_ID.match(c) and "HERO" not in c \
                        and e not in self._zone_gone \
                        and (self.friendly is None or p != self.friendly):
                    self._zone_shop[e] = c
                    self._zone_shop_p[e] = p
            self._zone_commit()
        if self._pending_is_shop:
            # Available board activations ride the same settled shop state
            # (error=NONE as of this block's print).
            self.activations = list(self._pending_activations)

    def tavern_offers(self):
        """Minion card ids offered by the tavern right now — excludes the
        friendly player's own minions, which DebugPrintOptions lists as sell
        options (they arrive BEFORE the actual shop offers)."""
        self._flush_shop_block()
        return [c for p, c in self.shop_cards
                if self.friendly is None or p != self.friendly]

    def level_cost(self):
        """The real tavern upgrade price right now (None if not applicable).

        Primary: the TechUp button's COST tag (GameState, live button) — the
        game prints the true price every turn. Fallback: the wiki rule — the
        upgrade starts at (target+3) gold and drops 1 at the start of each
        round you stay at your tier, i.e. cost = tier + 5 - turns_at_tier
        (verified against the log: turn 1 tier-2 button costs 5, turn 2 4,
        tier-3 6 then 5, tier-4 7). Unknown history (mid-game catch-up) uses
        the first-available price, tier + 4.
        """
        tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier") \
            if self.hero_card else None
        if not tier or tier >= 6:
            return None
        for rec in self.techup.values():
            if (rec["player"] == self.friendly and rec["tier"] == tier + 1
                    and rec["zone"] == "PLAY" and rec["cost"]):
                return rec["cost"]
        if self._tier_seen_turn is not None:
            turns_at_tier = max(1, self.actions.turn - self._tier_seen_turn)
            return max(2, tier + 5 - turns_at_tier)
        return tier + 4

    def state_fingerprint(self):
        """A cheap fingerprint of everything the advice depends on.

        (gold, tier, board, tavern offers, pending pick, next opponent,
        hand) — the monitor re-advises whenever this changes during a buy
        phase, so buys/rolls/plays/sells mid-turn update the advice instead
        of waiting for the next buy phase. The pick and scout are part of
        what the advice renders: without them in the fingerprint, resolving
        a trinket pick (2026-09-04, user report) left gold/board/shop
        identical, the fingerprint matched, and the overlay sat frozen on
        the pick panel until a refresh changed the shop. The hand too:
        buying a spell into hand, or casting one out, changes what the plan
        says without touching gold/board/shop. None before the hero is
        parsed (nothing to fingerprint yet).
        """
        if self.friendly is None:
            return None
        board, _ = self.gs.final_board(self.friendly)
        c = self.choice
        pick = ((c["ctype"], c["source"], c["picked"],
                 tuple(o for _n, o in c["options"])) if c else None)
        return (
            self.gs.gold.get(self.account) if self.account else None,
            self.gs.hero_meta.get(self.hero_card, {}).get("tier"),
            self.level_cost(),
            tuple(sorted((m["card"], m.get("atk") or 0, m.get("health") or 0,
                          m.get("golden") or False) for m in board)),
            tuple(self.tavern_offers()),
            pick,
            self.next_opponent,
            tuple(sorted(m.get("card") or ""
                         for m in self.gs.hand(self.friendly))),
        )

    def analyze(self):
        """Fast per-buy-phase analysis from the current incremental state."""
        self._ensure_meta()
        if self.friendly is None:
            return None  # no game/hero yet — nothing to analyze
        if not self._bans_ready:
            # The pool streams over the game's first seconds; if the hero
            # parse landed first, _ensure_meta returns before its ban refresh
            # ever re-runs (the 2026-09-04 Guff game stayed ban-blind).
            self._refresh_bans()
        self._resolve_boards()
        board, _ = self.gs.final_board(self.friendly)
        if not board and self.gs.snapshots:
            # A full-board turn's combat teardown removes the tavern board and
            # the game re-adds it only AFTER the next shop's options print
            # (2026-09-03 games: the coach saw board 0 for one phase). Until
            # the real board lands — the fingerprint re-advises when it does —
            # estimate from the fullest recent snapshot instead of advising
            # blind.
            board = _estimate_board(self.gs.snapshots, self.friendly)
        tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier")
        gold = self.gs.gold.get(self.account) if self.account else None
        scenario = self.actions.scenario()
        # Held trinkets (PLAY-zone BGxx_MagicItem_NNN): names feed the growth
        # simulator's requires_trinket steps; the merged records (description
        # + curated synergy from trinket_effects.json) feed the W_TRINKET
        # synergy term. Both were dead code until this wiring — analyze()
        # never passed trinkets to anything (2026-09-08 audit).
        _trinkets_by_id = {t["id"]: t for t in meta.trinkets()}
        _trinket_ann = meta.trinket_effects()
        held = [t for t in (self.gs.held_trinkets(self.friendly)
                            if self.friendly else [])
                if t in _trinkets_by_id]
        if held:
            scenario["trinkets"] = [_trinkets_by_id[c]["name"] for c in held]
            trinket_recs = [dict(_trinkets_by_id[c], **(_trinket_ann.get(c) or {}))
                            for c in held]
        else:
            trinket_recs = []
        # Dark gifts: the Dark Discovery button grants a RANDOM gift (real
        # logs show ~3 markers per press — three minions each carrying one);
        # the log prints each gift's name on a MidGameEffect marker attached
        # to its host minion (tag=1234, 2026-09-08 ground truth). Player
        # attribution is fuzzy mid-combat (the shared spectator number makes
        # one of the two tags lie) — require the marker's AND the host's
        # controller to both be the friendly player, and dedup by name: the
        # same gift recurs on new minions (Replication-class) and in later
        # presses. dark_gifts.json finally gets read.
        _dg_db = {d.get("name"): d for d in meta.dark_gifts()}
        dark_gifts, _dg_seen = [], set()
        for rec in self.gs.dark_gift_effects():
            info = _dg_db.get(rec["name"])
            if not info or rec["name"] in _dg_seen:
                continue
            if rec["host_player"] == self.friendly \
                    and rec["player"] == self.friendly:
                _dg_seen.add(rec["name"])
                dark_gifts.append({"name": rec["name"],
                                   "description": info.get("description")})
        # Opponent trinkets: the log reveals every player's chosen trinkets
        # (2026-09-08 ground truth) — free scout intel.
        opp_trinkets = sorted({
            _trinkets_by_id[c]["name"]
            for p in set(self.gs.player.values()) if p != self.friendly
            for c in self.gs.held_trinkets(p)
            if c in _trinkets_by_id})
        hero_power = _hero_power_text(self.hero_name)
        # Recent acquisitions (this turn's plays + buys, and the last
        # completed turn's) feed the pivot override — the board alone lags
        # an actual pivot, and a buy IS intention (a card can sit in hand
        # behind a full board, and a spell is acquired by buying).
        friendly = self.friendly
        recent = _recent_acquisitions(
            self.actions.plays, self.actions.buys,
            self.actions.turn_plays[-1] if self.actions.turn_plays else [],
            self.actions.turn_buys[-1] if self.actions.turn_buys else [],
            friendly)
        target = comp_target(board, self.playable, recent_cards=recent)
        # Sticky same-tribe direction (2026-09-06 Guff game: the target
        # churned 'Summon Beetles' -> 'Tasty Lobstah' phase-to-phase on
        # identical tribe evidence, reading as "which build am I doing?").
        # Same tribe + no strictly more evidence -> keep showing the
        # previous comp; cross-tribe pivots always pass through.
        prev = self._sticky_target
        if prev is not None and self.playable is not None and not any(
                c.get("name") == prev.get("name")
                for c in self.playable.values()):
            # The ban/pool filter removed the held comp (2026-09-07, twice:
            # before the 5/5 ban resolves the coach runs fail-open with
            # every comp playable — a target locked in that window, and the
            # sticky hold then kept showing Nagas AFTER Naga was banned).
            # A comp the filter removed can no longer be the direction.
            self._sticky_target = prev = None
        if prev is not None:
            # Same-tribe churn and sub-threshold dips both go through the
            # sticky rule; the prev hit count decides whether a dip holds
            # (>=1 core still evidenced) or the direction dies (0).
            prev_hits = _core_hits(board, recent,
                                   set(prev.get("core", [])))
            new_hits = _core_hits(board, recent,
                                  set(target.get("core", []))) \
                if target else 0
            target = sticky_comp_target(prev, target, prev_hits, new_hits)
        self._sticky_target = target
        # ONE comp target feeds sell + buy + display — the evidence-based
        # target. The old per-function comp picks (crude tribe overlap for
        # sells, an arbitrary dict-order comp for buys) disagreed with the
        # "committing to" display and mis-floored the glue: Banana Slamma
        # headlined a Naga game (t9) and "sell Fauna Whisperer" — the comp's
        # own payoff — fired while Balinda (in the wrong comp's core) was
        # protected (the 2026-09-04 1st-place game).
        ranked = sell_recommendation(board, self.playable, self.allowed,
                                     scenario=scenario, hero_power=hero_power,
                                     trinkets=trinket_recs, comp=target)
        # The hand: casts from hand are free, stuck minions play free — the
        # coach's blind spot until 2026-09-04 (five spells sat in hand that
        # would 10x the board while the coach said nothing). Spell entities
        # are filtered by the tavern-spell DB (generated junk can carry a
        # spell cardtype but has no real spell id).
        hand = [m for m in self.gs.hand(self.friendly)
                if m.get("type") != "spell"
                or m.get("card") in _load_spell_db()]
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
                            trinkets=trinket_recs, scenario=scenario,
                            recent_cards=recent, comp=target,
                            hand=hand) if offer_ids else []
        shop_costs = shop_cost_map(self.gs, offer_ids, self.shop_eids)
        # Own-side pool ledger (phase 1, analysis/pool_availability.md):
        # everything we hold (board + hand, golden = 3) is out of the shared
        # pool until sold. Feeds the Market availability chips and the value
        # layer's triple/hunt gates; opponents' holdings join in phase 2.
        own_pool = pool.own_holdings(board, hand)
        hand_steps = hand_plan(hand, board, scenario, pool_held=own_pool)
        golden_by_cid = {m["card"]: m.get("golden") for m in hand}
        for s in hand_steps:
            s["golden"] = golden_by_cid.get(s["card"], False)
        # Armor flow (loss-streak signal, analysis/LEVELING_MODEL.md Q0):
        # the per-turn record's LAST armor/HP write is the end-of-turn
        # effective health; quiet turns (won combats — no writes) carry the
        # last known values forward. The combat that ends turn t costs
        # series[t-1] - series[t], readable at the NEXT buy phase. ANY damage
        # is a loss (a won combat never drops health+armor — the 2026-09-04
        # Guff game lost every fight by 1-5 and the old >=3 "real loss" rule
        # read it as no streak at all); 1-2 is flagged close, not discounted.
        hero_meta = self.gs.hero_meta.get(self.hero_card, {})
        # Effective health: HEALTH - DAMAGE. This season hero damage logs as
        # a DAMAGE tag with HEALTH staying at base (the 2026-09-08 Guff
        # session: DAMAGE 11, HEALTH 30, true HP 19 — the coach read 30 all
        # game and every loss streak read zero).
        health = None
        if hero_meta.get("health") is not None:
            health = hero_meta["health"] - (hero_meta.get("damage") or 0)
        armor = hero_meta.get("armor")
        damage_cap = self.gs.damage_cap
        turn = self.actions.turn

        series = {}
        last = {}
        if self._armor_hist:
            for t in range(max(self._armor_hist) + 1):
                rec = self._armor_hist.get(t)
                if rec:
                    for k in ("al", "hl", "dl"):
                        if rec.get(k) is not None:
                            last[k] = rec[k]
                if last.get("al") is not None and last.get("hl") is not None:
                    # true HP = armor + HEALTH - DAMAGE
                    series[t] = (last["al"] + last["hl"]
                                 - (last.get("dl") or 0))

        def _combat_damage(t):
            if t < 0 or t - 1 not in series or t not in series:
                return None
            return series[t - 1] - series[t]

        damage_last = None
        loss_streak = 0
        close_losses = False  # every loss in the streak was by 1-2
        d = _combat_damage(turn - 1)
        if d is not None and d > 0:
            damage_last = d
            loss_streak = 1
            if d <= 2:
                close_losses = True
            t = turn - 2
            while t >= 1:
                pd = _combat_damage(t)
                if pd is not None and pd > 0:
                    loss_streak += 1
                    if pd > 2:
                        close_losses = False
                    t -= 1
                else:
                    break
        # The pending pick (hero / trinket / discover), ranked against the
        # current board and comp. Its rows are (name, cid, score, why) — a
        # DIFFERENT shape from the sell ranking's (cid, score). They used to
        # share the `ranked` variable, so any pending pick silently replaced
        # the sell ranking: top_move crashed comparing the name string to a
        # score threshold, and the overlay's Sell box showed the pick
        # options (2026-09-05 game 2, records 172-173 of the replay).
        choice_advice = None
        c = self.choice
        if c and c["picked"] is None and c["options"]:
            kind = choice_kind(c["ctype"], c["source"], c["options"])
            # comp=target: the pick panel ranks against (and labels with) the
            # SAME evidence-based target the "committing to" box shows — the
            # old call let the ranking re-derive a comp from the board, which
            # is how Lurking Leviathan (core of Beasts - Leviathan) headlined
            # as "comp fit" in a game committed to Tasty Lobstah (2026-09-11).
            pick_ranked = rank_choices(kind, c["options"], board, self.playable,
                                       comp=target)
            choice_advice = {"kind": kind, "source": c["source"],
                             "ranked": pick_ranked}
        result = {
            "hero": self.hero_name,
            # Hero-power text (meta/heroes.json): feeds value ranking AND the
            # turn-structure gate (a "Skip your first turn" hero can't take a
            # turn-1 plan).
            "hero_power": hero_power,
            # Shop sighting history: minion cid -> turn last offered. The
            # hunt's recency evidence (value._hunt_check) — a missing core
            # the shop isn't producing is not a plan.
            "shop_seen": dict(self._shop_seen),
            "tier": tier,
            "turn": turn,
            "gold": gold,
            "shop_costs": shop_costs,
            "level_cost": self.level_cost(),
            "dark_gifts": dark_gifts,
            "opp_trinkets": opp_trinkets,
            "health": health,
            "armor": armor,
            # This season's per-combat damage cap (BACON_COMBAT_DAMAGE_CAP,
            # escalating by round) — the mortality bands key on it.
            "damage_cap": damage_cap,
            "damage_last": damage_last,
            "loss_streak": loss_streak,
            "close_losses": close_losses,
            "board": board,
            # Own-side pool ledger (base cid -> held copies, golden = 3):
            # what the Market availability chips and the triple/hunt pool
            # gates are computed from. Dict, not Counter — the overlay
            # serializes the analysis verbatim.
            "own_pool": dict(own_pool),
            # Scout (gates 3+4, analysis/LEVELING_MODEL.md): our board's
            # stat total; the announced next opponent's LAST-KNOWN board
            # (the buy-phase preview, from a fight we were in); the median
            # of every opponent board we've fought (lobby); and the corpus
            # baseline for this turn.
            "board_stats": sum((m.get("atk") or 0) + (m.get("health") or 0)
                               for m in board),
            # The next opponent's last-known board is the buy-phase preview
            # — but only while it's FRESH: a rematch against a player whose
            # stored board is rounds old reads as far weaker than the board
            # they'll actually bring (the Holmes t9 rematch vs a turn-1
            # board). Older than 2 rounds -> unknown, lobby median instead.
            "opp_stats": self._fresh_opp_stats(turn),
            "last_opp_stats": (self._lobby_stats[-1] or {}).get("stats")
            if self._lobby_stats else None,
            # The lobby scales fast; a median over every fight ever fought
            # lags it badly by the late game (37 vs boards of 141/229 in the
            # Holmes t9). The last 3 fights are the honest "what boards look
            # like right now".
            # The lobby median only counts fights from the last 2 rounds:
            # boards grow ~2x/round mid-game, so older boards consistently
            # UNDER-estimate the lobby (2026-09-07 Tickatus t7: '~25 theirs'
            # from t3-t5 boards while the turn-matched baseline said 56 —
            # the player's 'why only 25?' report). Stale fights fall back
            # to the baseline instead of dragging old boards forward.
            "lobby_opp": _median([r["stats"] for r in
                                  [r for r in self._lobby_stats
                                   if turn - r.get("turn", 0) <= 2][-3:]]),
            "baseline_opp": _baseline_opp(turn),
            "banned": _banned(self.allowed),
            "playable_comps": self.playable,
            # The comps panel's list (game-level; playable_comps is the
            # advisory filter, evidence-only while the bans stream in).
            "game_comps": self.game_comps,
            # True while the 5/5 tribe set is still streaming in: the comps
            # panel then labels its list and dims unconfirmed-tribe rows
            # instead of implying every tribe shown is confirmed (2026-09-10).
            "tribes_detecting": self.tribes_detecting,
            "tribes_seen": self.tribes_seen,
            # Commit-readiness meter: how close each candidate comp is to the
            # commit threshold, so the UI can show direction BEFORE
            # comp_target declares a target (the pre-commit blind spot).
            "comp_progress": comp_progress(board, self.playable,
                                           recent_cards=recent),
            "sell_rank": ranked,
            "shop_rank": shop,
            "buy_this": shop[0][0] if shop else None,
            "choice": choice_advice,
            "target_comp": target["name"] if target else None,
            "target_state": target_state(target, board),
            "target_cards": comp_cards(target, board),
            "hand": hand_steps,
            "hand_plan": hand_steps,
            "scenario": scenario,
            # Board activations usable right now (error=NONE in the settled
            # options block) — the planner turns them into Activate steps
            # instead of advising a reroll with the last gold.
            "activations": [{"cid": c} for c in self.activations],
        }
        result["situation"] = situation_line(result)
        result["forecast"] = combat_forecast(result)
        result["top_move"] = top_move(result)
        return result
