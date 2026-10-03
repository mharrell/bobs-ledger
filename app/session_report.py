#!/usr/bin/env python3
"""Distil one session's decision log into a small, safe report for upload.

WHY THIS EXISTS

The full decision log is 7.5 MB for one session (154 advisories x ~48 KB):
`game_comps` alone is 38 KB per record and `playable_comps` 15 KB, because
every advisory stores the whole comp tree. Uploading that barely beats
shipping the raw log. What answers the coach's open question — does the advice
help? — is much smaller: per advisory, the state, the call, and what happened
next. That is what this module keeps, and it is tens of KB per session.

THE LEAK THIS IS BUILT AROUND

`analysis.opp_comp.name` is the opponent's DISPLAY HANDLE — the field the
overlay renders as "Hero · Odin3539". It sits in every logged advisory, and
`privacy_scan` does NOT flag it: the scanner looks for the shapes the log
writes (`PlayerName=`, `Entity=`, `GameAccountId=`), and a name inside a JSON
key called "name" matches none of them. So a bundle built from raw decisions
passes "verified clean by an independent scan" while carrying a real person's
handle (found 2026-10-03 while designing the automatic upload path).

The fix is structural rather than a regex: this module can only emit fields
it names explicitly, so a new analysis field — however personal — cannot
appear in a report by accident. `verify()` re-walks the finished report
against the same spec and reports any field that is not in it, which is what
makes "nothing personal is in here" a measurement instead of a promise.

Usage:
  python session_report.py --latest            # newest session -> session_reports/
  python session_report.py --inspect FILE      # verify a report before sending
"""
import argparse
import datetime
import glob
import gzip
import hashlib
import json
import os
import sys

from config import HS_LOG_GLOB
import decision_log
import privacy_scan

SCHEMA = 1
OUT_DIR_NAME = "session_reports"

#: Spec markers. Everything else is a dict/list spec: a dict spec means "only
#: these keys", which is the whole point — an unlisted key is dropped on the
#: way out and reported by verify() if it ever appears.
SCALAR = "scalar"
MAP_SCALARS = "map-of-scalars"     # dict whose values are all scalars
DEEP_SCALARS = "nested-scalars"    # scalars nested in dicts/lists

#: The whole report shape. Read it as the answer to "what may leave the
#: machine": numbers about the game, the advice the coach gave, and the
#: opponent's HERO (a game character). Not the opponent's name, not a path,
#: not a session directory, not the player's identity, and nothing that links
#: one session to another.
SPEC = {
    "schema": SCALAR,
    "report_id": SCALAR,
    "ts": SCALAR,
    "coach_version": SCALAR,
    "game": SCALAR,
    "turn": SCALAR,
    "gold": SCALAR,
    "tier": SCALAR,
    "health": SCALAR,
    "analysis": {
        # state and danger
        "armor": SCALAR,
        "current_place": SCALAR,
        "damage_cap": SCALAR,
        "damage_last": SCALAR,
        "damage_recent3": SCALAR,
        "loss_streak": SCALAR,
        "close_losses": SCALAR,
        "fragility": {"band": SCALAR, "eff_health": SCALAR, "health": SCALAR,
                      "armor": SCALAR, "last_hit": SCALAR, "recent3": SCALAR,
                      "cap": SCALAR, "note": SCALAR},
        "forecast": SCALAR,
        "situation": SCALAR,
        "hero": SCALAR,
        "hero_power": SCALAR,
        # the board, summarised: a count and a stat total, not the minion list
        "board_stats": SCALAR,
        "board_count": SCALAR,
        # what was advised
        "top_move": SCALAR,
        "top_move_steps": [{"text": SCALAR, "kind": SCALAR, "card": SCALAR,
                            "action": SCALAR, "tag": SCALAR,
                            "reason": SCALAR}],
        "choice": DEEP_SCALARS,
        # comp targeting / progress
        "target_comp": SCALAR,
        "target_comp_label": SCALAR,
        "target_comp_provisional": SCALAR,
        "comp_progress": DEEP_SCALARS,
        "tribes_seen": SCALAR,
        "banned": [SCALAR],
        # turn counters (cast_spell_total, play_naga, ...): all small ints
        "scenario": MAP_SCALARS,
        # the announced opponent: hero and board only. Never "name". Shapes
        # taken from a real session's payload (`cards` is {card_id: count}).
        "opponent": {"hero_name": SCALAR, "hero": SCALAR, "turn": SCALAR,
                     "cards": MAP_SCALARS, "goldens": [SCALAR]},
    },
}

#: Fields the spec deliberately does NOT include, so a reader can tell the
#: difference between "forgotten" and "dropped on purpose".
DROPPED_ON_PURPOSE = (
    "opp_comp.name (the opponent's handle), log (session directory name), "
    "offset, fingerprint, board[], hand[], hand_plan[], shop_rank[], "
    "shop_seen[], game_comps, playable_comps, own_pool, out_of_pool, "
    "reach_sources, sell_rank, target_cards, dark_gifts, engine_recipes, "
    "lobby_opp, opp_pool, opp_trinkets, activations, baseline_opp",
)

#: The envelope around the rows. Verified separately, because SPEC above
#: describes ONE advisory: checking the whole file against it reported the
#: report's own "manifest"/"advisories" keys as intruders (2026-10-03).
MANIFEST_SPEC = {
    "created": SCALAR, "report_id": SCALAR, "coach_version": SCALAR,
    "advisories": SCALAR, "games": SCALAR, "opponent_names_dropped": SCALAR,
}
REPORT_SPEC = {"schema": SCALAR, "manifest": MANIFEST_SPEC,
               "advisories": [SPEC]}


def _is_scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


#: Returned when a value cannot satisfy its spec. Such a key is OMITTED
#: rather than written as null: a null where the spec declares a list is a
#: shape violation, and "we do not have it" is better said by absence. (The
#: first run of this module emitted `opponent.cards: null` and the verifier
#: called it out — correctly.)
OMIT = object()


def project(value, spec):
    """Copy only what the spec names. Anything else is left behind."""
    if spec is SCALAR:
        return value if _is_scalar(value) else OMIT
    if spec is MAP_SCALARS:
        if not isinstance(value, dict):
            return OMIT
        return {k: v for k, v in value.items() if _is_scalar(v)}
    if spec is DEEP_SCALARS:
        if _is_scalar(value):
            return value
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                got = project(v, DEEP_SCALARS)
                if got is not OMIT:      # OMIT must never reach the output
                    out[k] = got
            return out
        if isinstance(value, list):
            out = []
            for v in value:
                got = project(v, DEEP_SCALARS)
                if got is not OMIT:
                    out.append(got)
            return out
        return OMIT
    if isinstance(spec, list):
        if not isinstance(value, list):
            return OMIT
        out = []
        for v in value:
            got = project(v, spec[0])
            if got is not OMIT:          # an item that cannot match is dropped
                out.append(got)
        return out
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return OMIT
        out = {}
        for key, sub in spec.items():
            if key not in value:
                continue
            got = project(value[key], sub)
            if got is not OMIT:
                out[key] = got
        return out
    return OMIT


def verify(report, spec=SPEC, path=""):
    """Every field of a report that the spec does not declare.

    The whitelist IS the privacy control, so it needs its own check: a report
    that gained a field (a new analysis key carrying something personal, a
    merge gone wrong) shows up here instead of being uploaded.
    """
    problems = []
    if spec is SCALAR:
        if not _is_scalar(report):
            problems.append(f"{path or '<root>'}: not a scalar")
        return problems
    if spec is MAP_SCALARS:
        if not isinstance(report, dict):
            problems.append(f"{path or '<root>'}: not an object")
            return problems
        for k, v in report.items():
            if not _is_scalar(v):
                problems.append(f"{path}.{k}: not a scalar")
        return problems
    if spec is DEEP_SCALARS:
        if _is_scalar(report):
            return problems
        if isinstance(report, dict):
            for k, v in report.items():
                problems += verify(v, DEEP_SCALARS, f"{path}.{k}")
        elif isinstance(report, list):
            for i, v in enumerate(report):
                problems += verify(v, DEEP_SCALARS, f"{path}[{i}]")
        else:
            problems.append(f"{path or '<root>'}: unusable value")
        return problems
    if isinstance(spec, list):
        if not isinstance(report, list):
            problems.append(f"{path or '<root>'}: not a list")
            return problems
        for i, v in enumerate(report):
            problems += verify(v, spec[0], f"{path}[{i}]")
        return problems
    if isinstance(spec, dict):
        if not isinstance(report, dict):
            problems.append(f"{path or '<root>'}: not an object")
            return problems
        for k, v in report.items():
            if k not in spec:
                problems.append(f"{path}.{k}" if path else k)
                continue
            problems += verify(v, spec[k], f"{path}.{k}" if path else k)
        return problems
    return problems


def report_id_for(records):
    """A per-session id that links nothing.

    Used only so a retried upload of the SAME report can be recognised.
    Deliberately derived from the advisory timestamps and count rather than
    from the log path or filename: a session directory or an account id links
    a player's sessions together, which is exactly what privacy_scan calls a
    finding.
    """
    first = str(records[0].get("ts", "")) if records else ""
    blob = f"{first}|{len(records)}|{records[0].get('coach_version', '') if records else ''}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _one(record):
    """One advisory as a compact report row."""
    a = record.get("analysis") or {}
    row = project({**record, "analysis": a}, SPEC)
    row.pop("report_id", None)          # the manifest carries it
    row.setdefault("analysis", {})
    # board_count is derived, not copied: the spec keeps the summary, never
    # the minion list.
    board = a.get("board")
    row["analysis"]["board_count"] = (
        len(board) if isinstance(board, list) else None)
    # opp_comp -> opponent by EXPLICIT key selection. hero_name is a game
    # character and is worth keeping; "name" is a person and is never named
    # here, which is what stops the handle travelling — not a filter that
    # could be forgotten, but the absence of the key.
    oc = a.get("opp_comp")
    if isinstance(oc, dict) and oc:
        row["analysis"]["opponent"] = project(
            {k: oc.get(k) for k in ("hero_name", "turn", "cards", "stats")},
            SPEC["analysis"]["opponent"])
    return row


def build(records, now=None):
    """The report dict for one session's advisories."""
    rows = [_one(r) for r in records]
    return {
        "schema": SCHEMA,
        "manifest": {
            "created": (now or datetime.datetime.now()).isoformat(
                timespec="seconds"),
            "report_id": report_id_for(records),
            "coach_version": (records[0].get("coach_version")
                              if records else None),
            "advisories": len(rows),
            "games": len({r.get("game") for r in rows}),
            # Counted from the SOURCE, not the output: the point of the
            # number is how many handles were left behind.
            "opponent_names_dropped": sum(
                1 for r in records
                if ((r.get("analysis") or {}).get("opp_comp") or {}).get("name")),
        },
        "advisories": rows,
    }


def decisions_for(log_path):
    """The advisories for one session — the same source package_corpus uses."""
    path = os.path.join(decision_log.LOG_DIR,
                        f"decision_{decision_log.session_stem(log_path)}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        out = []
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out


def write(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stamp = report["manifest"]["created"].replace(":", "").replace("-", "")[:12]
    path = os.path.join(out_dir, f"report_{stamp}.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(report, f)
    return path


def inspect(path):
    """Is this report safe to send, and does it match the spec?

    Returns 0 when it is, 1 when it is not. The two checks are independent:
    the spec walk proves no undeclared field got in, and privacy_scan proves
    no known-personal shape is in the text.
    """
    if not os.path.exists(path):
        print(f"no such report: {path}")
        return 1
    with gzip.open(path, "rt", encoding="utf-8") as f:
        report = json.load(f)
    body = json.dumps(report, ensure_ascii=False)
    print(f"report: {path} ({os.path.getsize(path) / 1024:.1f} KB)")
    for k, v in report.get("manifest", {}).items():
        print(f"  {k}: {v}")
    print(f"  fields kept per advisory: {len(report['advisories'][0]) if report['advisories'] else 0}")
    print(f"  dropped on purpose: {DROPPED_ON_PURPOSE}")
    bad = verify(report, REPORT_SPEC)
    found = privacy_scan.find(body)
    for line in privacy_scan.describe("report", found):
        print(line)
    if bad:
        print("\n  FAIL — fields not in the spec (something new got in):")
        for b in bad[:10]:
            print(f"    {b}")
        return 1
    if found:
        print("\n  FAIL — personal-data patterns survived.")
        return 1
    print("\n  OK: every field is one the spec declares, and an independent "
          "scan finds no BattleTag, handle, account id, path or session name.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", help="session Power.log")
    ap.add_argument("--latest", action="store_true",
                    help="use the newest session log")
    ap.add_argument("-o", "--out",
                    default=os.path.join(decision_log._HERE, OUT_DIR_NAME))
    ap.add_argument("--inspect", metavar="REPORT",
                    help="verify a report against the spec before sending")
    args = ap.parse_args()
    if args.inspect:
        return inspect(args.inspect)
    path = args.log
    if not path or args.latest:
        logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime,
                      reverse=True)
        if not logs:
            print("no session log found")
            return 1
        path = logs[0]
    records = decisions_for(path)
    if not records:
        print(f"no advisories logged for {os.path.basename(path)}")
        return 1
    report = build(records)
    out = write(report, args.out)
    raw = sum(len(json.dumps(r, default=str)) for r in records)
    print(f"report: {out}")
    print(f"  {report['manifest']['advisories']} advisories from "
          f"{raw / 1e6:.1f} MB of decision log -> "
          f"{os.path.getsize(out) / 1024:.1f} KB")
    return inspect(out)


if __name__ == "__main__":
    sys.exit(main())
