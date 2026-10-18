"""Keep a test module out of the PLAYER's saved games (2026-10-17).

`replay_store` writes to `app/saved_replays/` whenever it is not given a `root`,
and the monitor's auto-save path writes there too — gated on the player's own
`.save_all_replays.json`, which is ON for the maintainer. So any test module that
drives a game to its end can leave a real-looking entry in Settle Up.

MEASURED 2026-10-17: two `run-na` files with STABLE gids reappeared in the
maintainer's list on every suite run, and they read like a save that had gone
wrong. They were `test_monitor_smoke`'s fixtures: its session is named
`Hearthstone_2026_01_01`, and only ONE of its tests redirected the store.

Usage, at module level:

    import hermetic_store

    def setUpModule():    hermetic_store.begin()
    def tearDownModule(): hermetic_store.end()
"""
import os
import tempfile

import replay_store

_saved = None
_tmp = None


def begin():
    """Point the store and the auto-save flag at a scratch directory."""
    global _saved, _tmp
    if _tmp is not None:
        return                      # already hermetic
    _saved = (replay_store.store_dir, replay_store.AUTO_PATH)
    _tmp = tempfile.TemporaryDirectory()
    replay_store.store_dir = (lambda root=None:
                              os.path.join(_tmp.name, "saved_replays"))
    # A flag of this module's own, so the PLAYER's answer is neither read nor
    # written. Auto-save ON here, because the leak happened with it on: a test
    # that drives a game to its end must exercise the save path too.
    replay_store.AUTO_PATH = os.path.join(_tmp.name, ".save_all_replays.json")


def end():
    global _saved, _tmp
    if _saved is not None:
        replay_store.store_dir, replay_store.AUTO_PATH = _saved
    if _tmp is not None:
        _tmp.cleanup()
    _saved = _tmp = None
