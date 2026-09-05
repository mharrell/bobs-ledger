#!/usr/bin/env python3
"""Live coach monitor: tail the active Power.log and advise on each buy phase.

While Hearthstone is running and writing Power.log, poll it for new data. When a
new buy phase (MAIN_ACTION) begins, parse the in-progress game and run the coach
situation analysis. This is the first step toward advising in real time (the
advice model would turn the analysis into spoken coaching).

The parsers (board_state, bans, coach) already work on partial games, so we just
re-read the tail and run the existing coach loop on each decision point.

Usage:
    python live.py                     # auto-find the active session
    python live.py <Power.log> [--once] [--poll N]
"""
import glob
import os
import sys
import time

from choices import choice_kind, rank_choices
from coach import describe
from config import HS_LOG_GLOB
from live_coach import LiveCoach
import coach_ui
import decision_log


def find_active_log():
    """Newest Hearthstone_*/Power.log written more recently than `recent_seconds`."""
    recent_seconds = int(os.environ.get("LIVE_RECENT", "600"))
    logs = sorted(
        glob.glob(HS_LOG_GLOB),
        key=os.path.getmtime, reverse=True,
    )
    for path in logs:
        age = time.time() - os.path.getmtime(path)
        if age < recent_seconds:
            return path
    return logs[0] if logs else None


_last_board = None  # (card, atk, health) fingerprint of the last advised board


_last_state = None  # last fingerprint the console was advised on


def _advise_pick(coach, log_path=None, log_offset=None, game_no=None):
    """A pending pick with no shop yet (hero selection) — rank it directly.

    The buy-phase loop can't fire here: hero selection has no tavern offers
    and the full analysis returns None until the hero locks in, so without
    this path the hero pick (the most consequential pick of the game) never
    showed. Pushes a minimal analysis (the "Choose 1" overlay box) and prints
    the ranked options.
    """
    global _last_state
    c = coach.choice
    if not c or c.get("picked") is not None or not c.get("options"):
        return
    # Dedup BEFORE ranking: rank_choices runs the full shop-ranking pipeline,
    # and this fires every poll tick while the pick sits on screen — checked
    # after ranking it re-ranked ~3x/second for as long as the pick waited.
    state = ("pick", c.get("source"), tuple(c["options"]))
    if state == _last_state:
        return
    kind = choice_kind(c["ctype"], c["source"], c["options"])
    ranked = rank_choices(kind, c["options"], [], None)
    if not ranked:
        return
    best = ranked[0]
    a = {
        "hero": None, "tier": None, "gold": None, "board": [], "banned": [],
        "sell_rank": [], "shop_rank": [], "scenario": {},
        "target_cards": None, "comps": [],
        "choice": {"kind": kind, "source": c["source"], "ranked": ranked},
        "top_move": ("1. PICK " + best[0]
                     + (f" ({best[3]})" if best[3] else "")
                     + (f" — if locked, {ranked[1][0]}"
                        if kind == "hero" and len(ranked) > 1 else "")),
    }
    state = ("pick", c.get("source"), tuple(c["options"]))
    _last_state = state
    coach_ui.update_analysis(a)
    decision_log.record(a, log_path=log_path, log_offset=log_offset,
                        game_no=game_no)
    fallback = f" (or {ranked[1][0]} if locked)" if (kind == "hero" and len(ranked) > 1) else ""
    print("\n" + "=" * 52)
    print(f"CHOOSE 1 ({kind}) — pick {best[0]}{fallback}")
    for n, _cid, s, why in ranked:
        mark = " <-- " if n == best[0] else "     "
        print(f"  {mark}{n}" + (f"  [{s:.1f} {why}]" if s is not None and why else ""))
    print("=" * 52 + "\n", flush=True)


def _advise(coach, force=False, log_path=None, log_offset=None, game_no=None):
    """Analyze the current incremental state, push to the overlay, and print.

    Skips the text print if the decision state (gold, tier, board, shop) is
    unchanged since the last advisory, but always pushes to the overlay. The
    state fingerprint — not just the board — is the dedup key, so a mid-turn
    buy/roll (gold down, shop changed) re-advices with the new affordability
    and remaining offers, while unrelated log chatter doesn't re-print.
    Each NEW advisory is also recorded to the decision log (log basename +
    byte offset are the join keys with the Power.log in the beta corpus).
    """
    global _last_state
    try:
        a = coach.analyze()
        if a is None:
            return
        coach_ui.update_analysis(a)
        fingerprint = coach.state_fingerprint()
        if fingerprint == _last_state and not force:
            return  # nothing the advice depends on has changed
        _last_state = fingerprint
        decision_log.record(a, log_path=log_path, log_offset=log_offset,
                            game_no=game_no)
        print("\n" + "=" * 52)
        print(describe(a))
        print("=" * 52 + "\n", flush=True)
    except Exception as e:  # noqa: BLE001 - a bad partial parse shouldn't kill the loop
        print(f"  (coach skipped: {e})", flush=True)


def _catch_up(f, coach):
    """Feed the file's current content into the coach; return the new offset."""
    f.seek(0)
    data = f.read().decode("utf-8", errors="replace")
    for line in data.splitlines():
        coach.feed(line)
    return f.tell()


def monitor(path, poll=1.0):
    """Tail the log; advise on every decision-state change during a buy phase.

    A new buy phase is the first MAIN_ACTION of a turn. MAIN_ACTION re-enters
    within a turn (e.g. after a refresh); only GameState STEP lines delimit it
    (the PowerTaskList copies re-arm mid-turn on a stale shop). While in the
    buy phase, the coach re-advises whenever the decision state changes — a
    buy (gold down, shop loses an offer), a roll, a play, a sell — so the
    advice tracks the turn instead of firing once and going stale. Each tick
    it re-finds the newest active log and switches to a newly-started session
    automatically. The parse is maintained incrementally (LiveCoach), so each
    analysis is fast (~ms).
    """
    coach = LiveCoach()
    print(f"Live-coaching {path}", flush=True)
    f = open(path, "rb")
    last_offset = _catch_up(f, coach)
    _advise(coach, force=True)  # seed the overlay with the current (last) game
    in_action = False
    last_state = None
    next_log_check = 0.0  # session discovery throttled to ~5s (was every tick)
    meta_checked_lines = 0  # only retry the hero parse when new lines arrived
    try:
        while True:
            # A new session (Hearthstone_*/Power.log) may appear; switch to it.
            # Re-globbing the Logs dir every 0.3s tick was pure overhead —
            # a new session can only appear every few seconds.
            active = None
            if time.time() >= next_log_check:
                next_log_check = time.time() + 5.0
                active = find_active_log()
            if active and os.path.abspath(active) != os.path.abspath(path):
                print(f"New session detected: {active}", flush=True)
                f.close()
                path = active
                f = open(path, "rb")
                coach = LiveCoach()
                last_offset = _catch_up(f, coach)
                _advise(coach, force=True)
                in_action = False
                last_state = None
                meta_checked_lines = 0

            f.seek(last_offset)
            data = f.read().decode("utf-8", errors="replace")
            if data:
                last_offset = f.tell()
                for line in data.splitlines():
                    coach.feed(line)
                    # Only GameState STEP lines delimit the buy phase — the
                    # PowerTaskList copies arrive after MAIN_END and would
                    # re-arm mid-turn on a stale shop.
                    is_gs = "GameState." in line
                    if is_gs and "tag=STEP value=MAIN_ACTION" in line:
                        in_action = True
                    elif is_gs and "tag=STEP value=MAIN_END" in line:
                        in_action = False  # combat ends the buy phase
                        last_state = None  # force a fresh advisory next phase
                # Advise while the shop is parsed and the decision state has
                # changed: the first MAIN_ACTION of a turn (last_state None),
                # then again on every mid-turn change (buy, roll, play, sell).
                # The empty-shop gap right after a buy (before the game
                # re-prints the options) can't fire — tavern_offers() is empty.
                # A None fingerprint (new game, hero not yet parsed) can't
                # differ from a None last_state, so retry the hero parse each
                # tick until it lands — otherwise the game never advises.
                if in_action and coach.tavern_offers():
                    state = coach.state_fingerprint()
                    if state is None:
                        # Retry the hero parse only when new lines arrived:
                        # ensure_meta re-runs extract_game over the whole line
                        # buffer, and a hero that never parses (spectate, odd
                        # formats) would otherwise rescan an ever-growing
                        # buffer ~3x/second for the whole session.
                        if len(coach.cur_lines) > meta_checked_lines:
                            coach.ensure_meta()
                            meta_checked_lines = len(coach.cur_lines)
                    elif state != last_state:
                        last_state = state
                        _advise(coach, log_path=path, log_offset=last_offset,
                                game_no=coach.game_no)
                # A pending pick outside the buy phase (hero selection has no
                # tavern offers and the full analysis isn't ready yet) still
                # gets its Choose-1 advice.
                else:
                    _advise_pick(coach, log_path=path, log_offset=last_offset,
                                 game_no=coach.game_no)
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    path = args[0] if args else find_active_log()
    if not path or not os.path.exists(path):
        print("No active Power.log found (Hearthstone not running recently).")
        return 1
    poll = 0.3  # fast tail cadence — analysis is ~5ms, so sub-second updates
    ui_on = "--no-ui" not in opts
    for o in opts:
        if o.startswith("--poll"):
            poll = float(o.split("=")[1])
    # Start the overlay server (unless --no-ui); open it in the browser.
    if ui_on:
        try:
            server = coach_ui.start_server()
            print(f"Coach UI: http://127.0.0.1:{server.server_address[1]}/")
        except OSError as e:
            print(f"Coach UI skipped ({e})")
    if "--once" in opts:
        coach = LiveCoach()
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                coach.feed(line)
        _advise(coach)
        return 0
    try:
        monitor(path, poll)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
