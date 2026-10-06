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
    the next turn. The opponent's survivors are NOT recoverable this way and are
    reported as absent rather than guessed at.

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


def _snap_board(minions, friendly, side):
    """One side of a snapshot as the structured board shape everything else uses.

    Snapshots are 6-tuples — (player, card, atk, health, golden, keywords) — since
    the projection widening; older/shorter tuples are tolerated rather than
    dropped, because a missing keyword list is not a reason to lose a minion.

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
        out.append({"card": m[1], "atk": m[2], "health": m[3],
                    "golden": bool(m[4]) if len(m) > 4 else False,
                    "keywords": list(m[5]) if len(m) > 5 and m[5] else []})
    return out


def stats(board):
    """The board's stat total — atk + health — the number the player can eyeball.

    NOT the value function's opinion of the board. `value.py` prices cards by
    comp role, growth and synergy, and that is a different question; this is the
    one a player can verify against what the game showed them.
    """
    return sum((m.get("atk") or 0) + (m.get("health") or 0) for m in board or [])


def _drive(chunk):
    """Feed the chunk the way the audit does, returning (coach, analysis_by_turn).

    One pass: walk the buy phases, settle inside each one (the shop has stopped
    changing), and call analyze(). That call is what resolves `friendly` and
    populates `_snap_by_turn`; feeding alone populates neither usefully.
    """
    coach = LiveCoach()
    seen = {}
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
        if a:
            turn = (a.get("scenario") or {}).get("turns")
            if turn is not None and turn not in seen:
                seen[turn] = a
    return coach, seen


def _turn_rows(snaps, analysis, friendly, final_board=None):
    """Assemble the per-turn rows from snapshots. PURE — no coach, no log.

    Split out of `timeline()` so the reconstruction's decisions are testable
    without a real Power.log: which snapshot is the buy-end board, where the
    lag note comes from, what the growth series measures. A test that builds a
    row by hand and asserts the fields it just wrote is not a control.
    """
    turns = sorted(snaps)
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
        # Combat START = the first combat snapshot of the burst. Several bursts
        # can share a turn (turn 4 has four); the first is where the fight
        # begins, and it is the one that stages both boards.
        combat = fight[0] if fight else None
        ours_at_combat = _snap_board(combat.get("minions") if combat else [],
                                     friendly, "ours")
        theirs_at_combat = _snap_board(combat.get("minions") if combat else [],
                                       friendly, "theirs")

        # Battle END = the next turn's opening board: the survivors, with combat
        # buffs reverted to what persisted.
        nxt = snaps.get(turns[i + 1]) if i + 1 < len(turns) else None
        nxt_buy = [s for s in (nxt or []) if s.get("phase") == "buy"]
        if nxt_buy:
            battle_end = _snap_board(nxt_buy[0].get("minions"), friendly, "ours")
        elif i + 1 == len(turns):
            battle_end = list(final_board or [])
        else:
            battle_end = []

        a = analysis.get(t) or {}
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
            if lag > 0:
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
        rows.append({
            "turn": t,
            "gold": a.get("gold"),
            "tier": a.get("tier"),
            "buy_end": buy_end,
            "combat_start": {"ours": ours_at_combat, "theirs": theirs_at_combat},
            "battle_end": battle_end,
            "stats": {
                "buy_end": bstats,
                "growth": None if prev_stats is None else bstats - prev_stats,
                "theirs": stats(theirs_at_combat),
                "combat_ours": stats(ours_at_combat),
            },
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

        {turn, gold, buy_end, combat_start: {ours, theirs}, battle_end,
         stats: {buy_end, growth, theirs}, notes: [...]}

    `notes` carries what the reconstruction is NOT, per turn, so a renderer
    cannot accidentally present an inference as a fact.
    """
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    bounds = list(split_game_chunks(lines))
    if not 1 <= game_index <= len(bounds):
        raise SystemExit(f"{os.path.basename(log_path)} has {len(bounds)} "
                         f"game(s); game {game_index} does not exist")
    lo, hi = bounds[game_index - 1]
    chunk = lines[lo:hi]
    coach, analysis = _drive(chunk)
    friendly = coach.friendly
    snaps = getattr(coach, "_snap_by_turn", {}) or {}

    # The last turn has no successor to read its survivors from. board_state's
    # final board is the persistent board read before the end-of-game cleanup —
    # it comes back as coach minion DICTS, not snapshot tuples, so it goes
    # through the same transform fight_table uses rather than a second one
    # written here.
    final_board = []
    if friendly is not None and hasattr(coach.gs, "final_board"):
        final_board = _struct_board(coach.gs.final_board(friendly)[0])

    rows = _turn_rows(snaps, analysis, friendly, final_board)
    turns = sorted(snaps)
    first = (analysis.get(turns[0]) or {}) if turns else {}
    return {"turns": rows,
            "hero": first.get("hero"),
            "friendly": friendly,
            "phases_analyzed": len(analysis),
            "turn_count": len(turns)}
