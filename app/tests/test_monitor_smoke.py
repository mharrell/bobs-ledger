"""The monitor itself: a smoke test, because nothing else in the suite calls it.

Two published builds (5ce8f58, 5b7e83c) crashed on their FIRST tick with
`NameError: name 'opts' is not defined`, and 1229 tests passed through both,
because no test ever called `monitor()`. The shape of that release is the worst
one available: the overlay came up, looked healthy, and never advised.

Three things here that a plain "did it raise?" test would miss:

* **the game-end share line is REACHED.** The first `NameError` shipped on that
  line, and it only runs when the log says the game ended — a fixture that is
  simply mid-game never touches it, so a naive one-tick smoke test would still
  have passed. The fixture ends its game and has a decision log behind it.
* **a session SWITCH is exercised**, which is where the second `NameError`
  shipped (fixed in 6bcfbcc) and which is only reached when a newer `Power.log`
  appears.
* **nothing was SILENTLY swallowed.** `monitor()` catches per-tick and per-line
  exceptions and keeps looping on purpose, so "it did not raise" is not the same
  as "it worked". The test watches for the signatures it prints when it swallows
  something, and for the advice path actually producing a recorded advisory.

Nothing is sent and nothing real is written: every path the share path touches is
redirected into a temp dir, and the POST is captured rather than performed.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import coach_ui        # noqa: E402
import decision_log    # noqa: E402
import live            # noqa: E402
import session_report  # noqa: E402
import share           # noqa: E402
from tests.test_shop_parsing import opt_block  # noqa: E402

GS = "D 0:00:01.0 GameState.DebugPrintPower() - "
GAME = "D 0:00:01.0 GameState.DebugPrintGame() - "

#: Assembled rather than written as one literal, like test_friendly_player.py:
#: this file ships, and the release's privacy gate reads a handle-shaped literal
#: as a real player. Both are documented placeholders.
_LOCAL = "Tester" + "#" + "1234"
_OPP = "Player" + "#" + "1234"

#: The signatures monitor() prints when it swallows a failure. Asserting on them
#: is what makes this a smoke test rather than a crash test.
SWALLOWED = ("(monitor tick failed:", "(line skipped:", "(coach skipped:")

#: A live Power.log GROWS, and monitor() only looks for advice when new lines
#: arrived (the advise check sits inside `if chunk:`). Three further facts shape
#: what has to be appended, and all three are the real game's shape:
#:
#:   * the buy phase the monitor catches up on is deliberately NOT advised — the
#:     force-advise seed was removed so attaching to a finished game cannot paint
#:     the previous game's panel as live advice. The fixture therefore closes that
#:     phase and opens a NEW one, exactly as a turn boundary does.
#:   * MAIN_END is when the tavern closes, so the new turn needs its own options
#:     block; the offers from turn 1 are gone by then.
#:   * at the new turn's first gate the hero is not resolved yet, so
#:     `state_fingerprint()` is None and monitor() calls `ensure_meta()` instead
#:     of advising.
#:
#: The purse writes then change the decision state on a later tick, which is what
#: turns the resolved state into a real advisory.
GROWTH = (
    [f"{GS}Entity=GameEntity tag=STEP value=MAIN_END"],
    [f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION"]
    + opt_block(2, [("River Skipper", "BG33_140", 15),
                    ("Tusked Camper", "BG33_886", 15)]),
    [f"{GS}Entity={_LOCAL} tag=RESOURCES value=5"],
    [f"{GS}Entity={_LOCAL} tag=RESOURCES value=3"],
)


def _named_tag(eid, cid, player, tag, value):
    return (f"{GS}TAG_CHANGE Entity=[entityName=H id={eid} zone=PLAY "
            f"cardId={cid} player={player}] tag={tag} value={value}")


def _fixture(ended=True):
    """A session log that reaches a real buy phase, for one game.

    Local player 7 versus 15, and shop offers carrying `player=15`, match the
    convention the rest of the suite uses (test_shop_parsing.opt_block's tavern
    button is `player=7`).

    `ended` appends the local player's own PLAYSTATE, which is what flips
    `GameState._game_ended` and so is the only way to reach the share line.
    """
    lines = [
        f"{GS}CREATE_GAME",
        f"{GAME}PlayerID=7, PlayerName={_LOCAL}",
        f"{GAME}PlayerID=15, PlayerName={_OPP}",
        f"{GS}    Player EntityID=11 PlayerID=7 GameAccountId=[hi=9 lo=8]",
        f"{GS}        tag=HERO_ENTITY value=119",
        f"{GS}    Player EntityID=12 PlayerID=15 GameAccountId=[hi=0 lo=0]",
        f"{GS}        tag=HERO_ENTITY value=62",
        _named_tag(119, "BG33_HERO_001", 7, "ZONE", "PLAY"),
        _named_tag(62, "TB_BaconShop_HERO_PH", 15, "ZONE", "PLAY"),
        _named_tag(130, "BG23_HERO_306", 15, "PLAYER_LEADERBOARD_PLACE", 2),
        _named_tag(140, "BG32_HERO_001", 15, "PLAYER_LEADERBOARD_PLACE", 3),
        _named_tag(119, "BG33_HERO_001", 7, "PLAYER_LEADERBOARD_PLACE", 1),
        f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION",
    ]
    lines += opt_block(1, [("River Skipper", "BG33_140", 15),
                           ("Tusked Camper", "BG33_886", 15)])
    if ended:
        lines.append(f"{GS}TAG_CHANGE Entity={_LOCAL} tag=PLAYSTATE value=LOST")
    return lines


class MonitorSmokeTest(unittest.TestCase):
    """monitor() runs ticks over a real-shaped session. Read-only and offline."""

    TICKS = 8

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Every path the share path touches, redirected. Each is restored by
        # addCleanup: leaving a module global pointing at a deleted temp dir is
        # a real bug this suite has already had once (test_package_corpus.py).
        self._patch(decision_log, "LOG_DIR",
                    os.path.join(self.tmp.name, "decision_logs"))
        self._patch(share, "REPORTS_DIR", os.path.join(self.tmp.name, "reports"))
        self._patch(share, "SENT_PATH",
                    os.path.join(self.tmp.name, "reports", ".sent.json"))
        self._patch(share, "CONSENT_PATH",
                    os.path.join(self.tmp.name, "consent.json"))
        self._patch(session_report, "ID_MAP_DIR",
                    os.path.join(self.tmp.name, "reports"))
        # Consent is ON so the share path is actually walked, but the POST is
        # captured: the console/network is never touched.
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "share": true}')
        self.posted = []
        self._patch(share, "post_report", self._capture)
        # The module globals the monitor mutates.
        self._patch(live, "_shared_games", set())
        self._patch(live, "_LAST_SHARE_ATTEMPT", [0.0])
        self._patch(live, "_LAST_GAME", None)
        # No flags: monitor() reads argv itself, and that lookup is exactly where
        # the shipped NameError was.
        self._patch(sys, "argv", ["live.py"])
        self.out = io.StringIO()

    def _patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def _capture(self, blob, url=None, timeout=30):
        self.posted.append(blob)
        return True, "stored"

    def _session(self, name, ended=True, advisories=1):
        """A session dir + Power.log, plus a decision log behind it.

        The decision log matters: the share path only has something to send when
        a game's advisories are already recorded, which is also the real case
        (the coach is started while a session is in progress).
        """
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        log = os.path.join(path, "Power.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(_fixture(ended=ended)) + "\n")
        for _ in range(advisories):
            decision_log.record({"top_move": "1. Buy a thing", "gold": 3,
                                 "tier": 1, "board": [], "hand": [],
                                 "shop_rank": []},
                                log_path=log, log_offset=42, game_no=1)
        return log

    def _drive(self, log, growth=GROWTH, ticks=None):
        """Run monitor() for `ticks` ticks, then leave it as Ctrl-C does.

        One growth line is appended before each tick after the first: that is
        what a live log does, and without it the monitor correctly decides there
        is nothing new to reason about.
        """
        ticks = self.TICKS if ticks is None else ticks
        seen = {"n": 0}

        def fake_sleep(_seconds):
            seen["n"] += 1
            if seen["n"] <= len(growth):
                with open(log, "a", encoding="utf-8") as f:
                    for line in growth[seen["n"] - 1]:
                        f.write(line + "\n")
            if seen["n"] > ticks:
                raise KeyboardInterrupt

        with mock.patch.object(live.time, "sleep", fake_sleep), \
                contextlib.redirect_stdout(self.out):
            live.monitor(log, 0.01)
        return seen["n"]

    def _text(self):
        return self.out.getvalue()

    def assertNothingSwallowed(self):
        text = self._text()
        for signature in SWALLOWED:
            self.assertNotIn(
                signature, text,
                f"monitor() swallowed a failure and kept looping:\n{text[-2000:]}")

    def _records(self):
        out = []
        log_dir = decision_log.LOG_DIR
        for name in sorted(os.listdir(log_dir)):
            with open(os.path.join(log_dir, name), encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.append(json.loads(line))
        return out

    # ---------------------------------------------------------------- tests

    def test_a_tick_runs_and_the_advice_path_produces_an_advisory(self):
        """The overdue one: one game, real ticks, real advice, no exception."""
        log = self._session("Hearthstone_2026_10_04_11_36_38")
        self._patch(live, "find_active_log", lambda: log)
        before = len(self._records())

        ticks = self._drive(log)                      # raises if monitor() does

        self.assertGreaterEqual(ticks, self.TICKS)
        self.assertNothingSwallowed()
        self.assertIsNotNone(coach_ui.latest_analysis(),
                             "no analysis was ever pushed to the overlay")
        records = [r for r in self._records() if r.get("game") == 1]
        self.assertGreater(
            len(records), before,
            "the advice path never recorded an advisory for the live game")
        # The join keys are the point of the record: without them the corpus
        # cannot place this advisory against the Power.log it came from.
        for r in records:
            self.assertEqual(r.get("log"), "Power.log")
            self.assertIsNotNone(r.get("offset"))
            self.assertEqual(r.get("game"), 1)

    def test_an_ended_game_is_shared_once(self):
        """The game-end share line runs, and only once.

        This is the line the first `NameError` shipped on. It needs the log to
        say the game ended, which is why the fixture does.
        """
        log = self._session("Hearthstone_2026_10_04_11_36_38")
        self._patch(live, "find_active_log", lambda: log)

        self._drive(log)

        self.assertNothingSwallowed()
        self.assertEqual(len(self.posted), 1,
                         "an ended game should be shared exactly once")
        self.assertEqual(live._LAST_GAME, (1, True),
                         "the exit backstop's view of the game is wrong")

    def test_a_game_still_being_played_is_never_shared(self):
        """The backstop's measured bug: a mid-game session must send nothing.

        A turn-5 game was uploaded with 14 of its eventual 128 advisories under a
        report id no later rebuild could correct (2026-10-04). The game here has
        not ended, so there is nothing complete to send.
        """
        log = self._session("Hearthstone_2026_10_04_11_36_38", ended=False)
        self._patch(live, "find_active_log", lambda: log)

        self._drive(log)

        self.assertNothingSwallowed()
        self.assertEqual(self.posted, [],
                         "a game that had not finished was uploaded")
        self.assertEqual(live._LAST_GAME, (1, False))
        # And the exit path, which is the one that actually fired in the field.
        live._LAST_GAME = (1, False)
        self.assertEqual(live._share_finished(log), "skipped")
        self.assertEqual(self.posted, [])

    def test_a_session_switch_shares_the_old_session_and_keeps_going(self):
        """The second `NameError` shipped in this branch (fixed in 6bcfbcc).

        The old session's game has ended (the new session is proof of that), so
        switching to the new one must share it — and the new session, which is
        mid-game, must send nothing.
        """
        first = self._session("Hearthstone_2026_10_04_10_00_00")
        second = self._session("Hearthstone_2026_10_04_11_36_38", ended=False)
        self._patch(live, "find_active_log", lambda: second)

        self._drive(first)

        txt = self._text()
        self.assertIn("New session detected", txt)
        self.assertNothingSwallowed()
        self.assertEqual(len(self.posted), 1,
                         "the previous session's finished game was not shared")
        self.assertIn("shared", txt)
        # Attributed to the session that ended, not to the one now being played.
        with open(share.REPORTS_DIR + os.sep + ".report_ids.json",
                  encoding="utf-8") as f:
            ids = json.load(f)
        self.assertIn("Hearthstone_2026_10_04_10_00_00#1", ids)
        self.assertNotIn("Hearthstone_2026_10_04_11_36_38#1", ids)

    def test_the_monitor_survives_a_log_it_cannot_open(self):
        """A missing log is a startup error, not a swallowed tick.

        `main()` checks the path, but monitor() is also called directly by tests
        and by hand, and its `finally` closes the file — so an unopenable file
        must fail loudly rather than leave the loop half-built.
        """
        with self.assertRaises(OSError):
            with contextlib.redirect_stdout(self.out):
                live.monitor(os.path.join(self.tmp.name, "nope", "Power.log"), 0.01)


if __name__ == "__main__":
    unittest.main()
