#!/usr/bin/env python3
"""Redact personal data from a Power.log before sharing it.

WHAT IS PERSONAL IN A POWER.LOG (corrected 2026-10-02)
-----------------------------------------------------
The original claim here was "BattleTags are the only personal data". That
was wrong, and measuring it is what showed it. A privacy scan of two real
session logs found three separate categories:

1. BattleTags — `handle#discriminator`, ~13k mentions in one 83 MB session.
2. BARE OPPONENT HANDLES — a bare `Entity=<handle>` with no discriminator.
   In Battlegrounds the log writes most opponents this way, so a
   `handle#digits` regex never sees them. One session carried fifteen
   distinct opponent handles; the old sanitizer redacted none of them.
3. ACCOUNT IDS — `GameAccountId=[hi=... lo=...]`. The `lo` half is stable
   for a given account across every session, so it links a player's uploads
   together even after names are gone.

Non-ASCII handles were a fourth gap: the old pattern required an ASCII
letter first (`[A-Za-z][A-Za-z0-9_-]*`), so accented, Cyrillic and CJK
handles survived intact even WITH a discriminator — and accented handles
are ordinary on EU realms.

WHAT THIS DOES
--------------
Collects every name-shaped value (tags, `PlayerName=` values, bare `Entity=`
values), then rewrites each to a stable `P1, P2, ...` placeholder in a
single pass. Consistency is what keeps the corpus analysable: the same
handle always becomes the same token, in every position, so parsers that
key on player names (gold, PLAYSTATE, pool ownership) keep working and a
re-analysis of the sanitized log reaches the same conclusions.

Deliberately NOT redacted: `PlayerID`/`EntityID` numbers (seat indexes and
entity ids, not people) and the engine sentinels `GameEntity` / `UNKNOWN` /
`UNKNOWN HUMAN PLAYER`, which are not people and whose absence would be
noisier than their presence.

Verification lives in `privacy_scan.py`, which is separate code on purpose —
see its docstring.

Usage:
  python sanitize_log.py <Power.log> [-o out.log]   # default: <name>.sanitized.log
  python sanitize_log.py <Power.log> --verify       # sanitize, then re-scan
"""
import argparse
import os
import re

import privacy_scan

#: Any `handle#discriminator`. Broad on purpose: a short discriminator
#: (`Bob#17`) and a long one (`Bob#1234567`) are both real handles, and a
#: near-miss costs nothing — the only `#digits` in a Power.log is a tag.
BATTLETAG = re.compile(r"[^\s\[\]={},'\"<>|]+#\d{1,8}")
PLAYER_NAME_FIELD = re.compile(r"PlayerName=([^\r\n]+)")
BARE_ENTITY = re.compile(r"\bEntity=([^\s\[\],]+)")
ACCOUNT_ID = re.compile(r"GameAccountId=\[hi=(\d+) lo=(\d+)\]")

#: Engine slots that look like names but are not people.
SENTINELS = privacy_scan.SENTINELS


def _candidate_names(text):
    """Every person-shaped token, in order of first appearance.

    Order comes from the match position, so numbering is stable for a given
    log and needs no extra scan of the text.
    """
    found = {}

    def _note(value, pos):
        v = value.strip()
        if not v or v.isdigit() or v in SENTINELS:
            return
        if privacy_scan.PLACEHOLDER.match(v):
            return
        if v not in found:
            found[v] = pos

    for m in BATTLETAG.finditer(text):
        _note(m.group(0), m.start())
    for m in PLAYER_NAME_FIELD.finditer(text):
        _note(m.group(1), m.start())
    for m in BARE_ENTITY.finditer(text):
        _note(m.group(1), m.start())
    return [n for n, _ in sorted(found.items(), key=lambda kv: kv[1])]


def sanitize_text(text):
    """Redact every person-shaped token to a stable placeholder.

    Returns (sanitized_text, mapping {placeholder: original}). The map lets
    the LOCAL user audit what was removed; it is never written to the
    output and never uploaded.
    """
    names = _candidate_names(text)
    if not names:
        return _redact_accounts(text)[0], {}
    mapping = {}
    # Longest first so a name that contains another still matches whole.
    alternation = "|".join(re.escape(n) for n in
                           sorted(names, key=len, reverse=True))
    pattern = re.compile(r"(?<![\w])(?:" + alternation + r")(?![\w])")

    def _sub(m):
        original = m.group(0)
        if original not in mapping:
            mapping[original] = f"P{len(mapping) + 1}"
        return mapping[original]

    out = pattern.sub(_sub, text)
    out, _ = _redact_accounts(out)
    return out, mapping


def _redact_accounts(text):
    """Number the account pairs, keeping their shape for any parser that
    reads them: `[hi=... lo=...]` -> `[hi=H1 lo=A1]`, stable per account."""
    seen = {}

    def _sub(m):
        key = (m.group(1), m.group(2))
        if key not in seen:
            n = len(seen) + 1
            seen[key] = f"[hi=H{n} lo=A{n}]"
        return "GameAccountId=" + seen[key]

    return ACCOUNT_ID.sub(_sub, text), seen


def decode_log(raw):
    """Decode log bytes without mangling non-ASCII handles.

    Hearthstone writes mostly-ASCII text with occasional Windows-1252 bytes
    (`CalzónFeliz` arrives as 0xF3). The old reader used
    `utf-8, errors="replace"`, which turned those into U+FFFD — a lossy
    transcode that both corrupted the corpus and left the name legible.
    UTF-8 first, then cp1252, which is lossless for this content.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def read_log(path):
    with open(path, "rb") as f:
        return decode_log(f.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="path to Power.log")
    ap.add_argument("-o", "--out", help="output path "
                    "(default: <name>.sanitized.log next to the input)")
    ap.add_argument("--verify", action="store_true",
                    help="re-scan the output with the independent detector "
                         "and fail loudly if anything survived")
    args = ap.parse_args()
    out = args.out or re.sub(r"\.log$", "", args.log) + ".sanitized.log"
    text = read_log(args.log)
    sanitized, mapping = sanitize_text(text)
    with open(out, "w", encoding="utf-8") as f:
        f.write(sanitized)
    print(f"{len(mapping)} identities redacted -> {out}")
    if args.verify:
        findings = privacy_scan.find(sanitized)
        if findings:
            print("VERIFY FAILED — personal data survived:")
            for line in privacy_scan.describe("out", findings):
                print(line)
            return 1
        print("verify: independent re-scan found nothing (clean)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
