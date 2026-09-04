#!/usr/bin/env python3
"""Redact BattleTags from a Power.log before sharing it.

A privacy scan of real session logs (2026-09-03, ~1M lines) found exactly
one category of personal data in Power.log: BattleTags — the player's and
every opponent's (~14k mentions). No IPs, emails, Windows paths, account
ids, or machine/session identifiers appear at all.

sanitize_log rewrites each BattleTag to a stable placeholder (P1, P2, ...)
so every parser still works (player names are only used as keys) while
removing the log's only personal data. Tags are never printed.

Usage:
  python sanitize_log.py <Power.log> [-o out.log]   # default: <name>.sanitized.log
"""
import argparse
import os
import re

# BattleTag: handle#discriminator, the only personal data in Power.log.
BATTLETAG = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*#\d{3,6})\b")


def sanitize_text(text):
    """Redact every BattleTag to a stable P1/P2/... placeholder.

    Returns (sanitized_text, redaction_map {placeholder: original}) — the
    map lets the LOCAL user verify what was redacted; it is not written to
    the output.
    """
    mapping = {}

    def _sub(m):
        tag = m.group(1)
        if tag not in mapping:
            mapping[tag] = f"P{len(mapping) + 1}"
        return mapping[tag]

    return BATTLETAG.sub(_sub, text), mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="path to Power.log")
    ap.add_argument("-o", "--out", help="output path "
                    "(default: <name>.sanitized.log next to the input)")
    args = ap.parse_args()
    out = args.out or re.sub(r"\.log$", "", args.log) + ".sanitized.log"
    with open(args.log, encoding="utf-8", errors="replace") as f:
        text = f.read()
    sanitized, mapping = sanitize_text(text)
    with open(out, "w", encoding="utf-8") as f:
        f.write(sanitized)
    print(f"{len(mapping)} BattleTags redacted -> {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())