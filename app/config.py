r"""Shared install paths for the Bob's Ledger tools.

Every tool hardcoded the Windows client path — a non-default install (or a
non-Windows machine) meant editing each file separately. One module now owns
them; override the client root with the HEARTHSTONE_HOME env var.

The macOS values come from the community logging reference
(https://github.com/jleclanche/fireplace/wiki/How-to-enable-logging): the
client is /Applications/Hearthstone and it writes Logs/ inside that. NOTHING
here has been verified on a Mac — no Mac has ever run this — which is exactly
why every path stays overridable and why the log lookup asks for both known
shapes rather than the one we have seen.

Constants:
    HS_DIR        client root (Windows: C:\Program Files (x86)\Hearthstone;
                  macOS: /Applications/Hearthstone)
    HS_LOG_GLOB   glob for the per-session Power.log files
    HS_LOG_GLOBS  both known Power.log shapes, session-dir first
    HS_DATA_DIR   client data dir (UnityPy carddef*.unity3d bundles)
    LAUNCHERS     the launcher filenames shipped at the zip root
"""
import os
import sys

#: The client root per platform. macOS keeps the game in /Applications, not
#: under Program Files. Anything unlisted takes the Windows default.
_DEFAULT_HOME = {
    "win32": r"C:\Program Files (x86)\Hearthstone",
    "darwin": "/Applications/Hearthstone",
}

#: One release zip serves every platform, so both launchers ship in it; only
#: one of them means anything per platform. A .command is what macOS opens in
#: Terminal on a double-click.
LAUNCHERS = ("Start Bob's Ledger.cmd", "Start Bob's Ledger.command")


def default_home(platform=None):
    """The client root for `platform` (default: the one we are running on)."""
    return _DEFAULT_HOME.get(platform or sys.platform,
                             _DEFAULT_HOME["win32"])


def log_globs(root=None, platform=None):
    """Both shapes a Power.log turns up in, session-dir shape first.

    Windows writes `Logs/Hearthstone_<timestamp>/Power.log`. The macOS
    reference documents a flat `Logs/Power.log`, and whether the Mac client
    has since adopted session directories is unverified — so ask for both. On
    Windows the flat pattern simply matches nothing, and on a Mac the
    session-dir pattern does, whichever way round it turns out.

    `platform` is accepted for the sake of a pure signature; the shapes are
    the same two everywhere.
    """
    root = root or HS_DIR
    return (os.path.join(root, "Logs", "Hearthstone_*", "Power.log"),
            os.path.join(root, "Logs", "Power.log"))


def launcher(platform=None):
    """The launcher that does something when double-clicked on `platform`."""
    return (LAUNCHERS[0] if (platform or sys.platform) == "win32"
            else LAUNCHERS[1])


def config_hint(platform=None):
    """The log.config path as a player should READ it, not as this machine
    resolves it.

    Deliberately an env-var form on Windows and a ~ form on macOS: the
    resolved absolute path carries the local username, and this string goes
    into the overlay's own text and therefore into every screenshot of it —
    including the one in the README.
    """
    if (platform or sys.platform) == "darwin":
        return "~/Library/Preferences/Blizzard/Hearthstone/log.config"
    return "%LocalAppData%\\Blizzard\\Hearthstone\\log.config"


HS_DIR = os.environ.get("HEARTHSTONE_HOME") or default_home()
#: The session-dir shape, kept as the single-glob constant ~20 tools import
#: and expect. Ask for both shapes with HS_LOG_GLOBS.
HS_LOG_GLOB = log_globs(HS_DIR)[0]
HS_LOG_GLOBS = log_globs(HS_DIR)
#: The card-art bundles are inside the client's data dir. Windows-only: the
#: macOS bundle layout has never been inspected, and inventing a path for it
#: would be worse than the tool reporting no bundles (2026-10-03).
HS_DATA_DIR = os.path.join(HS_DIR, "Data", "Win")
