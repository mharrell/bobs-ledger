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

from coach import analyze, describe
import coach_ui


def find_active_log():
    """Newest Hearthstone_*/Power.log written more recently than `recent_seconds`."""
    recent_seconds = int(os.environ.get("LIVE_RECENT", "600"))
    logs = sorted(
        glob.glob(r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"),
        key=os.path.getmtime, reverse=True,
    )
    for path in logs:
        age = time.time() - os.path.getmtime(path)
        if age < recent_seconds:
            return path
    return logs[0] if logs else None


def _last_game_index(path):
    from extract_game import split_game_chunks
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return len(list(split_game_chunks(lines)))


_last_board = None  # (card, atk, health) fingerprint of the last advised board


def run_coach(path):
    """Analyze the in-progress (last) game and print the analysis.

    Skips if the friendly board is unchanged since the last advisory, so the
    monitor doesn't spam on MAIN_ACTION re-entries within the same turn.
    """
    global _last_board
    try:
        gi = _last_game_index(path)
        a = analyze(path, gi)
        # Push the latest analysis to the UI overlay server (every parse, so gold
        # / trigger counts update even if the board is unchanged).
        coach_ui.update_analysis(a)
        board = a["board"]
        fingerprint = tuple(sorted((m["card"], m.get("atk"), m.get("health"))
                                   for m in board))
        if fingerprint == _last_board:
            return  # board unchanged -> don't re-advise
        _last_board = fingerprint
        print("\n" + "=" * 52)
        print(describe(a))
        print("=" * 52 + "\n", flush=True)
    except Exception as e:  # noqa: BLE001 - a bad partial parse shouldn't kill the loop
        print(f"  (coach skipped: {e})", flush=True)


def monitor(path, poll=1.0):
    """Tail the log; advise exactly once per buy phase.

    A new buy phase is the first MAIN_ACTION of a turn. MAIN_ACTION re-enters
    within a turn (e.g. after a refresh), so we advise only on the transition
    into MAIN_ACTION (in_action False -> True), and reset after MAIN_END
    (combat) starts the next turn.
    """
    last_offset = os.path.getsize(path)
    in_action = False
    print(f"Live-coaching {path}", flush=True)

    with open(path, "rb") as f:
        while True:
            f.seek(last_offset)
            data = f.read().decode("utf-8", errors="replace")
            if data:
                last_offset = f.tell()
                for line in data.splitlines():
                    if "tag=STEP value=MAIN_ACTION" in line:
                        if not in_action:  # entering the buy phase -> advise once
                            run_coach(path)
                            in_action = True
                    elif "tag=STEP value=MAIN_END" in line:
                        in_action = False  # combat ends the buy phase
            time.sleep(poll)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    path = args[0] if args else find_active_log()
    if not path or not os.path.exists(path):
        print("No active Power.log found (Hearthstone not running recently).")
        return 1
    poll = 1.0
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
        run_coach(path)
        return 0
    try:
        monitor(path, poll)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
