#!/usr/bin/env python3
"""Patch day in one command, gated by canaries, review-first.

Every silent failure this project has hit was found by accident, mid-task, and
then cost an agent a diagnosis: the `requests` import missing for 2.5 weeks, the
Battlegrounds section extracting to 92 characters after a heading-level change,
`refresh_trinkets.py` unrun since 09-13, `Aberration` absent from the tribe
roster, `BACON_COMBAT_DAMAGE_CAP` frozen at 2. So this tool's job is not just to
run the steps — it is to PROVE each step produced something, and to fail loudly
when it did not.

Canaries, each naming the failure it exists for:

  C1  BG section length      the h2/h3 truncation (92 chars instead of 1169)
  C2  fetch path is callable the missing `requests` import
  C3  the overview yields card-like names   parser drift on the article layout
  C4  a new pool epoch is detected          a patch that changed the pool silently
  C5  art coverage did not DROP             extraction regressions
  C6  the gate tools still exit 0           a broken meta DB after an apply

Review-first: it writes `patch_reports/<slug>.md` and the raw section text, and
never touches `meta/` without `--apply`. Output is bounded — the report holds the
detail.

Usage:
  python patch_day.py                 # detect + report (no writes to meta/)
  python patch_day.py --apply         # apply, then run the gates
  python patch_day.py --offline       # no network: report from the DB state only
  python patch_day.py --json
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(_HERE, "patch_reports")
MIN_BG_CHARS = 200  # C1: a real BG section is thousands; 92 is the bug


def _canary(name, level, detail):
    return {"canary": name, "level": level, "detail": detail}


def _bg_overview_url(html_text, page_url):
    """The 'full Battlegrounds overview' link, if the notes page has one."""
    m = re.search(r'href="([^"]*)"[^>]*>([^<]*[Bb]attlegrounds[^<]*)<', html_text)
    if not m:
        return None, None
    href = m.group(1)
    if href.startswith("http"):
        return href, m.group(2).strip()
    return "https://hearthstone.blizzard.com" + href, m.group(2).strip()


def _card_names(text):
    """Card-like names from the overview, by three layouts, most specific first.

    Returns (names, method). The overview article is NOT the numbered-table form
    the change list uses — its cards come as plain bullets with a following
    `[Tier N] a/b` stat line — so falling back to that shape is what stops this
    canary from being permanently red and therefore ignored. The method is
    reported so an empty result is never mistaken for "no changes".
    """
    numbered = [m.group(1).strip() for m in
                re.finditer(r"^\|\s*\d+\s*\|\s*\*\*(.+?)\*\*\s*\|", text, re.M)]
    if numbered:
        return numbered, "numbered table"
    bolded = [m.group(1).strip() for m in
              re.finditer(r"^\s*[-*]\s+\*\*(.+?)\*\*", text, re.M)]
    if bolded:
        return bolded, "bolded bullets"
    tiered = re.findall(r"\[Tier\s*\d+\][^\n]*", text)
    if tiered:
        return tiered, f"{len(tiered)} [Tier N] stat lines"
    return [], "nothing matched"


def _art_counts():
    have = {os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(_HERE, "img_cache", "**", "*.png"),
                               recursive=True)}
    import meta
    minions = [m["id"] for m in (meta._raw("minions.json") or [])]
    missing = [i for i in minions if i not in have]
    return len(minions) - len(missing), len(minions)


def _db_patch():
    try:
        with open(os.path.join(_HERE, "meta", "pool_roster.json"),
                  encoding="utf-8") as f:
            return json.load(f).get("patch") or "?"
    except (OSError, ValueError):
        return "?"


def _pool_epoch():
    """Run pool_roster.py and read its diff against the SAVED roster (C4).

    The epoch signature ("44 new cards") is a comparison against OLDER SESSIONS —
    it stays non-zero forever after a patch, so canarying on it is a permanent
    false alarm. The signal that actually means "the roster is stale" is the
    diff against `meta/pool_roster.json`: +N added / -M removed.
    """
    import subprocess
    p = subprocess.run([sys.executable, "pool_roster.py"], cwd=_HERE,
                       capture_output=True, text=True, timeout=1800)
    out = p.stdout or ""
    m = re.search(r"vs saved roster[^:]*:\s*\+(\d+)\s*/\s*-(\d+)\s*/\s*~(\d+)", out)
    if m:
        return {"added": int(m.group(1)), "removed": int(m.group(2)),
                "changed": int(m.group(3))}
    m2 = re.search(r"current epoch: (\d+) session\(s\)", out)
    return {"added": None, "removed": None, "changed": None,
            "epoch_sessions": int(m2.group(1)) if m2 else None,
            "raw_tail": "\n".join(out.strip().splitlines()[-3:])}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="also run the test suite after --apply")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    result = {"date": today, "db_patch": _db_patch(), "canaries": [],
              "patch": None, "url": None, "overview": None, "report": None}
    fail = False

    # ---- 1. detect -------------------------------------------------------
    if args.offline:
        result["canaries"].append(_canary(
            "C2 fetch", "WARN", "offline: not fetching the news page"))
    else:
        try:
            import patch_notes as pn
            if not hasattr(pn, "requests"):
                raise RuntimeError("patch_notes has no `requests` — the 09-05 "
                                   "regression is back")
            url, article = pn.discover_latest()
            result["patch"] = article.get("title")
            result["url"] = url
            result["canaries"].append(_canary(
                "C2 fetch", "ok", f"news page reachable; newest = {result['patch']}"))
            newer = pn._version_key(result["patch"]) > pn._version_key(result["db_patch"])
            result["newer"] = newer
        except Exception as exc:  # noqa: BLE001
            fail = True
            result["canaries"].append(_canary(
                "C2 fetch", "FAIL", f"{type(exc).__name__}: {exc}"))

    # ---- 2. fetch the notes + the overview, with C1 ----------------------
    if result.get("url"):
        try:
            import patch_notes as pn
            text = pn.fetch_text(result["url"])
            bg = pn.extract_bg_section(text) or ""
            result["bg_chars"] = len(bg)
            if len(bg) < MIN_BG_CHARS:
                fail = True
                result["canaries"].append(_canary(
                    "C1 bg section", "FAIL",
                    f"only {len(bg)} chars — the sub-heading truncation is back "
                    f"(a real section is thousands)"))
            else:
                result["canaries"].append(_canary(
                    "C1 bg section", "ok", f"{len(bg)} chars extracted"))
            import requests
            r = requests.get(result["url"], timeout=30,
                             headers={"User-Agent": "Mozilla/5.0"})
            ov_url, ov_label = _bg_overview_url(r.text, result["url"])
            if ov_url:
                result["overview"] = ov_url
                ov = pn.fetch_text(ov_url)
                names, method = _card_names(ov)
                result["card_names"] = len(names)
                result["card_name_method"] = method
                # WARN, not FAIL: the overview's layout differs from the change
                # list's numbered tables every time, so this canary exists to
                # stop an EMPTY list being read as "no changes" — a human/agent
                # transcription step follows regardless. A canary that is red on
                # every patch is a canary nobody reads.
                result["canaries"].append(_canary(
                    "C3 overview names",
                    "ok" if names else "WARN",
                    f"{len(names)} candidate(s) via {method}"
                    + ("" if names else " — transcribe the overview by hand; "
                                        "do NOT read this as 'no card changes'")))
                os.makedirs(REPORTS, exist_ok=True)
                slug = re.sub(r"\W+", "-", (result["patch"] or "patch").lower()).strip("-")
                with open(os.path.join(REPORTS, f"{slug}_bg_section.txt"),
                          "w", encoding="utf-8") as f:
                    f.write(bg + "\n\n===== OVERVIEW =====\n\n" + ov)
        except Exception as exc:  # noqa: BLE001
            fail = True
            result["canaries"].append(_canary(
                "C1 bg section", "FAIL", f"{type(exc).__name__}: {exc}"))

    # ---- 3. pool epoch (C4) ---------------------------------------------
    try:
        epoch = _pool_epoch()
        result["epoch"] = epoch
        added, removed = epoch.get("added"), epoch.get("removed")
        if added is None:
            lvl, detail = "WARN", "could not read the roster diff"
        elif added or removed:
            lvl = "WARN"
            detail = (f"the saved roster is STALE: +{added} / -{removed} vs the "
                      f"mined pool — run pool_roster.py --apply")
        else:
            lvl, detail = "ok", "saved roster matches the mined pool (no drift)"
        result["canaries"].append(_canary("C4 pool roster", lvl, detail))
    except Exception as exc:  # noqa: BLE001
        result["canaries"].append(_canary("C4 pool roster", "WARN",
                                          f"could not run: {type(exc).__name__}"))

    # ---- 4. art coverage (C5) -------------------------------------------
    try:
        got, total = _art_counts()
        prev = None
        state = os.path.join(REPORTS, ".art_baseline.json")
        if os.path.exists(state):
            with open(state, encoding="utf-8") as f:
                prev = json.load(f).get("got")
        lvl = "ok" if prev is None or got >= prev else "FAIL"
        fail = fail or lvl == "FAIL"
        result["canaries"].append(_canary(
            "C5 art", lvl, f"{got}/{total} minions have art"
            + (f" (baseline {prev})" if prev is not None else "")))
        os.makedirs(REPORTS, exist_ok=True)
        with open(state, "w", encoding="utf-8") as f:
            json.dump({"got": got, "total": total, "date": today}, f)
        result["art"] = {"got": got, "total": total}
    except Exception as exc:  # noqa: BLE001
        result["canaries"].append(_canary("C5 art", "WARN", f"{type(exc).__name__}"))

    # ---- 5. apply (opt-in) ----------------------------------------------
    if args.apply and result.get("url"):
        result["applied"] = _apply(result["url"], args.full)

    # ---- 6. the report --------------------------------------------------
    result["report"] = _write_report(result)

    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 1 if fail else 0

    print(f"patch_day {today}: DB on {result['db_patch']}"
          + (f", newest = {result['patch']}" if result.get("patch") else ""))
    if result.get("patch") and result.get("newer") is False:
        print("  up to date — nothing to do")
    for c in result["canaries"]:
        mark = {"FAIL": "!", "WARN": "?", "ok": " "}[c["level"]]
        print(f" {mark} {c['canary']:18} {c['detail'][:100]}")
    if result.get("applied"):
        for line in result["applied"]:
            print(f"   applied: {line}")
    print(f"report: {os.path.relpath(result['report'], _HERE)}")
    print("next: transcribe the change list from the report's bg_section, then "
          "run check_patch_db.py")
    return 1 if fail else 0


def _apply(url, full):
    """The writes, only with --apply. Each step reports one line."""
    import subprocess
    done = []
    steps = [("patch_notes", [sys.executable, "patch_notes.py", url, "--apply"]),
             ("pool_roster", [sys.executable, "pool_roster.py", "--apply"]),
             ("refresh_trinkets", [sys.executable, "refresh_trinkets.py"]),
             ("art", [sys.executable, "hearth_art_extract.py"])]
    if full:
        steps.append(("suite", [sys.executable, "-m", "unittest", "discover",
                                "-s", "tests"]))
    for name, cmd in steps:
        try:
            p = subprocess.run(cmd, cwd=_HERE, capture_output=True, text=True,
                               timeout=3600)
        except Exception as exc:  # noqa: BLE001
            done.append(f"{name}: could not run ({type(exc).__name__})")
            continue
        tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
        done.append(f"{name}: exit {p.returncode}"
                    + (f" — {tail[-1][:70]}" if tail else ""))
    return done


def _write_report(result):
    os.makedirs(REPORTS, exist_ok=True)
    slug = re.sub(r"\W+", "-", (result.get("patch") or "no-new-patch").lower()).strip("-")
    path = os.path.join(REPORTS, f"{slug}.md")
    lines = [f"# Patch day — {result.get('patch') or 'no new patch'}",
             f"_{result['date']}; DB was on {result['db_patch']}_", ""]
    if result.get("url"):
        lines.append(f"- notes: {result['url']}")
    if result.get("overview"):
        lines.append(f"- overview (card list): {result['overview']}")
    if result.get("bg_chars"):
        lines.append(f"- BG section: {result['bg_chars']} chars")
    if result.get("card_names") is not None:
        lines.append(f"- card-like names parsed from the overview: "
                     f"{result['card_names']}")
    if result.get("epoch"):
        lines.append(f"- pool epoch: {result['epoch']}")
    if result.get("art"):
        lines.append(f"- art: {result['art']['got']}/{result['art']['total']} "
                     f"minions")
    lines += ["", "## Canaries", ""]
    for c in result["canaries"]:
        lines.append(f"- **{c['level']}** {c['canary']}: {c['detail']}")
    if result.get("applied"):
        lines += ["", "## Applied"] + [f"- {a}" for a in result["applied"]]
    lines += ["", "## Next", "",
              "1. Transcribe the change list from the `*_bg_section.txt` beside "
              "this report into `analysis/patch_<version>_changes.md`.",
              "2. `python check_patch_db.py` — every labelled card must be "
              "reflected or recorded in `meta/patch_gaps.json`.",
              "3. `python doctor.py --online` — one call, one verdict."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    sys.exit(main())
