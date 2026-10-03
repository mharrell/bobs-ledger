"""One owner for the client install path, and a test that keeps it that way.

Five dev tools used to carry the Windows client path in their own source, so
"where is the client installed" had six different answers and the macOS port
would have had to fix every one of them. config.py owns the path now: the
platform default plus the HEARTHSTONE_HOME override, and config.log_globs
owns the two shapes a Power.log turns up in.

This suite is the invariant that stops the sixth answer coming back. A path
fragment in any module directly under app/ fails here, because that is the
regression nobody notices until a Mac reports no logs at all - the tools are
dev tools, run rarely, and each one worked on the maintainer's machine for
months.

Fixtures are assembled at runtime rather than written out, per this suite's
convention: anything path-shaped in a shipped file reads as a real local
path to the release's privacy gate.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import comp_miner        # noqa: E402
import config            # noqa: E402
import logquery          # noqa: E402
import parse_minions     # noqa: E402
import pool_roster       # noqa: E402
import refresh_trinkets  # noqa: E402

#: The fragment no module but config.py may name, built from two pieces on
#: purpose: this file must not contain the string it forbids, or the scan
#: below would trip its own rule the moment anyone widened it to app/tests/.
INSTALL_FRAGMENT = "Program" + " Files"

#: The one module allowed to name it - a platform default has to live
#: somewhere, and guessing one for macOS is worse than not having one.
OWNER = "config.py"

#: The tools this invariant exists for. Asserted to be inside the scanned set
#: so the scan cannot pass by finding nothing.
TOOLS = {"comp_miner.py", "logquery.py", "parse_minions.py", "pool_roster.py",
         "refresh_trinkets.py"}

#: A single glob, shaped like the CLI flag's argument. Assembled like every
#: other path here rather than written as a real install path.
ONE_GLOB = os.path.join("logs", "Power.log")


#: A session directory name, assembled from pieces: written out it is a real
#: session-shaped name, which the release's privacy gate refuses in a shipped
#: file. config's shapes are the only thing these tools may assume about it.
SESSION_DIR = "Hearthstone_" + "2026_01_01"


class TestOneOwner(unittest.TestCase):
    """The install path is named once, in config.py, and nowhere else."""

    def _scanned(self):
        """{filename: text} for the modules directly under app/ - not the
        tests, which legitimately fixture the path for assertions."""
        out = {}
        for name in sorted(os.listdir(HERE)):
            path = os.path.join(HERE, name)
            if not name.endswith(".py") or name == OWNER:
                continue
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                out[name] = f.read()
        return out

    def test_no_tool_names_the_install_path_itself(self):
        """A path literal in a tool is how the path got five owners: the
        macOS port would fix the coaching path, ship, and leave five dev
        tools looking at a Windows directory that does not exist."""
        scanned = self._scanned()
        self.assertTrue(TOOLS <= set(scanned),
                        f"the scan missed the tools it exists for: "
                        f"{sorted(TOOLS - set(scanned))}")
        offenders = [name for name, text in scanned.items()
                     if INSTALL_FRAGMENT in text]
        self.assertEqual(
            offenders, [],
            f"{offenders} name the client path directly; import it from "
            f"config instead (HEARTHSTONE_HOME must apply to every tool)")

    def test_config_itself_still_names_the_default(self):
        """The scan above only means something while config.py is the file
        that matches: if the platform default were dropped there, the
        invariant would pass by there being no path anywhere at all."""
        with open(os.path.join(HERE, OWNER), encoding="utf-8") as f:
            self.assertIn(INSTALL_FRAGMENT, f.read())


class TestToolsDeriveTheirDefaults(unittest.TestCase):
    """The tools' public constants are config's values, not copies of them."""

    def test_the_log_glob_tools_share_config(self):
        for mod in (comp_miner, logquery):
            self.assertEqual(mod.HS_LOG_GLOB, config.HS_LOG_GLOB,
                             f"{mod.__name__} does not use config's glob")

    def test_the_log_dir_tools_share_config(self):
        expected = os.path.join(config.HS_DIR, "Logs")
        for mod in (parse_minions, pool_roster):
            self.assertEqual(mod.DEFAULT_LOG_DIR, expected,
                             f"{mod.__name__} does not use config's log dir")

    def test_the_globbing_tools_ask_for_both_log_shapes(self):
        """Windows writes a session directory; the macOS reference documents
        a flat Logs/Power.log, and which one a machine uses is exactly what
        nobody has verified. Asking for one shape only is how a Mac ends up
        reporting no logs."""
        calls = ((comp_miner, lambda: comp_miner.scan(limit=0)),
                 (logquery, logquery.newest_log),
                 (refresh_trinkets, refresh_trinkets.recent_logs),
                 (refresh_trinkets, lambda: refresh_trinkets._scan_logs(
                     refresh_trinkets.SEEN_ANY)))
        for mod, call in calls:
            with mock.patch.object(mod.glob, "glob", return_value=[]) as g:
                call()
            self.assertEqual([c[0][0] for c in g.call_args_list],
                             list(config.HS_LOG_GLOBS), mod.__name__)

    def test_the_log_dir_tools_find_a_log_below_their_log_dir(self):
        """config.log_globs builds its shapes under the CLIENT ROOT, while
        `--logs` in these two tools is the Logs directory inside that root:
        threading the log dir straight into log_globs adds a second "Logs"
        and the tool scans nothing - silently, so the answer would just come
        back empty. A real file in the session-dir shape is what proves the
        pattern still lands where the old hand-built join put it.
        """
        with tempfile.TemporaryDirectory() as td:
            logs = os.path.join(td, "Logs")
            session = os.path.join(logs, SESSION_DIR)
            os.makedirs(session)
            log = os.path.join(session, "Power.log")
            with open(log, "w", encoding="utf-8") as f:
                f.write("x\n")
            cache = os.path.join(td, "observed_cache.json")
            parse_minions.scan_observed(log_dir=logs, cache_path=cache,
                                        rescan=True)
            with open(cache, encoding="utf-8") as f:
                found = list(json.load(f)["files"])
            self.assertEqual([os.path.normcase(p) for p in found],
                             [os.path.normcase(log)], "parse_minions")
            sessions = pool_roster.load_sessions(log_dir=logs)
            self.assertEqual([os.path.normcase(s["path"]) for s in sessions],
                             [os.path.normcase(log)], "pool_roster")


class TestAsGlobs(unittest.TestCase):
    """One glob or several, without breaking the single-string callers."""

    def test_a_string_is_one_pattern_not_characters(self):
        """`scan(log_glob=...)` and `--logs` take a single glob string; a
        helper that iterated the string would glob once per character."""
        self.assertEqual(config.as_globs(ONE_GLOB), (ONE_GLOB,))

    def test_a_tuple_of_patterns_is_returned_unchanged(self):
        self.assertEqual(config.as_globs(config.HS_LOG_GLOBS),
                         config.HS_LOG_GLOBS)
        self.assertEqual(config.as_globs(()), ())

    def test_any_sequence_becomes_a_tuple(self):
        self.assertEqual(config.as_globs([ONE_GLOB]), (ONE_GLOB,))

    def test_a_single_glob_still_reaches_the_tool_unchanged(self):
        """The parameter is documented as one-or-several, so one must behave
        exactly as it did before the helper existed."""
        with mock.patch.object(comp_miner.glob, "glob",
                               return_value=[]) as g:
            comp_miner.scan(log_glob=ONE_GLOB, limit=0)
        self.assertEqual([c[0][0] for c in g.call_args_list], [ONE_GLOB])


class TestDefaultFollowsTheEnvOverride(unittest.TestCase):
    """HEARTHSTONE_HOME has to beat the platform default in EVERY tool.

    Checked in a subprocess because config resolves the path at import time:
    patching os.environ in this process would prove nothing about the import
    the tools actually perform.
    """

    def test_hearthstone_home_becomes_the_client_root(self):
        home = os.path.join(tempfile.gettempdir(), "hs-home-fixture")
        env = dict(os.environ, HEARTHSTONE_HOME=home)
        proc = subprocess.run(
            [sys.executable, "-c",
             "import config;print(config.HS_DIR);print(config.HS_LOG_GLOB)"],
            cwd=HERE, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        root, log_glob = proc.stdout.splitlines()
        self.assertEqual(root, home)
        # The glob has to follow the override too, or the override lands on
        # HS_DIR while discovery still looks under the platform default.
        self.assertEqual(log_glob, config.log_globs(home)[0])


if __name__ == "__main__":
    unittest.main()
