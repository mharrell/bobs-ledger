#!/usr/bin/env python3
"""Turn Hearthstone's file logging on, by editing the game's own config.

WHY THIS EXISTS

This is the step nearly every new player misses, and it is the difference
between a coach that advises and a coach that shows an empty card forever.
Telling someone to hold Win, press R, paste a path, create a file and type five
lines is where they give up (2026-10-03).

WHY IT EDITS RATHER THAN REPLACES

`log.config` is NOT a one-block file. A real one (this machine, 2026-10-03) has
six sections - [Achievements], [Arena], [FullScreenFX], [LoadingScreen],
[Power] and one more - each carrying its own LogLevel / FilePrinting /
ConsolePrinting / ScreenPrinting / Verbose. So handing a player a file to copy
in would silently delete the other five sections for everyone who already has
one, which is every Deck Tracker and Firestone user, and it would break logging
they rely on.

  * no file      -> create it with just the [Power] block
  * file exists  -> back it up once, then set ONLY the keys the coach needs
                    inside the existing [Power] section and leave every other
                    byte of the file exactly as it was

Nothing outside `log.config` is touched, ever. The keys are LogLevel=1 and
FilePrinting=true: the coach never reads the console log, and turning
Screenshots off is not ours to decide.

WHY A SECOND FILE EXISTS (`client.config`)

`log.config` turns logging ON. It does not stop the client from CAPING the file:
Hearthstone closes a log once it reaches its size limit, and the limit is the
client config variable `Log.FileSizeLimit.Int`, registered by the game's own
`PopulateLogSessionConfigOptions` with a default of 10000 (KB). The client says
so in the log itself:

    Truncating log, which has reached the size limit of 10000KB

Measured on macOS 2026-10-15: a Battlegrounds game hit that 10 MB cap, the
client CLOSED Power.log (it disappeared from the process's open files), and
nothing more was written. The game's ending -- and so the review, the saved
replay, and the placement -- was lost, with the coach showing a stale frame and
saying nothing. The maintainer has never seen this on Windows, where the
truncation succeeds and logging resumes.

The fix is the variable the client already defines, set to unlimited (-1), in
the client's own config file beside the game. This is the one piece of local
state outside `log.config` the coach writes, so it is written with the same
care: only the one key is set, every other line survives, and the original is
backed up once.

Usage:
  python setup_logging.py --check     # exit 0 when logging is already on
  python setup_logging.py --apply     # do it, and say what changed
  python setup_logging.py --path DIR  # for tests; or HEARTHSTONE_CONFIG_DIR
"""
import argparse
import os
import shutil
import subprocess
import sys

#: The two keys the coach actually needs, and the values it needs them at.
REQUIRED = {"LogLevel": "1", "FilePrinting": "true"}

#: The client's own config file, beside the game, and the one variable in it
#: that removes the log size cap. `-1` is "no limit"; the client's default is
#: 10000 (KB), which is the 10 MB wall this exists to remove.
CLIENT_CONFIG = "client.config"
CLIENT_REQUIRED = {"Log.FileSizeLimit.Int": "-1"}

#: Kept beside the original, so a player can see exactly what the file looked
#: like before we touched it - and only ever written once, so it stays the
#: true original even if this runs twice.
BACKUP_SUFFIX = ".bobs-ledger-backup"


def config_dir(platform=None):
    """Where Hearthstone keeps `log.config`.

    `HEARTHSTONE_CONFIG_DIR` overrides it: that is how the tests point this at
    a scratch directory, and how a player with an unusual install redirects it,
    without any risk to the real file.

    macOS keeps the same Blizzard/Hearthstone folder, one level under
    Preferences instead of AppData:
    https://github.com/jleclanche/fireplace/wiki/How-to-enable-logging
    Reading LOCALAPPDATA there would have resolved to `~/Blizzard/Hearthstone`
    — a directory the game never looks at — and created a log.config in it.
    """
    override = os.environ.get("HEARTHSTONE_CONFIG_DIR")
    if override:
        return override
    if (platform or sys.platform) == "darwin":
        return os.path.expanduser("~/Library/Preferences/Blizzard/Hearthstone")
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Blizzard", "Hearthstone")


def config_path():
    return os.path.join(config_dir(), "log.config")


def client_config_path(root=None):
    """Where the client keeps `client.config`: beside the GAME, not here.

    `log.config` lives under the user's preferences; `client.config` is read from
    the install root — the same folder the client writes `Logs/` into, which is
    what `config.HS_DIR` resolves. So `HEARTHSTONE_HOME` and `config.py --set`
    move this file for free, and a game installed somewhere unusual needs no
    second answer.
    """
    if root:
        return os.path.join(root, CLIENT_CONFIG)
    import config
    return os.path.join(config.HS_DIR, CLIENT_CONFIG)


def read_client_state(path=None):
    """(state, missing) for `client.config`: 'missing', 'incomplete' or 'ok'.

    Flat `name=value` lines, one per client config var — the format the client's
    own `getvar`/`setvar` console commands read and write. Every other line is
    left alone; only the one variable is judged.
    """
    p = path or client_config_path()
    if not os.path.exists(p):
        return "missing", dict(CLIENT_REQUIRED)
    have = {}
    for line in _lines(p):
        if "=" in line:
            key, _, value = line.partition("=")
            have[key.strip().lower()] = value.strip().lower()
    missing = {k: v for k, v in CLIENT_REQUIRED.items()
               if have.get(k.lower()) != v.lower()}
    return ("ok" if not missing else "incomplete"), missing


def apply_client(path=None, force=False):
    """(state_before, changed, note) — set ONLY the size-limit variable.

    The same contract `apply()` keeps for `log.config`: create when absent, keep
    the original once, and change only the key that is ours. A player who has
    other client config vars (a Deck Tracker's, an event UID's) keeps every one.
    """
    p = path or client_config_path()
    state, _missing = read_client_state(p)
    if state == "ok":
        return state, [], "already-on"
    if not force and hearthstone_running():
        return state, [], "hearthstone-running"

    if state == "missing":
        # This lives in the GAME's folder, which on Windows is under Program
        # Files and may not be writable by a standard user. A failure here is an
        # ordinary outcome to report, not a traceback: the launcher turns a
        # non-zero exit into "close Hearthstone and run this again", and a raw
        # PermissionError in the middle of that would be a worse message than
        # the one it already knows how to print.
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="") as f:
                for key, value in CLIENT_REQUIRED.items():
                    f.write(f"{key}={value}\n")
        except OSError as exc:
            return state, [], f"not-writable:{exc}"
        return state, [f"created {CLIENT_CONFIG} with "
                       + ", ".join(f"{k}={v}" for k, v in CLIENT_REQUIRED.items())], \
            "created"

    backup = p + BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(p, backup)

    lines = _lines(p)
    crlf = any(line.endswith("\r\n") for line in lines)
    nl = "\r\n" if crlf else "\n"
    changed = []
    for key, value in CLIENT_REQUIRED.items():
        for i, line in enumerate(lines):
            if "=" not in line:
                continue
            if line.split("=", 1)[0].strip().lower() != key.lower():
                continue
            if line.split("=", 1)[1].strip().lower() != value.lower():
                lines[i] = f"{key}={value}{nl}"
                changed.append(f"{key} -> {value}")
            break
        else:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += nl
            lines.append(f"{key}={value}{nl}")
            changed.append(f"added {key}={value}")
    try:
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
    except OSError as exc:
        return state, [], f"not-writable:{exc}"
    return state, changed, "backed-up"


def _lines(path):
    """The file's lines with their endings intact (CRLF is preserved)."""
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read().splitlines(keepends=True)


def _section_span(lines, name):
    """(first body line, one past last) of the [name] section, or (None, None)."""
    want = f"[{name}]".lower()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("[") and stripped.endswith("]"):
            if start is not None:
                return start, i          # the next section ends ours
            if stripped == want:
                start = i + 1
    return (start, len(lines)) if start is not None else (None, None)


def read_state(path=None):
    """(state, missing) — 'missing', 'incomplete' or 'ok', and what's missing."""
    p = path or config_path()
    if not os.path.exists(p):
        return "missing", dict(REQUIRED)
    lines = _lines(p)
    start, end = _section_span(lines, "Power")
    if start is None:
        return "incomplete", dict(REQUIRED)
    have = {}
    for line in lines[start:end]:
        if "=" in line:
            key, _, value = line.partition("=")
            have[key.strip().lower()] = value.strip().lower()
    missing = {k: v for k, v in REQUIRED.items()
               if have.get(k.lower()) != v.lower()}
    return ("ok" if not missing else "incomplete"), missing


def _probe(platform=None):
    """True / False / None — None when this machine has no usable probe.

    Windows asks tasklist and looks for Hearthstone.exe. macOS has no
    tasklist, and the old `except: return False` meant "not running" on a Mac
    — which would have let this module edit log.config underneath a live game,
    the one thing it promises not to do. pgrep ships with macOS and exits 1
    for "no match", so its exit code is the answer, not its output.
    """
    platform = platform or sys.platform
    if platform == "darwin":
        for cmd in (["pgrep", "-x", "Hearthstone"],
                    ["ps", "-Ao", "comm="]):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=20)
            except Exception:               # noqa: BLE001 - no pgrep and no ps
                continue
            if cmd[0] == "pgrep":
                return proc.returncode == 0
            # `ps` prints the whole bundle path, so match the name anywhere.
            return "Hearthstone" in proc.stdout
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hearthstone.exe"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:                       # noqa: BLE001 - no tasklist
        return None
    return "Hearthstone.exe" in out


def hearthstone_running(platform=None):
    """The game reads this file at startup, so editing it under the game is
    asking for the change to be ignored (or reverted).

    A machine with no probe at all answers False rather than blocking the
    player: the edit is still made in place, with the original backed up
    first, so the worst case is a change the game ignores — not damage.
    """
    return _probe(platform) is True


def apply(path=None, force=False):
    """(state_before, changed, note) — edit only the [Power] section."""
    p = path or config_path()
    state, _missing = read_state(p)
    if state == "ok":
        return state, [], "already-on"
    if not force and hearthstone_running():
        return state, [], "hearthstone-running"

    if state == "missing":
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("[Power]\r\nLogLevel=1\r\nFilePrinting=true\r\n")
        return state, [f"created log.config with a [Power] block "
                       f"({', '.join(f'{k}={v}' for k, v in REQUIRED.items())})"], \
            "created"

    # A file exists. Keep the original once, before the first change we make.
    backup = p + BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(p, backup)

    lines = _lines(p)
    crlf = any(line.endswith("\r\n") for line in lines)
    nl = "\r\n" if crlf else "\n"
    start, end = _section_span(lines, "Power")
    changed = []
    if start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += nl
        elif lines and lines[-1].strip():
            pass
        lines.append(f"[Power]{nl}")
        for key, value in REQUIRED.items():
            lines.append(f"{key}={value}{nl}")
            changed.append(f"added {key}={value}")
    else:
        for key, value in REQUIRED.items():
            for i in range(start, end):
                if "=" not in lines[i]:
                    continue
                if lines[i].split("=", 1)[0].strip().lower() != key.lower():
                    continue
                if lines[i].split("=", 1)[1].strip().lower() != value.lower():
                    lines[i] = f"{key}={value}{nl}"
                    changed.append(f"{key} -> {value}")
                break
            else:
                lines.insert(end, f"{key}={value}{nl}")
                end += 1
                changed.append(f"added {key}={value}")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return state, changed, "backed-up"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report only; exit 0 when logging is already on and "
                         "the log size cap is removed")
    ap.add_argument("--apply", action="store_true", help="turn it on")
    ap.add_argument("--path", help="the config DIRECTORY to use")
    ap.add_argument("--client-path", help="the client root to write "
                                          "client.config into (tests)")
    ap.add_argument("--force", action="store_true",
                    help="apply even with Hearthstone running")
    args = ap.parse_args()
    if args.path:
        os.environ["HEARTHSTONE_CONFIG_DIR"] = args.path
    p = config_path()
    cp = client_config_path(args.client_path)

    if args.check or not args.apply:
        cstate, cmissing = read_client_state(cp)
        # The cap is reported alongside logging because BOTH have to be right
        # for a long game to survive, and the exit code answers the same
        # question the launcher asks: is there anything left to fix?
        if cstate == "ok":
            print(f"log size cap removed  ({cp})")
        else:
            detail = ("no client.config" if cstate == "missing" else
                      "missing " + ", ".join(f"{k}={v}"
                                             for k, v in cmissing.items()))
            print(f"log size cap STILL SET ({cp}): {detail}")
        state, missing = read_state()
        if state == "ok":
            print(f"file logging is on  ({p})")
            return 0 if cstate == "ok" else 1
        detail = (f"missing {', '.join(f'{k}={v}' for k, v in missing.items())}"
                  if state == "incomplete" else "no log.config")
        print(f"file logging is OFF ({p}): {detail}")
        return 1

    state, changed, note = apply(force=args.force)
    if note == "hearthstone-running":
        print("Hearthstone is running, so the game would ignore the change.")
        print("Close Hearthstone and run this again.")
        return 1
    for line in changed:
        print(f"  {line}")
    if note == "backed-up":
        print(f"  your original is at {p}{BACKUP_SUFFIX}")

    cstate, cchanged, cnote = apply_client(cp, force=args.force)
    if cnote == "hearthstone-running":
        print("Hearthstone is running, so the game would ignore the change.")
        print("Close Hearthstone and run this again.")
        return 1
    if cnote.startswith("not-writable"):
        print(f"could not write {cp}: {cnote.split(':', 1)[-1]}")
        print("  The game's own folder is not writable by this account. Either")
        print("  run this file as an administrator once, or move Hearthstone")
        print("  somewhere you can write to, then run it again.")
        return 1
    for line in cchanged:
        print(f"  {line}")
    if cnote == "backed-up":
        print(f"  your original is at {cp}{BACKUP_SUFFIX}")

    if note == "already-on" and cnote == "already-on":
        print("file logging and the log size cap were already right; "
              "nothing changed")
        return 0
    print("File logging is on and the log size cap is removed. Start "
          "Hearthstone (or restart it) and the coach will see your games -- "
          "all of them, however long the session runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
