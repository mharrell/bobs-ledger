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
read exactly what was shared.

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


def _sent_ids():
    try:
        with open(SENT_PATH, encoding="utf-8") as f:
            return set(json.load(f).get("ids") or [])
    except (OSError, ValueError):
        return set()


def _remember_sent(report_id):
    ids = _sent_ids()
    ids.add(report_id)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(SENT_PATH, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(ids)}, f)


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


def share_session(log_path, url=None, quiet=False):
    """Distil, verify and send one session. Returns a short outcome word.

    Never raises and never blocks play: the coach's job is advice, and a
    report that cannot be sent is a lost measurement, not a failure the player
    should have to deal with.
    """
    if status() != "on":
        return status()
    records = session_report.decisions_for(log_path)
    if not records:
        return "nothing"
    report = session_report.build(records)
    report_id = report["manifest"]["report_id"]
    if report_id in _sent_ids():
        return "already"

    problems, findings = session_report.check(report)
    if problems or findings:
        # Refuse, loudly. Sending a report its own verifier rejects would
        # make the verifier decoration.
        print("  NOT SENT: this report failed verification "
              f"({len(problems)} spec problem(s), {len(findings)} finding(s)). "
              "Please report this — nothing was uploaded.")
        if problems:
            print(f"    spec: {problems[:5]}")
        if findings:
            print(f"    scan: {list(findings)[:5]}")
        return "refused"

    blob = gzip.compress(json.dumps(report).encode("utf-8"))
    os.makedirs(REPORTS_DIR, exist_ok=True)
    local = os.path.join(REPORTS_DIR, f"report_{report_id}.json.gz")
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
    if not ok:
        if not quiet:
            print(f"  could not share this session ({detail}); it is kept in "
                  f"{os.path.relpath(REPORTS_DIR, _HERE)} and will not be "
                  "retried this run")
        return "failed"
    _remember_sent(report_id)
    if not quiet:
        print(f"  shared {len(records)} advisories "
              f"({len(blob) / 1024:.1f} KB) — {detail}")
    return "sent"


def share_latest(url=None, quiet=False):
    """Share the newest session on disk (used at startup and by the CLI)."""
    logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime, reverse=True)
    if not logs:
        return "nothing"
    return share_session(logs[0], url=url, quiet=quiet)


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
