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
import functools
import glob
import gzip
import hashlib
import json
import os
import re
import secrets
import sys

from config import HS_LOG_GLOB
import decision_log
import meta
import privacy_scan
import tribes

_HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = 1
OUT_DIR_NAME = "session_reports"

#: Spec markers. Everything else is a dict/list spec: a dict spec means "only
#: these keys", which is the whole point — an unlisted key is dropped on the
#: way out and reported by verify() if it ever appears.
SCALAR = "scalar"
MAP_SCALARS = "map-of-scalars"     # dict whose values are all scalars
DEEP_SCALARS = "nested-scalars"    # scalars nested in dicts/lists

#: The per-game counters the coach keeps. Named ONE BY ONE: a map that accepts
#: any key is not a whitelist, and `scenario` was `MAP_SCALARS`, so a new
#: analysis field dropped in here would have shipped without the verifier ever
#: being able to see it — verify() only reports keys it was told about. A new
#: counter now costs one line in this dict, which is this module's whole rule,
#: and source_problems() makes forgetting that line loud rather than silent.
#: Every key and type below is measured from 641 real advisories.
_SCENARIO = {
    "cast_spell": SCALAR, "cast_spell_total": SCALAR,
    "discover": SCALAR, "discover_total": SCALAR,
    "play_elemental": SCALAR, "play_elemental_total": SCALAR,
    "play_mech": SCALAR, "play_mech_total": SCALAR,
    "play_naga": SCALAR, "play_naga_total": SCALAR,
    "play_tier3_or_lower": SCALAR, "play_tier3_or_lower_total": SCALAR,
    "turns": SCALAR,
    # A LIST, and MAP_SCALARS dropped every element of it: 560 of those 641
    # advisories carry the trinkets that were offered, and not one reached a
    # report. Dropping it was the spec's doing, silently, for a whole patch.
    "trinkets": [SCALAR],
}

#: One row of the comps panel's progress list. Ten of the twelve values are
#: scalars; `evidence` is sometimes an object and `needs` is always a list, so
#: those two keep DEEP_SCALARS — scalars at any depth, and nothing else.
_COMP_PROGRESS_ROW = {
    "name": SCALAR, "tribe": SCALAR, "meta_tier": SCALAR,
    "provisional": SCALAR, "evidence": DEEP_SCALARS, "hits": SCALAR,
    "lean_hits": SCALAR, "leaning": SCALAR, "ready": SCALAR,
    "needs": DEEP_SCALARS, "trinket_fit": SCALAR, "tribe_hits": SCALAR,
}

#: A pending choice: which pick it is, where it came from, and the ranked
#: options — each of which is a list of scalars (name, card, score, why).
_CHOICE = {"kind": SCALAR, "source": SCALAR, "ranked": DEEP_SCALARS}

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
    # Derived at build time, never copied from the analysis: the effective HP
    # the NEXT advisory of the same game reports, minus this one's — i.e. what
    # the fight between them cost. None when unknown (see _hp_change).
    "hp_change": SCALAR,
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
        # WHICH CARD each hand step of the plan is about — the grading join
        # the review uses (value._top_move_text writes it while the id is
        # still in hand; labels are the keys). Shipped 747d4a8 without this
        # entry, and the verifier refused every report until it was named.
        "hand_step_cards": DEEP_SCALARS,
        "choice": _CHOICE,
        # comp targeting / progress
        "target_comp": SCALAR,
        "target_comp_label": SCALAR,
        "target_comp_provisional": SCALAR,
        "comp_progress": [_COMP_PROGRESS_ROW],
        "tribes_seen": SCALAR,
        "banned": [SCALAR],
        "scenario": _SCENARIO,
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
    "shop_offers[], shop_entities[], shop_seen[], game_comps, playable_comps, "
    "own_pool, "
    "out_of_pool, "
    "reach_sources, sell_rank, target_cards, dark_gifts, engine_recipes, "
    "lobby_opp, opp_pool, opp_trinkets, activations, baseline_opp",
)

#: Analysis keys the report knowingly does NOT carry, as a machine-readable set.
#: The prose above is for a reader; this is the one source_problems() consults,
#: so "we drop this on purpose" and "nobody has thought about this yet" are
#: different answers instead of the same silence.
#:
#: `gold`, `tier`, `health`, `turn` and `game_no` appear at BOTH levels: the
#: record's own copy is what ships (SPEC names them at the top), and the
#: analysis repeats them, so the duplicate is dropped here. Every entry was
#: measured against 641 real advisories; a key in neither set is a finding.
DROPPED_FROM_ANALYSIS = frozenset({
    "activation_step", "activations", "bans_manual", "baseline_opp", "board",
    "buy_step_card", "buy_step_roll", "buy_step_swap_veto", "buy_this",
    "comp_gap", "comps", "dark_gifts", "discard_target", "engine_recipes",
    "game_comps", "game_no", "gold", "hand", "hand_plan", "health",
    "hunt_targets", "last_opp_stats", "level_cost", "lobby_opp", "never_won",
    "opp_age", "opp_comp", "opp_pool", "opp_quiet", "opp_stats", "opp_trinkets",
    "out_of_pool", "own_pool", "playable_comps", "reach_sources", "sell_rank",
    "shop_costs", "shop_entities", "shop_offers", "shop_rank", "shop_seen",
    "target_cards",
    "target_comp_evidence", "target_state", "tier", "tribe_pressure",
    "tribe_roster", "tribes_detecting", "turn",
})

#: The envelope around the rows. Verified separately, because SPEC above
#: describes ONE advisory: checking the whole file against it reported the
#: report's own "manifest"/"advisories" keys as intruders (2026-10-03).
MANIFEST_SPEC = {
    "created": SCALAR, "report_id": SCALAR, "coach_version": SCALAR,
    "coach_versions": [SCALAR],
    "advisories": SCALAR, "games": SCALAR, "opponent_names_dropped": SCALAR,
    # The game's own final placement (2026-10-07) — the outcome the corpus
    # needs in order to compare advice against how games actually went. Named
    # here on purpose: this spec is the whitelist, and a field it does not name
    # is one nobody decided to send.
    "placement": SCALAR,
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


#: Where the per-session id map lives. A module constant so tests can point it
#: somewhere disposable.
ID_MAP_DIR = os.path.join(_HERE, OUT_DIR_NAME)


def _id_map_path():
    return os.path.join(ID_MAP_DIR, ".report_ids.json")


def _load_ids():
    try:
        with open(_id_map_path(), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def report_id_for(records, session_key=None):
    """A per-session id that links nothing and cannot be guessed.

    Two jobs, and the first version of this did neither well:

    * It must not be DERIVED from anything, because a derivable id can be
      guessed — and the collector's storage key IS this id, so a guessable one
      lets a stranger aim at a specific player's report. The old id was
      sha256(first timestamp | count | coach version), every input of which is
      either guessable or visible in a report.
    * It must be STABLE for one session, or a re-share after a crash would
      upload the same game twice under two ids. So the random id is remembered
      against `session_key` (the session's log stem) in a small local file.

    With no session_key the id is simply random: the caller is not sharing a
    session, so nothing needs to come back to it.
    """
    if not session_key:
        return secrets.token_hex(8)
    ids = _load_ids()
    if session_key in ids:
        return ids[session_key]
    new = secrets.token_hex(8)
    try:
        os.makedirs(ID_MAP_DIR, exist_ok=True)
        ids[session_key] = new
        with open(_id_map_path(), "w", encoding="utf-8") as f:
            json.dump(ids, f)
    except OSError:
        pass                    # unwritable: the id is still unique this run
    return new


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


def _eff_hp(row):
    """Effective HP as the ROW has it: health plus armor, or None.

    `health` is the record's own top-level field (the report carries it there,
    and the analysis's duplicate is dropped as an unaccounted source key);
    `armor` lives in the analysis, because that is where the coach records it.
    """
    health = row.get("health")
    if health is None:
        return None
    return health + ((row.get("analysis") or {}).get("armor") or 0)


def _hp_change(rows, i):
    """Effective HP the NEXT advisory of the SAME game reports, minus this one.

    None when there is no next row, when the next row belongs to another game
    (the report can span games for a session), or when either side has no
    health — an unknown outcome must not be recorded as 0.
    """
    if i + 1 >= len(rows):
        return None
    here, nxt = rows[i], rows[i + 1]
    if here.get("game") != nxt.get("game"):
        return None
    a, b = _eff_hp(here), _eff_hp(nxt)
    return None if a is None or b is None else b - a


def build(records, now=None, session_key=None, game=None, placement=None):
    """The report dict for one session's advisories — or for one game's.

    `game` filters to a single game, using the `game` field the decision
    records already carry. Sharing moved from per-session to per-game on
    2026-10-04, after a measured case: the player finished a game, closed
    Hearthstone, and nothing left the machine until they closed the coach
    window. Two costs to that — an abandoned session shared nothing at all if
    the console window was closed with the X button (which terminates the
    process instead of running live.py's cleanup), and every report that did go
    mixed several games together.

    Nothing about WHAT a summary contains changes here. SPEC and verify() are
    still the whole privacy story; this only decides how much of it is in one
    report.
    """
    if game is not None:
        records = [r for r in records if r.get("game") == game]
    rows = [_one(r) for r in records]
    # The OUTCOME, which is what makes the corpus able to say whether advice
    # went well rather than only what it said (2026-10-07). Both are numbers
    # about the game, so neither changes what may leave the machine:
    #
    #   * `manifest.placement` — the game's own final placement, passed in by
    #     the coach that watched it end (`LiveCoach.final_placement()`), NOT
    #     read back off the last advisory: that advisory is taken before the
    #     final fight resolves and its standing can be one the game revised
    #     (measured: 4 against a true 3). Unknown -> None, never a guess.
    #   * `hp_change` per row — the effective HP (health + armor) the NEXT
    #     advisory in the same game reports, minus this one's. That is the fight
    #     between them, which is the same quantity the review grades a plan
    #     against. The last row of a game has none, and neither has a game the
    #     player quit: the absence is the honest signal, and a 0 would read as
    #     "it cost nothing".
    for i, row in enumerate(rows):
        row["hp_change"] = _hp_change(rows, i)
    # Which build produced this advice? The FIRST record's version was the old
    # answer, and it is a lie for any game coached across an update: the report
    # rebuilt at 11:57:39 on 2026-10-04 claims 5b7e83c while 114 of its 128
    # advisories were recorded by 6bcfbcc. The corpus compares builds, so a
    # mislabeled report is a measurement error in the one field that exists to
    # prevent it. One version -> that version; several -> null, with the list
    # beside it, because there is no single honest answer.
    versions = list(dict.fromkeys(
        r.get("coach_version") for r in records if r.get("coach_version")))
    return {
        "schema": SCHEMA,
        "manifest": {
            "created": (now or datetime.datetime.now()).isoformat(
                timespec="seconds"),
            "report_id": report_id_for(records, session_key),
            "coach_version": versions[0] if len(versions) == 1 else None,
            "coach_versions": versions,
            "advisories": len(rows),
            "games": len({r.get("game") for r in rows}),
            # The game's own outcome, when the caller that watched it end knew
            # it (see build). Numbers only.
            "placement": placement,
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


def check(report):
    """(spec_problems, privacy_findings) for a report dict.

    The same two checks inspect() runs, without going through a file, so the
    sending path can refuse a report using the identical test a human would
    run by hand — rather than a lighter one that happens to be convenient.
    """
    body = json.dumps(report, ensure_ascii=False)
    return verify(report, REPORT_SPEC), privacy_scan.find(body)


def _spec_keys(spec):
    """The key set a dict spec declares, or None when it is not a dict spec."""
    return set(spec) if isinstance(spec, dict) else None


def source_problems(records):
    """Analysis fields the records carry that the spec does not account for.

    verify() walks the REPORT, and by then an undeclared field is already gone —
    project() dropped it on the way out. So the control is safe but blind: a new
    analysis field, or a new key inside one of the named maps, disappears without
    anybody being told. That is how `scenario.trinkets` went missing from 560 of
    641 real advisories for a whole patch, and how a field added to `scenario`
    would have shipped unremarked — MAP_SCALARS accepted any key it was handed,
    so the verifier was never told to look for one.

    This is the other half: what the SOURCE carries must be either named by SPEC
    or listed in DROPPED_FROM_ANALYSIS, so "we drop this deliberately" and
    "nobody has thought about this yet" stop being the same silence. The sending
    path refuses on a finding, deliberately — a report is not worth losing
    quietly, and the fix is one line in the spec.
    """
    problems = []
    top = _spec_keys(SPEC["analysis"])
    for i, record in enumerate(records):
        a = record.get("analysis") or {}
        if not isinstance(a, dict):
            problems.append(f"[{i}].analysis: not an object")
            continue
        for key in sorted(set(a) - top - DROPPED_FROM_ANALYSIS):
            problems.append(f"[{i}].analysis.{key}: not in SPEC and not "
                            "dropped on purpose")
        # One level into the named maps: a new key HERE is exactly the shape the
        # old open MAP_SCALARS let through unexamined.
        for key, spec in (("scenario", SPEC["analysis"]["scenario"]),
                          ("choice", SPEC["analysis"]["choice"])):
            declared = _spec_keys(spec)
            value = a.get(key)
            if declared and isinstance(value, dict):
                for k in sorted(set(value) - declared):
                    problems.append(f"[{i}].analysis.{key}.{k}: not in SPEC")
        declared = _spec_keys(SPEC["analysis"]["comp_progress"][0])
        progress = a.get("comp_progress")
        if declared and isinstance(progress, list):
            for row in progress:
                if isinstance(row, dict):
                    for k in sorted(set(row) - declared):
                        problems.append(
                            f"[{i}].analysis.comp_progress[].{k}: not in SPEC")
    return problems


def _game_vocabulary(report):
    """Words this payload uses as GAME terms, not as identities.

    A player is free to call themselves after a tribe or a comp — and one of the
    four handles in the real sessions on this machine is literally "Demon", which
    the payload then carries 88 times inside the banned-tribe and comp-tribe
    columns. A check that called that a leak would refuse to share for that
    player in every single game, which is worse than the leak it was guarding
    against: it would silently end their measurement. So a word the report itself
    uses as vocabulary is not evidence of anything.

    This is the coarse half of the exemption and it is read from the payload, so
    it covers the columns whose values ARE vocabulary. The precise half is
    _game_name_spans, which exempts a word only where it sits inside a name the
    game defines — that one is what keeps a card name from reading as a handle
    (the 2026-10-05 refusal).
    """
    words = {t.lower() for t in tribes.DISPLAY_TRIBES}
    for row in report.get("advisories", []):
        a = row.get("analysis") or {}
        for t in (a.get("banned") or []):
            if isinstance(t, str):
                words.add(t.lower())
        for cp in (a.get("comp_progress") or []):
            if isinstance(cp, dict):
                for key in ("tribe", "name"):
                    v = cp.get(key)
                    if isinstance(v, str):
                        words.add(v.lower())
    return words


def _game_names():
    """Every name the GAME defines that a report can print.

    Read from the same curated DBs the coach names its objects from, so the
    catalogue cannot drift from the text a report carries: every minion, tavern
    spell, trinket, hero and comp, plus the tribes. A report prints these names
    because they ARE the thing it is advising about, which makes their words
    game vocabulary — and a player is free to call themselves after one.
    """
    names = set(tribes.DISPLAY_TRIBES)
    for rows in (meta.minions(), meta.spells(), meta.trinkets(), meta.heroes()):
        for row in rows:
            name = row.get("name")
            if isinstance(name, str):
                names.add(name)
    for row in (meta.cards() or {}).values():
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            names.add(row["name"])
    for comp in meta.comps().values():
        if isinstance(comp, dict) and isinstance(comp.get("name"), str):
            names.add(comp["name"])
    # Three characters is the floor: a two-letter "name" would blanket spans over
    # prose it does not own. A missing DB contributes nothing and the rest of the
    # catalogue still works — meta.py's accessors are forgiving by design.
    return {n.strip() for n in names if len(n.strip()) >= 3}


@functools.lru_cache(maxsize=8)
def _game_name_pattern(words=()):
    """The catalogue as one case-insensitive alternation, or None when empty.

    `words` restricts it to the names that CONTAIN one of them, which is what
    keeps this cheap: a span can only explain a handle occurrence if the span's
    text contains the handle, so a name without the word in it cannot be the
    answer. The live call passes the handle words it actually matched — the
    difference between scanning 791 names over a 330 KB payload (630 ms, when
    this was written) and scanning the one or two that could matter.

    Longest first: with the names sorted by length the most specific one wins, so
    "Snazzy Phantom" is one span rather than a shorter name nested inside a
    longer one. Cached — a patch changes the catalogue, not a process.
    """
    names = _game_names()
    if words:
        wanted = tuple(w.lower() for w in words)
        names = {n for n in names if any(w in n.lower() for w in wanted)}
    if not names:
        return None
    alternation = "|".join(re.escape(n)
                           for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


def _game_name_spans(body, words=()):
    """[(start, end)] of every game-defined name the body prints.

    These are the stretches of the payload where a handle-shaped word is the
    game talking, not an identity leaking: the "Phantom" in "Snazzy Phantom" is
    there because the coach is offering that card, not because anybody is called
    that, and only a payload that prints the card can be explained this way.

    `words` are the handle words that actually matched; the catalogue is limited
    to the names that contain one of them, which cannot lose an explanation (a
    span has to contain the handle to cover it) and is what makes this cheap.
    """
    pattern = _game_name_pattern(tuple(sorted(words)))
    if pattern is None:
        return []
    return [m.span() for m in pattern.finditer(body)]


def _inside(span, spans):
    """Is `span` wholly inside one of `spans`?"""
    start, end = span
    return any(s <= start and end <= e for s, e in spans)


def identity_findings(report, records):
    """Handles this session showed us, found inside the report about to leave.

    privacy_scan cannot look for a bare Battlegrounds display name: it matches
    the shapes the log writes (`PlayerName=`, `Entity=`, `GameAccountId=`) and a
    name under a JSON key matches none of them. This check does not have to
    guess, because the session's own records say exactly which handles were in
    play — `analysis.opp_comp.name` is where every handle rides (50 in one real
    session, 93 in another). So the question becomes evidential rather than
    heuristic: does anything we are about to send contain one of the names this
    session already showed us?

    Word boundaries, not a substring: an opponent called "Ann" must not be found
    inside "Annoy-o-Module". An occurrence is then explained two ways, and both
    have to hold before the name is dropped: the payload must not use the word as
    its own vocabulary (_game_vocabulary), and the occurrence must not sit inside
    a name the GAME defines (_game_name_spans).

    That second exemption is not a nicety. It was measured on 2026-10-05: an
    opponent's display handle was a word inside an Undead minion's name, the
    payload named that minion because a discover offered it
    (`choice.ranked[2]`), and the coincidence refused the whole game's report —
    `1 handle(s)`, with the spec walk, the privacy scan and the source check all
    clean. Nothing was uploaded; that game's measurement was simply lost, for a
    word the game put there. The fix keeps the check's teeth in the direction
    that matters: an occurrence that stands on its own is still a finding.

    What remains invisible: a handle that is also a whole game name (exempt by
    the same rule the "Demon" case needed), a handle that never reached
    `opp_comp` in the first place, and — the accepted false-positive risk — a
    handle that is an ordinary word of the coach's OWN prose, which no
    catalogue can enumerate ("hold", "cost", "the rest of your hand"). A
    refusal names the handle it saw, which is how this one was found.
    source_problems() and the SPEC walk cover the other directions.
    """
    names = set()
    for record in records:
        opp = (record.get("analysis") or {}).get("opp_comp") or {}
        name = opp.get("name")
        if isinstance(name, str) and len(name.strip()) >= 3:
            names.add(name.strip())
    vocabulary = _game_vocabulary(report)
    names = {n for n in names if n.lower() not in vocabulary}
    if not names:
        return []
    body = json.dumps(report, ensure_ascii=False)
    matched = {}
    for name in names:
        hits = [m.span() for m in
                re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", body,
                            re.IGNORECASE)]
        if hits:
            matched[name] = hits
    if not matched:
        # The common case by far, and the reason the span scan is built HERE
        # rather than up front: with no occurrence to explain there is nothing
        # for the catalogue to excuse, and a report costs nothing to clear.
        return []
    spans = _game_name_spans(body, matched)
    return sorted(name for name, hits in matched.items()
                  if any(not _inside(hit, spans) for hit in hits))


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
    print(f"report: {path} ({os.path.getsize(path) / 1024:.1f} KB)")
    for k, v in report.get("manifest", {}).items():
        print(f"  {k}: {v}")
    print(f"  fields kept per advisory: {len(report['advisories'][0]) if report['advisories'] else 0}")
    print(f"  dropped on purpose: {DROPPED_ON_PURPOSE}")
    bad, found = check(report)
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
                    default=os.path.join(_HERE, OUT_DIR_NAME))
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
