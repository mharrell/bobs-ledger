"""Which real Power.log the machine-dependent tests smoke-test against.

Several tests parse a log from this machine's own Hearthstone install, because
real format drift is the one thing hand-built fixtures cannot catch. What they
must not do is parse *whatever is newest*: while the game is running that file
is a moving target. It grows between reads, and its first game can be a shape
the assertions were never written for.

Measured on 2026-10-03, Hearthstone open: a live 14 MB session failed
test_integration_real_log's hero assertion every run, and pushed
test_friendly_player from about 2s to 154s because it re-parses the file in
each of its 15 tests. Both would have been reported as product bugs.

So the rule is: the newest session that has stopped being written, preferring
one small enough to parse cheaply. No settled log means these tests SKIP and
say why — a skip is honest, a moving target is not.

Overridable, for a developer who deliberately wants the live file:
    HEARTH_REAL_LOG_SETTLE=0    treat even a just-written log as settled
    HEARTH_REAL_LOG_MAX=...     raise the size preference
"""
import glob
import os
import time

from config import HS_LOG_GLOBS

#: A log untouched for this long is treated as finished.
SETTLE_SECONDS = int(os.environ.get("HEARTH_REAL_LOG_SETTLE", "180"))

#: Bigger than this and every test that touches it pays seconds for the
#: privilege. A preference, not a filter: if only large logs exist, the newest
#: of those is still used rather than skipping the tests outright.
MAX_BYTES = int(os.environ.get("HEARTH_REAL_LOG_MAX", str(12 * 1024 * 1024)))


def all_logs():
    """Every session log on this machine, newest first (both known shapes)."""
    paths = {p for pattern in HS_LOG_GLOBS for p in glob.glob(pattern)}
    return sorted(paths, key=os.path.getmtime, reverse=True)


def newest_settled():
    """The newest finished session log, or None while the game is writing."""
    now = time.time()
    settled = [p for p in all_logs()
               if now - os.path.getmtime(p) > SETTLE_SECONDS]
    if not settled:
        return None
    small = [p for p in settled if os.path.getsize(p) <= MAX_BYTES]
    return (small or settled)[0]


def why_none():
    """The skip message, naming the actual reason this machine gave."""
    logs = all_logs()
    if not logs:
        return "no Hearthstone session log found on this machine"
    now = time.time()
    live = [p for p in logs if now - os.path.getmtime(p) <= SETTLE_SECONDS]
    if live:
        return (f"the newest session is still being written "
                f"({os.path.basename(os.path.dirname(live[0]))}) — these tests "
                f"need a finished log; close Hearthstone to run them")
    return "no usable Hearthstone session log found"
