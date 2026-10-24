"""The dev live-replay tool: what it pushes, and what it must never do.

`live_replay.py` is a maintainer tool that drives the REAL Another Round page
from a finished game, so two things about it have to be true and neither is
visible from its source:

  * **a frame it pushes IS a live frame.** Every step goes through the live push
    functions, so the test that matters is an EQUALITY: the payload served for
    phase N must be byte-identical (bar the wall-clock stamp) to what
    `replay_review._advise_point` — the review's own reader of the same moment —
    computes. `test_the_frame_equals_the_review` is that, and it is why a fresh
    coach per step is not an implementation detail: the first version kept one
    coach and resumed it, and the measured result was phase 8 differing from the
    review in 15 keys with `board`/`gold`/`board_stats` among them. Slow and
    right beat fast and wrong.
  * **it writes nothing.** No decision-log record, no share, no saved replay
    written by the tool itself, no `replay_store.backfill()` (which deletes
    files). Those are asserted as ABSENCES with the collaborators patched to
    raise, because "it did not raise" is not the same claim.

The fixtures are synthetic (`tests.test_shop_parsing.opt_block`, the shape
`test_monitor_smoke` already drives), so the suite is green on a machine with no
Hearthstone install. The real-data tests SKIP with a reason when no settled log
exists — a moving target is not a test (`tests/real_logs.py`).
"""
import copy
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)                                # the code sits in app/
sys.path.insert(0, os.path.join(HERE, "tests"))

import browser            # noqa: E402
import coach_ui           # noqa: E402
import decision_log       # noqa: E402
import live_coach         # noqa: E402  (the circular-import primer, see below)
import live               # noqa: E402
import live_replay        # noqa: E402
import replay_review      # noqa: E402
import replay_store       # noqa: E402
import settle_up          # noqa: E402
from extract_game import split_game_chunks              # noqa: E402
from tests.test_shop_parsing import opt_block           # noqa: E402

#: `live_coach` is imported above, before `coach_ui`, on purpose: coach_ui →
#: settle_up → outcome_audit → live_coach → `from coach_ui import
#: latest_manual_in_play` is a cycle, so live_coach has to be in sys.modules first.
#: Importing live_replay alone happens to do the same priming; keeping it here
#: means this module cannot be broken by a reordering inside live_replay.

GS = "D 0:00:01.0 GameState.DebugPrintPower() - "
GAME = "D 0:00:01.0 GameState.DebugPrintGame() - "

#: A line no parser looks at: it carries no "GameState." (so `_phases` and
#: `feed_to_settle` ignore it) and no STEP marker. It still advances the line
#: index, which is what `feed_to_settle`'s 20-line settle counts — so this is
#: how a fixture reproduces "the shop has stopped changing".
FILLER = "D 0:00:01.0 nothing the parsers look at"
SETTLE_FILLER = 25                   # > feed_to_settle's own 20

#: Assembled rather than written as one literal, like test_monitor_smoke.py:
#: this file SHIPS (app/tests/ is in the release zip), and the privacy gate reads
#: a handle-shaped literal as a real player. Both are documented placeholders.
_LOCAL = "Tester" + "#" + "1234"
_OPP = "Player" + "#" + "1234"


def _named_tag(eid, cid, player, tag, value):
    return (f"{GS}TAG_CHANGE Entity=[entityName=H id={eid} zone=PLAY "
            f"cardId={cid} player={player}] tag={tag} value={value}")


def game_lines(phases=3, ended=True, shop_on=None):
    """A synthetic game with `phases` settled buy phases.

    The opening block is test_monitor_smoke's fixture: local player 7 against
    opponent 15, hero entities and a placement tag for the local hero, which is
    what `final_placement()` reads on the way to the end-of-game card.

    `shop_on` names the phases (1-based) whose options block is a real tavern
    shop. A phase left out still OPENS and CLOSES — it simply has no offer set
    to settle on, which is a real shape (the measured 2026-10-12 game phase 2)
    and the one that used to make the driver report the game was over.
    """
    shop_on = set(phases and {1} if shop_on is None else shop_on)
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
        _named_tag(119, "BG33_HERO_001", 7, "PLAYER_LEADERBOARD_PLACE", 1),
    ]
    for i in range(1, phases + 1):
        lines.append(f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION")
        if i in shop_on:
            lines += opt_block(i, [("River Skipper", "BG33_140", 15),
                                   ("Tusked Camper", "BG33_886", 15)])
        lines += [FILLER] * SETTLE_FILLER
        lines.append(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
    if ended:
        lines.append(f"{GS}TAG_CHANGE Entity={_LOCAL} tag=PLAYSTATE value=LOST")
    return lines


def _driver(lines, game=1, **kw):
    """A LiveReplay over `lines`, with no log file anywhere."""
    bounds = list(split_game_chunks(lines))
    with mock.patch.object(live_replay, "read_log",
                           lambda _path: (bounds, lines)):
        return live_replay.LiveReplay("fixture.log", game, **kw)


def _served():
    with coach_ui._state.lock:
        return json.loads(coach_ui._state.payload)


def _clockless(obj):
    """The payload without its wall-clock stamp, through a JSON round trip.

    `render_json` sets `generated = time.time()` on every push, so two renders
    of the SAME analysis differ in exactly that key and nothing else — which is
    what the real-log measurement showed (phase 1: "identical but for
    `generated`"), and why the equality below is not weakened by dropping it.

    The round trip is NOT cosmetic (2026-10-23): the LIVE side of the comparison
    is a payload read back from JSON, so its tuples are lists, while
    `render_json(ref)` is a Python dict that can still hold tuples (a `ranked`
    option row is one). That mismatch is invisible on any frame whose choice is
    empty — which is why it went unnoticed until a real game's last phase ended
    on a pick — and it says nothing about the two analyses agreeing. Both sides
    go through the same encoder so the comparison is about the DATA.
    """
    obj = copy.deepcopy(obj)
    obj.pop("generated", None)
    return json.loads(json.dumps(obj))


class _PayloadCase(unittest.TestCase):
    def setUp(self):
        # The overlay state is process-global, like every other test that
        # touches it: start each case from the welcome card it serves on boot.
        coach_ui.clear_analysis()

    def tearDown(self):
        coach_ui.clear_analysis()


# ---------------------------------------------------------------- the frames

class TestAFrameIsALiveFrame(_PayloadCase):
    """The one property the whole tool rests on."""

    def test_the_frame_equals_the_review(self):
        """Phase N served == phase N as `_advise_point` reads it.

        Two different readers of the same moment, and they must not disagree:
        the review is what a player reads afterwards, and the page is what the
        game would have shown. A drift here is a dev tool that lies about the
        product, which is worse than no dev tool.
        """
        lines = game_lines(phases=3)
        d = _driver(lines)
        self.assertEqual(d.phase_count, 3)
        for n in (1, 2, 3):
            with self.subTest(phase=n):
                d.goto_phase(n)
                lo, hi = d.phases[n - 1]
                ref, _stop, _saw = replay_review._advise_point(d.chunk, lo, hi)
                self.assertIsNotNone(ref, "the fixture reaches a real analysis")
                self.assertEqual(_clockless(_served()),
                                 _clockless(coach_ui.render_json(ref)))

    def test_the_frame_carries_the_game_state(self):
        """A pushed frame is a populated one, not a welcome card with a box."""
        d = _driver(game_lines(phases=2))
        d.goto_phase(1)
        served = _served()
        self.assertFalse(served.get("welcome"))
        # The hero's NAME, not its card id: resolved through the same DB the
        # live page uses. Asserted as "not the id" rather than against a
        # literal, so a patch that renames the card cannot break this test —
        # the claim is that resolution happened, not which name it is.
        self.assertTrue(served.get("hero"))
        self.assertNotEqual(served.get("hero"), "BG33_HERO_001")
        self.assertEqual(len(served.get("shop_rank") or []), 2,
                         "both tavern offers are on the page")

    def test_no_verdict_key_reaches_the_replay(self):
        """The pivot's wall, on a REPLAYED frame rather than a live one.

        `LIVE_VERDICT_KEYS` is the single list that keeps the plan off the
        page, and this tool pushes through the same producer — so the claim is
        worth asserting here too, because "the dev tool is a way to see the
        plan early" is exactly the worry a reviewer would have.
        """
        d = _driver(game_lines(phases=2))
        d.goto_phase(2)
        self.assertEqual(sorted(k for k in _served()
                                if k in coach_ui.LIVE_VERDICT_KEYS), [])

    def test_the_welcome_step_serves_the_welcome_card(self):
        d = _driver(game_lines(phases=2))
        d.goto_phase(1)
        d.welcome()
        self.assertTrue(_served().get("welcome"))
        self.assertEqual(d.mode, "welcome")
        self.assertEqual(d.phase_of(), 0)


# ---------------------------------------------------------------- the cursor

class TestTheFrameCursor(_PayloadCase):
    """Which phase is on screen — the bug the first smoke run found.

    `feed_to_settle` returns `len(chunk)` as its sentinel when a phase never
    settles, so a cursor taken straight from it points at the end of the game:
    stepping to a shopless phase 2 and pressing `n` reported "phase 16 is the
    last one". The phase number is therefore STORED, and the lines fed are
    bounded by the phase's own end.
    """

    def test_a_phase_with_no_settled_shop_does_not_end_the_game(self):
        lines = game_lines(phases=3, shop_on={1, 3})
        d = _driver(lines)
        two = d.goto_phase(2)
        self.assertFalse(two["saw_offers"], "phase 2 has no shop to settle on")
        self.assertEqual(d.phase_of(), 2, "the frame is phase 2, not the last")
        self.assertLess(two["fed"], len(d.chunk),
                        "the lines fed stop at the phase's own end")
        self.assertEqual(live_replay.step(d, "n")[0][:12], "phase 3/3 (r")

    def test_stepping_forward_and_back_lands_on_the_same_frame(self):
        d = _driver(game_lines(phases=3))
        d.goto_phase(3)
        third = _clockless(_served())
        d.goto_phase(1)
        first = _clockless(_served())
        self.assertNotEqual(third, first)
        d.goto_phase(3)
        self.assertEqual(_clockless(_served()), third,
                         "a revisit re-reads the same game state, not a "
                         "resumed one")

    def test_the_last_phase_is_where_forward_stops(self):
        d = _driver(game_lines(phases=2))
        d.goto_phase(2)
        msg, done = live_replay.step(d, "n")
        self.assertFalse(done)
        self.assertIn("last one this game has", msg)
        self.assertEqual(d.phase_of(), 2, "and it is still on screen")

    def test_back_at_the_first_phase_says_so(self):
        d = _driver(game_lines(phases=2))
        d.goto_phase(1)
        msg, _done = live_replay.step(d, "p")
        self.assertIn("first buy phase", msg)

    def test_a_phase_that_does_not_exist_is_refused(self):
        d = _driver(game_lines(phases=2))
        for bad in (0, 3, 99):
            with self.subTest(phase=bad):
                with self.assertRaises(live_replay.SpecError):
                    d.goto_phase(bad)
        self.assertIn("does not exist", live_replay.step(d, "g", 99)[0])
        self.assertIn("needs a phase number",
                      live_replay.step(d, "g", "banana")[0])


# --------------------------------------------------------------- the absence

class TestItWritesNothing(_PayloadCase):
    """Every collaborator that could write is patched to RAISE.

    A replayed game is not a played game: its advisories would land in the
    decision log under the same (log, offset, game) keys the corpus joins on,
    and a tool that saved replays by itself would be making a player's decision
    for them. `live_replay` reaching any of these is a failure, not a warning.
    """

    def _guarded(self):
        boom = AssertionError("live_replay wrote something it must not")
        return [
            mock.patch.object(decision_log, "record", side_effect=boom),
            mock.patch.object(settle_up, "build", side_effect=boom),
            mock.patch.object(replay_store, "save", side_effect=boom),
            mock.patch.object(replay_store, "backfill", side_effect=boom),
            mock.patch.object(coach_ui, "auto_save_current_review",
                              side_effect=boom),
        ]

    def test_a_full_step_through_writes_nothing(self):
        import share
        patchers = self._guarded()
        patchers.append(mock.patch.object(share, "share_session",
                                          side_effect=AssertionError("shared")))
        patchers.append(mock.patch.object(live, "_share_finished",
                                          side_effect=AssertionError("shared")))
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        d = _driver(game_lines(phases=3))
        for key in ("n", "n", "n", "p", "k", "w", "r", "s", "n"):
            live_replay.step(d, key)
        d.to_end(build_review=False)
        self.assertIsNotNone(coach_ui.latest_analysis() or d.mode == "end")

    def test_the_review_build_never_auto_saves(self):
        """`build_review` is `live._settle_up_in_background` minus one line.

        The line it drops is `coach_ui.auto_save_current_review()`, which writes
        a saved replay with no click: reusing that function would mean a dev
        pressing `e` silently kept a game.
        """
        d = _driver(game_lines(phases=1))
        with mock.patch.object(coach_ui, "auto_save_current_review",
                               side_effect=AssertionError("auto-saved")):
            with mock.patch.object(settle_up, "build",
                                   return_value={"hero": "Reno Jackson",
                                                 "placement": 1, "phases": []}):
                with mock.patch.object(settle_up, "render_html",
                                       return_value="<html></html>"):
                    out = d.build_review()
        self.assertEqual(out["hero"], "Reno Jackson")

    def test_the_whole_tool_runs_without_touching_the_store(self):
        """`main()` end to end on a real fixture log, with the writers armed.

        `backfill()` DELETES duplicate stored games and `live.py` runs it at
        every startup on purpose; a dev harness that pruned the store would be
        a data-loss bug wearing a dev-tool hat. Patching it to raise while the
        REAL startup path runs is a stronger claim than reading the source for
        a name — and it also covers `--list`, `resolve`, the banner and the
        command loop, which nothing else here drives as a whole.
        """
        import contextlib
        import io
        import tempfile
        boom = AssertionError("main() wrote something it must not")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Power.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(game_lines(phases=2)))
            buf = io.StringIO()
            with mock.patch.object(replay_store, "backfill", side_effect=boom), \
                    mock.patch.object(replay_store, "save", side_effect=boom), \
                    mock.patch.object(decision_log, "record", side_effect=boom), \
                    mock.patch.object(coach_ui, "auto_save_current_review",
                                      side_effect=boom), \
                    mock.patch.object(live_replay, "_read_key",
                                      side_effect=["n", "q"]):
                with contextlib.redirect_stdout(buf):
                    rc = live_replay.main(["--log", path, "--no-ui",
                                           "--quiet"])
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("REPLAY (dev)", text)
        self.assertIn("not live", text)


# --------------------------------------------------------- the end of a game

class TestTheEndOfTheGame(_PayloadCase):
    def test_a_finished_game_serves_the_card_the_live_path_serves(self):
        d = _driver(game_lines(phases=2, ended=True))
        info, refusal = d.to_end(build_review=False)
        self.assertIsNone(refusal, refusal)
        self.assertEqual(info["placement"], 1)
        served = _served()
        self.assertTrue(served.get("welcome"), "the card is a welcome payload")
        self.assertEqual(served["title"], "Game over")
        self.assertEqual(served["game_over"]["placement"], 1)
        self.assertIn("save", json.dumps(served).lower(),
                      "the card's own Save replay control is on it")

    def test_an_unfinished_game_gets_no_card_and_no_review(self):
        """The pivot, enforced at the one place a dev could break it.

        `--latest` against a log being written right now IS the game in
        progress, so `e` must refuse rather than build a review whose plan
        describes a game that is still actionable — and the refusal is a
        sentence, not a traceback.
        """
        d = _driver(game_lines(phases=2, ended=False))
        # `settle_up.build` raises rather than being merely observed: the claim
        # is that the build is not attempted at all. (The overlay's own review
        # slot is process-global and another case's build may still be in it, so
        # asserting on `review_meta` would be testing the wrong object.)
        with mock.patch.object(settle_up, "build",
                               side_effect=AssertionError("built a review for "
                                                          "a live game")):
            info, refusal = d.to_end(build_review=True)
        self.assertIsNone(info)
        self.assertIn("has not ended", refusal)
        self.assertIsNone(d.built_review)
        self.assertNotIn("game_over", _served())

    def test_the_console_says_the_save_button_needs_a_review(self):
        """`--no-review` leaves the card's Save button answering 409, and the
        console has to say so: a dev who clicks it and sees a red error will
        otherwise read it as a broken card."""
        import contextlib
        import io
        d = _driver(game_lines(phases=1))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            live_replay.step(d, "e", opts={"no_review": True})
        self.assertIn("409", buf.getvalue())
        self.assertTrue(_served().get("welcome"), "the card itself is served")


# --------------------------------------------------------------- the command

class TestTheCommandSurface(_PayloadCase):
    def test_a_command_splits_from_its_argument(self):
        """`g 7` is one command and one value.

        The single-key reader hands back one character and the piped reader a
        whole line, so the split has to happen here: the first version turned
        `g 7` into the unknown command "g 7".
        """
        self.assertEqual(live_replay._split_command("g 7"), ("g", "7"))
        self.assertEqual(live_replay._split_command("n"), ("n", None))
        self.assertEqual(live_replay._split_command("  m  12:34:56 "),
                         ("m", "12:34:56"))
        self.assertEqual(live_replay._split_command(""), ("\n", None))

    def test_an_unknown_command_says_so_and_keeps_going(self):
        d = _driver(game_lines(phases=1))
        msg, done = live_replay.step(d, "Z")
        self.assertFalse(done)
        self.assertIn("unknown command", msg)

    def test_status_names_the_frame_and_the_log(self):
        d = _driver(game_lines(phases=2))
        d.goto_phase(2)
        msg, _done = live_replay.step(d, "s")
        self.assertIn("game 1/1", msg)
        self.assertIn("phase", msg)

    def test_quit_is_the_only_thing_that_stops_the_loop(self):
        d = _driver(game_lines(phases=1))
        self.assertTrue(live_replay.step(d, "q")[1])
        self.assertFalse(live_replay.step(d, "h")[1])


class TestThePointerAndTheCommandLine(_PayloadCase):
    """`resolve()` — every refusal is a sentence the caller can act on."""

    def _args(self, **kw):
        base = {"rid": None, "log": None, "latest": False, "game": None}
        base.update(kw)
        return type("A", (), base)()

    def test_no_source_says_what_to_pass(self):
        with self.assertRaises(live_replay.SpecError) as caught:
            live_replay.resolve(self._args())
        for wanted in ("--rid", "--latest", "--log"):
            self.assertIn(wanted, str(caught.exception))

    def test_rid_refuses_a_game_it_does_not_own(self):
        with self.assertRaises(live_replay.SpecError) as caught:
            live_replay.resolve(self._args(rid="x", game=2))
        self.assertIn("names its own game", str(caught.exception))

    def test_a_missing_log_says_which_path(self):
        with self.assertRaises(live_replay.SpecError) as caught:
            live_replay.resolve(self._args(log="C:/nope/Power.log"))
        self.assertIn("no such log", str(caught.exception))

    def test_an_unknown_replay_id_says_where_the_ids_are(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(replay_store, "store_dir",
                                   lambda root=None: tmp):
                with self.assertRaises(live_replay.SpecError) as caught:
                    live_replay.resolve(self._args(rid="nope"))
        self.assertIn("no saved replay", str(caught.exception))
        self.assertIn("--list", str(caught.exception))

    def test_a_saved_replay_resolves_through_its_own_pointer(self):
        """The id, the pointer and the game number all come from the store."""
        seen = {}

        def fake_path(session, log):
            seen["pointer"] = (session, log)
            return "C:/logs/Power.log"

        args = self._args(rid="2026-01-01_000000-Chenvaala-1st")
        stored = {"rep": {"session": "Hearthstone_2026_01_01",
                          "log": "Power.log", "game": 4, "hero": "Chenvaala"}}
        with mock.patch.object(replay_store, "load", return_value=stored):
            with mock.patch.object(settle_up, "log_path_for",
                                   side_effect=fake_path):
                path, game, label = live_replay.resolve(args)
        self.assertEqual(seen["pointer"],
                         ("Hearthstone_2026_01_01", "Power.log"))
        self.assertEqual((path, game), ("C:/logs/Power.log", 4))
        self.assertIn("Chenvaala", label)

    def test_a_rotated_log_refuses_in_the_stores_own_words(self):
        args = self._args(rid="old")
        stored = {"rep": {"session": "Hearthstone_2026_01_01",
                          "log": "Power.log", "game": 1}}
        with mock.patch.object(replay_store, "load", return_value=stored):
            with mock.patch.object(settle_up, "log_path_for",
                                   return_value=None):
                with self.assertRaises(live_replay.SpecError) as caught:
                    live_replay.resolve(args)
        self.assertIn("rotates", str(caught.exception))

    def test_the_filename_is_accepted_with_a_note(self):
        """A dev copies the name Explorer shows: `--rid <id>.json`."""
        args = self._args(rid="2026-01-01_000000-Chenvaala-1st.json")
        stored = {"rep": {"session": "Hearthstone_2026_01_01",
                          "log": "Power.log", "game": 2}}
        seen = {}
        with mock.patch.object(replay_store, "load",
                               side_effect=lambda rid: seen.setdefault(
                                   "rid", rid) and None or stored):
            with mock.patch.object(settle_up, "log_path_for",
                                   return_value="C:/logs/Power.log"):
                _path, game, _label = live_replay.resolve(args)
        self.assertEqual(seen["rid"], "2026-01-01_000000-Chenvaala-1st")
        self.assertEqual(game, 2)

    def test_a_log_with_no_game_is_refused_before_anything_starts(self):
        bounds = []
        with mock.patch.object(live_replay, "read_log",
                               lambda _p: (bounds, [])):
            with self.assertRaises(live_replay.SpecError) as caught:
                live_replay.LiveReplay("empty.log", 1)
        self.assertIn("no game at all", str(caught.exception))

    def test_a_game_number_past_the_end_is_refused(self):
        lines = game_lines(phases=1)
        with self.assertRaises(live_replay.SpecError) as caught:
            _driver(lines, game=2)
        self.assertIn("does not exist", str(caught.exception))

    def test_the_game_defaults_to_the_last_one(self):
        """`--latest` with no --game means the last game in the log."""
        d = _driver(game_lines(phases=2) + game_lines(phases=1), game=None)
        self.assertEqual((d.game, d._games), (2, 2))
        self.assertEqual(d.phase_count, 1, "and it sliced the SECOND game")


# ------------------------------------------------------------------ the band

class TestTheBand(unittest.TestCase):
    def test_the_band_lands_after_the_nav_and_before_the_panes(self):
        """Placement is the claim: outside everything `render()` clears.

        `render()` clears the card slot (`#col-decide`) and the live view's own
        container on every frame, and `showTab` toggles `#app` — so a band
        inside any of those would vanish on the first step or tab switch, which
        is exactly when it is needed. (The classic REFERENCE pane `#col-ref` was
        the third container when this test was written; it went with the classic
        renderer on 2026-10-13, and the anchor it asserted is unchanged.)
        """
        html = live_replay.install_band(coach_ui._HTML)
        band_at = html.index('id="replay-band"')
        self.assertLess(html.index("</nav>"), band_at)
        self.assertLess(band_at, html.index('<div id="app">'))
        self.assertLess(band_at, html.index('<section id="settle">'))
        self.assertNotIn('id="replay-band"', coach_ui._HTML,
                         "the shipped page is untouched until a dev run")

    def test_the_band_says_it_is_a_replay(self):
        html = live_replay.install_band(coach_ui._HTML)
        self.assertIn("REPLAY", html)
        self.assertIn("not live advice", html)

    def test_the_band_warns_about_the_controls_that_write(self):
        """On a replayed welcome card the sharing question is the REAL one.

        Clicking it writes the consent answer that governs this install's future
        games, so the band has to say that the writing controls are real rather
        than leaving a dev to discover it from the log.
        """
        html = live_replay.install_band(coach_ui._HTML)
        for control in ("sharing", "Save replay", "auto-save"):
            self.assertIn(control, html)

    def test_a_page_without_the_anchor_is_refused_not_silently_banded(self):
        """Fail loudly: a silent miss is a replay that looks like live advice."""
        for broken in (coach_ui._HTML.replace("</nav>", ""),
                       coach_ui._HTML.replace("</nav>", "</nav></nav>"),
                       coach_ui._HTML.replace("</head>", "")):
            with self.subTest(broken=broken[:40]):
                with self.assertRaises(live_replay.SpecError):
                    live_replay.install_band(broken)

    def test_the_freshness_strip_is_only_hidden_when_asked(self):
        kept = live_replay.install_band(coach_ui._HTML)
        hidden = live_replay.install_band(coach_ui._HTML, hide_freshness=True)
        self.assertNotIn("#freshness{display:none", kept)
        self.assertIn("#freshness{display:none", hidden)

    def test_the_band_is_one_static_string(self):
        """Never formatted from a path, an id or a handle.

        `coach_ui._page_html()` rewrites `_HTML` per request and hands it to the
        browser, so anything interpolated into the band would be interpolated
        into served HTML. The band is a constant; this pins that it stays one.
        """
        self.assertEqual(live_replay.BAND, live_replay.BAND)
        self.assertNotIn("{", live_replay.BAND)
        self.assertNotIn("%", live_replay.BAND)


class TestTheBandInABrowser(unittest.TestCase):
    """The band, laid out — the one claim a string assertion cannot make.

    A page that carries the markup can still put it nowhere visible, and the
    whole point of the band is that a dev SEES it. Chromium unavailable is a
    SKIP (`browser.py`: a browser that cannot start says nothing about the
    artifact).
    """

    _DRIVER = """
<pre id="out">pending</pre>
<script>
(function () {
  // COUNTS ARE MARKED `#` (2026-10-12): `browser.fields` returns an int only
  // for a value the page marked with a leading '#'; every other value comes
  // back as TEXT (that is the convention `test_settle_browser` and
  // `test_live_browser` both follow). This driver pushed bare `1`s, so
  // `assertEqual(got['bandpresent'], 1)` compared '1' to 1 and
  // `assertGreater(got['classicpane'], 0)` raised TypeError on a str. Both
  // assertions therefore FAILED rather than passing — which nobody saw, because
  // that session's sandbox could not start Chromium, so these two tests
  // SKIPPED (a browser that cannot start is a skip, `browser.py`). The repair
  // is the marker, not weaker assertions.
  const rec = [];
  const num = v => '#' + String(v);
  const band = document.getElementById('replay-band');
  rec.push('bandpresent=' + num(band ? 1 : 0));
  rec.push('bandvisible=' + num(band && band.offsetHeight > 0 ? 1 : 0));
  rec.push('bandtop=' + num(band ? Math.round(band.getBoundingClientRect().top) : -1));
  rec.push('navtop=' + num(Math.round(
    document.getElementById('tabs').getBoundingClientRect().top)));
  // REVERSED 2026-10-13: this read `col-decide`'s child count as "the classic
  // panes still draw under the band". There are no classic panes — what has to
  // be on screen is the tavern view (the field below), and the card slot has to
  // be EMPTY, because a live frame is not a card.
  rec.push('cardslotkids=' + num(document.getElementById('col-decide').children.length));
  rec.push('tavern=' + num(document.querySelector('.tavern.live') ? 1 : 0));
  rec.push('share=' + num(document.getElementById('share-toggle') ? 1 : 0));
  document.getElementById('out').textContent = rec.join(' ;; ');
})();
</script>
"""

    def _fields(self, payload, hide=False):
        saved = coach_ui._HTML
        coach_ui._HTML = live_replay.install_band(saved, hide_freshness=hide)
        try:
            page = coach_ui._page_html()
        finally:
            coach_ui._HTML = saved
        setup = "<script>render(%s);</script>" % json.dumps(payload)
        return browser.fields(page.replace("</body>",
                                           setup + self._DRIVER + "</body>"))

    def _payload(self):
        analysis = _driver(game_lines(phases=1))
        analysis.goto_phase(1)
        return _served()

    def test_the_band_is_on_screen_above_the_page(self):
        try:
            got = self._fields(self._payload())
        except browser.BrowserUnavailable as exc:
            self.skipTest(str(exc))
        self.assertEqual(got["bandpresent"], 1)
        self.assertEqual(got["bandvisible"], 1, "the band must be laid out")
        self.assertGreater(got["bandtop"], -1)

    def test_the_page_still_renders_under_it(self):
        """The band must not cost the page anything: this is a dev aid on the
        real overlay, not a replacement page.

        REVERSED 2026-10-13 from `assertGreater(got['classicpane'], 0)` ("the
        classic panes still draw under the band"). The classic panes do not
        exist; what the apparatus is for is unchanged — the LIVE view is what a
        dev must see under the band — so the tavern root is asserted present and
        the card slot is asserted EMPTY, which is the other half of "a live frame
        is not a welcome card".
        """
        try:
            got = self._fields(self._payload())
        except browser.BrowserUnavailable as exc:
            self.skipTest(str(exc))
        self.assertEqual(got["tavern"], 1,
                         "the live view does not draw under the band")
        self.assertEqual(got["cardslotkids"], 0,
                         "a card is in the slot on a live frame")
        self.assertEqual(got["share"], 1, "the corner controls still draw")


# ------------------------------------------------------------- on a real log

class TestOnARealGame(unittest.TestCase):
    """Real format drift is the one thing a fixture cannot catch.

    Everything here SKIPS — with the reason `real_logs.why_none()` gives — when
    this machine has no finished session log, because a log being written right
    now is a moving target rather than a test.
    """

    @classmethod
    def setUpClass(cls):
        import real_logs
        cls.path = real_logs.newest_settled()
        cls.why = real_logs.why_none() if cls.path is None else None

    def _driver(self, game=None):
        if self.path is None:
            self.skipTest(self.why)
        return live_replay.LiveReplay(self.path, game, quiet=True)

    def test_a_real_frame_equals_the_review(self):
        """The same equality as the fixture, on a game this machine played."""
        d = self._driver(1)
        if not d.phases:
            self.skipTest("that log's first game has no buy phase")
        try:
            for n in {1, len(d.phases)}:
                with self.subTest(phase=n):
                    d.goto_phase(n)
                    lo, hi = d.phases[n - 1]
                    ref, _stop, _saw = replay_review._advise_point(d.chunk, lo,
                                                                   hi)
                    self.assertEqual(_clockless(_served()),
                                     _clockless(coach_ui.render_json(ref)))
        finally:
            coach_ui.clear_analysis()

    def test_the_round_is_read_from_the_game_not_the_phase_index(self):
        d = self._driver(1)
        if len(d.phases) < 2:
            self.skipTest("that log's first game has one buy phase")
        d.goto_phase(2)
        self.assertIsInstance(d.round, int,
                              "the console prints the game's own round count "
                              "beside the phase index, because a skipped turn "
                              "makes them disagree")

    def test_a_real_pick_panel_is_reachable(self):
        """`k` — the state the tool mostly exists for.

        The hero pick and the mid-game Choose-1 panels are the screens nothing
        else in the suite can reach without a game in progress.
        """
        d = self._driver(1)
        found = d.goto_pick()
        if found is None:
            self.skipTest("that game has no Choose-1 panel in the log")
        served = _served()
        self.assertTrue(served.get("choice") or served.get("board") is not None)
        self.assertEqual(d.mode, "pick")
        self.assertIn(found["at"], (d.pos,))

    def test_the_last_game_of_a_settled_log_ends_cleanly(self):
        """`e` on a real finished game: the card, or the honest refusal."""
        d = self._driver(None)
        try:
            info, refusal = d.to_end(build_review=False)
            if refusal:
                self.skipTest(f"that session's last game did not end in the "
                              f"log: {refusal}")
            served = _served()
            self.assertTrue(served.get("welcome"))
            self.assertEqual(served["game_over"]["placement"], info["placement"])
        finally:
            coach_ui.clear_analysis()


class TestTheLiveDispatchIsNotCopied(_PayloadCase):
    """The dev tool must branch where the monitor branches.

    `live_replay.goto_pick` mirrors live.py's tick — inside a shop the full
    analysis is the frame, outside one the minimal pick panel is — and that
    condition is the one thing here that is a COPY rather than a shared call.
    Extracting it would mean refactoring the shipped hot loop, so the guard is
    pinned in both files instead: the same technique `test_live_tavern` uses for
    the `render` branch that must consult the viewer.
    """

    GUARD = "if in_action and coach.tavern_offers():"

    def _src(self, module):
        with open(module.__file__, encoding="utf-8") as fh:
            return fh.read()

    def test_both_the_monitor_and_the_driver_carry_the_same_guard(self):
        self.assertIn(self.GUARD, self._src(live))
        self.assertIn(self.GUARD, self._src(live_replay))

    def test_the_driver_pushes_through_the_live_functions(self):
        """Not a lookalike: the same functions live.py calls.

        The two push functions are passed as OBJECTS to `_run` (so they can be
        silenced under `--quiet`), so the source carries their names without a
        call parens — asserting on `live._advise(` would have been asserting on
        a shape the file deliberately does not have.
        """
        src = self._src(live_replay)
        for call in ("live._advise", "live._advise_pick",
                     "coach_ui.show_game_over(", "coach_ui.update_analysis("):
            self.assertTrue(call in src,
                            f"{call} is not in live_replay.py — a frame pushed "
                            f"by anything else is a lookalike, not a live one")

    def test_the_driver_never_records(self):
        """`record=False` on every push. The keyword is the whole reason the
        seam exists, and a `record=True` default makes it easy to drop."""
        src = self._src(live_replay)
        self.assertIn("record=False", src)
        self.assertNotIn("record=True", src)


if __name__ == "__main__":
    unittest.main()
