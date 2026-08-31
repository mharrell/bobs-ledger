"""Scheduled patch-notes check for the local meta DB (review-first).

Detects the latest official Hearthstone patch, extracts the Battlegrounds
changes, and writes a reviewable report to patch_reports/ — it does NOT edit
the meta DB. A human reviews the report and applies it with
`patch_notes.py <url> --apply`. This is the "set and forget" entry point meant
to run from Windows Task Scheduler (see register_patch_check.ps1).

State (the last-seen patch) is kept in meta/.patch_state.json so a given patch
is only reported once.

Usage:
    python check_patch_notes.py [--url <url>] [--apply] [--no-notify]

    --url       check a specific patch-notes URL (default: discover the latest)
    --apply     also write matched changes into meta/ (NOT used by the scheduled
                task; review-first means the task only writes a report)
    --no-notify suppress the Windows toast notification

The DeepSeek key is read from DEEPSEEK_API_KEY, falling back to
meta/.patch_config.json {"api_key": "..."}. Without a key, the report still
captures the Battlegrounds section for manual review.
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import re
import subprocess
import sys

import patch_notes as pn

_HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(pn.META, ".patch_state.json")
CONFIG_FILE = os.path.join(pn.META, ".patch_config.json")
REPORT_DIR = os.path.join(_HERE, "patch_reports")


# ---------------------------------------------------------------------------
# State + config
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(pn.META, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f).get("api_key")
    return None


# ---------------------------------------------------------------------------
# Report + notification
# ---------------------------------------------------------------------------

def format_report(report, do_apply):
    """Render pn.print_report's output as a string (reuses its formatting)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pn.print_report(report, do_apply)
    return buf.getvalue()


def write_report(slug, title, bg_text, changes_text):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{slug}.md")
    lines = [f"# {title}", "", "## Battlegrounds section", "", bg_text, ""]
    if changes_text:
        lines += ["## Detected changes (dry-run — review before applying)", "",
                  changes_text]
    else:
        lines += ["## No card/hero data changes detected (bug fixes only, or "
                  "none).", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def notify(title, text):
    """Best-effort Windows toast via WinForms NotifyIcon (no extra modules)."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.BalloonTipTitle='{0}';"
        "$n.BalloonTipText='{1}';"
        "$n.Visible=$true;"
        "$n.ShowBalloonTip(10000);"
        "Start-Sleep -Seconds 1;"
        "$n.Dispose();"
    ).format(title.replace("'", "''"), text.replace("'", "''"))
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       timeout=15, check=False)
    except Exception:
        pass  # notification is best-effort


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=None,
                    help="patch-notes URL (default: discover the latest)")
    ap.add_argument("--apply", action="store_true",
                    help="also write matched changes into meta/ (review-first "
                         "default is report-only)")
    ap.add_argument("--no-notify", action="store_true",
                    help="suppress the Windows toast notification")
    args = ap.parse_args(argv)

    if args.url:
        url = args.url
        m = re.search(r"/news/(\d+)/", url)
        article = {"id": int(m.group(1)) if m else 0,
                   "title": url, "slug": url.rstrip("/").rsplit("/", 1)[-1]}
    else:
        url, article = pn.discover_latest()

    state = load_state()
    if state.get("last_id") == article["id"]:
        print(f"No new patch since {state.get('last_title', '?')} "
              f"(id {article['id']}). Nothing to do.")
        return 0

    print(f"New patch detected: {article.get('title', '?')} "
          f"(id {article['id']})")
    text = pn.fetch_text(url)
    bg = pn.extract_bg_section(text)
    if bg is None:
        print("No Battlegrounds section found; nothing to do.")
        return 0

    changes_text = None
    key = get_api_key()
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key
        try:
            changes = pn.extract_changes(bg)
            if changes:
                report = pn.apply_changes(changes, do_apply=args.apply)
                changes_text = format_report(report, args.apply)
        except Exception as e:  # noqa: BLE001 — report the failure, keep going
            changes_text = f"(LLM extraction failed: {e})"
    else:
        changes_text = ("(No DEEPSEEK_API_KEY set — LLM extraction skipped. "
                        "Review the Battlegrounds section manually.)")

    path = write_report(article["slug"], article.get("title", "patch"),
                        bg, changes_text)
    state.update({
        "last_id": article["id"],
        "last_title": article.get("title"),
        "last_checked": datetime.date.today().isoformat(),
    })
    save_state(state)

    print(f"Report written to {path}")
    if not args.no_notify:
        notify("Hearthstone patch check",
               f"New patch: {article.get('title', '?')}. Review {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
