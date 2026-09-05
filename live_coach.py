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
from meta import hero_power as _hero_power_text
from tribes import DISPLAY_TRIBES, normalize
from player_actions import (
    STEP_RE, _GS, ENTITY, CHOICE,
    _load_bg_pool, _load_bg_minion_ids,
)
from choices import _CHOICE_HEADER, _CHOICE_OPT, _CHOICE_SOURCE, _CHOSEN, choice_kind, rank_choices
from value import (
    comp_cards, sell_recommendation, shop_ranking, top_move, comp_target,
    target_state, hand_plan, _load_spell_db,
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
# cardId and the owning player, so the player's own minions (shown as sell
# options) are excluded from the shop.
# e.g. "option 4 type=POWER mainEntity=[entityName=X cardId=BG36_345 .. player=15]"
_SHOP_OPT = re.compile(r"DebugPrintOptions\(\).*?cardId=(\w+)[^\]]*player=(\d+)")
# A new options block starts (GameState). Options re-print after every game
# event; each block is the authoritative current shop.
_OPTIONS_HEADER = re.compile(r"GameState\.DebugPrintOptions\(\) -\s+id=\d+")
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


class LiveCoach:
    """Feeds lines incrementally; analyze() is fast on each buy phase."""

    def __init__(self):
        self.gs = GameState()
        self.actions = _LiveActions()
        self.cur_lines = []
        self.shop_cards = []
        self.choice = None  # pending pick (hero/trinket/discover) or None
        self.game_no = 0    # bumped by _reset() on each CREATE_GAME
        self.techup = {}    # TechUp button id -> {tier, player, cost, zone}
        self._last_tier = None
        self._tier_seen_turn = None  # turn the current tier was reached
        self._armor_hist = {}  # turn -> {af, al, hf, hl} first/last armor+HP
        self._stat_seen = 0    # hero_stat_log entries already drained
        self._stat_pending = []  # (turn, cid, tag, value) before hero parse
        self.next_opponent = None  # announced NEXT_OPPONENT_PLAYER_ID
        self._pair_cand = None  # pairing announced during the open buy phase
        self._pairing = {}     # turn -> opponent id announced for its fight
        self._snap_by_turn = {}  # turn -> [(player, stat_total), ...] snapshot
        self._resolved = set()  # turns already committed to the lobby stats
        self._opp_boards = {}  # player id -> {"stats", "n", "turn"} last-known
        self._lobby_stats = []  # stats of every opponent board we fought
        self._snap_seen = 0    # snapshots already buffered
        self._phase = "buy"    # buy phase vs combat window (GameState STEP)
        self._bans_ready = False
        self._card_races = None
        self._seed = None
        self._comps = None
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
        self.choice = None  # pending pick: {'kind','source','options','picked'}
        self.game_no += 1
        self.techup = {}
        self._last_tier = None
        self._tier_seen_turn = None
        self._armor_hist = {}
        self._stat_seen = 0
        self._stat_pending = []
        self.next_opponent = None
        self._pair_cand = None
        self._pairing = {}
        self._snap_by_turn = {}
        self._resolved = set()
        self._opp_boards = {}
        self._lobby_stats = []
        self._snap_seen = 0
        self._phase = "buy"
        self._bans_ready = False
        self._card_races = None
        self._seed = None
        self._comps = None
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
            cid, p = m.group(1), int(m.group(2))
            # Keep every card option, minions and tavern spells (shop offers are
            # owned by the tavern player; the friendly player's own board/hand
            # minions — and the spells they cast — are filtered in analyze()).
            if MINION_ID.match(cid) and "HERO" not in cid \
                    and all(cid != c for c, _ in self.shop_cards):
                self.shop_cards.append((p, cid))
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
        """Record hero ARMOR/HEALTH writes into the per-turn first/last
        history. A turn's record starts seeded with the previous turn's
        ending values (an armor-only combat still knows the health)."""
        for turn, cid, tag, value in entries:
            if self.hero_card and cid != self.hero_card:
                continue
            v = int(value)
            rec = self._armor_hist.get(turn)
            if rec is None:
                prev = self._armor_hist.get(turn - 1) or {}
                rec = {"af": prev.get("al"), "hf": prev.get("hl")}
                rec["al"] = rec["af"]
                rec["hl"] = rec["hf"]
                self._armor_hist[turn] = rec
            rec["al" if tag == "ARMOR" else "hl"] = v  # last write wins

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
        with open(os.path.join(_HERE, "meta", "comps.json"), encoding="utf-8") as f:
            self._comps = json.load(f)
        self._refresh_bans()

    def _refresh_bans(self):
        """Family-ban info, retried until the pool reveal is complete.

        bans_from_log derives allowed tribes from pool minions SEEN so far,
        and the pool streams over the game's first seconds — a partial set
        (one tribe's minions) once froze 9 banned tribes in the UI for a whole
        game (2026-09-03 screenshot). The real family ban is 5 allowed / 5
        banned, so only a 5-tribe set is accepted; until then allowed stays
        None (fail OPEN — no bans shown, every comp playable) and this
        re-runs on each analyze. More than 5 seen = not a 5/5 ban mode —
        fail open permanently.
        """
        if self._bans_ready or self._comps is None or not self.cur_lines:
            return
        allowed = None
        if self._seed is not None:
            for g in bans_from_log(None, self._card_races,
                                   lines=self.cur_lines):
                if g["seed"] == self._seed:
                    allowed = g["allowed"]
                    break
        if allowed is not None and len(allowed) > 5:
            self.allowed = None  # not a 5/5 ban mode
            self._bans_ready = True
        elif allowed and len(allowed) == 5:
            self.allowed = allowed
            self._bans_ready = True
        else:
            self.allowed = None  # still streaming — retry next analyze
        self.playable = filter_comps_by_available_tribes(
            self._comps, self._card_races, self.allowed)

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

    def tavern_offers(self):
        """Minion card ids offered by the tavern right now — excludes the
        friendly player's own minions, which DebugPrintOptions lists as sell
        options (they arrive BEFORE the actual shop offers)."""
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
            # estimate from the last snapshot instead of advising blind.
            board = [m for m in self.gs.snapshots[-1]
                     if m["player"] == self.friendly]
        tier = self.gs.hero_meta.get(self.hero_card, {}).get("tier")
        gold = self.gs.gold.get(self.account) if self.account else None
        scenario = self.actions.scenario()
        hero_power = _hero_power_text(self.hero_name)
        # Recent acquisitions (this turn's plays + buys, and the last
        # completed turn's) feed the pivot override — the board alone lags
        # an actual pivot, and a buy IS intention (a card can sit in hand
        # behind a full board, and a spell is acquired by buying).
        friendly = self.friendly
        recent = [cid for p, cid in self.actions.plays if p == friendly]
        recent += [cid for p, cid in self.actions.buys if p == friendly]
        if self.actions.turn_plays:
            recent += [cid for p, cid in self.actions.turn_plays[-1]
                       if p == friendly]
        if self.actions.turn_buys:
            recent += [cid for p, cid in self.actions.turn_buys[-1]
                       if p == friendly]
        target = comp_target(board, self.playable, recent_cards=recent)
        # ONE comp target feeds sell + buy + display — the evidence-based
        # target. The old per-function comp picks (crude tribe overlap for
        # sells, an arbitrary dict-order comp for buys) disagreed with the
        # "committing to" display and mis-floored the glue: Banana Slamma
        # headlined a Naga game (t9) and "sell Fauna Whisperer" — the comp's
        # own payoff — fired while Balinda (in the wrong comp's core) was
        # protected (the 2026-09-04 1st-place game).
        ranked = sell_recommendation(board, self.playable, self.allowed,
                                     scenario=scenario, hero_power=hero_power,
                                     comp=target)
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
                            scenario=scenario, recent_cards=recent,
                            comp=target) if offer_ids else []
        # The hand: casts from hand are free, stuck minions play free — the
        # coach's blind spot until 2026-09-04 (five spells sat in hand that
        # would 10x the board while the coach said nothing). Spell entities
        # are filtered by the tavern-spell DB (generated junk can carry a
        # spell cardtype but has no real spell id).
        hand = [m for m in self.gs.hand(self.friendly)
                if m.get("type") != "spell"
                or m.get("card") in _load_spell_db()]
        hand_steps = hand_plan(hand, board, scenario)
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
        health = self.gs.hero_meta.get(self.hero_card, {}).get("health")
        armor = self.gs.hero_meta.get(self.hero_card, {}).get("armor")
        turn = self.actions.turn

        series = {}
        last = {}
        if self._armor_hist:
            for t in range(max(self._armor_hist) + 1):
                rec = self._armor_hist.get(t)
                if rec:
                    for k in ("al", "hl"):
                        if rec.get(k) is not None:
                            last[k] = rec[k]
                if last.get("al") is not None and last.get("hl") is not None:
                    series[t] = last["al"] + last["hl"]

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
        # current board and comp.
        choice_advice = None
        c = self.choice
        if c and c["picked"] is None and c["options"]:
            kind = choice_kind(c["ctype"], c["source"], c["options"])
            ranked = rank_choices(kind, c["options"], board, self.playable)
            choice_advice = {"kind": kind, "source": c["source"],
                             "ranked": ranked}
        result = {
            "hero": self.hero_name,
            "tier": tier,
            "turn": turn,
            "gold": gold,
            "level_cost": self.level_cost(),
            "health": health,
            "armor": armor,
            "damage_last": damage_last,
            "loss_streak": loss_streak,
            "close_losses": close_losses,
            "board": board,
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
            "lobby_opp": _median([r["stats"]
                                  for r in self._lobby_stats[-3:]]),
            "baseline_opp": _baseline_opp(turn),
            "banned": _banned(self.allowed),
            "playable_comps": self.playable,
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
        }
        result["top_move"] = top_move(result)
        return result
