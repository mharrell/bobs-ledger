"""The client root is RESOLVED, not assumed — and no message may contradict it.

The measured problem (2026-10-06): a game that is not under
`C:\\Program Files (x86)\\Hearthstone` produced three lines that cannot all be
true — "File logging is on", "no Hearthstone log folder at <the default>", and
"Hearthstone's file logging is probably OFF". The last one sent the player to
fix a setting the launcher had just switched on, and `log.config` is under
%LOCALAPPDATA%, so it was never the problem: `Logs/` lives inside the client
root, and that root was assumed rather than found.

Two kinds of case here, and both are load-bearing:

  * ORDER. A cheaper source must never quietly outrank a better one, the drive
    walk must stay last and rare, and the worst case must remain exactly what
    every version before this one did — a search that makes working installs
    worse would be its own bug.
  * THE MESSAGES. `live.no_log_advice()` and `coach_ui._welcome_hint()` are
    pure functions so a test can execute them, because the sentence that
    blamed logging is not coming back.

Fixtures are assembled at runtime, per this suite's convention: a path that
looks like a real install reads as one to the release's privacy gate.
"""
import contextlib
import glob
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import coach_ui      # noqa: E402
import config        # noqa: E402
import live          # noqa: E402

#: A session directory name, built from pieces like every other fixture here.
SESSION = "Hearthstone_" + "2026_01_01_00_00_00"

#: The platform default, spelled the way the module spells it. Nothing is ever
#: created here: this is the "nothing else answered" case.
WIN_DEFAULT = os.path.join("C:" + os.sep, "Program Files (x86)", "Hearthstone")

#: A folder that does not exist, for the sources that must report nothing.
#: `resolve_home` compares the drive walk against the default, so the default
#: always has to be a string.
MISSING = os.path.join(tempfile.gettempdir(), "bobs-ledger-no-such-client-root")


def _client_root(base, name="Hearthstone", logs=True):
    """A folder that passes for a client root: with Logs/, or only the game."""
    root = os.path.join(base, name)
    if logs:
        os.makedirs(os.path.join(root, "Logs", SESSION))
    else:
        os.makedirs(root)
        with open(os.path.join(root, "Hearthstone.exe"), "w") as f:
            f.write("")
    return root


def _resolve(registry=(), drives=(), remembered=None, default=MISSING,
             env=None):
    """`resolve_home` with every machine-dependent source under test control."""
    with mock.patch.object(config, "_registry_homes",
                           return_value=list(registry)), \
         mock.patch.object(config, "_drive_homes", return_value=list(drives)), \
         mock.patch.object(config, "remembered_home",
                           return_value=remembered), \
         mock.patch.object(config, "default_home", return_value=default):
        return config.resolve_home(env=({} if env is None else env),
                                   platform="win32")


class TestResolutionOrder(unittest.TestCase):
    """One test per step, and one per way a step could outrank its better."""

    def test_hearthstone_home_wins_without_consulting_anything_else(self):
        """An explicit answer is an answer. The env var is also how a player
        with an install the search cannot see fixes this, so it may not be
        second-guessed — not even by a registry entry that disagrees."""
        def boom(*_a, **_kw):
            raise AssertionError("HEARTHSTONE_HOME must short-circuit the "
                                 "search, not be compared with it")
        nowhere = os.path.join(tempfile.gettempdir(), "not-installed-anywhere")
        with mock.patch.object(config, "remembered_home", boom), \
             mock.patch.object(config, "_registry_homes", boom), \
             mock.patch.object(config, "_drive_homes", boom), \
             mock.patch.object(config, "default_home", boom):
            home, source = config.resolve_home(
                env={"HEARTHSTONE_HOME": nowhere}, platform="win32")
        self.assertEqual((home, source), (nowhere, "HEARTHSTONE_HOME"))

    def test_a_remembered_folder_beats_the_registry(self):
        """It is the player's own answer, given to this install, about this
        machine — the registry only knows what an installer once wrote."""
        with tempfile.TemporaryDirectory() as td:
            remembered = _client_root(td, "remembered")
            other = _client_root(td, "registry-says")
            home, source = _resolve(registry=[other], remembered=remembered)
            self.assertEqual(home, remembered)
            self.assertIn("told", source)

    def test_a_remembered_folder_that_has_gone_is_ignored_not_obeyed(self):
        """A drive that changed letter, or a game since uninstalled, must not
        pin a dead path for good: obeying it would put the coach back on "no
        log folder" with the fix already saved on disk."""
        with tempfile.TemporaryDirectory() as td:
            gone = os.path.join(td, "Hearthstone")     # never created
            real = _client_root(td, "registry-says")
            home, _source = _resolve(registry=[real], remembered=gone)
            self.assertEqual(home, real)

    def test_the_registry_beats_the_platform_default(self):
        """The uninstall key is rewritten when the game is installed or moved;
        a folder left behind after a move is only a folder."""
        with tempfile.TemporaryDirectory() as td:
            installed = _client_root(td, "on-another-drive")
            leftover = _client_root(td, "left-behind")
            home, source = _resolve(registry=[installed], default=leftover)
            self.assertEqual(home, installed)
            self.assertIn("uninstall", source)

    def test_a_registry_path_that_is_not_a_client_root_is_skipped(self):
        """InstallLocation can outlive the game: the folder is still there
        while the game inside it is not."""
        with tempfile.TemporaryDirectory() as td:
            empty = os.path.join(td, "not-the-game")
            os.makedirs(empty)
            real = _client_root(td, "real")
            home, _source = _resolve(registry=[empty, real])
            self.assertEqual(home, real)

    def test_the_platform_default_answers_when_the_registry_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            default = _client_root(td, "Hearthstone")
            home, source = _resolve(default=default)
            self.assertEqual(home, default)
            self.assertIn("usual place", source)

    def test_the_drive_walk_finds_a_game_the_registry_never_saw(self):
        """The belt for an install no uninstall key names: a folder copied
        rather than installed, or a key Windows lost in a reinstall."""
        with tempfile.TemporaryDirectory() as td:
            found = _client_root(td, "Hearthstone")
            home, source = _resolve(drives=[found])
            self.assertEqual(home, found)
            self.assertIn("scan", source)

    def test_the_drive_walk_is_not_reached_when_a_cheaper_answer_exists(self):
        """It is the only step that touches other volumes, and on a cloud
        mount every probe is a round trip (a Google Drive letter answers
        DRIVE_FIXED). Last, and skipped whenever anything above it answers."""
        def boom(*_a, **_kw):
            raise AssertionError("the drive walk must stay last, and rare")
        with tempfile.TemporaryDirectory() as td:
            default = _client_root(td, "Hearthstone")
            with mock.patch.object(config, "_drive_homes", boom), \
                 mock.patch.object(config, "_registry_homes",
                                   return_value=[]), \
                 mock.patch.object(config, "remembered_home",
                                   return_value=None), \
                 mock.patch.object(config, "default_home",
                                   return_value=default):
                self.assertEqual(
                    config.resolve_home(env={}, platform="win32")[0], default)

    def test_nothing_found_falls_back_to_the_platform_default(self):
        """The worst case has to be what every earlier version did, or this
        search can make a working install worse than it was: the platform
        default is returned even when nothing is there — the coach then says
        what it always said, at a folder it did not invent."""
        home, source = _resolve(default=MISSING)
        self.assertEqual(home, MISSING)
        self.assertIn("nothing else found", source)


class TestWhatCountsAsAClientRoot(unittest.TestCase):
    def test_logs_is_the_strongest_evidence(self):
        """Logs/ is the folder the coach actually reads, so a root that has it
        wins over one that only has the executable."""
        with tempfile.TemporaryDirectory() as td:
            both = _client_root(td, "both")
            with open(os.path.join(both, "Hearthstone.exe"), "w") as f:
                f.write("")
            self.assertEqual(config.root_score(both), 2)

    def test_the_executable_alone_still_counts(self):
        """A game that has not been started since it was installed has no
        Logs/ yet — and a player setting this up before their first game is
        exactly who buys a fresh install."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(config.root_score(_client_root(td, "fresh",
                                                            logs=False)), 1)

    def test_a_folder_with_neither_scores_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(config.root_score(td), 0)

    def test_a_folder_that_is_not_there_scores_zero(self):
        self.assertEqual(config.root_score(MISSING), 0)
        self.assertEqual(config.root_score(""), 0)


class TestRegistryValues(unittest.TestCase):
    """The two values Windows' uninstall entry carries, parsed."""

    def test_install_location_is_the_folder_itself(self):
        self.assertEqual(
            config.install_root_from(WIN_DEFAULT, "InstallLocation"),
            WIN_DEFAULT)

    def test_the_display_icon_gives_its_directory(self):
        icon = os.path.join(WIN_DEFAULT, "Hearthstone.exe")
        self.assertEqual(config.install_root_from(icon, "DisplayIcon"),
                         WIN_DEFAULT)

    def test_an_icon_index_is_cut_off(self):
        """Some uninstallers write `"<path>",0`, which is not a path."""
        icon = f'"{os.path.join(WIN_DEFAULT, "Hearthstone.exe")}",0'
        self.assertEqual(config.install_root_from(icon, "DisplayIcon"),
                         WIN_DEFAULT)

    def test_an_empty_value_gives_nothing(self):
        for value in (None, "", "  ", '""'):
            self.assertEqual(config.install_root_from(value, "InstallLocation"),
                             "")


class TestRememberingTheAnswer(unittest.TestCase):
    """`--set` is what makes the discovery escape hatch usable: an env var is
    not something a player who double-clicks a launcher can set."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = os.path.join(self._tmp.name, "hs_home.json")
        self._env = mock.patch.dict(
            os.environ, {"HEARTHSTONE_HOME_FILE": self.book})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(out):
            code = config.main(list(argv))
        return code, out.getvalue()

    def test_set_remembers_and_reports_the_new_answer(self):
        root = _client_root(self._tmp.name)
        code, text = self._run("--set", root)
        self.assertEqual(code, 0, text)
        self.assertEqual(config.remembered_home(), root)
        # The line must describe the answer --set just produced, not the one
        # this process resolved at import.
        self.assertIn(root, text)

    def test_forget_goes_back_to_looking(self):
        root = _client_root(self._tmp.name)
        self._run("--set", root)
        code, _text = self._run("--forget")
        self.assertEqual(code, 0)
        self.assertIsNone(config.remembered_home())

    def test_a_folder_that_does_not_exist_is_refused(self):
        code, _text = self._run("--set", os.path.join(self._tmp.name, "nope"))
        self.assertEqual(code, 2)
        self.assertIsNone(config.remembered_home())

    def test_a_root_the_player_chooses_is_where_the_next_run_looks(self):
        """The whole point, end to end: `--set`, then a FRESH process finds
        the game's log there. In-process asserts could not show this, because
        config resolves its root at import.

        The remembered file is redirected with HEARTHSTONE_HOME_FILE — this
        test must not write into app/, and the same override is what a
        read-only install (unzipped into Program Files) uses.
        """
        root = _client_root(self._tmp.name)
        log = os.path.join(root, "Logs", SESSION, "Power.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("x\n")
        env = dict(os.environ, HEARTHSTONE_HOME_FILE=self.book)
        p = subprocess.run([sys.executable, "config.py", "--set", root],
                           cwd=HERE, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        q = subprocess.run(
            [sys.executable, "-c",
             "import config;print(config.HS_DIR);"
             "print(config.HS_LOG_GLOBS[0]);"
             "print(config.HS_HOME_SOURCE)"],
            cwd=HERE, env=env, capture_output=True, text=True)
        self.assertEqual(q.returncode, 0, q.stderr)
        home, pattern, source = q.stdout.splitlines()
        self.assertEqual(home, root)
        self.assertEqual(pattern, config.log_globs(root)[0])
        self.assertEqual(glob.glob(pattern), [log],
                         "the remembered root is not where the glob looks")
        self.assertIn("told", source)

    def test_a_corrupt_remembered_file_is_not_a_crash(self):
        """Written by one code path, read on every start, and hand-editable:
        garbage has to degrade to "no remembered answer"."""
        for junk in ("", "{", "[]", '{"home": 3}', '{"nope": "x"}'):
            with open(self.book, "w", encoding="utf-8") as f:
                f.write(junk)
            self.assertIsNone(config.remembered_home(), repr(junk))


class TestTheCommandLine(unittest.TestCase):
    """`--check` is the launcher's question and `--discover` is support's."""

    def _run(self, env, *argv):
        return subprocess.run([sys.executable, "config.py", *argv],
                              cwd=HERE, env=env, capture_output=True,
                              text=True)

    def test_check_is_silent_and_answers_through_the_exit_code(self):
        """Silent because the launcher only wants the answer, and a stray line
        of prose on stdout is one more thing that can break batch parsing."""
        with tempfile.TemporaryDirectory() as td:
            found = _client_root(td, "with-logs")
            env = dict(os.environ, HEARTHSTONE_HOME=found)
            p = self._run(env, "--check")
            self.assertEqual((p.returncode, p.stdout), (0, ""))
            env = dict(os.environ, HEARTHSTONE_HOME=MISSING)
            q = self._run(env, "--check")
            self.assertEqual((q.returncode, q.stdout), (1, ""))

    def test_check_never_writes_the_remembered_file(self):
        """`--check` is the README's "look without touching", and the launcher
        promises the same sentence. Resolution reads; only --set writes."""
        with tempfile.TemporaryDirectory() as td:
            book = os.path.join(td, "hs_home.json")
            env = dict(os.environ, HEARTHSTONE_HOME_FILE=book,
                       HEARTHSTONE_HOME=_client_root(td, "with-logs"))
            self._run(env, "--check")
            self._run(env, "--show")
            self.assertFalse(os.path.exists(book),
                             "resolution wrote the remembered file")

    def test_importing_config_writes_nothing(self):
        """Every tool in the tree imports this module. An import that writes
        is an import that can fail for a reason nobody asked about."""
        with tempfile.TemporaryDirectory() as td:
            book = os.path.join(td, "hs_home.json")
            env = dict(os.environ, HEARTHSTONE_HOME_FILE=book)
            p = subprocess.run([sys.executable, "-c", "import config"],
                               cwd=HERE, env=env, capture_output=True,
                               text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse(os.path.exists(book))

    def test_discover_names_every_source_it_consulted(self):
        with tempfile.TemporaryDirectory() as td:
            root = _client_root(td, "with-logs")
            env = dict(os.environ, HEARTHSTONE_HOME_FILE=os.path.join(
                td, "hs_home.json"), HEARTHSTONE_HOME=root)
            p = self._run(env, "--discover")
            self.assertEqual(p.returncode, 0, p.stderr)
            for needle in ("HEARTHSTONE_HOME", "remembered", "uninstall entry",
                           "platform default", "drive scan", root):
                self.assertIn(needle, p.stdout)

    def test_json_is_the_same_answer_in_a_parseable_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = _client_root(td, "with-logs")
            env = dict(os.environ, HEARTHSTONE_HOME_FILE=os.path.join(
                td, "hs_home.json"), HEARTHSTONE_HOME=root)
            p = self._run(env, "--json", "--discover")
            payload = json.loads(p.stdout)
            self.assertEqual(payload["home"], root)
            self.assertEqual(payload["source"], "HEARTHSTONE_HOME")
            self.assertTrue(payload["logs"])
            self.assertTrue(payload["sources"])


class TestTheMessagesDoNotLie(unittest.TestCase):
    """The failure this whole change exists for was a MESSAGE, not a crash."""

    def test_the_no_log_advice_names_where_it_looked(self):
        lines = live.no_log_advice(root="R:\\somewhere",
                                   source="the usual place for this platform",
                                   python="python", config_py="config.py")
        text = "\n".join(lines)
        self.assertIn("R:\\somewhere", text)
        self.assertIn("the usual place for this platform", text)

    def test_the_no_log_advice_does_not_claim_logging_is_off(self):
        """It used to say "Hearthstone's file logging is probably OFF" — the
        one line a player acts on, printed at a point where the coach has no
        way to know that, one line after the launcher said it turned logging
        ON. The conditional form is the honest one."""
        text = "\n".join(live.no_log_advice(root="X", source="Y"))
        self.assertNotIn("probably", text.lower())
        self.assertIn("If it IS installed there", text)

    def test_the_no_log_advice_says_how_to_point_the_coach(self):
        text = "\n".join(live.no_log_advice(root="X", source="Y",
                                            python="py", config_py="config.py"))
        self.assertIn('"py" "config.py" --set', text)

    def test_the_overlay_hint_leads_with_the_cause_that_applies(self):
        """The card is what the player is looking at while nothing happens, so
        it may not name only the logging setting: with no log folder there,
        that is not what is wrong."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(config, "HS_DIR", _client_root(td, "ok")):
                logged = coach_ui._welcome_hint()
            with mock.patch.object(config, "HS_DIR", MISSING):
                no_folder = coach_ui._welcome_hint()
        self.assertIn("file logging is ON", logged)
        self.assertNotIn("no Hearthstone log folder", logged)
        self.assertIn("no Hearthstone log folder", no_folder)
        self.assertNotIn("only writes the log this reads when file logging is "
                         "ON. Run", no_folder)

    def test_the_overlay_hint_keeps_the_log_config_block_reachable(self):
        """test_coach_ui_http pins this for the real payload; the second branch
        needs it too, because that is the branch a broken install sees."""
        with mock.patch.object(config, "HS_DIR", MISSING):
            self.assertIn("log.config", coach_ui._welcome_hint())

    def test_no_message_prints_a_path_from_this_machine(self):
        """Overlay text ends up in screenshots, which is why config_hint() is
        an env-var form rather than the resolved path."""
        with mock.patch.object(config, "HS_DIR", MISSING):
            hint = coach_ui._welcome_hint()
        self.assertNotIn(MISSING, hint)


class TestTheLauncherAsksInsteadOfGuessing(unittest.TestCase):
    """The Windows twin of test_launcher_sh's config-deferral case.

    This branch used to set `LOGDIR=%ProgramFiles(x86)%\\Hearthstone\\Logs` and
    tell a player whose game was elsewhere that the folder was missing, one
    line before live.py blamed file logging — which this same file had just
    switched on.
    """

    def _code_lines(self):
        """The lines that EXECUTE. A comment may name the old path: that is how
        the next reader learns why it is gone, and it is what the assertion
        below would otherwise have to delete from the record."""
        with open(os.path.join(ROOT, "Start Bob's Ledger.cmd"),
                  encoding="ascii") as f:
            lines = f.read().splitlines()
        return "\n".join(ln for ln in lines
                         if ln.strip() and not ln.strip().lower()
                         .startswith("rem"))

    def test_it_asks_config_for_the_client_root(self):
        self.assertIn('app\\config.py" --show', self._code_lines())

    def test_no_line_of_code_still_guesses_the_root(self):
        """The guess was two lines — the `set "LOGDIR=..."` and the `if exist`
        that reported the game as missing — and the player-facing variable it
        told them to go and set is gone with them."""
        code = self._code_lines()
        self.assertNotIn("%ProgramFiles(x86)%", code)
        self.assertNotIn("HEARTHSTONE_HOME", code)


if __name__ == "__main__":
    unittest.main()
