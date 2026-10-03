"""
Battlegrounds Pool Estimator v2 — built against confirmed Power.log structure.

Ground truth established by reading an actual Power.log (not guessed):

  - Your own player is a stable entity (controller=1) with continuous,
    exact zone-change visibility for purchases/sells/deaths.

  - Opponents are NOT persistently tracked. There is exactly one shared
    "combat slot" (controller=9) that gets torn down and rebuilt with
    FULL_ENTITY creates immediately before each combat, populated with
    whichever real opponent you're paired against that round.

  - `tag=BACON_CURRENT_COMBAT_PLAYER_ID` on the combat-slot entity gives
    a STABLE SEAT NUMBER for that opponent (confirmed: e.g. value=7),
    persistent across the match even though entity ids and display names
    get recycled every combat. This is the correlation key across sightings.

  - `tag=NEXT_OPPONENT_PLAYER_ID` on your own player entity tells you who
    you're paired against for the *next* round, before that snapshot loads.

  - `tag=PREMIUM` on a minion entity: confirmed value=0 (normal) / value=1
    (golden). A golden minion represents 3 copies of the base card for
    pool-accounting purposes.

  - `tag=TURN` is a simple global turn counter (confirmed 1..N across a
    game) — use it as the staleness clock for opponent snapshots.

  - Still UNCONFIRMED / to verify next: the exact tag(s) that mark a seat
    as eliminated (so its last-known board can be flushed back into the
    pool and stop being counted as "still held"). Nothing definitive
    turned up in a first pass — worth checking the log around an actual
    bust event before relying on auto-elimination detection.
"""

from dataclasses import dataclass, field
from collections import defaultdict, Counter


POOL_SIZE_BY_TIER = {1: 18, 2: 15, 3: 13, 4: 11, 5: 9, 6: 6, 7: 5}


@dataclass(frozen=True)
class MinionDef:
    id: str
    tier: int
    tribes: tuple


# ---------------------------------------------------------------------------
# Your own holdings — exact, event-sourced (unchanged in spirit from v1,
# just scoped explicitly to controller==1 zone changes)
# ---------------------------------------------------------------------------

class OwnHoldingsTracker:
    def __init__(self):
        self.counts = Counter()   # card_id -> copies currently on board/hand

    def on_zone_change(self, card_id: str, prev_zone: str, new_zone: str, is_golden: bool):
        weight = 3 if is_golden else 1
        # NOTE: a golden fusion is itself a zone-neutral event (the 3
        # underlying purchases already accounted for it) — only count
        # entry/exit of the *golden entity itself* if your parser
        # represents golden as a distinct entity replacing 3 singles.
        # Verify how your specific parser surfaces TRIPLE/fusion events
        # before trusting this path for goldens.
        if new_zone == "PLAY" and prev_zone in ("SETASIDE", "SECRET", None):
            self.counts[card_id] += weight
        elif prev_zone == "PLAY" and new_zone in ("GRAVEYARD", "REMOVEDFROMGAME", "SETASIDE"):
            self.counts[card_id] -= weight


# ---------------------------------------------------------------------------
# Opponent tracking — one snapshot per seat, replaced wholesale each time
# you're paired against that seat. This is inherently an estimate: churn
# that happens entirely between two of your sightings of a seat (bought
# AND sold before you saw them again) is invisible, full stop.
# ---------------------------------------------------------------------------

@dataclass
class SeatSnapshot:
    seat_id: int
    board: Counter = field(default_factory=Counter)   # card_id -> copies (golden = 3)
    last_seen_turn: int = -1


class OpponentSeatTracker:
    def __init__(self):
        self.seats: dict[int, SeatSnapshot] = {}

    def record_snapshot(self, seat_id: int, board_card_ids_with_premium: list[tuple[str, bool]], turn: int):
        """
        board_card_ids_with_premium: [(card_id, is_golden), ...] for every
        minion entity created/shown under controller=9 for this combat load.
        Call this once you've collected the full burst of FULL_ENTITY /
        SHOW_ENTITY lines that follow a BACON_CURRENT_COMBAT_PLAYER_ID
        change — see `SeatSnapshotCollector` sketch below for the grouping
        logic.
        """
        board = Counter()
        for card_id, is_golden in board_card_ids_with_premium:
            board[card_id] += 3 if is_golden else 1
        self.seats[seat_id] = SeatSnapshot(seat_id=seat_id, board=board, last_seen_turn=turn)

    def total_held(self, card_id: str) -> int:
        return sum(snap.board.get(card_id, 0) for snap in self.seats.values())

    def staleness(self, seat_id: int, current_turn: int) -> int:
        """Turns since last snapshot for this seat. Higher = less trustworthy."""
        snap = self.seats.get(seat_id)
        if snap is None:
            return None  # never seen
        return current_turn - snap.last_seen_turn

    def forget_seat(self, seat_id: int):
        """Call once you've confirmed a seat's elimination (see open item above)."""
        self.seats.pop(seat_id, None)


# ---------------------------------------------------------------------------
# Grouping raw log events into a seat snapshot
# ---------------------------------------------------------------------------
#
# Confirmed sequence shape, from the actual log:
#
#   TAG_CHANGE Entity=<your name> tag=BACON_CURRENT_COMBAT_PLAYER_ID value=<your seat>
#   TAG_CHANGE Entity=<opponent name> tag=BACON_CURRENT_COMBAT_PLAYER_ID value=<opp seat>
#   FULL_ENTITY - Creating ID=<hero id> CardID=<hero card>
#       tag=CONTROLLER value=9
#       tag=ZONE value=PLAY
#   ... (hero power, trinkets, hand-carried minions moved in via
#        HIDE_ENTITY/SHOW_ENTITY with CONTROLLER switched to 9) ...
#   FULL_ENTITY - Creating ID=<minion id> CardID=<card>
#       tag=CONTROLLER value=9
#   ... repeated per board minion ...
#
# A practical collector: watch for the BACON_CURRENT_COMBAT_PLAYER_ID
# TAG_CHANGE on a *non-you* entity as the "snapshot opening" signal, then
# buffer every subsequent FULL_ENTITY/SHOW_ENTITY line with CONTROLLER=9
# and a minion-type CardID (filter out hero/hero-power/trinket cardIds
# using your card DB's CARDTYPE) until you hit the next BLOCK_START for
# the actual combat resolution (BlockType=TRIGGER or similar combat-start
# marker) — that's your snapshot boundary.
#
# This grouping logic is the part I'd actually test against your log
# first, since "when does the burst end" is a judgment call until you've
# watched it happen a few times.

class SeatSnapshotCollector:
    def __init__(self, minion_card_ids: set, own_player_name: str):
        self.minion_card_ids = minion_card_ids
        self.own_player_name = own_player_name
        self._active_seat = None
        self._buffer = []  # list[(card_id, is_golden)]

    def on_combat_player_id(self, entity_name: str, seat_id: int):
        if entity_name == self.own_player_name:
            return  # this is just telling you your own seat — ignore
        # a new opponent snapshot is opening
        self._active_seat = seat_id
        self._buffer = []

    def on_entity_created_or_shown(self, card_id: str, controller: int, is_golden: bool):
        if self._active_seat is None or controller != 9:
            return
        if card_id in self.minion_card_ids:
            self._buffer.append((card_id, is_golden))

    def on_combat_block_start(self, tracker: OpponentSeatTracker, turn: int):
        """Call this when the actual combat-resolution block begins — flushes the buffer."""
        if self._active_seat is not None:
            tracker.record_snapshot(self._active_seat, self._buffer, turn)
        self._active_seat = None
        self._buffer = []


# ---------------------------------------------------------------------------
# Combined estimator
# ---------------------------------------------------------------------------

class PoolEstimator:
    def __init__(self, defs: dict, own: OwnHoldingsTracker, opponents: OpponentSeatTracker):
        self.defs = defs
        self.own = own
        self.opponents = opponents

    def remaining(self, card_id: str) -> int:
        d = self.defs[card_id]
        total = POOL_SIZE_BY_TIER[d.tier]
        held = self.own.counts.get(card_id, 0) + self.opponents.total_held(card_id)
        return max(0, total - held)

    # No generic confidence score — for tiers 1-4 the number of live,
    # actively-churning seats is too high relative to snapshot frequency
    # for a confidence figure to mean anything real; it'd just be false
    # precision dressed up as a number. Dropped.


# ---------------------------------------------------------------------------
# High-tier exception: fewer seats ever contest T5/T6, and PLAYER_TECH_LEVEL
# (confirmed tag) tells you exactly which ones do. That shrinks the "unknown
# actor" count enough that a real certainty check is worth computing — not
# a probability, just a hard fact: "every copy of this card is accounted
# for by seats I know can even buy it, so remaining() is trustworthy right
# now" vs. "someone I can't see is still a wildcard."
# ---------------------------------------------------------------------------

class TechLevelTracker:
    """Tracks each seat's current tavern tier via PLAYER_TECH_LEVEL."""
    def __init__(self):
        self.tech_level = {}  # seat_id -> int

    def on_tech_level_change(self, seat_id: int, level: int):
        self.tech_level[seat_id] = level

    def seats_eligible_for_tier(self, tier: int) -> set:
        return {seat for seat, lvl in self.tech_level.items() if lvl >= tier}


class HighTierCertainty:
    """
    Only meaningful for tiers where the eligible-seat count is small —
    T6 always, T5 often. Don't bother wiring this up for T1-4.
    """
    def __init__(self, estimator: PoolEstimator, opponents: OpponentSeatTracker,
                 tech: TechLevelTracker):
        self.estimator = estimator
        self.opponents = opponents
        self.tech = tech

    def is_trustworthy(self, card_id: str, current_turn: int, max_staleness: int = 2) -> bool:
        """
        True only if every seat currently eligible to buy this card's tier
        has a snapshot fresh enough to trust. If an eligible seat has never
        been seen, or their snapshot is stale, this returns False — meaning
        `remaining()` for this card is a guess, not a fact, right now.
        """
        d = self.estimator.defs[card_id]
        eligible = self.tech.seats_eligible_for_tier(d.tier)
        if not eligible:
            return True  # nobody can even buy this yet — trivially trustworthy
        for seat_id in eligible:
            snap = self.opponents.seats.get(seat_id)
            if snap is None or (current_turn - snap.last_seen_turn) > max_staleness:
                return False
        return True


# ---------------------------------------------------------------------------
# Tribe pressure — reuses the same seat snapshots, no new data collection.
# Confirmed from the log: PLAYER_TECH_LEVEL for opponents only updates in
# the same burst as their combat snapshot, so "which tier is this seat even
# shopping at" has the same staleness as their board — no independent feed.
# ---------------------------------------------------------------------------

class TribePressure:
    def __init__(self, defs: dict, opponents: OpponentSeatTracker, tech: TechLevelTracker):
        self.defs = defs
        self.opponents = opponents
        self.tech = tech

    def seat_tribe_counts(self, seat_id: int) -> Counter:
        """
        Copies-of-tribe on this seat's last-known board. This is EXACT, not
        an estimate — the snapshot itself is ground truth for the moment it
        was taken (real card ids, real counts, no ambiguity). The only
        uncertainty is (a) whether it's still current — see last_seen_turn
        — and (b) whether board presence implies actual strategic
        commitment, which is an interpretation layered on top of a fact,
        not a measurement error. A dual-tribe card counts toward both
        tribes — that's correct, it's genuinely contesting both pools.
        """
        snap = self.opponents.seats.get(seat_id)
        if snap is None:
            return Counter()
        counts = Counter()
        for card_id, copies in snap.board.items():
            for tribe in self.defs[card_id].tribes:
                counts[tribe] += copies
        return counts

    def seats_committed_to(self, tribe: str, min_copies: int = 2, tier_floor: int = None) -> set:
        """
        Which seats show at least `min_copies` of a tribe on their exact
        last-known board. `min_copies` is the interpretive part — a guess
        at where "incidental purchase" ends and "real strategic commitment"
        begins, not something the log tells you directly. Tune it once you
        can eyeball it against real games; a single stray Naga reads very
        differently from four.

        Pass tier_floor to also require tech-level eligibility for that
        tier right now (e.g. tier_floor=5 to ask "who's actually shopping
        T5 Naga," not "who has any Naga at all," which includes T1-4
        fodder that isn't competing for the scarce high-tier copies).
        """
        committed = set()
        for seat_id in self.opponents.seats:
            if tier_floor is not None and self.tech.tech_level.get(seat_id, 0) < tier_floor:
                continue
            if self.seat_tribe_counts(seat_id).get(tribe, 0) >= min_copies:
                committed.add(seat_id)
        return committed

    def pressure_summary(self, tribe: str, tier_floor: int = None) -> str:
        """
        Deliberately a count over KNOWN seats, not a lobby-wide fraction —
        seats never yet seen in a snapshot are omitted, not assumed absent.
        e.g. "3 of 5 seen seats committed to Naga" — honest about the gap
        rather than implying "3 of 8" when 3 seats are still unaccounted for.
        """
        known = len(self.opponents.seats)
        committed = len(self.seats_committed_to(tribe, tier_floor=tier_floor))
        return f"{committed} of {known} seen seats committed to {tribe}"
