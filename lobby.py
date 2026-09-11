r"""Seat-level opponent tracking from the combat staging bursts.

Phase 2 of card availability (analysis/pool_availability.md). Phase 0
verified the log mechanics this rides on:

  - Every combat window stages BOTH boards as fresh entities under the
    shared combat-slot controller. The staging marker is tag=CREATOR
    pointing at the persistent TB_BaconShop_8P_PlayerE enchantment; combat
    summons, shop offers, and hero/trinket re-creations don't carry it.
  - Our board stages FIRST, the opponent's SECOND; the final duel stages
    only the opponent's. Both facts are handled by subtraction: the staged
    counter minus our exactly-known own holdings is the opponent's board,
    clamped at zero.
  - BACON_CURRENT_COMBAT_PLAYER_ID tags name the account of each fighter
    and their seat (1..8; 0 = slot cleared after the fight) — the stable
    per-player key. Seats are what NEXT_OPPONENT_PLAYER_ID speaks too, so
    the resolved boards attribute to the same ids live_coach's pairing
    tracker already uses.

Honesty limits (must ride into any label shown to the player):
  - A seat board is exact at the moment it staged; it ages from there.
    Consumers label with the round it was seen.
  - Opponent hands and shops are invisible: their held copies are
    undercounted, so lobby remaining() runs optimistic between sightings.
  - A double-staged window (two boards in one combat, the 2026-09-11 r7/r8
    pair) blends into one counter — rare, and bounded by the seat's next
    clean sighting.
"""
import re
from collections import Counter

POWER = r"GameState\.DebugPrintPower\(\) - "
_CREATE = re.compile(POWER + r"\s*FULL_ENTITY - Creating ID=(\d+) CardID=(\w*)")
# SHOW_ENTITY reveals come in both a bare and a bracketed entity form.
_SHOW_ENT = re.compile(POWER + r"\s*SHOW_ENTITY - Updating "
                       r"Entity=(?:\[[^\]]*?id=(\d+)[^\]]*\]|(\d+)) "
                       r"CardID=(\w*)")
_ENT_UPD = re.compile(POWER + r"\s*FULL_ENTITY - Updating \[[^\]]*?id=(\d+)[^\]]*\] CardID=(\w*)")
# Tag lines inside an entity block (indented, no TAG_CHANGE head).
_BLOCK_TAG = re.compile(r"tag=(\w+) value=(\S+)")
# TAG_CHANGE meta writes on a bracketed or bare entity (controller flips,
# CREATOR/CARDTYPE late writes).
_WRITE = re.compile(
    r"TAG_CHANGE Entity=(?:\[[^\]]*?id=(\d+)[^\]]*\]|(\d+)) tag=(\w+) value=(\S+)")
# BACON_CURRENT_COMBAT_PLAYER_ID: bare-account form names the fighter.
_SEAT_TAG = re.compile(
    r"TAG_CHANGE Entity=(\S+) tag=BACON_CURRENT_COMBAT_PLAYER_ID value=(\d+)")
STAGED_CREATOR = "TB_BaconShop_8P_PlayerE"
META_TAGS = ("CONTROLLER", "CARDTYPE", "CREATOR", "PREMIUM", "ZONE_POSITION")


def base_cid(cid):
    return cid[:-2] if isinstance(cid, str) and cid.endswith("_G") else cid


class LobbyScout:
    """Buffers staged combat-burst entities and resolves them into per-seat
    board counters once the friendly player and the turn's pairing are known.

    Live usage (from live_coach): feed() every GameState line; open_round()
    at the buy-phase MAIN_END with our exact holdings at that moment;
    close_round() at the next MAIN_ACTION; seat_event() on seat tags;
    resolve_completed() each analyze()."""

    def __init__(self):
        self._meta = {}        # eid -> {card, controller, cardtype, creator,
                               #        premium, zonepos}
        self._cur = None       # eid of the entity block being read
        self._creators = set() # entity ids of the staging enchantment
        self._open = None      # round being captured:
                               # {turn, own, eids: [eid in feed order]}
        self._rounds = {}      # turn -> {"own", "eids"} (closed, unresolved)
        self._resolved = set()
        self.seats = {}        # seat -> {"cards": Counter, "turn": int,
                               #        "goldens": set, "name": str}
        self._names = {}       # account name -> seat (last nonzero)

    def __eq__(self, other):
        # Value identity for the _reset() contract (test_live_updates pins
        # that a reset instance equals a fresh one, field by field).
        if not isinstance(other, LobbyScout):
            return NotImplemented
        return all(getattr(self, a) == getattr(other, a)
                   for a in ("_meta", "_creators", "_open", "_rounds",
                             "_resolved", "seats", "_names"))

    # ---- feeding -------------------------------------------------------

    @staticmethod
    def _entity_line(line):
        """(eid, cid, is_update) for create/show/update lines, else None."""
        m = _CREATE.search(line)
        if m:
            return int(m.group(1)), m.group(2), False
        m = _SHOW_ENT.search(line)
        if m:
            return int(m.group(1) or m.group(2)), m.group(3), False
        m = _ENT_UPD.search(line)
        if m:
            return int(m.group(1)), m.group(2), True
        return None

    def feed(self, line):
        """Entity metadata from GameState lines (creates, block tags,
        TAG_CHANGE meta writes). Cheap: one or two regex probes per line."""
        if "GameState." not in line:
            return
        ent = self._entity_line(line)
        if ent is not None:
            eid, cid, is_update = ent
            self._cur = eid
            if cid:
                self._meta.setdefault(eid, {})["card"] = cid
                if cid == STAGED_CREATOR:
                    self._creators.add(eid)
            # Scope the open round to entities that surface in its
            # window: staged boards are FRESH creations every combat
            # (phase 0), so the round's candidate set is exactly what
            # arrives while it is open — without this, resolution would
            # re-count every earlier round's staged copies. Feed order is
            # preserved: the position-run grouping needs it. (Reveal/
            # update lines describe existing entities — count creates and
            # shows, not every stat re-description.)
            if self._open is not None and not is_update:
                self._open["eids"].append(eid)
        else:
            m = _WRITE.search(line)
            if m:
                # A TAG_CHANGE names its entity explicitly — it never
                # continues the previous block.
                self._cur = None
                eid = m.group(1) or m.group(2)
                tag, val = m.group(3), m.group(4)
                if tag in META_TAGS and eid:
                    self._set(int(eid), tag, val)
                return
            m = _SEAT_TAG.search(line)
            if m:
                self._cur = None
                self.seat_event(m.group(1), int(m.group(2)))
                return
            if "TAG_CHANGE" in line:
                # Any other TAG_CHANGE (STEP, hero stats, ...) also closes
                # the block; its tag= value= shape must not read as block
                # tags of the previous entity.
                self._cur = None
                return
            if self._cur is not None:
                m = _BLOCK_TAG.search(line)
                if m:
                    tag, val = m.groups()
                    if tag in META_TAGS:
                        self._set(self._cur, tag, val)

    def _set(self, eid, tag, val):
        e = self._meta.setdefault(eid, {})
        if tag == "CREATOR":
            try:
                e["creator"] = int(val)
            except ValueError:
                pass
        elif tag == "PREMIUM":
            e["premium"] = val
        elif tag == "ZONE_POSITION":
            try:
                e["zonepos"] = int(val)
            except ValueError:
                pass
        elif tag == "CONTROLLER":
            try:
                e["controller"] = int(val)
            except ValueError:
                pass
        else:
            e[tag.lower()] = val

    # ---- round lifecycle -------------------------------------------------

    def open_round(self, turn, own):
        """The buy phase just ended (MAIN_END): combat staging begins.
        `own` is pool.own_holdings(board, hand) at this exact moment."""
        self._open = {"turn": turn, "own": Counter(own or {}), "eids": []}

    def close_round(self):
        """The next buy phase started (MAIN_ACTION): the combat window is
        over. materialize the staged counters per controller."""
        if self._open is not None:
            self._rounds[self._open["turn"]] = self._open
            self._open = None

    def seat_event(self, name, seat):
        """A BACON_CURRENT_COMBAT_PLAYER_ID write: account name -> seat."""
        if seat and name and not name.startswith("UNKNOWN"):
            self._names[name] = int(seat)

    # ---- resolution ------------------------------------------------------

    def resolve_completed(self, cur_turn, pairing, friendly):
        """Resolve every closed round of completed turns. `pairing` is
        live_coach's turn -> announced-seat map; `friendly` the player
        number. Returns the list of seats updated."""
        updated = []
        for turn in sorted(self._rounds):
            if turn < 1 or turn >= cur_turn or turn in self._resolved:
                continue
            self._resolved.add(turn)
            rnd = self._rounds.pop(turn)
            seat = pairing.get(turn)
            if seat is None:
                continue
            board, goldens, hero = self._opp_board(rnd, friendly)
            if board is None:
                continue
            prev = self.seats.get(seat) or {}
            # A real fight board holds at most 7 minions (goldens weight
            # 3). Records above that blended a second staged group into
            # the counter — keep them for the pool ledger (an upper bound
            # on holds) but never show them as the composition preview.
            blended = sum(board.values()) > 7
            self.seats[seat] = {
                "cards": board,
                "turn": turn,
                "goldens": goldens,
                "hero": hero or prev.get("hero"),
                "name": self._name_of(seat) or prev.get("name"),
                "blended": blended,
            }
            updated.append(seat)
        return updated

    def _opp_board(self, rnd, friendly):
        """The fight board from a round's staged burst, minus our own
        holdings, clamped at zero. Returns (counter, goldens, hero_cid) or
        (None, (), None) when nothing staged.

        Phase 0 ground truth: a combat window stages boards as fresh
        entities under ONE shared combat-slot controller, and the board
        copies arrive as POSITION RUNS — zonepos climbing 1..N, then
        RESTARTING at 1 for the next staged group. Windows can carry more
        than one run (both fighters, a stale re-stage of an old board —
        the 2026-09-11 r7/r8 pair). The fight board is the run with the
        LARGEST position reach (the fullest staged view — same philosophy
        as the stat scout's "most opponent presence" rule); ties go to the
        LATER run (ours stages first when both stage — phase 0). Our own
        held copies (board + hand at MAIN_END) then subtract out, since
        some windows stage ours inside the winning run too.
        """
        ents = []          # staged minion entities, feed order
        hero = None
        hero_ctrl = None
        for eid in rnd["eids"]:
            e = self._meta.get(eid) or {}
            if e.get("creator") not in self._creators:
                continue
            card = e.get("card")
            if not card:
                continue
            ctype = e.get("cardtype")
            ctrl = e.get("controller")
            if ctype == "HERO":
                hero, hero_ctrl = card, ctrl
                continue
            if ctype != "MINION" or ctrl is None:
                continue
            if friendly is not None and ctrl == friendly:
                continue   # copies under OUR number are ours, never theirs
            base = base_cid(card)
            golden = e.get("premium") == "1" or base != card
            ents.append((ctrl, base, golden, e.get("zonepos") or 0))
        if not ents:
            return None, (), None
        # Split into position runs (a new run starts at zonepos == 1).
        runs = []
        cur = None
        for ctrl, base, golden, pos in ents:
            if pos == 1 or cur is None:
                cur = {"count": Counter(), "goldens": set(), "reach": 0,
                       "ctrls": Counter(), "idx": len(runs)}
                runs.append(cur)
            cur["count"][base] += 3 if golden else 1
            if golden:
                cur["goldens"].add(base)
            cur["reach"] = max(cur["reach"], pos)
            cur["ctrls"][ctrl] += 1

        def score(r):
            total = sum(r["ctrls"].values())
            friendly_share = (r["ctrls"].get(friendly, 0) / total
                              if friendly is not None and total else 0)
            return (r["reach"], -friendly_share, total, r["idx"])

        best = max(runs, key=score)
        opp = Counter()
        for cid, n in best["count"].items():
            left = n - rnd["own"].get(cid, 0)
            if left > 0:
                opp[cid] = left
        win_ctrl = best["ctrls"].most_common(1)[0][0]
        return (opp or None), best["goldens"], \
            (hero if hero_ctrl == win_ctrl else None)

    def _name_of(self, seat):
        for name, s in self._names.items():
            if s == seat:
                return name
        return None

    # ---- consumers -------------------------------------------------------

    def fresh_seats(self, cur_turn, max_age=2):
        """Seats whose snapshot is at most `max_age` rounds old."""
        return {s for s, rec in self.seats.items()
                if cur_turn - rec["turn"] <= max_age}

    def merged_holdings(self, cur_turn, max_age=2):
        """Counter of every fresh seat's held copies (base cid -> n)."""
        merged = Counter()
        for s in self.fresh_seats(cur_turn, max_age):
            merged.update(self.seats[s]["cards"])
        return merged

    def committed(self, tribe, min_copies=2, cur_turn=None, max_age=None,
                  matches=None):
        """Seats showing >= min_copies of `tribe` on their last-known board.

        `matches(cid_tribe_str, tribe)` is tribes.matches — membership is
        the tribe DB's job, never string equality (compounds, Amalgams).
        Pass (cur_turn, max_age) to restrict to fresh seats."""
        out = set()
        for seat, rec in self.seats.items():
            if cur_turn is not None and cur_turn - rec["turn"] > (
                    max_age if max_age is not None else 99):
                continue
            n = 0
            for cid, copies in rec["cards"].items():
                ct = self._tribe_of(cid)
                if ct and matches and matches(ct, tribe):
                    n += copies
            if n >= min_copies:
                out.add(seat)
        return out

    _tribe_db = None

    @classmethod
    def _tribe_of(cls, cid):
        if cls._tribe_db is None:
            import meta
            cls._tribe_db = {m.get("id"): (m.get("tribe") or "")
                             for m in meta.minions()}
        return cls._tribe_db.get(cid)
