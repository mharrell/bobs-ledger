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
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import coach_ui        # noqa: E402
import decision_log    # noqa: E402
import live            # noqa: E402
import replay_store    # noqa: E402
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

#: Session directory names for the fixtures. `Hearthstone_2026_01_01` is the
#: placeholder privacy_scan names as THE session name our fixtures use: a session
#: directory is a local path, so a real-looking `Hearthstone_<date>` is a
#: personal-data finding in the publish gate (correctly — the first version of
#: this file invented one and the gate refused the release). The second name
#: deliberately carries no timestamp at all.
_SESSION_DIR = "Hearthstone_2026_01_01"
_NEXT_SESSION_DIR = "Hearthstone_test_next"

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

#: The same writes, plus the local player's elimination last: the game finishes
#: DURING the run, which is what lets a test tell "the panel was cleared when the
#: game ended" apart from "there was never a panel to clear".
GROWTH_THEN_END = GROWTH + (
    [f"{GS}TAG_CHANGE Entity={_LOCAL} tag=PLAYSTATE value=LOST"],)


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


def _advancing_clock(step=10.0):
    """A monotonic clock that jumps `step` seconds on every read.

    The cap notice waits for the writing to STOP rather than for the client's
    message (`live.CAP_STALL_SECONDS`), and no test should sit for twenty real
    seconds to prove a rule about elapsed time — so the clock is faked, exactly
    as `time.sleep` already is above.

    The step is deliberately UNDER that threshold: the monitor reads the clock
    twice in the tick that sees the banner (once to remember it, once to compare),
    so a step of 20 or more would look like a stall in the very tick the banner
    arrived — which is not what the real clock does, and not what is being tested.
    """
    state = {"t": 0.0}

    def now():
        state["t"] += step
        return state["t"]

    return now


class _MonitorHarness(unittest.TestCase):
    """The shared harness for driving `monitor()`: every path it touches is
    redirected into a temp dir, nothing is sent, and the run is ended the way
    Ctrl-C ends it.

    A real base class rather than a mixin, because both suites below need it and
    a shared one pays for the setup once. It is also the fix for a mistake worth
    recording: the rotation tests first subclassed `MonitorSmokeTest`, which
    silently re-ran every one of its tests inside the subclass — 20 tests became
    40, and the count was the only thing that noticed.
    """

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


class MonitorSmokeTest(_MonitorHarness):
    """monitor() runs ticks over a real-shaped session. Read-only and offline."""

    # ---------------------------------------------------------------- tests

    def test_a_tick_runs_and_the_advice_path_produces_an_advisory(self):
        """The overdue one: one game, real ticks, real advice, no exception."""
        log = self._session(_SESSION_DIR)
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
        log = self._session(_SESSION_DIR)
        self._patch(live, "find_active_log", lambda: log)

        self._drive(log)

        self.assertNothingSwallowed()
        self.assertEqual(len(self.posted), 1,
                         "an ended game should be shared exactly once")
        self.assertEqual(live._LAST_GAME, (1, True),
                         "the exit backstop's view of the game is wrong")

    def test_a_restart_saves_and_shares_the_finished_game_once(self):
        """The 2026-10-09 report, end to end: opening the app again must not
        re-create the last game's replay, and the card must show the placement
        and the round it previously read as `—`.

        Run 1 watches the game end and (auto-save on) writes its replay. Run 2
        is the restart: a fresh coach catches up on the SAME leftover log, so
        the finished game is re-detected with no analysis in memory. It must
        save nothing, share nothing, and still put `3rd`-shaped numbers — here
        the fixture's own — on the card.
        """
        store = os.path.join(self.tmp.name, "saved_replays")
        saved_dir = replay_store.store_dir
        replay_store.store_dir = (lambda root=None: store)
        self.addCleanup(setattr, replay_store, "store_dir", saved_dir)
        saved_auto = replay_store.AUTO_PATH
        replay_store.AUTO_PATH = os.path.join(self.tmp.name,
                                              ".save_all_replays.json")
        self.addCleanup(setattr, replay_store, "AUTO_PATH", saved_auto)
        replay_store.set_auto_save(True)

        def _store_files():
            return sorted(os.listdir(store)) if os.path.isdir(store) else []

        log = self._session(_SESSION_DIR)
        self._patch(live, "find_active_log", lambda: log)

        # ---- run 1: the game ends while the coach watches.
        self._drive(log)
        for _ in range(100):                    # the build runs off-thread
            if _store_files():
                break
            time.sleep(0.05)
        self.assertEqual(len(_store_files()), 1, "run 1 saves exactly one")
        self.assertEqual(len(self.posted), 1, "run 1 shares exactly once")
        after_run_1 = _store_files()

        # ---- run 2: the restart. Fresh process state, same leftover log.
        live._LAST_GAME = None
        live._LAST_SHARE_ATTEMPT[0] = 0.0
        live._shared_games.clear()
        self._drive(log, growth=())
        for _ in range(100):                    # allow any (wrong) late save
            if len(_store_files()) > 1:
                break
            time.sleep(0.05)
        self.assertEqual(_store_files(), after_run_1,
                         "the restart wrote a second file for the same game")
        self.assertEqual(len(self.posted), 1,
                         "the restart shared the game a second time")
        served = json.loads(coach_ui._analysis_response()[2])
        self.assertEqual(served.get("title"), "Game over")
        self.assertEqual(served.get("game_over"),
                         {"placement": 1, "turn": 1},
                         "the restart card names the placement and the round "
                         "instead of a dash (the round is the action tracker's "
                         "read of THIS fixture: its first options block sits "
                         "unflushed until the second MAIN_ACTION, the shape "
                         "the phantom-turn rule reads as a fight)")
        self.assertNothingSwallowed()

    def test_a_game_still_being_played_is_never_shared(self):
        """The backstop's measured bug: a mid-game session must send nothing.

        A turn-5 game was uploaded with 14 of its eventual 128 advisories under a
        report id no later rebuild could correct (2026-10-04). The game here has
        not ended, so there is nothing complete to send.
        """
        log = self._session(_SESSION_DIR, ended=False)
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

    def test_a_finished_game_does_not_leave_its_plan_on_screen(self):
        """The panel has to clear when the game ends, not at the next game.

        The last buy phase ends well before the game does — 34 s of combat and up
        to 76 s of post-game in one measured session, and indefinitely for a
        session's last game, because the only other clear is the NEXT game's
        `CREATE_GAME`. Until then the player is reading a buy instruction for a
        game that is over.
        """
        log = self._session(_SESSION_DIR, ended=False)
        self._patch(live, "find_active_log", lambda: log)
        before = len(self._records())

        self._drive(log, growth=GROWTH_THEN_END)

        self.assertNothingSwallowed()
        self.assertGreater(len(self._records()), before,
                           "no advice was recorded, so there was nothing to clear")
        self.assertIsNone(coach_ui.latest_analysis(),
                          "the finished game's plan is still on the overlay")
        self.assertEqual(live._LAST_GAME, (1, True))

    def test_a_finished_game_leaves_a_card_that_says_so(self):
        """What replaces the panel is the point, and it is what the field
        report was about: the overlay fell back to the FIRST-RUN card, the same
        one a fresh install shows, so "the game ended" and "the coach died" were
        the same screen. Asserted on the payload the page actually polls."""
        log = self._session(_SESSION_DIR, ended=False)
        self._patch(live, "find_active_log", lambda: log)

        self._drive(log, growth=GROWTH_THEN_END)

        served = json.loads(coach_ui._analysis_response()[2])
        self.assertEqual(served.get("title"), "Game over",
                         "the finished game fell back to the first-run card")
        self.assertIn("still running", served.get("status", ""))
        self.assertNotIn("steps", served,
                         "the log.config block belongs on a first run, not after "
                         "a game")

    def test_a_live_game_keeps_its_panel(self):
        """The clear must be triggered by the END, not by old advice."""
        log = self._session(_SESSION_DIR, ended=False)
        self._patch(live, "find_active_log", lambda: log)

        self._drive(log)

        self.assertNothingSwallowed()
        self.assertIsNotNone(coach_ui.latest_analysis(),
                             "a game still being played lost its panel")

    def test_a_session_switch_shares_the_old_session_and_keeps_going(self):
        """The second `NameError` shipped in this branch (fixed in 6bcfbcc).

        The old session's game has ended (the new session is proof of that), so
        switching to the new one must share it — and the new session, which is
        mid-game, must send nothing.
        """
        first = self._session(_NEXT_SESSION_DIR)
        second = self._session(_SESSION_DIR, ended=False)
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
        self.assertIn(_NEXT_SESSION_DIR + "#1", ids)
        self.assertNotIn(_SESSION_DIR + "#1", ids)

    def test_a_quiet_shop_is_reread_without_recording_anything(self):
        """Fix list round 4 item 3, the half a browser cannot show.

        The monitor advises on every decision-state CHANGE and says nothing in
        between, so an open shop that the player is thinking about keeps the
        payload it was first given: measured on the 2026-10-08 07:45 game, 11 of
        the 12 turns with a shop had at least one stretch longer than 8 s with no
        state change while it was open — and the page calls the advice old after
        8 s, so the NORMAL state of a live shop was "Read from Ns ago".

        So there is a short periodic re-read now — and it must be `record=False`:
        the decision state is IDENTICAL, and a decision-log record per silent tick
        is exactly the corpus inflation the fingerprint dedup was added to stop
        (2026-10-02: 295 records for 58 analyses in one session, which the beta
        corpus then shipped). This is asserted as a COUNT, because that is the
        only way the difference shows: more pushes than records.
        """
        log = self._session(_SESSION_DIR, ended=False)
        self._patch(live, "find_active_log", lambda: log)
        pushes, recorded = [], []
        clock = {"t": 0.0}
        self._patch(live.coach_ui, "update_analysis",
                    lambda a: pushes.append(a))
        self._patch(live.decision_log, "record",
                    lambda *a, **k: recorded.append(a))
        # A line the parser reads and the decision state does not: the log always
        # grows, and the monitor's advise block sits inside `if chunk:`.
        quiet = [f"{GS}TAG_CHANGE Entity=[entityName=idle id=999 zone=PLAY] "
                 f"tag=TURN_START value=1"]
        seen = {"n": 0}

        def fake_sleep(_seconds):
            seen["n"] += 1
            clock["t"] += 1.0          # the shop stays open for 12 fake seconds
            step = GROWTH[seen["n"] - 1] if seen["n"] <= len(GROWTH) else quiet
            with open(log, "a", encoding="utf-8") as f:
                for line in step:
                    f.write(line + "\n")
            if seen["n"] > 12:
                raise KeyboardInterrupt

        with mock.patch.object(live.time, "sleep", fake_sleep), \
                mock.patch.object(live.time, "monotonic",
                                  lambda: clock["t"]), \
                contextlib.redirect_stdout(self.out):
            live.monitor(log, 0.01)

        self.assertNothingSwallowed()
        self.assertTrue(recorded, "no advisory was recorded at all, so this "
                                  "proves nothing about the re-read")
        self.assertGreater(
            len(pushes), len(recorded),
            "the quiet-shop re-read never pushed — the panel is left on a stale "
            "frame until the next state change")

    def test_the_reread_cannot_record(self):
        """The source half of the same claim, because the count above passes on
        any extra push: the re-read call site has to SAY `record=False`."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "live.py"), encoding="utf-8").read()
        self.assertIn("elif time.monotonic() - last_push >= SHOP_REREAD_SECONDS:",
                      src)
        tail = src.split("elif time.monotonic() - last_push >= "
                         "SHOP_REREAD_SECONDS:")[1][:500]
        self.assertIn("record=False", tail,
                      "the periodic re-read is recording every silent tick")

    def test_the_monitor_survives_a_log_it_cannot_open(self):
        """A missing log is a startup error, not a swallowed tick.

        `main()` checks the path, but monitor() is also called directly by tests
        and by hand, and its `finally` closes the file — so an unopenable file
        must fail loudly rather than leave the loop half-built.
        """
        with self.assertRaises(OSError):
            with contextlib.redirect_stdout(self.out):
                live.monitor(os.path.join(self.tmp.name, "nope", "Power.log"), 0.01)


#: The second game's opening, deliberately distinct from `_fixture`'s: if any of
#: these lines reach a coach, the tail re-read the file from byte 0.
_REUSED_MARKER = "D 0:00:09.0 GameState.DebugPrintGame() - PlayerID=7,"


class TestALogReusedAtTheSamePath(_MonitorHarness):
    """A log that stops being the file we opened, WITHOUT changing path.

    Windows writes `Logs/Hearthstone_<date>/Power.log`, a fresh directory per
    launch, so rotation hands the monitor a new PATH — and the session switch
    covers it (see `test_a_restart_saves_and_shares_the_finished_game_once`).
    macOS is documented to write ONE flat `Logs/Power.log`, which the game
    erases on every start: the path never changes, so the switch can never see
    it.

    Measured on the first macOS install (2026-10-15) before this was fixed:
    the monitor seeked past the new end of the file, read nothing, and — once
    the new game had grown past the old byte offset — resumed MID-LINE. The
    new game's opening, `CREATE_GAME` and the hero pick included, was never
    read at all, and the panel stayed on the previous game.

    Both ways a log comes back at the same path are pinned here, because they
    fail differently: truncation leaves the same inode (a size test catches
    it) and a re-created file is longer than what we already read (only an
    identity test catches it).
    """

    def _reuse(self, log, how, ticks=5):
        """Run monitor() over `log`, then hand it back as `how` says."""
        real = live.LiveCoach
        made = []

        def factory():
            coach = real()
            made.append(coach)
            return coach

        seen = {"n": 0}

        def fake_sleep(_seconds):
            seen["n"] += 1
            if seen["n"] == 1:
                # The first game, read normally, so there is real state to lose.
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"{GS}Entity={_LOCAL} tag=RESOURCES value=4\n")
            elif seen["n"] == 2:
                how(log)
            elif seen["n"] == 3:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"{GS}Entity={_LOCAL} tag=RESOURCES value=2\n")
            if seen["n"] > ticks:
                raise KeyboardInterrupt

        with mock.patch.object(live, "LiveCoach", factory), \
                mock.patch.object(live, "find_active_log", lambda: log), \
                mock.patch.object(live.time, "sleep", fake_sleep), \
                contextlib.redirect_stdout(self.out):
            live.monitor(log, 0.01)
        return made

    def _flat_log(self, ended=False):
        """One game at a flat path, with no session directory around it."""
        os.makedirs(os.path.join(self.tmp.name, "Logs"), exist_ok=True)
        log = os.path.join(self.tmp.name, "Logs", "Power.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(_fixture(ended=ended)) + "\n")
        # The share path only has something to send for a game whose advisories
        # are already recorded — the same fixture `_session` sets up, for the
        # same reason.
        decision_log.record({"top_move": "1. Buy a thing", "gold": 3,
                             "tier": 1, "board": [], "hand": [],
                             "shop_rank": []},
                            log_path=log, log_offset=42, game_no=1)
        return log

    def _assert_reused_from_the_start(self, made, text):
        self.assertNothingSwallowed()
        self.assertGreaterEqual(
            len(made), 2,
            "the monitor never re-attached: the reused log was tailed from a "
            f"stale offset and its opening was lost\n{text[-1500:]}")
        fresh = made[-1]
        self.assertTrue(
            any(_REUSED_MARKER in line for line in fresh.cur_lines),
            "the re-attached coach never saw the new game's opening lines")

    def _truncate(self, log):
        """The game erases the log and starts again: SAME inode, shorter."""
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(_fixture(ended=False)) + "\n")
            f.write(_REUSED_MARKER + "\n")

    def _replace(self, log):
        """The game deletes the log and makes a new one: a NEW inode.

        Deliberately LONGER than what the monitor has already consumed, because
        that is the case the size test cannot see — without the identity test
        this one would tail on into the new file at a stale offset.
        """
        os.remove(log)
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(_fixture(ended=False)) + "\n")
            f.write(_REUSED_MARKER + "\n")
            for i in range(200):
                f.write(f"{GS}Entity={_LOCAL} tag=RESOURCES value={i % 9}\n")

    def test_a_truncated_log_is_re_read_from_the_start(self):
        log = self._flat_log()
        made = self._reuse(log, self._truncate)
        self._assert_reused_from_the_start(made, self._text())
        self.assertIn("restarted in place", self._text(),
                      "the monitor re-read the log without saying why")

    def test_a_replaced_log_is_re_read_from_the_start(self):
        log = self._flat_log()
        made = self._reuse(log, self._replace)
        self._assert_reused_from_the_start(made, self._text())
        self.assertIn("replaced at the same path", self._text(),
                      "the monitor re-read the log without saying why")

    def test_the_old_game_is_shared_before_the_reuse(self):
        """The other moment a game is certainly over, so the share path runs
        here exactly as it does on a session switch."""
        log = self._flat_log(ended=True)
        self._reuse(log, self._truncate)
        self.assertEqual(len(self.posted), 1,
                         "the finished game was not shared before re-attaching")


class TestTheLogSizeCapIsNotSilent(_MonitorHarness):
    """Hearthstone closes a log at `Log.FileSizeLimit.Int` KB (default 10000).

    The coach cannot stop the client doing that. What it must not do is sit on a
    stale frame and say nothing — which is exactly what happened on the first
    macOS install (2026-10-15): the page held a turn-7 shop for 24 minutes, the
    console printed no warning, and the game's ending, its review and its saved
    replay were all lost without the player being told anything was wrong.
    """

    BANNER = "Truncating log, which has reached the size limit of 10000KB"

    def setUp(self):
        super().setUp()
        coach_ui.clear_log_cap_notice()
        self.addCleanup(coach_ui.clear_log_cap_notice)
        self._patch(live, "_LOG_CAP_ANNOUNCED", False)

    def test_the_banner_replaces_the_stale_frame_instead_of_hiding(self):
        log = self._session(_SESSION_DIR)
        self._patch(live, "find_active_log", lambda: log)
        # The notice waits for the SILENCE, not for the message: give the clock
        # enough room to prove the writing stopped.
        self._patch(live.time, "monotonic", _advancing_clock())

        self._drive(log, growth=([self.BANNER],))

        self.assertNothingSwallowed()
        text = self._text()
        self.assertIn("capped", text.lower(),
                      "the console never said the client had capped the log")
        self.assertIn("10000KB", text,
                      "the console did not name the limit the client reported")
        notice = coach_ui.log_cap_notice()
        self.assertTrue(notice, "the page was left with no explanation")
        self.assertIn("10000KB", notice)
        self.assertIsNone(coach_ui.latest_analysis(),
                          "the stale frame was left on the page")

    def test_a_windows_resume_after_the_banner_is_not_a_warning(self):
        """The same banner appears where the cap is survivable.

        On Windows the client truncates the log and carries on, so a banner is
        NOT evidence that anything was lost. Warning on it would cry wolf on the
        one platform the maintainer has never seen this problem on — so the
        notice keys on the writing having stopped, which this fixture shows
        continuing.
        """
        log = self._session(_SESSION_DIR)
        self._patch(live, "find_active_log", lambda: log)
        self._patch(live.time, "monotonic", _advancing_clock())

        # The banner, then more of the same game: exactly the Windows shape.
        self._drive(log, growth=([self.BANNER], GROWTH[2]))

        self.assertNothingSwallowed()
        self.assertIsNone(coach_ui.log_cap_notice(),
                          "a survivable cap was reported as a lost game")
        self.assertNotIn("capped", self._text().lower())

    def test_the_card_the_player_sees_carries_it(self):
        """The console scrolls; the card is what is still on screen."""
        import json
        coach_ui.set_log_cap_notice("10000")
        payload = json.loads(coach_ui.welcome_payload())
        self.assertEqual(payload.get("title"), "The log stopped")
        self.assertIn("10000KB", payload.get("status", ""))
        self.assertIn("client.config", payload.get("status", ""),
                      "the card must carry the fix, not just the symptom")

    def test_it_is_said_once_per_session(self):
        """A capped log stays capped: repeating it every tick would bury the
        advice it exists to give."""
        with contextlib.redirect_stdout(self.out):
            live._note_log_capped(self.BANNER, "/tmp/Power.log")
        first = self._text()
        with contextlib.redirect_stdout(self.out):
            live._note_log_capped(self.BANNER, "/tmp/Power.log")
        self.assertEqual(first, self._text())
        self.assertEqual(first.count("capped"), 1)

    def test_a_new_session_takes_the_notice_down(self):
        """A restarted client writes a NEW log; that one is not capped."""
        coach_ui.set_log_cap_notice("10000")
        self._patch(live, "_LOG_CAP_ANNOUNCED", False)
        log = self._session(_SESSION_DIR)
        other = self._session(_NEXT_SESSION_DIR)
        self._patch(live, "find_active_log", lambda: other)
        self._drive(log, growth=())
        self.assertIsNone(coach_ui.log_cap_notice(),
                          "the cap warning survived into an uncapped session")


if __name__ == "__main__":
    unittest.main()
