r"""Shared install paths for the Bob's Ledger tools.

Every tool hardcoded the Windows client path — a non-default install (or a
non-Windows machine) meant editing each file separately. One module now owns
them; override the client root with the HEARTHSTONE_HOME env var.

RESOLVED, NOT ASSUMED (2026-10-06)

The root used to be the platform default and nothing else, so a game installed
on another drive — or in another folder on the same drive — put the player in
front of three lines that cannot all be true: "File logging is on", "no
Hearthstone log folder at <the default>", and "Hearthstone's file logging is
probably OFF". The last one sent them to fix the thing that already worked.
`resolve_home()` answers the question instead of assuming the answer:

    HEARTHSTONE_HOME  an explicit answer wins, even when the folder is not
                      there (a player who set it knows better than a probe)
    remembered        `app/.hs_home.json`, written by `--set`. Ignored when
                      the folder it names has gone, so a drive that changed
                      letter cannot pin a dead path.
    registry          the Windows uninstall entry's InstallLocation, asked in
                      the 32-BIT view. The game is 32-bit, so a 64-bit Python
                      asking the default view gets "file not found" while the
                      key sits right there (measured 2026-10-06). Outranks the
                      platform default on purpose: this key is rewritten when
                      the game is installed or moved, while a folder left
                      behind after a move is only a folder.
    default           the platform default, when it looks like a client root
    drive walk        fixed drives x a short list of install suffixes
    default           again, unconditionally — the worst case is exactly what
                      every version before this one did

A root is SCORED, never assumed: `Logs/` is what the coach reads (2),
`Hearthstone.exe` is what the game is (1). The macOS bundle name is
deliberately not guessed; this file's rule is that an invented path is worse
than a probe that reports nothing.

Two sources that read as authoritative and are NOT, both checked 2026-10-06:

  * `HKLM\SOFTWARE\WOW6432Node\Blizzard Entertainment\Hearthstone` does not
    exist. `HKCU\SOFTWARE\Blizzard Entertainment\Hearthstone` does, and holds
    nothing but Unity display settings — it is the key a search engine offers
    first, and it says nothing about where the game is.
  * Battle.net's own `C:\ProgramData\Battle.net\Agent\product.db` (6081 bytes
    on that machine) carries no readable install path: no path-shaped string
    in UTF-8 or UTF-16 decoding. Reading it would need the protobuf schema.

`Logs/` lives INSIDE the client root; `log.config` does not — it is under
%LOCALAPPDATA% (or ~/Library/Preferences), which is why the logging switch
already worked on a non-default install while the log lookup did not.

The macOS values come from the community logging reference
(https://github.com/jleclanche/fireplace/wiki/How-to-enable-logging): the
client is /Applications/Hearthstone and it writes Logs/ inside that. NOTHING
here has been verified on a Mac — no Mac has ever run this — which is exactly
why every path stays overridable and why the log lookup asks for both known
shapes rather than the one we have seen.

Constants:
    HS_DIR        client root (Windows default: C:\Program Files (x86)\Hearthstone;
                  macOS: /Applications/Hearthstone)
    HS_HOME_SOURCE  how that root was chosen, so a message need not guess
    HS_LOG_GLOB   glob for the per-session Power.log files
    HS_LOG_GLOBS  both known Power.log shapes, session-dir first
    HS_DATA_DIR   client data dir (UnityPy carddef*.unity3d bundles)
    LAUNCHERS     the launcher filenames shipped at the zip root

Usage:
    python config.py --show           # the root and how it was chosen
    python config.py --check          # exit code only: is there a Logs folder
    python config.py --discover       # every source consulted, with verdicts
    python config.py --set DIR        # remember DIR as the client root
"""
import argparse
import json
import os
import string
import sys

#: The client root per platform. macOS keeps the game in /Applications, not
#: under Program Files. Anything unlisted takes the Windows default.
_DEFAULT_HOME = {
    "win32": r"C:\Program Files (x86)\Hearthstone",
    "darwin": "/Applications/Hearthstone",
}

#: Sibling folders a Battle.net install turns up in, per drive, in the order
#: they are worth trying. Cheap `isdir` calls, and the list stays short on
#: purpose: a cloud mount reports DRIVE_FIXED (Google Drive's G: answered 3
#: when this was measured), so on such a mount every suffix is a round trip.
_DRIVE_SUFFIXES = (
    "Hearthstone",
    os.path.join("Program Files (x86)", "Hearthstone"),
    os.path.join("Program Files", "Hearthstone"),
    os.path.join("Games", "Hearthstone"),
    os.path.join("Blizzard", "Hearthstone"),
    os.path.join("Battle.net", "Hearthstone"),
    os.path.join("Games", "Blizzard", "Hearthstone"),
    os.path.join("Program Files (x86)", "Blizzard", "Hearthstone"),
)

#: The one Windows subkey Hearthstone's install leaves behind. A single subkey
#: rather than a family of guesses: a second dead key is how the
#: "Blizzard Entertainment\Hearthstone" mistake above gets made again.
_UNINSTALL_SUBKEY = "\\".join(
    ("SOFTWARE", "Microsoft", "Windows", "CurrentVersion", "Uninstall",
     "Hearthstone"))

#: The player's answer, remembered, beside the code — the same place every
#: other piece of local state lives (decision_logs/, img_cache/). The README's
#: install promise is that uninstalling is deleting one folder, so a per-user
#: file under %LOCALAPPDATA% would be a promise broken.
#: HEARTHSTONE_HOME_FILE moves it: for a read-only install (unzipped into
#: Program Files) and for the tests, which must not write into app/.
HOME_FILE = ".hs_home.json"

#: One release zip serves every platform, so both launchers ship in it; only
#: one of them means anything per platform. A .command is what macOS opens in
#: Terminal on a double-click.
LAUNCHERS = ("Start Bob's Ledger.cmd", "Start Bob's Ledger.command")


def app_dir():
    """The directory holding the code — one level below the install root."""
    return os.path.dirname(os.path.abspath(__file__))


def default_home(platform=None):
    """The client root for `platform` (default: the one we are running on)."""
    return _DEFAULT_HOME.get(platform or sys.platform,
                             _DEFAULT_HOME["win32"])


def home_file():
    """Where the remembered root is written."""
    override = os.environ.get("HEARTHSTONE_HOME_FILE")
    return override or os.path.join(app_dir(), HOME_FILE)


def remembered_home(path=None):
    """The root this install was TOLD to use, or None.

    Tolerant by design: written by one code path and read on every start, so a
    half-written or hand-edited file has to degrade to "no remembered answer"
    rather than raise into a coach start.
    """
    try:
        with open(path or home_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    home = data.get("home")
    if isinstance(home, str) and home.strip():
        return os.path.expanduser(home.strip())
    return None


def remember_home(home, path=None):
    """Remember `home` as the client root. Raises OSError if it cannot write."""
    target = path or home_file()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"home": home}, f, indent=1)
        f.write("\n")
    return target


def forget_home(path=None):
    """Drop the remembered root. True when there was one to drop."""
    try:
        os.remove(path or home_file())
        return True
    except OSError:
        return False


def root_score(path):
    """How much a folder looks like the client root: 2, 1 or 0.

    2 — it holds `Logs/`, the folder the coach reads.
    1 — it holds `Hearthstone.exe`, so it is the game, but the log folder is
        not there yet (a game that has not been started since it was
        installed).
    0 — neither: a folder that was moved away, or uninstalled.
    """
    if not path or not os.path.isdir(path):
        return 0
    if os.path.isdir(os.path.join(path, "Logs")):
        return 2
    if os.path.isfile(os.path.join(path, "Hearthstone.exe")):
        return 1
    return 0


def _fixed_drives():
    """Local drives worth probing, as `C:\\`-style roots; [] off Windows.

    Windows is asked for the drive TYPE rather than every letter that happens
    to resolve, because a mapped network drive and a CD-ROM are slow to stat
    and can block. Note the limit of that filter, measured 2026-10-06: a
    Google Drive mount answers DRIVE_FIXED, so a cloud drive is still probed.
    One more reason this walk is the LAST step.

    A machine where the type cannot be read gets an empty list: the registry
    step already covers the install that moved, and a wrong guess at a drive
    letter is not worth a startup hang.
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        get = ctypes.windll.kernel32.GetDriveTypeW
        get.argtypes = [ctypes.c_wchar_p]
        get.restype = ctypes.c_uint
    except Exception:                       # noqa: BLE001 - no ctypes, no walk
        return []
    fixed = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        try:
            if get(drive) == 3:             # DRIVE_FIXED
                fixed.append(drive)
        except Exception:                   # noqa: BLE001 - never break import
            continue
    return fixed


def install_root_from(value, name):
    """The client root named by one uninstall value, or "".

    `InstallLocation` IS the folder. `DisplayIcon` is the game's own
    executable, so its directory is the second chance — Battle.net has always
    written both. Some installers append an icon index (`"path",0`), which is
    why the value is cut at the first comma and the quotes come off after.
    """
    text = (value or "").strip().split(",")[0].strip().strip('"')
    if not text:
        return ""
    return os.path.dirname(text) if name == "DisplayIcon" else text


def _registry_homes():
    """Install paths from Windows' uninstall entry, best first; [] elsewhere.

    Both views and both hives, because a 64-bit Python asking the default view
    finds nothing while the key sits right there in WOW6432Node — the exact
    trap this function exists to avoid (measured 2026-10-06 on a normal
    install). Anything unexpected returns [] rather than raising: this runs at
    import time for every tool in the tree, and a registry read must never be
    the reason a coach does not start.
    """
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:                     # pragma: no cover - Windows only
        return []
    out = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                key = winreg.OpenKey(hive, _UNINSTALL_SUBKEY, 0,
                                     winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                for name in ("InstallLocation", "DisplayIcon"):
                    try:
                        raw = winreg.QueryValueEx(key, name)[0]
                    except OSError:
                        continue
                    path = install_root_from(raw, name)
                    if path and path not in out:
                        out.append(path)
            except Exception:               # noqa: BLE001
                continue
            finally:
                winreg.CloseKey(key)
    return out


def _drive_homes(roots=None):
    """Every folder the drive walk would look at, in the order it looks."""
    return [os.path.join(drive, suffix)
            for drive in (_fixed_drives() if roots is None else roots)
            for suffix in _DRIVE_SUFFIXES]


def resolve_home(env=None, platform=None):
    """(client root, how it was chosen) — see the module docstring for order.

    Testable by design: the machine-dependent steps (`remembered_home`,
    `_registry_homes`, `_drive_homes`) are module functions a test patches,
    and the filesystem is only ever asked whether a folder exists.
    """
    env = os.environ if env is None else env
    platform = platform or sys.platform
    explicit = env.get("HEARTHSTONE_HOME")
    if explicit:
        return explicit, "HEARTHSTONE_HOME"
    remembered = remembered_home()
    if remembered and os.path.isdir(remembered):
        return remembered, "the folder this install was told to use"
    for path in _registry_homes():
        if root_score(path) >= 1:
            return path, "Windows' uninstall entry"
    default = default_home(platform)
    if root_score(default) >= 1:
        return default, "the usual place for this platform"
    for path in _drive_homes():
        if os.path.normcase(path) == os.path.normcase(default):
            continue
        if root_score(path) >= 1:
            return path, "a scan of this machine's drives"
    return default, "the usual place for this platform (nothing else found)"


def _verdict(path):
    """One word for a candidate folder, for `--discover`."""
    if root_score(path) == 2:
        return "logs"
    if root_score(path) == 1:
        return "the game, but no Logs folder yet"
    return "nothing of ours" if os.path.isdir(path) else "not there"


def evidence(env=None, platform=None):
    """[(source, value, verdict)] for every place the root could have come
    from, in the order `resolve_home` consults them.

    This answers "why is the coach looking THERE?", which used to take a
    support round trip. The drive walk is summarised rather than listed, since
    8 folders per drive is not a report.
    """
    env = os.environ if env is None else env
    platform = platform or sys.platform
    rows = []
    explicit = env.get("HEARTHSTONE_HOME")
    rows.append(("HEARTHSTONE_HOME", explicit or "(not set)",
                 "used as-is" if explicit else ""))
    remembered = remembered_home()
    rows.append(("remembered", remembered or f"(no file: {HOME_FILE})",
                 _verdict(remembered) if remembered else ""))
    for path in _registry_homes():
        rows.append(("uninstall entry", path, _verdict(path)))
    default = default_home(platform)
    rows.append(("platform default", default, _verdict(default)))
    candidates = _drive_homes()
    drives = {os.path.splitdrive(p)[0] for p in candidates}
    found = [p for p in candidates if root_score(p) >= 1]
    rows.append(("drive scan",
                 f"{len(candidates)} folder(s) on {len(drives)} drive(s)",
                 f"{len(found)} found"))
    for path in found:
        rows.append(("drive scan found", path, _verdict(path)))
    return rows


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


def as_globs(patterns):
    """One glob or several, as a tuple — a caller passing a single string keeps working."""
    if isinstance(patterns, str):
        return (patterns,)
    return tuple(patterns)


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


HS_DIR, HS_HOME_SOURCE = resolve_home()
#: The session-dir shape, kept as the single-glob constant ~20 tools import
#: and expect. Ask for both shapes with HS_LOG_GLOBS.
HS_LOG_GLOB = log_globs(HS_DIR)[0]
HS_LOG_GLOBS = log_globs(HS_DIR)
#: The card-art bundles are inside the client's data dir. Windows-only: the
#: macOS bundle layout has never been inspected, and inventing a path for it
#: would be worse than the tool reporting no bundles (2026-10-03).
HS_DATA_DIR = os.path.join(HS_DIR, "Data", "Win")


def _payload(discover=False, home=None, source=None):
    home = HS_DIR if home is None else home
    source = HS_HOME_SOURCE if source is None else source
    out = {"home": home, "source": source,
           "logs": os.path.isdir(os.path.join(home, "Logs")),
           "home_file": home_file(), "remembered": remembered_home()}
    if discover:
        out["sources"] = [{"source": s, "value": v, "verdict": n}
                          for s, v, n in evidence()]
    return out


def _show(home=None, source=None):
    """The one line the launcher echoes, plus the fix when it applies.

    One line, because this lands in a first-run console next to "Python:" and
    "Dependencies:", and the fix is printed only when there is something to
    fix — a working install says nothing alarming.

    `home`/`source` are passed by `--set` and `--forget`, which must report the
    answer their own change produced rather than the one this process read at
    import: saying "remembered" and then printing the old folder would be the
    same class of lie this whole module was rewritten to remove.
    """
    home = HS_DIR if home is None else home
    source = HS_HOME_SOURCE if source is None else source
    print(f"Hearthstone:  {home}   [{source}]")
    if not os.path.isdir(os.path.join(home, "Logs")):
        print("  no Logs folder there yet. If the game is installed "
              "somewhere else, tell the coach once:")
        print(f'    "{sys.executable}" "{os.path.join(app_dir(), "config.py")}"'
              f' --set "<the folder holding Hearthstone.exe>"')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit code only: 0 when the resolved root holds a "
                         "Logs folder")
    ap.add_argument("--show", action="store_true",
                    help="the root and how it was chosen (the default)")
    ap.add_argument("--discover", action="store_true",
                    help="every source consulted, with its verdict")
    ap.add_argument("--set", dest="set_home", metavar="DIR",
                    help="remember DIR as the client root: the folder that "
                         "holds Hearthstone.exe")
    ap.add_argument("--forget", action="store_true",
                    help="forget the remembered root and go back to looking")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    changed = False
    if args.set_home:
        home = os.path.abspath(os.path.expanduser(args.set_home))
        if not os.path.isdir(home):
            print(f"not a folder: {home}", file=sys.stderr)
            return 2
        if root_score(home) == 0:
            print(f"note: no Hearthstone.exe and no Logs folder in {home} — "
                  f"remembering it anyway, since a game that has never been "
                  f"started has neither yet", file=sys.stderr)
        try:
            remember_home(home)
        except OSError as exc:
            print(f"could not remember it ({exc.strerror or exc}): this "
                  f"install folder is not writable. Set the environment "
                  f"variable HEARTHSTONE_HOME to {home} instead.",
                  file=sys.stderr)
            return 2
        changed = True
    elif args.forget:
        changed = forget_home()

    if changed:
        home, source = resolve_home()
    else:
        home, source = HS_DIR, HS_HOME_SOURCE

    if args.json:
        print(json.dumps(_payload(args.discover, home, source), indent=1))
    elif args.discover:
        _show(home, source)
        print()
        for row_source, value, verdict in evidence():
            print(f"  {row_source:22} {value}"
                  + (f"  ({verdict})" if verdict else ""))
    elif not args.check:
        _show(home, source)

    return 0 if os.path.isdir(os.path.join(home, "Logs")) else 1


if __name__ == "__main__":
    sys.exit(main())
