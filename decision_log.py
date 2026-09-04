"""Decision log: what the coach advised, at each decision point.

The beta corpus pairs every Power.log with a record of the advice the
player actually saw, so follow-rate can be compared against placement and
advice compared across coach versions. (Advice is derivable from the log —
but only under the exact coach version that produced it; re-deriving with
newer code would silently rewrite history.)

One JSONL line per advisory:
  {schema, ts, coach_version, log, offset, game, turn, gold, tier, health,
   armor, fingerprint, analysis {...}}

Join keys with the Power.log: the session-log basename + the byte offset in
it at advisory time. Contains no personal data (card ids and minion names
only — BattleTags never reach the analysis), so unlike the Power.log it
needs no sanitizing.
"""
import datetime
import json
import os
import subprocess

SCHEMA = 1
_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "decision_logs")
_coach_version = None


def coach_version():
    """The running code's git commit — the advice/replay version join."""
    global _coach_version
    if _coach_version is None:
        try:
            _coach_version = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_HERE, capture_output=True, text=True,
                timeout=5).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001 - never break advising over telemetry
            _coach_version = "unknown"
    return _coach_version


def record(analysis, log_path=None, log_offset=None, game_no=None):
    """Append one advisory to decision_logs/decision_<session>.jsonl.

    Never raises: telemetry must not kill the advise loop.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        base = os.path.basename(log_path or "unknown")
        path = os.path.join(LOG_DIR, f"decision_{base}.jsonl")
        entry = {
            "schema": SCHEMA,
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "coach_version": coach_version(),
            "log": base,
            "offset": log_offset,
            "game": game_no,
            "turn": (analysis.get("scenario") or {}).get("turns"),
            "gold": analysis.get("gold"),
            "tier": analysis.get("tier"),
            "health": analysis.get("health"),
            "fingerprint": None,  # filled by the caller when it has one
            "analysis": analysis,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass