#!/usr/bin/env python3
"""Consent, and sending this session's report when a game ends.

The coach used to say "Nothing leaves your machine unless you share a
session" while providing no way to share one, and nothing was ever sent. This
module is the other half of that sentence, so the wording has to stay true:
nothing is sent until the player has been asked and has said yes, the answer
is remembered, and one click turns it off again.

What is sent is session_report's distilled advisory set — tens of KB, with a
whitelist spec deciding every field that may appear — and it is verified with
the same two checks a human would run by hand (session_report.check) before it
leaves. A report that fails either check is NOT sent, and says so loudly: a
privacy control that silently degrades is worse than none.

The local copy of everything sent stays in session_reports/, so a player can
read exactly what was shared. It is also the retry payload: a report id's content
is fixed when it is first built, because a rebuild changes `created` and the
collector refuses one id carrying two different bodies (409).

Consent lives in .share_consent.json next to the code:
  absent or share=None -> not asked yet (the overlay shows the question)
  share=true           -> send reports
  share=false          -> do not send, and do not ask again

No client identifier is sent, by design: a stable install id would link a
player's sessions to each other, which is the same linkability that makes
privacy_scan treat an account id as a finding.
"""
import datetime
import glob
import gzip
import json
import os
import sys
import urllib.error
import urllib.request

from config import HS_LOG_GLOB
import decision_log
import session_report

_HERE = os.path.dirname(os.path.abspath(__file__))
CONSENT_PATH = os.path.join(_HERE, ".share_consent.json")
REPORTS_DIR = os.path.join(_HERE, session_report.OUT_DIR_NAME)
SENT_PATH = os.path.join(REPORTS_DIR, ".sent.json")
DEFAULT_URL = ("https://hearth-telemetry-collector.bobs-ledger.workers.dev"
               "/session")
UA = "hearth-coach-telemetry/1.0"      # workers.dev 403s the python-urllib UA


def consent_path():
    return CONSENT_PATH


def load():
    """The stored choice, {} when there is none."""
    try:
        with open(CONSENT_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def status():
    """'on', 'off' or 'undecided'."""
    share = load().get("share")
    if share is True:
        return "on"
    if share is False:
        return "off"
    return "undecided"


def enabled():
    return status() == "on"


def set_choice(share):
    """Record the player's answer. Returns the new status."""
    os.makedirs(_HERE, exist_ok=True)
    with open(CONSENT_PATH, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "share": bool(share),
                   "decided": datetime.datetime.now().isoformat(
                       timespec="seconds")}, f)
    return status()


def sent_count():
    """How many reports this install has shared — the overlay shows it, so a
    player can see the feature doing what it said it would."""
    return len(_sent_ids())


def _sent_ids():
    try:
        with open(SENT_PATH, encoding="utf-8") as f:
            return set(json.load(f).get("ids") or [])
    except (OSError, ValueError):
        return set()


def _remember_sent(report_id):
    """Record a delivered report id. Never raises.

    This call sits between a successful upload and this module's promise never to
    raise, so a ledger that cannot be written must not escape into the coach — the
    report file beside it carries the same fact (2026-10-04).
    """
    ids = _sent_ids()
    ids.add(report_id)
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(SENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"ids": sorted(ids)}, f)
    except OSError as e:
        print(f"  (could not record the sent report id {report_id}: {e})",
              flush=True)


def _local_report_path(report_id):
    return os.path.join(REPORTS_DIR, f"report_{report_id}.json.gz")


def _existing_blob(path):
    """The bytes already on disk for a report id, or None.

    A report id's content is IMMUTABLE: it is built once and thereafter re-sent
    byte-for-byte. `manifest.created` is a wall-clock stamp, so rebuilding the
    same game yields different bytes, and the collector refuses one id carrying
    two bodies (409) — which is how a game the exit backstop sent at turn 5 stayed
    frozen at 14 of its eventual 128 advisories, with every later complete rebuild
    refused (measured 2026-10-04). While the local file exists it IS the payload.
    """
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _already_stored(detail):
    """True when the collector refused a re-POST of an id it already holds.

    A 409 is not a failure: this id's bytes reached the cloud on an earlier
    attempt whose response we never saw. Treating it as a failure is what made a
    single truncated report permanent — every retry rebuilt different bytes, so it
    was refused again, and the id never reached the sent ledger.
    """
    return "409" in (detail or "")


def post_report(blob, url=None, timeout=30):
    """POST one gzipped report. Returns (ok, detail)."""
    url = url or os.environ.get("HEARTH_SHARE_URL", DEFAULT_URL)
    req = urllib.request.Request(
        url, data=blob, method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.read().decode('utf-8', 'replace').strip()}"
    except Exception as e:                      # noqa: BLE001 - offline etc.
        return False, f"{type(e).__name__}: {e}"


def _consented(records):
    """Only the records written AFTER the player said yes.

    The answer is scoped to the moment it was given: a game played while the
    answer was no — or before any answer existed — is never sent, not even later.
    It used to be swept up instead: answering yes uploaded every game already in
    the decision log, which is not what "Nothing is sent unless you say yes"
    leads a player to expect, and nothing on screen disclosed it (found
    2026-10-04, reproduced). `set_choice` stamps `decided` for exactly this, and
    every record carries the `ts` it was written at in the same ISO format, so
    the comparison is two strings.

    A consent file that `set_choice` did not write has no `decided`: the moment
    of the answer is then unknown, and no record can be shown to predate it.
    """
    decided = load().get("decided")
    if not isinstance(decided, str) or not decided:
        return records
    return [r for r in records
            if isinstance(r.get("ts"), str) and r["ts"] >= decided]


def share_session(log_path, url=None, quiet=False, game=None):
    """Distil, verify and send one session. Returns a short outcome word.

    Never raises and never blocks play: the coach's job is advice, and a
    report that cannot be sent is a lost measurement, not a failure the player
    should have to deal with.

    One report id means ONE payload, for good. A re-send therefore re-POSTs the
    bytes already on disk rather than rebuilding them, and a 409 means the cloud
    already has this id — both are what keep a retry able to succeed at all.

    What it may send is scoped by the consent answer in TWO ways: nothing at all
    unless the answer is yes, and then only the games played since it was given.
    """
    if status() != "on":
        return status()
    records = session_report.decisions_for(log_path)
    # Only what was recorded after the answer. A game the player played before
    # saying yes was played under "nothing leaves your machine", and it stays
    # that way — see _consented.
    records = _consented(records)
    if game is not None:
        # Filtered HERE as well as in build(), because the two filters have to be
        # applied before the emptiness test: otherwise a game whose records are
        # all pre-answer produced an empty report and POSTED it (found by the
        # consent test, 2026-10-04).
        records = [r for r in records if r.get("game") == game]
    if not records:
        # "nothing" covers the empty log, the session where every game predates
        # the answer, and the game that was played before it: in each case there
        # is nothing this install may send, which is not a failure.
        return "nothing"
    # The session's log stem keys the random report id, so re-sharing the same
    # finished game after a crash reuses its id instead of uploading twice.
    session_key = decision_log.session_stem(log_path)
    if game is not None:
        # One report id per GAME, and stable for that game's lifetime: the
        # collector answers 409 when the same id arrives with different bytes,
        # so a re-send has to be byte-identical, and each game is its own
        # report now (2026-10-04).
        session_key = f"{session_key}#{game}"
    report = session_report.build(records, session_key=session_key, game=game)
    report_id = report["manifest"]["report_id"]
    if report_id in _sent_ids():
        return "already"

    os.makedirs(REPORTS_DIR, exist_ok=True)
    local = _local_report_path(report_id)
    blob = _existing_blob(local)
    fresh = blob is None
    if fresh:
        problems, findings = session_report.check(report)
        # Two more checks, both against the SOURCE rather than the finished
        # report, because each covers a blind spot the other two have by
        # construction: verify() can only report fields it was told about, and by
        # the time it runs an undeclared field has already been dropped on the
        # way out — so a new analysis key would vanish without a word. And
        # privacy_scan cannot see a bare display name, so what the payload gets
        # checked against is the handles this session itself showed us.
        sources = session_report.source_problems(records)
        handles = session_report.identity_findings(report, records)
        if problems or findings or sources or handles:
            # Refuse, loudly. Sending a report its own verifier rejects would
            # make the verifier decoration.
            print("  NOT SENT: this report failed verification "
                  f"({len(problems)} spec problem(s), {len(findings)} scan "
                  f"categor(y/ies), {len(sources)} unaccounted source field(s), "
                  f"{len(handles)} handle(s)). Please report this — nothing was "
                  "uploaded.")
            for label, items in (("spec", problems), ("scan", list(findings)),
                                 ("source", sources), ("handle", handles)):
                if items:
                    print(f"    {label}: {items[:5]}")
            if sources:
                print("    a source field the spec does not name is either one to "
                      "drop on purpose (DROPPED_FROM_ANALYSIS) or one to add to "
                      "SPEC; nothing is uploaded until it is one of the two.")
            return "refused"
        blob = gzip.compress(json.dumps(report).encode("utf-8"))
        with open(local, "wb") as f:
            f.write(blob)

    try:
        ok, detail = post_report(blob, url=url)
    except Exception as e:                      # noqa: BLE001 - see docstring
        # The docstring above promises this never raises, and a coach that
        # dies on its way out because a report could not be sent would be a
        # worse bug than a lost measurement. (A test written before this
        # caught the contradiction: it asserted the raise that the promise
        # said could not happen.)
        ok, detail = False, f"{type(e).__name__}: {e}"
    if not ok and _already_stored(detail):
        # The id is spent: its bytes ARE the cloud's copy, so stop rebuilding a
        # report that can never be accepted and stop re-POSTing it every run.
        _remember_sent(report_id)
        if not quiet:
            print(f"  the cloud already holds this report ({detail}); "
                  "nothing was re-sent")
        return "already"
    if not ok:
        if not quiet:
            print(f"  could not share this session ({detail}); it is kept in "
                  f"{os.path.relpath(REPORTS_DIR, _HERE)} and will not be "
                  "retried this run")
        return "failed"
    _remember_sent(report_id)
    if not quiet:
        what = (f"{report['manifest']['advisories']} advisories" if fresh
                else "the report already built for this game")
        print(f"  shared {what} ({len(blob) / 1024:.1f} KB) — {detail}")
    return "sent"


def share_games(log_path, url=None, quiet=False):
    """Share each of a session's games as its own report.

    The CLI's path, and it must be per game for the same reason the live path is:
    a session-level report keys a DIFFERENT report id (the session stem without
    `#game`), so the two schemes do not dedup against each other and the same
    advisory set can reach the collector twice under two ids. Measured
    2026-10-04: one game arrived as two byte-identical reports 31 minutes apart.
    """
    records = session_report.decisions_for(log_path)
    games = sorted({r.get("game") for r in records if r.get("game") is not None})
    if not games:
        # Nothing carries a game number (an old record shape): one report for
        # whatever is there, which cannot collide with a per-game one.
        return share_session(log_path, url=url, quiet=quiet)
    outcomes = [share_session(log_path, url=url, quiet=quiet, game=g)
                for g in games]
    for outcome in outcomes:
        if outcome not in ("already", "skipped"):
            return outcome
    return "already"


def share_latest(url=None, quiet=False):
    """Share the newest session on disk (used at startup and by the CLI)."""
    logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime, reverse=True)
    if not logs:
        return "nothing"
    return share_games(logs[0], url=url, quiet=quiet)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("status", "--status"):
        print(f"sharing session reports: {status()}")
        if status() == "undecided":
            print("  (not asked yet — the overlay asks on first run; "
                  "`share.py on|off` answers here)")
        print(f"  what is sent: {session_report.OUT_DIR_NAME}/ keeps a copy "
              "of every report shared")
        return 0
    if argv[0] in ("on", "yes", "--on"):
        print(f"sharing session reports: {set_choice(True)}")
        return 0
    if argv[0] in ("off", "no", "--off"):
        print(f"sharing session reports: {set_choice(False)}")
        return 0
    if argv[0] in ("latest", "--latest"):
        print(f"sharing session reports: {status()}")
        print(f"  outcome: {share_latest()}")
        return 0
    print("usage: share.py [status|on|off|latest]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
