#!/usr/bin/env python3
"""Settle Up: the post-game review — what the model would have played, what you
actually did, and what it cost.

This is the other half of the pivot (`PIVOT.md` §4, Phase 2). The live overlay
ships STATE; the model's plan — the numbered line, the card it named, the level
it called — is shown HERE, after the game, where the decision it describes can
no longer be acted on. `value.top_move` was never deleted for this reason: it
has run on every buy phase all along, and this is what reads it back.

It is the same split the page cannot see and the corpus cannot do without, so
the rule for this module is simple: **this file is allowed to have opinions.**
It is the only place in the product that says "the model would have bought X".

WHAT A ROW IS

One row per advised buy phase — the grain `outcome_audit` and `fight_table`
already use. A buy phase produces dozens of advisories, and sampling them all
would inflate every count by roughly 10x (measured; see fight_table's
docstring).

Three things per row, kept apart on purpose:

  * WHAT THE MODEL PLANNED — the numbered line, rendered from the structured
    `top_move_steps`, plus which class of move led it (buy / level / roll /
    pass).
  * WHAT THE PLAYER DID — the buys, sells, rolls and level-ups read from the
    log's own action records, never inferred from the plan.
  * WHAT IT COST — `hp_delta_next_fight`: effective HP across the fight that
    followed. NEGATIVE IS BLEEDING. A phase with no following fight says so
    instead of showing a zero.

WHAT IT CANNOT GRADE, MEASURED

On the 2026-10-06 session (16 advised phases, Chenvaala, 2nd place) EIGHT of
sixteen phases led with a `cast` step, and this review calls all eight "not
graded" rather than guessing. The reason is precise and worth writing down:
`value.top_move` leaves `card` as **None** on a cast step, so the card it wants
cast exists only inside the `action` string ("Cast Them Apples"). Matching that
prose against the spells the log shows being cast would be exactly the
"formatting used as data" failure the audit flagged elsewhere, so it is not
done. The fix is one line in the planner (populate `card` on cast steps) and
`player_actions` recording WHICH spell was cast — it currently counts them
(`turns[-1]["spells"]`) rather than naming them. Until then the totals print the
ungraded count, because a review that shows three graded phases out of sixteen
without saying so reads as if it graded sixteen.

THE HONESTY RULE, which every summary here repeats because it is the whole
reason this is honest at all: following the model is CORRELATED with easy
spots. A "followed" row looking better is not evidence the model is right, and
`outcome_audit` refuses to claim otherwise. This prints the split and the
caveat; it does not print a score.

WHAT IT READS, AND THE ONE THING IT LOSES

The Power.log (`outcome_audit.audit_game` replays it through the incremental
coach and joins the log's own actions and HP series). That means the plan here
is what TODAY's rules would play, not the bytes that were on screen during that
game — `outcome_audit`'s docstring owns that distinction, and it is the right
one for a review: the question is "what does the model think now", and no
version of this can re-run the code that gave the original advice unless the
decision log preserved it.

When the Power.log is gone (Hearthstone rotates them), `fight_table`'s
decision-log rows can still be shown — labelled, because that path cannot see
the player's actions or an independent outcome.

Usage:
  python settle_up.py --latest                 # the newest session log, game 1
  python settle_up.py <Power.log> [game]       # a specific log
  python settle_up.py --latest --html out.html
  python settle_up.py --latest --json
"""
import argparse
import datetime
import glob
import html
import json
import os
import sys

from config import HS_LOG_GLOB
from extract_game import split_game_chunks
import outcome_audit
from value import _load_bg_names

#: Bumped when the report's shape changes, so an HTML file or a JSON dump can
#: be told apart from one this code did not write.
SCHEMA = 1

#: Said wherever a followed/ignored split is printed. It is not boilerplate:
#: outcome_audit owns the same sentence for the same reason, and a review that
#: dropped it would read as "the model is right when you obey it".
CAVEAT = ("Observational, not causal: following the model is correlated with "
          "easy spots, so these numbers are a reason to LOOK at a phase, never "
          "proof the model was right.")


# ---------------------------------------------------------------- the reading

def _plan_line(steps):
    """The numbered plan, rendered from the structured steps.

    Same shape the overlay used to draw (and no longer does): "1. LEVEL
    (access to tier 4) · 2. Buy Bronze Warden (surviving until we can commit)".
    `action` is the imperative verb phrase; `tag` the parenthetical; `reason`
    the why-line, which gets its own row rather than being folded in.
    """
    out = []
    n = 0
    for s in steps or []:
        txt = s.get("action") or s.get("text") or ""
        if not txt:
            continue
        # Numbered contiguously as EMITTED, not by the step's own index: a
        # blank step would otherwise leave a hole ("1. LEVEL · 3. Buy X"),
        # which reads as a missing priority rather than as bad data.
        n += 1
        if s.get("tag"):
            txt += f" ({s['tag']})"
        out.append(f"{n}. {txt}")
    return " · ".join(out)


def _acted(names, row):
    """What the player did this phase, in words, from the log's own records.

    Card ids the name DB cannot resolve render as the raw id rather than being
    dropped — a review that silently omits a buy is worse than one that shows
    `BG36_318` (the same rule review_kit's pre-flight applies).
    """
    def nm(cid):
        return names.get(cid, cid)

    bits = []
    for c in row.get("player_buys") or []:
        bits.append("bought " + nm(c))
    pa = row.get("player_actions") or {}
    if pa.get("upgrades"):
        bits.append("levelled up")
    n = pa.get("refreshes") or 0
    if n:
        bits.append(f"rolled x{n}")
    # Sells live INSIDE player_actions, not at the top level of the row — the
    # first version read `row["sells"]`, found nothing, and silently dropped
    # every sell from every review (caught by test_settle_up).
    for c in pa.get("sells") or []:
        bits.append("sold " + nm(c))
    if pa.get("freezes"):
        bits.append("froze")
    return ", ".join(bits) if bits else "nothing"


def _verdict(row):
    """(label, kind) for one phase. kind is what the totals count.

    Three distinctions that matter, each of which this got wrong at first:

    * `no plan` is NOT the same as "a plan I cannot grade". A phase whose lead
      was a swap, a cast or a pick has a real plan (t7 of the 10-06 game reads
      "1. Swap: play Holy Vanguard, sell Crackling Cyclone"), and calling that
      "no plan" hid it. Those are `ungraded`: they speak for the model in
      neither direction.
    * `pass` is its own thing (a skip-turn hero), deliberately not "followed".
    * **"taken" must mean the card the model NAMED.** outcome_audit's
      `followed_buy` is broader on purpose — it counts any of the headline plus
      the next three ranked offers, because for an aggregate accuracy number
      "bought something it wanted" is the question. For a review it is not:
      t4 of the 10-06 game said "Buy Flighty Scout", the player bought two
      other things from the shortlist, and the row read "taken". The label now
      says which, and only the named card counts as taken.
    """
    lead = row.get("lead")
    if lead in (None, "none", "note"):
        return "no plan", "none"
    if lead == "pass":
        return ("as planned" if not (row.get("player_buys") or [])
                else "not as planned"), "pass"
    if lead == "buy":
        named = row.get("card")
        buys = row.get("player_buys") or []
        if named and named in buys:
            return "taken", "taken"
        if row.get("followed_buy"):
            return "shortlist only", "ignored"
        return "not taken", "ignored"
    if lead == "level":
        if row.get("followed_level"):
            return "taken", "taken"
        return "not taken", "ignored"
    if lead in ("roll", "hunt-roll"):
        if row.get("followed_roll"):
            return "taken", "taken"
        return "not taken", "ignored"
    # swap / cast / play / hold / pick — a real plan this row cannot grade.
    return f"not graded ({lead})", "ungraded"


def build(log_path, game_index=1):
    """The review for one game of one log. Pure reading — writes nothing.

    Returns a dict; `phases` is what a renderer walks. `outcome` is the HP
    delta across the fight that FOLLOWED each phase, so the last phase is
    `None` with a note rather than a zero that reads as "no damage".
    """
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    from decision_log import session_stem
    session = session_stem(log_path)
    # split_game_chunks yields (start, end) LINE INDEX PAIRS, not chunks —
    # outcome_audit and every other caller slices lines[s:e] themselves.
    bounds = list(split_game_chunks(lines))
    if not 1 <= game_index <= len(bounds):
        raise SystemExit(f"{os.path.basename(log_path)} has {len(bounds)} "
                         f"game(s); game {game_index} does not exist")
    lo, hi = bounds[game_index - 1]
    rows = outcome_audit.audit_game(lines[lo:hi], game_index, session)
    names = _load_bg_names()

    phases = []
    for i, r in enumerate(rows):
        label, kind = _verdict(r)
        steps = r.get("steps") or []
        plan = _plan_line(steps)
        outcome = r.get("hp_delta_next_fight")
        phases.append({
            "turn": r.get("turn"), "tier": r.get("tier"), "gold": r.get("gold"),
            "eff_hp": r.get("eff_hp"),
            "plan": plan or "(no plan recorded for this phase)",
            "lead": r.get("lead"), "kind": kind, "verdict": label,
            "named": r.get("card_name"),
            "reasons": [s.get("reason") for s in steps if s.get("reason")],
            "acted": _acted(names, r),
            "buys": [names.get(c, c) for c in (r.get("player_buys") or [])],
            "outcome": outcome,
            "outcome_note": ("no fight after this phase — the game ended here"
                             if outcome is None and i == len(rows) - 1 else
                             None if outcome is not None else
                             "health not readable at the next phase"),
        })

    head = rows[0] if rows else {}
    return {
        "schema": SCHEMA,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "session": session,
        "log": os.path.basename(log_path),
        "game": game_index,
        "hero": head.get("hero"),
        "placement": head.get("placement"),
        "phases": phases,
        "totals": _totals(phases, head),
        "caveat": CAVEAT,
    }


def _totals(phases, head):
    """Counts and the followed/ignored split. No score, deliberately."""
    counts = {"phases": len(phases), "taken": 0, "ignored": 0, "none": 0,
              "pass": 0, "ungraded": 0}
    bled = 0
    graded = 0
    taken_hp, ignored_hp = [], []
    for p in phases:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
        o = p["outcome"]
        if o is None:
            continue
        graded += 1
        # Negative is bleeding; only the damage counts as cost.
        if o < 0:
            bled += -o
        if p["kind"] == "taken":
            taken_hp.append(o)
        elif p["kind"] == "ignored":
            ignored_hp.append(o)

    def mean(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "counts": counts,
        "graded_phases": graded,
        # Coverage, said out loud. A review that quietly shows three graded
        # phases out of sixteen reads as if it graded sixteen; this is the
        # number that stops that. See the module docstring for WHY casts are
        # not gradable (value.top_move leaves `card` None on a cast step, so
        # the only name in the payload is prose).
        "ungraded_phases": counts.get("ungraded", 0),
        "bled_total": bled,
        "taken_mean": mean(taken_hp), "taken_n": len(taken_hp),
        "ignored_mean": mean(ignored_hp), "ignored_n": len(ignored_hp),
        "caveat": CAVEAT,
    }


# ------------------------------------------------------------- the rendering

def _hp(n):
    return "?" if n is None else f"{n:+d}"


def render_text(rep):
    """Bounded console output, in the house style: a few lines per phase."""
    out = []
    out.append(f"Settle Up — {rep['hero'] or 'unknown hero'}"
               f"{'  (finished ' + str(rep['placement']) + ')' if rep['placement'] else ''}")
    out.append(f"{rep['log']} · game {rep['game']} · {rep['session']}")
    out.append("")
    if not rep["phases"]:
        out.append("No advised buy phase in this game — nothing to settle.")
        return "\n".join(out)
    for p in rep["phases"]:
        head = (f"t{p['turn']}  tier {p['tier']}  gold {p['gold']}"
                f"  eff HP {p['eff_hp']}")
        out.append(head)
        out.append(f"   model: {p['plan']}")
        out.append(f"   you:   {p['acted']}   [{p['verdict']}]")
        if p["outcome"] is not None:
            cost = ("bled " + str(-p["outcome"])) if p["outcome"] < 0 else (
                "no damage" if p["outcome"] == 0 else
                f"gained {p['outcome']}")
            out.append(f"   fight after it: {cost}")
        elif p["outcome_note"]:
            out.append(f"   fight after it: {p['outcome_note']}")
        out.append("")
    t = rep["totals"]
    c = t["counts"]
    out.append(f"{c['phases']} advised phases: {c['taken']} taken, "
               f"{c['ignored']} not taken, {c['ungraded']} not graded, "
               f"{c['pass']} pass, {c['none']} with no plan")
    out.append(f"bled {t['bled_total']} effective HP across "
               f"{t['graded_phases']} phases with a readable outcome")
    if t["taken_n"] or t["ignored_n"]:
        out.append(f"mean HP change - took the plan: {t['taken_mean']} "
                   f"(n={t['taken_n']}) - did not: {t['ignored_mean']} "
                   f"(n={t['ignored_n']})")
    if t["ungraded_phases"]:
        out.append(f"{t['ungraded_phases']} of {c['phases']} phases led with a "
                   f"move this review cannot grade (cast/swap/play/pick) - it "
                   f"makes no claim about those.")
    out.append("")
    out.append("NOTE: " + rep["caveat"])
    return "\n".join(out)


def render_html(rep):
    """A standalone review page. No network, no scripts, no state: the file
    opens from disk and works forever.

    Self-contained on purpose — the overlay server has a /review route for the
    in-game case (see coach_ui), but a player who wants to keep one game's
    review should not need a running process to read it.

    Privacy: the page carries card names, hero names and the log's own file
    name, and nothing else. It never embeds log text, and an opponent's handle
    is not in any field it renders (the row comes from outcome_audit, which
    reads board state and actions, not the chat or the name lines).
    """
    e = html.escape
    t = rep["totals"]
    c = t["counts"]
    placement = f" · finished {e(str(rep['placement']))}" if rep["placement"] else ""
    who = e(rep["hero"] or "unknown hero")

    rows = []
    for p in rep["phases"]:
        o = p["outcome"]
        if o is None:
            badge, cls = (p["outcome_note"] or "no outcome"), "flat"
        elif o < 0:
            badge, cls = f"bled {-o} HP", "bad"
        elif o == 0:
            badge, cls = "no damage", "flat"
        else:
            badge, cls = f"gained {o} HP", "good"
        vcls = {"taken": "taken", "ignored": "ignored"}.get(p["kind"], "none")
        reasons = "".join(f"<div class=why>{e(r)}</div>" for r in p["reasons"])
        rows.append(f"""  <section class=phase>
    <div class=phead><span class=turn>Turn {e(str(p['turn']))}</span>
      <span class=meta>tier {e(str(p['tier']))} · {e(str(p['gold']))}g · {e(str(p['eff_hp']))} eff HP</span>
      <span class="badge {cls}">{e(badge)}</span></div>
    <div class=line><span class=lbl>Model</span><span class=plan>{e(p['plan'])}</span>{reasons}</div>
    <div class=line><span class=lbl>You</span><span class=acted>{e(p['acted'])}</span>
      <span class="verdict {vcls}">{e(p['verdict'])}</span></div>
  </section>""")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Settle Up — {who}</title>
<style>
  :root {{ --bg:#0d0d0d; --panel:#1a1a19; --panel2:#242422; --text:#fff;
    --text-2:#c3c2b7; --dim:#898781; --border:rgba(255,255,255,.10);
    --good:#0ca30c; --warn:#fab219; --bad:#ec835a; --critical:#d03b3b;
    --gold:#ffd97a; --gridline:#2c2c2a; }}
  body {{ margin:0; background:var(--bg); color:var(--text); padding:24px;
    font:14px/1.5 "Segoe UI", system-ui, sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:24px; color:var(--gold); margin:0 0 2px; }}
  .sub, .caveat {{ color:var(--dim); font-size:12px; }}
  .caveat {{ border-left:3px solid var(--warn); padding:6px 10px; margin:14px 0;
    color:var(--text-2); background:var(--panel); }}
  .totals {{ display:flex; gap:18px; flex-wrap:wrap; margin:16px 0 8px;
    padding:10px 12px; background:var(--panel); border:1px solid var(--border);
    border-radius:6px; }}
  .totals b {{ color:var(--gold); font-variant-numeric:tabular-nums; }}
  .phase {{ background:var(--panel); border:1px solid var(--border);
    border-radius:6px; padding:8px 11px; margin:8px 0; }}
  .phead {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .turn {{ font-weight:700; }}
  .meta {{ color:var(--dim); font-size:12px; }}
  .badge {{ margin-left:auto; font-size:12px; font-weight:700; }}
  .badge.bad {{ color:var(--bad); }}
  .badge.good {{ color:var(--good); }}
  .badge.flat {{ color:var(--dim); font-weight:400; }}
  .line {{ display:flex; gap:9px; align-items:baseline; margin-top:3px; }}
  .lbl {{ color:var(--dim); font-size:11px; text-transform:uppercase;
    letter-spacing:.06em; flex:none; width:46px; }}
  .plan {{ font-weight:600; }}
  .acted {{ color:var(--text-2); }}
  .why {{ color:var(--text-2); font-size:12px; margin-left:55px; }}
  .verdict {{ font-size:11px; font-weight:700; margin-left:auto; flex:none; }}
  .verdict.taken {{ color:var(--good); }}
  .verdict.ignored {{ color:var(--warn); }}
  .verdict.none {{ color:var(--dim); font-weight:400; }}
</style></head><body><div class=wrap>
<h1>Settle Up</h1>
<div class=sub>{who}{placement} · {e(rep['log'])} game {e(str(rep['game']))} · {e(rep['session'])}</div>
<div class=totals>
  <span><b>{c['phases']}</b> advised phases</span>
  <span><b>{c['taken']}</b> taken</span>
  <span><b>{c['ignored']}</b> not taken</span>
  <span><b>{t['bled_total']}</b> effective HP bled</span>
</div>
<div class=caveat>{e(rep['caveat'])}</div>
{chr(10).join(rows)}
<div class=sub style="margin-top:14px">Generated by Bob's Ledger · schema {SCHEMA} · {e(rep['created'])}</div>
</div></body></html>
"""


# ------------------------------------------------------------------ the entry

def latest_log():
    """The newest session Power.log, or None. Same rule replay_review uses."""
    paths = [p for p in glob.glob(HS_LOG_GLOB) if os.path.getsize(p)]
    return max(paths, key=os.path.getmtime) if paths else None


def main(argv=None):
    # The plan text this prints carries "·" and the analysis can carry "⚠";
    # a cp1252 console would raise UnicodeEncodeError instead of showing the
    # review it had just computed. Same guard, same reason, as live.py and
    # replay_review.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", help="a Power.log (default: --latest)")
    ap.add_argument("game", nargs="?", type=int, default=1)
    ap.add_argument("--latest", action="store_true",
                    help="use the newest session log")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    ap.add_argument("--html", metavar="PATH",
                    help="write a standalone review page here")
    args = ap.parse_args(argv)

    log = args.log
    if args.latest or not log:
        log = latest_log()
        if not log:
            print("No Power.log found. Is Hearthstone's file logging on, and "
                  "has a game been played?")
            return 2
    if not os.path.exists(log):
        print(f"No such log: {log}")
        return 2

    rep = build(log, args.game)

    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(rep))
        print(f"wrote {args.html}")
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    elif not args.html:
        print(render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
