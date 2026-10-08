#!/usr/bin/env python3
"""The turn timeline: what the board looked like, three times per turn.

**There is no in-game way to review a Battlegrounds game.** The game shows you
your board and nothing else — not what you had when the fight started, not what
the opponent brought, not what survived. This module reconstructs that, because
the log already contains it and nothing has ever read it for the player.

Three states per turn, and exactly where each comes from (measured, not assumed
— see `analysis/SETTLE_UP_BOARDS.md` for the evidence):

  * **end of buy phase** — the LAST `buy` snapshot of the turn. This is the board
    the player staged, and it is the only honest place to measure board growth.
  * **as combat began** — the FIRST `combat` snapshot of the turn's fight. The
    log stages BOTH boards there, with live stats and keywords, which makes it
    the only view of the opponent's board the log ever gives.
  * **end of battle** — the NEXT turn's first `buy` snapshot, i.e. what
    actually persisted. Turn 5 of the 2026-10-06 game drains 5 → 4 → 3 → 2 → 1
    → 0 inside combat as deaths empty the board, so the tail of a combat burst
    is a teardown, not a final board; the survivors are visible at the top of
    the next turn. The OPPONENT's survivors are the fight's own verdict: one
    board dies first (combat ends when a board dies), so the side that
    drained first lost, and the winner is reported with it — the next shop's
    teardown snapshots show dead minions still staged and once produced an
    aftermath with both sides "surviving".

The drive loop is `outcome_audit.audit_game`'s, deliberately: it is the version
that CALLS `analyze()` on a cadence. A replay that only feeds lines leaves
`coach.friendly` as None, and then every minion on both sides is attributed to
the opponent — a board of ten that is really five and five. That failure is
predicted in `REPLAY_LEARNING.md` and was reproduced here on the first try.

Cost: one full replay of the game (about 5 s for a 16-turn game here). It is a
review-path cost, paid after the game is over, never during play.
"""
import os

from extract_game import split_game_chunks
from fight_table import _board as _struct_board
from live_coach import LiveCoach
from outcome_audit import _phases, SETTLE
from value import _buy_prices, _load_card_db


def _snap_board(minions, friendly, side):
    """One side of a snapshot as the structured board shape everything else uses.

    Snapshots are 6-tuples — (player, card, atk, health, golden, keywords) — since
    the projection widening; older/shorter tuples are tolerated rather than
    dropped, because a missing keyword list is not a reason to lose a minion.
    Slots 6 and 7 (`eid`, `pos`) were added 2026-10-07 and are carried through
    when present, because `_opening_board` needs identity and slot to tell the
    board from the fight's leftovers — a saved replay written before that day
    simply has neither, and the filter then only applies the board cap.

    **An unresolved friendly player returns NOTHING for either side, on
    purpose.** With `friendly is None`, `player is None` compares equal, so every
    unattributed entity lands on "our" side while every real minion lands on the
    opponent's — a confident board of ten that is really five and five. That is
    the measured failure of a replay that feeds lines without calling
    `analyze()`; an empty board is a visible gap, a swapped one is a lie.
    """
    if friendly is None:
        return []
    out = []
    for m in minions or []:
        if len(m) < 4:
            continue
        player = m[0]
        ours = player == friendly
        if side == "ours" and not ours:
            continue
        if side == "theirs" and (ours or player is None):
            continue
        row = {"card": m[1], "atk": m[2], "health": m[3],
               "golden": bool(m[4]) if len(m) > 4 else False,
               "keywords": list(m[5]) if len(m) > 5 and m[5] else []}
        if len(m) > 6 and m[6] is not None:
            row["eid"] = m[6]
        if len(m) > 7 and m[7] is not None:
            row["pos"] = m[7]
        out.append(row)
    return out


BOARD_CAP = 7


def _opening_board(snap, friendly):
    """(board, removed) — OUR side of a shop-opening snapshot, cleaned.

    **A fight's leftovers outlive the fight in the log, and they land on the
    first buy snapshot of the next turn.** Measured 2026-10-07 on the newest
    game (Tavish Stormpike, Undead, 1st): the
    Eternal Summoner's deathrattle summons Eternal Knights that the log keeps in
    PLAY as the shop opens, so the "Opened with" board read NINE minions —
    four golden Eternal Knights at 271/116 plus a non-golden `131/46` and a
    `223/92` copy — where the real board was seven, and they took eight
    snapshots to drain. Turn 12 opened with eight, turn 13 with nine, and turn
    14's RESULT inherited nine from turn 15's opening snapshot.

    Two things are therefore true of a real board and false of that mess, and
    they are what this filter uses:

    * **A board holds at most seven minions** (`BOARD_CAP`). This is the game's
      own rule, so a snapshot showing more is contaminated by definition.
    * **Two minions cannot share a board SLOT.** The log's leftovers keep the
      position they died at, so they COLLIDE with a minion that is really there
      — the 2026-10-07 leftovers sat at positions 3 and 4 while the real board
      held 3 and 4 itself. On every collision measured (7 of them, across 6
      games), the real minion is the one whose entity id is LOWER: the fight's
      summons are allocated while the fight runs, the board's entities before
      it. That ordering is the tie-break here, and it is what the control in
      `test_turn_review.TestTheOpeningBoard` rehearses.

    Returns the board in the log's own order (identity kept for the caller's
    notes) plus how many minions were dropped, so a renderer can say so instead
    of quietly showing a shorter board. An empty `snap` — turn 1 has no buy
    snapshot — returns `([], 0)`: nothing to clean, not a board of nothing.
    """
    if not snap or friendly is None:
        return [], 0
    board = _snap_board(snap.get("minions"), friendly, "ours")

    # Identity-first: the lowest entity id wins a contested slot, and the same
    # order breaks the cap. A missing id (a replay saved before 2026-10-07)
    # sorts last, so it never wins a slot on evidence that is not there.
    def _key(i):
        eid = board[i].get("eid")
        return (eid is None, eid or 0)

    order = sorted(range(len(board)), key=_key)
    occupied, keep = set(), []
    for i in order:
        pos = board[i].get("pos")
        if pos in (None, 0):
            # No slot on record (an old replay, or an entity the log never
            # placed): it cannot contest one, so it is kept rather than guessed
            # at. The cap below still applies.
            keep.append(i)
            continue
        if pos in occupied:
            continue
        occupied.add(pos)
        keep.append(i)
    # The board cap, applied in the same identity-first order.
    keep_set = set(keep[:BOARD_CAP])
    kept = [m for i, m in enumerate(board) if i in keep_set]
    return kept, len(board) - len(kept)



def stats(board):
    """The board's stat total — atk + health — the number the player can eyeball.

    NOT the value function's opinion of the board. `value.py` prices cards by
    comp role, growth and synergy, and that is a different question; this is the
    one a player can verify against what the game showed them.
    """
    return sum((m.get("atk") or 0) + (m.get("health") or 0) for m in board or [])


def _drive(chunk):
    """One pass over a game: (coach, info_by_turn, header_friendly).

    Walks the buy phases, settles inside each one (the shop has stopped
    changing), and calls analyze() — that call is what populates
    `_snap_by_turn`; feeding alone gives the snapshots but no per-turn analysis.

    **`friendly` is resolved from the game header FIRST, not from the coach.**
    `extract_game` + `_friendly_player` name the player from the heroes, which
    does not depend on analyze() having run; the coach's own resolution is the
    fallback. That ordering is the fix for the measured failure where a
    feed-only replay left `coach.friendly` as None and every minion was
    attributed to the opponent — with the header player, the boards split
    correctly even if no analysis ever succeeds.

    Player actions are parsed here too, on the phase slice, exactly as
    `outcome_audit.audit_game` does — gold spend, sells and rolls all come from
    them, and a second pass to collect them would double the replay.
    """
    from extract_game import extract_game, _friendly_player
    from player_actions import parse_actions

    game = extract_game(chunk)
    header_friendly = _friendly_player(game["heroes"], game.get("choice_players"))

    coach = LiveCoach()
    info = {}
    j = 0
    n = len(chunk)
    for lo, hi in _phases(chunk):
        while j < lo and j < n:
            coach.feed(chunk[j])
            j += 1
        prev_offers = None
        last_change = j
        a = None
        stop = hi if hi is not None else n
        while j < stop:
            coach.feed(chunk[j])
            offers = tuple(coach.tavern_offers())
            if offers != prev_offers:
                prev_offers = offers
                last_change = j
            elif offers and j - last_change >= SETTLE:
                a = coach.analyze()
                j += 1
                break
            j += 1
        if not a:
            continue
        turn = (a.get("scenario") or {}).get("turns")
        if turn is None or turn in info:
            continue
        actual = {}
        if header_friendly is not None:
            acts = parse_actions(chunk[lo:hi], friendly=header_friendly)
            actual = acts[0] if acts else {}
        info[turn] = {"analysis": a, "actual": actual}
    return coach, info, header_friendly


def _spend(actual, level_cost, prices=None):
    """Countable gold OUT this turn, with its parts named rather than summed away.

    **Every bought card is priced through `value._buy_prices`** — the one price
    layer — not at a flat 3. The naive "3 × buys" is wrong: measured on the
    2026-10-06 game, 5 of its 24 buys were tavern SPELLS (Enchanted Lasso,
    Repair Job, Armor Stash, Energizing Chamber, Natural Blessing), which keep
    their own per-spell prices. Minions are a FLAT 3 at every tier; spells are
    not, and a spell priced at 3 inflates the total.

    What it still does NOT include: a hero power that costs gold, and any spend
    the log does not attribute to a buy, a roll or the level button. So it is
    close to exact for purchases and a slight UNDER-count otherwise — the parts
    are returned so a renderer never has to present the total as the whole
    story.
    """
    buys = list(actual.get("buys") or [])
    costs = [(prices or {}).get(c, 3) for c in buys]
    rolls = actual.get("refreshes") or 0
    levelled = bool(actual.get("upgrades"))
    out = {"cards_bought": len(buys), "card_gold": sum(costs),
           "card_costs": list(zip(buys, costs)),
           "rolls": rolls, "roll_gold": rolls,
           "levelled": levelled, "level_gold": level_cost if levelled else None}
    out["total"] = out["card_gold"] + out["roll_gold"] + (out["level_gold"] or 0)
    return out


def _commitment(analysis):
    """Comp commitment at this turn's buy end, straight from the analysis.

    `live_coach.analyze()` already computes `comp_progress` (how close each
    candidate comp is to its commit threshold) and names the target comp, so
    this is a projection, not a second computation — the per-turn series is
    free once the replay exists.
    """
    prog = analysis.get("comp_progress") or []
    return {
        "target": analysis.get("target_comp"),
        "gap": analysis.get("comp_gap"),
        "progress": [{"name": r.get("name"), "hits": r.get("hits"),
                      "ready": bool(r.get("ready")),
                      "owned": len([n for n in (r.get("needs") or [])]),
                      } for r in prog[:3]],
    }


#: Roles that make a card worth KEEPING on the board it sits on, and roles that
#: make it the obvious thing to sell instead. `value.sell_reason` is the single
#: source of these strings — the same function the overlay's "Your board" row
#: prints, so a blunder call cannot drift from what the player was shown.
_HIGH_ROLES = frozenset({"comp core", "comp addon", "comp glue",
                         "engine piece", "scaler"})
_LOW_ROLES = frozenset({"filler", "off-comp filler", "off-comp body",
                        "stats only — no comp role"})


def _took(actual):
    """The card ids that moved this turn — what the gold was spent ON.

    Kept as ids rather than prose: `settle_up` already owns the one place that
    turns ids into words, and two formatters for the same thing would drift.
    """
    return {"bought": list(actual.get("buys") or []),
            "sold": list(actual.get("sells") or []),
            "triples": len(actual.get("triples") or []),
            "hero_power": actual.get("hero_power") or 0,
            "spells_cast": actual.get("spells") or 0}


def _sell_questions(sold_ids, end_board, analysis, card_db):
    """One sell-side question per TURN: a key card sold while a filler stayed.

    THE MAINTAINER'S EXAMPLE, made computable: "selling a key minion instead of
    the throwaway". The comparison is between the role of each card SOLD this
    turn and the roles of the cards the player KEPT — read off the board at buy
    end, which is by definition what remained.

    **One question per turn, not per card.** The first version fired per sold
    card and produced 12 questions in an 11-turn game, nearly all of them the
    same sentence: the identical filler sat on the board while four scalers were
    sold, so it printed that board state four times. One turn is one decision
    about what to sell, and it gets one line.

    **A turn that sells most of its board is a REBUILD, and is labelled as one.**
    Selling four minions at once is repositioning or pivoting, not four mistakes
    — the choice the detector can actually see (this card over that filler) is
    not what happened there. `rebuild` is set so a renderer can say "rebuilt the
    board" instead of implying a blunder, and a count of sell questions can keep
    meaning what it says. Three is the threshold: a five-minion board selling
    three has committed to a new board, and below that the swap reading holds.

    It returns QUESTIONS, never verdicts, and the naming says so. A comp core is
    sometimes exactly right to sell (making room for a triple, a duplicate core,
    a pivot the model has not caught up with), and this cannot see the player's
    reasoning.
    """
    from value import sell_reason
    if not card_db:
        # Without the card DB no role can be classified, and an unclassified
        # card is not evidence of a blunder. Return nothing rather than
        # defaulting every sold card into a "filler" it may not be.
        return []
    tc = analysis.get("target_cards") or {}
    core = {c.get("card") for c in (tc.get("core") or []) if isinstance(c, dict)}
    addons = {c.get("card") for c in (tc.get("addons") or []) if isinstance(c, dict)}
    comp = None
    for c in (analysis.get("playable_comps") or {}).values():
        if isinstance(c, dict) and c.get("name") == analysis.get("target_comp"):
            comp = c
            break
    banned = set(analysis.get("banned") or [])

    def role(cid, tribe=None):
        rec = card_db.get(cid) or {}
        return sell_reason({"card": cid, "tribe": tribe or rec.get("race")},
                           rec, comp=comp, core=core, addons=addons,
                           banned_tribes=banned)

    kept = [(m.get("card"), role(m.get("card"))) for m in (end_board or [])]
    low_kept = [(c, r) for c, r in kept if r in _LOW_ROLES]
    # Distinct cards, in the order they were sold. The list can repeat an id —
    # measured: turn 7 of the 10-06 game reports ['TB_BaconUps_159',
    # 'Fire Baller', 'Fire Baller'], three entries for two cards.
    seen, sold = set(), []
    for cid in sold_ids or []:
        if cid not in seen:
            seen.add(cid)
            sold.append((cid, role(cid)))
    high = [(c, r) for c, r in sold if r in _HIGH_ROLES]
    if not high or not low_kept:
        return []
    best = high[0]
    return [{
        "sold": best[0], "role": best[1],
        "also_sold": [{"card": c, "role": r} for c, r in high[1:]],
        "sold_count": len(sold),
        "kept_fillers": [c for c, _r in low_kept],
        "rebuild": len(sold) >= 3,
    }]


def _fights(fight, friendly):
    """A turn's combat snapshots, grouped into fights. PURE.

    The separator is the OPPONENT's board restaging after it drained: a
    fight runs from the opponent's first staged burst until their side is
    gone again (our survivors can stay on screen through the drain — the
    2026-10-07 final kept ours between the two fights). A new group starts
    only when their board comes BACK. One turn can hold more than one
    fight: that final staged the round's fight vs a 107-stat board and
    then the game's final duel vs a 1510-stat board in the SAME turn, and
    a renderer that takes the first burst shows the wrong game. Ours-only
    bursts (their staging lagged ours, or the log ended mid-stage) belong
    to the current group, never start one.
    """
    groups, cur = [], []
    theirs_seen = False   # the current group has staged an opponent
    theirs_gone = False   # ... and their side drained again afterwards
    for s in fight:
        ms = s.get("minions") or []
        theirs = friendly is not None and any(
            len(m) > 0 and m[0] is not None and m[0] != friendly for m in ms)
        if theirs and theirs_gone:
            groups.append(cur)
            cur = []
            theirs_seen = False
            theirs_gone = False
        cur.append(s)
        if theirs:
            theirs_seen = True
        elif theirs_seen:
            theirs_gone = True
    if cur:
        groups.append(cur)
    return groups


def _burst_stats(snap):
    """Combined atk+health of every minion in one raw snapshot, both sides —
    the measure the Battle peak picks (post-procs, pre-deaths)."""
    return sum((m[2] or 0) + (m[3] or 0) for m in (snap.get("minions") or [])
               if len(m) >= 4)


def _turn_rows(snaps, info, friendly, final_board=None, card_db=None):
    """Assemble the per-turn rows from snapshots. PURE — no coach, no log.

    Split out of `timeline()` so the reconstruction's decisions are testable
    without a real Power.log: which snapshot is the buy-end board, where the
    lag note comes from, what the growth series measures. A test that builds a
    row by hand and asserts the fields it just wrote is not a control.

    The turn list is the union of the snapshot buckets and the analyzed
    phases: a recruit phase the player did nothing in can be analyzed (its
    shop offers settled) while almost no snapshot fired in it, and dropping
    it would silently renumber every later turn against what the coach's
    phase rows — graded on the same numbers — say.
    """
    turns = sorted(set(snaps) | set(info))
    rows = []
    prev_stats = None
    for i, t in enumerate(turns):
        snaps_t = snaps.get(t) or []
        buy = [s for s in snaps_t if s.get("phase") == "buy"]
        fight = [s for s in snaps_t if s.get("phase") == "combat"]

        # Buy END = the last buy snapshot. The FIRST one belongs to the previous
        # fight's teardown (its `theirs` is the last opponent's survivors), so
        # using it would show the wrong opponent on every single turn.
        buy_end = _snap_board((buy[-1].get("minions") if buy else []),
                              friendly, "ours")
        # Buy START = the first buy snapshot, OUR side only: what survived the
        # previous fight and opened the shop. (Its `theirs` side is the stale
        # teardown — trap 3.4 — so this board is deliberately one-sided.) The
        # fight's summoned leftovers are still in PLAY in that snapshot and
        # have to come out of it — see _opening_board.
        buy_start, buy_start_removed = _opening_board(buy[0] if buy else None,
                                                     friendly)
        # Combat START = the first snapshot of the turn's LAST fight. Several
        # bursts share a turn (turn 4 has four — deaths and buffs re-stage
        # continuously); the first burst of a FIGHT is where that fight
        # begins, and it is the one that stages both boards. When the turn
        # holds two fights (round fight, then the final duel), the decisive
        # one is the last — see _fights.
        fights = _fights(fight, friendly)
        combat = fights[-1][0] if fights else None
        ours_at_combat = _snap_board(combat.get("minions") if combat else [],
                                     friendly, "ours")
        theirs_at_combat = _snap_board(combat.get("minions") if combat else [],
                                       friendly, "theirs")
        # Battle PEAK = the fight's burst after beginning-of-combat effects
        # have landed and before the first death: the staging burst reads LOW
        # (start-of-combat procs fire between the staging and the first
        # swing — measured 2026-10-06: 31 stats staged, 51 a burst later),
        # and everything after the first minion-count drop is the fight
        # thinning. So: candidates are the bursts up to the first count
        # drop, and the peak is the strongest of those. Plain max-combined
        # lands on a late ours-snowball burst with the opponent's board
        # already dead — measured on the 2026-10-07 final (4730 vs 448: the
        # duel's aftermath, not its beginning).
        peak = None
        if fights:
            group = fights[-1]
            counts = [len(s.get("minions") or []) for s in group]
            upto = len(group)
            for bi, bc in enumerate(counts):
                if bc < counts[0]:
                    upto = bi
                    break
            peak = max(group[:upto] or group[:1], key=_burst_stats)
        ours_at_peak = _snap_board(peak.get("minions") if peak else [],
                                   friendly, "ours")
        theirs_at_peak = _snap_board(peak.get("minions") if peak else [],
                                     friendly, "theirs")

        # Battle END = the next turn's opening board: the survivors, with combat
        # buffs reverted to what persisted. It is read through the SAME filter
        # as buy_start, because it IS the next turn's buy_start: the fight's
        # summoned leftovers are in PLAY there too, and turn 14 of the
        # 2026-10-07 game reported nine survivors for a board of seven.
        nxt = snaps.get(turns[i + 1]) if i + 1 < len(turns) else None
        nxt_buy = [s for s in (nxt or []) if s.get("phase") == "buy"]
        if nxt_buy:
            battle_end, battle_end_removed = _opening_board(nxt_buy[0],
                                                            friendly)
        elif i + 1 == len(turns):
            battle_end, battle_end_removed = list(final_board or []), 0
        else:
            battle_end, battle_end_removed = [], 0

        # The RESULT, from the fight itself: combat ends when one side's board
        # dies, so the side whose staged board drains to empty first LOST. The
        # next shop's snapshots cannot answer this — they catch the combat
        # copies MID-TEARDOWN, dead minions still staged (measured 2026-10-07:
        # aftermath lists showed both sides holding minions, some of them
        # dead). When they lose, their last staged board is the closest thing
        # to their survivors; it carries combat-time stats and says so by
        # where it comes from.
        winner, their_last = None, []
        if fights and friendly is not None:
            seen_theirs = seen_ours = False
            prev_theirs_board = []
            for s2 in fights[-1]:
                ms2 = s2.get("minions") or []
                tn = sum(1 for m in ms2 if len(m) > 0 and m[0] is not None
                         and m[0] != friendly)
                on = sum(1 for m in ms2 if len(m) > 0 and m[0] == friendly)
                board_theirs = _snap_board(ms2, friendly, "theirs")
                if tn:
                    seen_theirs = True
                    prev_theirs_board = board_theirs
                if on:
                    seen_ours = True
                if seen_theirs and seen_ours and (not tn or not on):
                    if not tn and on:
                        winner = "us"          # their board died, ours stands
                        their_last = prev_theirs_board
                    elif not on and tn:
                        winner = "them"        # ours died, their board stands
                        their_last = board_theirs
                    else:
                        winner = "tie"         # both boards died together
                        their_last = []
                    break
        # Exactly one side holds survivors after a fight — theirs only when
        # THEY won (their last staged board, combat-time stats).
        theirs_survivors = their_last if winner == "them" else []

        entry = info.get(t) or {}
        a = entry.get("analysis") or {}
        actual = entry.get("actual") or {}
        bstats = stats(buy_end)
        notes = []
        # The buy-phase snapshots LAG the real end of the buy phase: they fire
        # on each minion entering PLAY and on each leaving it, and a player
        # keeps playing after the coach's last look. Measured: turn 4's last buy
        # snapshot holds 1 of our minions while the combat staging holds 3 —
        # two were played in between. The combat board is therefore the
        # authoritative "what you went in with", and this difference is worth
        # saying out loud rather than letting the buy-end row read as final.
        lag = len(ours_at_combat) - len(buy_end)
        if friendly is None:
            # Every board above is empty because the side split was refused
            # (see _snap_board). Say why, instead of reporting "no snapshot".
            notes.append("player identity was never resolved in this game, so "
                         "no board can be attributed to a side")
        else:
            # The lag note needs a buy board to lag. Turn 1 has no buy-phase
            # snapshot at all, and saying "1 minion was played after the last
            # buy-phase snapshot" there contradicted the very next note.
            if lag > 0 and buy_end:
                notes.append(
                    f"{lag} minion(s) were played after the last buy-phase "
                    f"snapshot — the combat board is the full picture")
            if not combat:
                notes.append("no combat staged for this turn")
            if not buy_end:
                notes.append("no buy-phase board snapshot (a skipped turn, or a "
                             "turn whose plays were all combat summons)")
            if i + 1 == len(turns) and not battle_end:
                notes.append("final board not recoverable")
        # Damage taken across THIS turn's fight, from the effective HP the
        # coach recorded at this turn and the next (armor is just extra
        # health). None where either side is missing — the last turn, or a
        # turn the coach never advised on.
        eff = None if a.get("health") is None \
            else (a.get("health") or 0) + (a.get("armor") or 0)
        nxt_entry = (info.get(turns[i + 1]) or {}).get("analysis") or {} \
            if i + 1 < len(turns) else {}
        nxt_eff = None if nxt_entry.get("health") is None \
            else (nxt_entry.get("health") or 0) + (nxt_entry.get("armor") or 0)
        rows.append({
            "turn": t,
            "gold": a.get("gold"),
            "tier": a.get("tier"),
            "buy_start": buy_start,
            "buy_end": buy_end,
            # How many of the log's raw minions the opening/surviving board
            # dropped as the fight's leftovers. Counts, not prose, so a
            # renderer puts each one beside the board it is about; both are 0
            # on an ordinary turn, and 0 on a replay saved before 2026-10-07
            # (no entity ids, so only the board cap can apply).
            "buy_start_removed": buy_start_removed,
            "battle_end_removed": battle_end_removed,
            "combat_start": {"ours": ours_at_combat, "theirs": theirs_at_combat},
            "combat_peak": {"ours": ours_at_peak, "theirs": theirs_at_peak},
            "battle_end": battle_end,
            "winner": winner,
            "theirs_survivors": theirs_survivors,
            "stats": {
                "buy_end": bstats,
                "growth": None if prev_stats is None else bstats - prev_stats,
                "theirs": stats(theirs_at_combat),
                "combat_ours": stats(ours_at_combat),
            },
            "spend": _spend(actual, a.get("level_cost"), _buy_prices(a)),
            "took": _took(actual),
            # The Shop section's events, straight off the action parse: what
            # was played, whether the tavern levelled, whether the hero
            # power was pressed, and which picks were trinkets (their ids
            # all carry MagicItem — hero picks and discovers do not).
            "shop_events": {
                "played": len(actual.get("plays") or []),
                "tier_up": (actual.get("upgrades") or 0) > 0,
                "hero_power": (actual.get("hero_power") or 0) > 0,
                "trinkets": [c for c in (actual.get("choices") or [])
                             if "MagicItem" in str(c)],
            },
            "damage_taken": None if (eff is None or nxt_eff is None)
                            else eff - nxt_eff,
            "commitment": _commitment(a),
            # Sell-side questions, from the roles of what left vs what stayed.
            # Empty when there is no card DB or nothing sold, never guessed at.
            "sell_questions": _sell_questions(actual.get("sells"), buy_end, a,
                                              card_db),
            "lag": max(0, lag),
            "notes": notes,
        })
        if buy_end:
            prev_stats = bstats
    return rows


def timeline(log_path, game_index=1):
    """The per-turn board timeline for one game. Pure reading — writes nothing.

    Returns {"turns": [...], "hero": ..., "placement": ..., "friendly": ...},
    where each turn is:

        {turn, gold, buy_start, buy_end, combat_start: {ours, theirs},
         combat_peak: {ours, theirs}, battle_end, theirs_survivors,
         stats: {buy_end, growth, theirs, combat_ours}, spend, took,
         shop_events: {played, tier_up, hero_power, trinkets}, damage_taken,
         commitment, sell_questions, buy_start_removed, battle_end_removed,
         lag, notes}

    `notes` carries what the reconstruction is NOT, per turn, so a renderer
    cannot accidentally present an inference as a fact. `sell_questions` is
    likewise named for what it is: a card that left while a filler stayed is
    worth a look, not a mistake until a human says so.
    """
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    bounds = list(split_game_chunks(lines))
    if not 1 <= game_index <= len(bounds):
        raise SystemExit(f"{os.path.basename(log_path)} has {len(bounds)} "
                         f"game(s); game {game_index} does not exist")
    lo, hi = bounds[game_index - 1]
    chunk = lines[lo:hi]
    coach, info, header_friendly = _drive(chunk)
    # The header player wins when the coach never resolved one (see _drive).
    friendly = header_friendly if header_friendly is not None else coach.friendly
    snaps = getattr(coach, "_snap_by_turn", {}) or {}

    # The last turn has no successor to read its survivors from. board_state's
    # final board is the persistent board read before the end-of-game cleanup —
    # it comes back as coach minion DICTS, not snapshot tuples, so it goes
    # through the same transform fight_table uses rather than a second one
    # written here.
    final_board = []
    if friendly is not None and hasattr(coach.gs, "final_board"):
        final_board = _struct_board(coach.gs.final_board(friendly)[0])

    rows = _turn_rows(snaps, info, friendly, final_board, card_db=_load_card_db())
    turns = sorted(set(snaps) | set(info))
    first = (info.get(turns[0]) or {}).get("analysis") or {} if turns else {}
    return {"turns": rows,
            "hero": first.get("hero"),
            "friendly": friendly,
            "phases_analyzed": len(info),
            "turn_count": len(turns)}
