"""Saved game reviews: the store behind the Settle Up tab.

`settle_up.build()` replays a log into a plain-dict review (the "rep"). This
module persists those — one JSON file per game under `app/saved_replays/` —
so a review outlives the process and the tab can list and reload past games.
It exists because the in-memory review covered exactly one game and died
with the coach (the 2026-10-06 tab work).

The rep is self-sufficient for DISPLAY — every board string already carries
resolved card names — so nothing here needs the Power.log. The source log is
recorded as a pointer (`log` + `game`), not copied: a session log is
megabytes and Hearthstone keeps its session dirs for days. Re-deriving NEW
analyses from an old game wants the log itself; that archive follow-up is
deliberately not here.

This is per-user data, the same class as `decision_logs/`: gitignored and
excluded from the release zip (`publish_release.EXCLUDE_DIRS`).

Usage:
    replay_store.save(rep)             -> {"id": ..., "path": ...}
    replay_store.list()                -> [{id, hero, placement, turns, ...}]
    replay_store.load(rid)             -> the stored dict, or None
    replay_store.open_dir()            -> None, or an error string
"""
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DIR_NAME = "saved_replays"

#: Characters that survive a filename on Windows and read well in a dropdown.
_SAFE = re.compile(r"[^A-Za-z0-9_+-]+")


def store_dir(root=None):
    """The store directory: `app/saved_replays/` unless overridden (tests)."""
    return root or os.path.join(_HERE, DIR_NAME)


def _slug(text, fallback):
    text = _SAFE.sub("-", str(text or "")).strip("-")
    return text[:40] or fallback


def make_id(rep, taken=None):
    """A readable, unique-enough id: date, hero, placement.

    `2026-10-06_185502-Chenvaala-2nd`. `taken` is the set of ids already in
    the store; a collision gets a numeric suffix, because two games can end
    in the same second and the id is the filename.
    """
    when = str(rep.get("created") or "").replace(":", "").replace("T", "_")
    when = when if when else "undated"
    base = "-".join((when, _slug(rep.get("hero"), "run"),
                     _slug(rep.get("placement"), "na")))
    base = _SAFE.sub("-", base).strip("-")
    taken = taken or set()
    rid, n = base, 1
    while rid in taken:
        n += 1
        rid = f"{base}-{n}"
    return rid


def summary(rep, rid):
    """The dropdown row for one stored game. Pure."""
    tl = rep.get("timeline") or {}
    turns = tl.get("turns") or []
    totals = rep.get("totals") or {}
    return {
        "id": rid,
        "hero": rep.get("hero"),
        "placement": rep.get("placement"),
        "turns": len(turns) or totals.get("phases"),
        "created": rep.get("created"),
        "session": rep.get("session"),
        "log": rep.get("log"),
        "game": rep.get("game"),
    }


def save(rep, root=None):
    """Persist one review. Atomic (tmp + rename), returns {"id", "path"}."""
    d = store_dir(root)
    os.makedirs(d, exist_ok=True)
    taken = {n[:-len(".json")] for n in os.listdir(d)
             if n.endswith(".json") and not n.endswith(".tmp")}
    rid = make_id(rep, taken=taken)
    path = os.path.join(d, rid + ".json")
    body = json.dumps(summary(rep, rid) | {"rep": rep}).encode("utf-8")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, path)
    return {"id": rid, "path": path}


def load(rid, root=None):
    """One stored review, or None. `rid` never contains a separator that
    could leave the store dir: anything but the kept charset fails."""
    if not rid or _SAFE.sub("", rid) != rid or "/" in rid or "\\" in rid:
        return None
    path = os.path.join(store_dir(root), rid + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def list(root=None):
    """Every stored game, newest first. A corrupt file is skipped, not an
    error — one bad save must not take the dropdown down."""
    d = store_dir(root)
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json") or name.endswith(".tmp"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                stored = json.load(fh)
            row = {k: v for k, v in stored.items() if k != "rep"}
            row["id"] = name[:-len(".json")]
            out.append(row)
        except (OSError, ValueError):
            continue
    return out


def open_dir(root=None):
    """Open the store in the OS file browser. Best effort — returns an error
    string on failure rather than raising into the server. The dir is
    created first, so the button works on a fresh install with no saves."""
    d = store_dir(root)
    try:
        os.makedirs(d, exist_ok=True)
        if os.name == "nt":
            os.startfile(d)  # noqa: S606 - Explorer, by explicit button
        elif sys.platform == "darwin":
            subprocess.run(["open", d], check=False)
        else:
            subprocess.run(["xdg-open", d], check=False)
        return None
    except Exception as exc:  # noqa: BLE001 - the button says why, in place
        return f"{type(exc).__name__}: {exc}"
