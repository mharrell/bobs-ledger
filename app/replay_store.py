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
    replay_store.rid_for_game(...)     -> the id a game is already saved under
    replay_store.backfill()            -> one-time gid backfill + dedupe
    replay_store.open_dir()            -> None, or an error string
    replay_store.auto_save_enabled()   -> the "save every replay" answer
    replay_store.set_auto_save(bool)   -> persist that answer

ONE GAME, ONE FILE (2026-10-09). The first id was minted from `created`, which
is the wall clock AT BUILD — so reprocessing the same game (a restart catches
up on the leftover log and re-detects the finished game) saved the same game
again under a fresh name, every start. `game_gid` is the identity instead:
a salted hash of the pointer every rebuild already agrees on (`session` +
`log` + `game`, the same triple `settle_up.rebuild` treats as THE address of a
stored game). It never changes between reads of the same log, and it is hashed
precisely because the session-directory name can carry the player's handle —
the id must stay free of it (the same reason `privacy_scan` flags a session
dir in a shipped file). `save` refuses to mint a second file for a gid it
already holds, and the startup path consults `rid_for_game` BEFORE paying for
a rebuild at all.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DIR_NAME = "saved_replays"

#: The end-of-game card's "save every replay" answer, next to the code the
#: same way the share consent answer is (.share_consent.json): one small
#: local file, written only by the card's checkbox (2026-10-07). Per-player
#: state, so it is guarded in the usual three places — .gitignore,
#: publish_release.EXCLUDE_FILES, update.PROTECTED: a release must neither
#: carry it nor overwrite it, and an update must not silently re-ask.
AUTO_PATH = os.path.join(_HERE, ".save_all_replays.json")

#: Characters that survive a filename on Windows and read well in a dropdown.
_SAFE = re.compile(r"[^A-Za-z0-9_+-]+")

#: Fixed domain salt for `game_gid`. Not a secret — its job is to make the
#: hash a one-way commitment rather than a decoding exercise, so a stored id
#: cannot be walked back to a session-directory name.
_GID_SALT = "bobs-ledger-game-v1"


def game_gid(session, log, game):
    """The stable identity of one game, or None when there is nothing to key.

    The pointer triple `settle_up.build` records (session dir, log basename,
    game index) — exactly what `settle_up.rebuild` resolves a stored game
    from, so every path that can re-read a game computes the same id for it.
    The readable id stays the display name; this is the join key.
    """
    if not session or not log or not game:
        return None
    raw = f"{_GID_SALT}\0{session}\0{log}\0{int(game)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


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
    """The dropdown row for one stored game. Pure.

    `gid` rides at the top level (outside `rep`) so the dedupe lookup and the
    backfill can read it without parsing the whole review apart."""
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
        "gid": rep.get("gid"),
    }


def save(rep, root=None, rid=None):
    """Persist one review. Atomic (tmp + rename), returns {"id", "path"}.

    `rid` re-saves under a KNOWN id — the rebuild path (settle_up.rebuild)
    updates a game in place instead of stacking a -2 suffixed copy beside
    it. The id still passes through the charset guard via the write below.

    A rep carrying a `gid` that is already in the store lands on THAT file
    (same game, same file — a reprocessed game overwrites itself instead of
    saving a copy), which is what makes a restart with a leftover log save
    nothing. A rep without one keeps the old behaviour, suffix included.
    """
    d = store_dir(root)
    os.makedirs(d, exist_ok=True)
    if rid is None and rep.get("gid"):
        rid = rid_for_gid(rep["gid"], root=root)
    if rid is not None:
        taken = {rid}
    else:
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


def rid_for_gid(gid, root=None):
    """The id `gid` is already saved under, or None. A corrupt file that
    cannot answer is skipped — the store's own rule for every reader."""
    if not gid:
        return None
    for row in list(root=root):
        if row.get("gid") == gid:
            return row.get("id")
    return None


def rid_for_game(session, log, game, root=None):
    """The id a game is already saved under, or None.

    This is the startup path's cheap question — asked BEFORE a rebuild is
    paid for, from the same pointer the saved rep carries. `game_gid` does
    the naming so a caller cannot pass a different-shaped key by mistake."""
    return rid_for_gid(game_gid(session, log, game), root=root)


def backfill(root=None):
    """Give every stored game its gid, and keep ONE file per game.

    The one-time migration for stores written before `game_gid` existed —
    every one of those files carries the pointer in its summary, so the id
    is computable from the file alone and no log is needed (Hearthstone
    rotates session logs away; a migration that required them would quietly
    never run). Idempotent by nature: a store that already carries gids and
    holds no duplicates is a pass that writes nothing, so this can run at
    every startup without a marker file.

    Within a group of duplicates the NEWEST `created` survives — a later
    build is a later pipeline's read of the same game — and the others are
    deleted, which is what "group existing replays by game id and keep one"
    means on disk. Returns what it did, for the console line.
    """
    d = store_dir(root)
    try:
        names = [n for n in os.listdir(d)
                 if n.endswith(".json") and not n.endswith(".tmp")]
    except OSError:
        return {"backfilled": 0, "removed": []}
    groups = {}
    backfilled = 0
    for name in names:
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                body = json.load(fh)
        except (OSError, ValueError):
            continue
        gid = body.get("gid")
        if not gid:
            gid = game_gid(body.get("session"), body.get("log"),
                           body.get("game"))
            if not gid:
                continue        # no pointer, no identity — left as it is
            body["gid"] = gid
            # Rewrite through the same atomic shape save() uses, so an
            # interrupted backfill cannot leave a half-written file behind.
            tmp = os.path.join(d, name + ".tmp")
            try:
                with open(tmp, "wb") as fh:
                    fh.write(json.dumps(body).encode("utf-8"))
                os.replace(tmp, os.path.join(d, name))
            except OSError:
                continue
            backfilled += 1
        row = groups.setdefault(gid, [])
        row.append((body.get("created") or "", name[:-len(".json")]))
    removed = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(reverse=True)         # newest created first
        for _created, rid in rows[1:]:
            try:
                os.remove(os.path.join(d, rid + ".json"))
                removed.append(rid)
            except OSError:
                pass
    return {"backfilled": backfilled, "removed": removed}


def auto_save_enabled():
    """The stored answer to "save every replay?", defaulting to NO.

    A missing or unreadable file is OFF, not an error — the checkbox must
    never be the thing that breaks a game's end. Tests patch AUTO_PATH the
    way the share tests patch share.CONSENT_PATH.
    """
    try:
        with open(AUTO_PATH, encoding="utf-8") as f:
            return bool((json.load(f) or {}).get("save_all"))
    except (OSError, ValueError):
        return False


def set_auto_save(enabled):
    """Persist the answer. Atomic (tmp + rename), like save()."""
    body = json.dumps(
        {"schema": 1, "save_all": bool(enabled),
         "answered": datetime.datetime.now().isoformat(timespec="seconds")},
    ).encode("utf-8")
    tmp = AUTO_PATH + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, AUTO_PATH)


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
