"""The maintainer's inbox: fetch, verify and index what players shared.

Two kinds of artifact arrive at the collector and they are NOT the same trade:

* a **session report** (`sessions/<date>/<id>.json.gz`, ~16 KB) — the distilled
  advisories, consented on the welcome card, no names by construction. This is
  what `fetch_sessions.py` already pulls; this tool adds the missing half: every
  file is run through `session_report.REPORT_SPEC` before it is indexed, and the
  ones a current build would refuse are named instead of sitting in the folder
  looking like data.
* a **corpus bundle** (`corpus/corpus_<stamp>.json.gz`, 1-2 MB) — the sanitized
  Power.log plus that session's decision log. Rare, uploaded on purpose with
  `upload_corpus.py --latest`. The collector has no listing route for these, so
  they come down through `wrangler` (the same authority the CLI uses), are
  re-scanned with `privacy_scan` (independent of the sanitizer), and are then
  unpacked so the log can be pointed at with `replay_review.py`.

Both paths write OUTSIDE this repository by default and only into `--out`, which
is required: what comes back is other people's data, and `publish_release` walks
the working tree.

    python report_corpus.py --out ~/bl-inbox --collect      # reports + index
    python report_corpus.py --out ~/bl-inbox --corpus       # corpus bundles
    python report_corpus.py --out ~/bl-inbox --tables       # what the inbox says

`--tables` is the processing half of the request it was built for ("how can we
process these for improving the coaching"): the three measurements the reports
CAN support — fight cost by fragility band, plan composition, comp commitment
against placement — each grouped by `coach_version` so a change can be read
against its predecessor. The one thing they cannot do is grade a card choice:
the shop list and the alternatives' scores are dropped on purpose.

Maintainer tool. It needs no key of its own: reports use
`HEARTH_TELEMETRY_KEY` exactly as `fetch_sessions.py` does, and corpus bundles
use whatever login `wrangler` already has.
"""
import argparse
import base64
import binascii
import collections
import gzip
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import fetch_sessions  # noqa: E402
import package_corpus  # noqa: E402
import privacy_scan  # noqa: E402
import session_report  # noqa: E402

INDEX = ".index.json"
KV_NAMESPACE = "abd7803c581b4470a2834e92ae0006a2"


# ---------------------------------------------------------------- reports

def _report_files(out):
    """Every stored report, `(relpath, bytes)` — the folder IS the index of
    files, so a half-finished download is caught by the parse below."""
    found = []
    for base, _dirs, names in os.walk(out):
        for name in names:
            if not name.endswith(".json.gz"):
                continue
            path = os.path.join(base, name)
            found.append((os.path.relpath(path, out), path))
    return sorted(found)


def load_reports(out):
    """(reports, problems): the decodable, SPEC-valid reports and what failed.

    A report that does not decode is a download that died; a report with SPEC
    problems is one an older build sent before the shape changed. Both are data
    about the pipeline, so both are returned rather than skipped silently.
    """
    good, bad = [], []
    for rel, path in _report_files(out):
        try:
            with gzip.open(path, "rb") as f:
                data = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, EOFError) as exc:
            bad.append((rel, f"not a gz json: {exc}"))
            continue
        problems = session_report.verify(data, session_report.REPORT_SPEC)
        if problems:
            bad.append((rel, problems[0]))
            continue
        good.append((rel, data))
    return good, bad


def collect_reports(out, url=None, key=None, force=False):
    """Download what is missing, then verify + index everything on disk."""
    base = (url or os.environ.get("HEARTH_TELEMETRY_URL")
            or fetch_sessions.DEFAULT_URL)
    key = key or os.environ.get("HEARTH_TELEMETRY_KEY")
    if not key:
        raise SystemExit("no key: set HEARTH_TELEMETRY_KEY (reading is keyed; "
                         "sending is not)")
    os.makedirs(out, exist_ok=True)
    downloaded, skipped = fetch_sessions.fetch(base, key, out, force=force)
    return downloaded, skipped


def build_index(out):
    """`(index dict, problems)` — one row per report, written to `--out`.

    The index is derived data: deleting it costs a re-scan, never a report.
    """
    good, bad = load_reports(out)
    rows = []
    for rel, rep in good:
        m = rep.get("manifest") or {}
        rows.append({
            "file": rel,
            "report_id": m.get("report_id"),
            "created": m.get("created"),
            "coach_version": m.get("coach_version"),
            "games": m.get("games"),
            "placement": m.get("placement"),
            "advisories": m.get("advisories"),
        })
    corpus = _corpus_rows(out)
    index = {
        "reports": rows,
        "corpus": corpus,
        "refused": [{"file": rel, "why": why} for rel, why in bad],
    }
    with open(os.path.join(out, INDEX), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")
    return index, bad


def _corpus_rows(out):
    rows = []
    root = os.path.join(out, "corpus")
    for base, _dirs, names in os.walk(root):
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8") as f:
                    bundle = json.load(f)
                m = bundle["manifest"]
            except (OSError, ValueError, KeyError):
                continue
            rows.append({
                "file": os.path.relpath(path, out),
                "created": m.get("created"),
                "coach_version": m.get("coach_version"),
                # `log_sha256`/`decision_count` are the shipped manifest's own
                # names (`package_corpus.package`); the nested forms are what a
                # hand-built bundle tends to look like.
                "log_sha256": m.get("log_sha256")
                if m.get("log_sha256") else (m.get("log") or {}).get("sha256"),
                "decisions": m.get("decision_count")
                if m.get("decision_count") is not None
                else (m.get("decisions") or {}).get("count"),
            })
    return rows


# ----------------------------------------------------------------- corpus

def _wrangler_cmd():
    """`npx wrangler@4`, with the Windows shim resolved.

    A list-form `subprocess` call does NOT go through PATHEXT: "npx" finds
    npx.exe but not the npx.cmd shim Node installs, so on Windows this failed
    with `[WinError 2]` the first time --corpus ran (measured 2026-10-24).
    """
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx.cmd"
    return [npx, "--yes", "wrangler@4"]


def _wrangler(*args, timeout=300):
    """Run wrangler and return stdout bytes. The OAuth login is wrangler's own;
    this module never reads a token."""
    proc = subprocess.run([*_wrangler_cmd(), *args], capture_output=True,
                          timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(tail[-1] if tail else f"wrangler exit {proc.returncode}")
    return proc.stdout


def wrangler_keys(prefix="corpus/"):
    out = json.loads(_wrangler("kv", "key", "list", "--namespace-id",
                               KV_NAMESPACE, "--remote", "--prefix", prefix)
                     or b"[]")
    return [row["name"] for row in out]


def wrangler_get(key):
    # `kv key get` writes the VALUE to stdout; it must stay bytes (a decoded
    # read would corrupt gzip), which is why this does not go through _wrangler.
    proc = subprocess.run([*_wrangler_cmd(), "kv", "key", "get",
                           "--namespace-id", KV_NAMESPACE, "--remote", key],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(tail[-1] if tail else f"wrangler exit {proc.returncode}")
    return proc.stdout


def _log_text(bundle):
    """The sanitized log as text. `log_gz_b64` is the SHIPPED shape
    (`package_corpus.package` gzips then base64s it, because a 1.6 MB log does
    not belong in JSON as a plain string); a plain `log` key is accepted too, so
    a hand-built bundle from a test or a note still reads. Returns None when the
    blob does not decode, which the caller treats as "no log"."""
    blob = bundle.get("log_gz_b64")
    if isinstance(blob, str) and blob:
        try:
            return gzip.decompress(base64.b64decode(blob)).decode(
                "utf-8", "replace")
        except (OSError, ValueError, binascii.Error):
            return None
    text = bundle.get("log")
    return text if isinstance(text, str) else None


def check_bundle(raw):
    """(bundle, problems): decode and independently scan the sanitized log.

    `package_corpus.inspect` is the human view; this is the machine gate, and it
    uses `privacy_scan` on the DECODED text rather than asking the sanitizer
    whether it sanitized.
    """
    problems = []
    try:
        bundle = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"not a gz json: {exc}"]
    log = _log_text(bundle)
    if not log or not log.strip():
        problems.append("bundle has no log text")
    else:
        findings = privacy_scan.find(log)
        if findings:
            problems.append(f"{len(findings)} finding(s) survived in the log")
    if not bundle.get("manifest"):
        problems.append("bundle has no manifest")
    return bundle, problems


def collect_corpus(out, force=False):
    """Pull, verify and unpack every corpus bundle. Returns `(stored, refused)`."""
    os.makedirs(os.path.join(out, "corpus"), exist_ok=True)
    stored, refused, skipped = 0, [], 0
    for key in wrangler_keys():
        name = os.path.basename(key)
        dest = os.path.join(out, "corpus", name[:-len(".json.gz")] + ".json")
        log_dest = dest[:-len(".json")] + ".log"
        if os.path.exists(dest) and os.path.exists(log_dest) and not force:
            skipped += 1
            continue
        bundle, problems = check_bundle(wrangler_get(key))
        if problems:
            refused.append((key, problems[0]))
            continue
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(bundle, f, sort_keys=True)
        text = _log_text(bundle) or ""
        with open(log_dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        stored += 1
    return stored, refused, skipped


# ----------------------------------------------------------------- tables

def _pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def _turns(good):
    """`{(report, game, turn): [advisories]}` for the turns that have a number."""
    turns = collections.defaultdict(list)
    for _rel, rep in good:
        for a in rep["advisories"]:
            if a.get("turn") is None:
                continue
            turns[(rep["manifest"].get("report_id"), a.get("game"),
                   a.get("turn"))].append(a)
    for rows in turns.values():
        rows.sort(key=lambda a: a.get("ts") or "")
    return turns


def tables(out):
    """The three measurements, plus a per-version cut of the same data."""
    good, bad = load_reports(out)
    turns = _turns(good)
    cost = []
    for (report, _game, _turn), rows in turns.items():
        last = rows[-1]
        if last.get("hp_change") is None:
            continue
        band = (last["analysis"].get("fragility") or {}).get("band")
        cost.append((report, band, last["hp_change"], len(rows)))

    versions = {}
    for _rel, rep in good:
        versions[rep["manifest"].get("report_id")] = \
            rep["manifest"].get("coach_version")

    by_band = collections.defaultdict(list)
    for report, band, change, _n in cost:
        by_band[band].append(change)

    kinds = collections.Counter()
    for rows in turns.values():
        for step in rows[-1]["analysis"].get("top_move_steps") or []:
            kinds[step.get("kind")] += 1

    by_place = collections.defaultdict(list)
    comps = []
    for _rel, rep in good:
        place = rep["manifest"].get("placement")
        rows = rep["advisories"][-1]["analysis"].get("comp_progress") or []
        if not isinstance(place, int) or not rows:
            continue
        best = max(rows, key=lambda x: (x.get("hits") or 0))
        by_place[place].append(best.get("hits") or 0)
        comps.append((place, best.get("hits") or 0,
                      versions.get(rep["manifest"].get("report_id"))))

    per_version = {}
    for version in sorted({v for *_, v in comps if v}):
        games = [(p, h) for p, h, v in comps if v == version]
        places = [p for p, _h in games]
        per_version[version] = {
            "games": len(games),
            "median_place": _pct(places, .5),
            "median_hits": _pct([h for _p, h in games], .5),
        }

    return {
        "reports": len(good),
        "refused": len(bad),
        "turns_seen": len(turns),
        "turns_with_cost": len(cost),
        "hp_change_none": sum(1 for _rel, rep in good
                              for a in rep["advisories"]
                              if a.get("hp_change") is None),
        "advisories": sum(len(rep["advisories"]) for _rel, rep in good),
        "band": {band: {
            "n": len(xs),
            "median": _pct(xs, .5),
            "p10": _pct(xs, .1),
            "p90": _pct(xs, .9),
            "lost_share": round(sum(1 for v in xs if v < 0) / len(xs), 3),
            "mean_loss": round(sum(min(0, v) for v in xs) / len(xs), 2),
        } for band, xs in sorted(by_band.items())},
        "kinds": dict(kinds.most_common()),
        "by_place": {str(p): {"n": len(xs), "median_hits": _pct(xs, .5)}
                     for p, xs in sorted(by_place.items())},
        "by_version": per_version,
    }


def _print_tables(t, as_json):
    if as_json:
        print(json.dumps(t, indent=1, sort_keys=True))
        return
    print(f"reports {t['reports']} ({t['refused']} refused), "
          f"{t['advisories']} advisories, {t['turns_seen']} turns")
    print(f"\nFIGHT COST by fragility band ({t['turns_with_cost']} turns with a "
          f"cost; hp_change None on {t['hp_change_none']} advisories)")
    print(f"  {'band':8s} {'n':>5s} {'median':>7s} {'p10':>6s} {'p90':>6s} "
          f"{'lost':>6s} {'mean':>6s}")
    for band, row in t["band"].items():
        print(f"  {band:8s} {row['n']:5d} {row['median']:7.1f} {row['p10']:6.1f} "
              f"{row['p90']:6.1f} {row['lost_share']:6.0%} {row['mean_loss']:6.2f}")
    print("\nPLAN KINDS at each turn's last read")
    for kind, n in t["kinds"].items():
        print(f"  {kind:10s} {n}")
    print("\nCOMP COMMITMENT vs PLACEMENT (last read's best core hits)")
    for place, row in t["by_place"].items():
        print(f"  place {place}: n={row['n']:3d} median hits={row['median_hits']}")
    print("\nBY COACH VERSION (games with a placement and a comp read)")
    for version, row in t["by_version"].items():
        print(f"  {version:10s} games={row['games']:3d} "
              f"median place={row['median_place']} "
              f"median hits={row['median_hits']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True,
                    help="where the inbox lives (required: never inside the "
                         "repo, which publish_release walks)")
    ap.add_argument("--collect", action="store_true",
                    help="download missing reports, then verify and index")
    ap.add_argument("--corpus", action="store_true",
                    help="pull corpus bundles through wrangler, verify, unpack")
    ap.add_argument("--tables", action="store_true",
                    help="print the three tables the reports can support")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--force", action="store_true", help="re-download/rewrite")
    ap.add_argument("--url", help="collector URL (reports)")
    args = ap.parse_args(argv)

    out = os.path.abspath(args.out)
    repo = os.path.dirname(os.path.abspath(_HERE))
    if os.path.commonpath([out, repo]) == repo:
        # A guard, not a policy: writing into the checkout is how other people's
        # data ends up in a release, and the reproducibility gate would only
        # catch it while a release happened to be building.
        raise SystemExit("--out must be outside the checkout (publish_release "
                         "walks the working tree)")

    if args.collect:
        downloaded, skipped = collect_reports(out, url=args.url,
                                               force=args.force)
        print(f"downloaded {downloaded}, already here {skipped}")
    if args.corpus:
        try:
            stored, refused, skipped = collect_corpus(out, force=args.force)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"corpus: {exc}")
            stored = refused = skipped = None
        if stored is not None:
            print(f"corpus bundles: stored {stored}, refused {len(refused)}, "
                  f"already here {skipped}")
            for key, why in refused[:5]:
                print(f"  refused {key}: {why}")
    if not (args.collect or args.corpus or args.tables):
        ap.print_usage()
        return 2
    index, bad = build_index(out)
    if args.json:
        print(json.dumps({"index": index}, indent=1, sort_keys=True))
    else:
        print(f"index: {len(index['reports'])} report(s), "
              f"{len(index['corpus'])} corpus bundle(s), "
              f"{len(index['refused'])} refused")
        for row in index["refused"][:10]:
            print(f"  refused {row['file']}: {row['why']}")
    if args.tables:
        print()
        _print_tables(tables(out), args.json)
    # A refused report is data about the pipeline, not a failure of this run:
    # the index names it and every later reader can decide. Returning nonzero
    # here would make a plain `--collect` look broken on an inbox that still
    # holds files an older build sent.
    return 0


if __name__ == "__main__":
    sys.exit(main())
