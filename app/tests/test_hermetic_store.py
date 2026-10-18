"""The suite must not write into the player's saved games (2026-10-17).

`replay_store` writes to `app/saved_replays/` when it is not given a `root`, and
the monitor's auto-save path writes there too, gated on the player's own
`.save_all_replays.json`. The maintainer has auto-save ON, so `test_monitor_smoke`
— which drives games to their end, and whose session is literally named
`Hearthstone_2026_01_01` — was leaving two `run-na` replays in the real Settle Up
list on every suite run, with stable gids. They read like a save that had gone
wrong; they were fixtures.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hermetic_store  # noqa: E402
import replay_store    # noqa: E402

#: Modules that drive a game to its end, and therefore reach the save path.
#:
#: `test_per_game_share` is NOT here, and that was checked rather than assumed:
#: it builds reports from hand-written advisory records and patches
#: `share.REPORTS_DIR` / `session_report.ID_MAP_DIR`, but never imports
#: `replay_store` and never drives the monitor. Adding a module here is the
#: moment to make it hermetic, not after it leaves debris behind.
MONITOR_DRIVERS = ("test_monitor_smoke.py",)


class TestNothingWritesIntoThePlayerStore(unittest.TestCase):

    def test_the_helper_redirects_the_store_and_the_flag(self):
        real_dir, real_flag = replay_store.store_dir, replay_store.AUTO_PATH
        try:
            hermetic_store.begin()
            redirected = replay_store.store_dir()
            self.assertNotEqual(os.path.abspath(redirected),
                                os.path.join(HERE, "saved_replays"),
                                "begin() did not move the store")
            self.assertNotEqual(replay_store.AUTO_PATH, real_flag,
                                "begin() left the player's auto-save answer in "
                                "place, so a test would read it")
            hermetic_store.end()
            self.assertEqual(replay_store.store_dir, real_dir)
            self.assertEqual(replay_store.AUTO_PATH, real_flag)
        finally:
            hermetic_store.end()

    def test_every_monitor_driver_is_hermetic(self):
        for name in MONITOR_DRIVERS:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("hermetic_store.begin()", src,
                          f"{name} drives a game to its end without redirecting "
                          f"replay_store, so with auto-save on it writes into the "
                          f"player's saved games")


if __name__ == "__main__":
    unittest.main()
