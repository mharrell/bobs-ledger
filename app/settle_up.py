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

WHAT IT COULD NOT GRADE, AND WHAT CLOSED (2026-10-06)

The first review could not judge a phase whose plan led with a cast, a play, a
swap or a pick — **8 of the 16 advised phases** in the game it was measured on.
A cast step carried `card: None` (`value.top_move` derived each step's card by
parsing the rendered text, and only a buy step ever resolved one), and
`player_actions` counted spells rather than naming them, so there was nothing to
match on either side.

Both ends now carry ids: `_top_move_text` records which card each hand step is
about, and `player_actions` records `spell_ids`. The same game reports ONE
ungraded phase, a swap.

Two limits remain, and the summary prints both rather than hiding them:

  * a SWAP needs the sell AND the play that replaced it as a pair, which the row
    does not carry, so swap-led phases stay out of the counts;
  * a phase LED BY A CAST counts for less than one led by a buy. A turn that
    casts several spells can satisfy "Cast X" incidentally, and a split that
    silently mixed the two would overstate the stronger signal.

THE HONESTY RULE, which every summary here repeats because it is the whole
reason this is honest at all: following the model is CORRELATED with easy
spots. A "followed" row looking better is not evidence the model is right, and
`outcome_audit` refuses to claim otherwise. This prints the split and the
caveat; it does not print a score. (The 2026-10-06 game is a good reminder: it
reports took-the-plan at -3.2 mean HP against -1.2 for did-not, i.e. following
the plan looked WORSE, at n=9 against n=5. That is a reason to look at phases,
which is all it was ever offered as.)

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
    if lead == "cast":
        # GRADABLE SINCE 2026-10-06. It was not before: `value.top_move` left
        # `card` as None on a cast step (the plan names the spell only in prose)
        # and `player_actions` counted spells instead of naming them, so 8 of 16
        # phases in the 2026-10-06 game read "not graded". Both now carry ids.
        named = row.get("card")
        cast = row.get("spells_cast") or []
        if not named:
            # The plan led with a cast but no card resolved (a token the DB
            # cannot name, say). "Cast something else" would be a guess.
            return "not graded (cast, card unresolved)", "ungraded"
        if named in cast:
            return "cast as planned", "taken"
        if cast:
            return "cast something else", "ignored"
        return "not cast", "ignored"
    if lead == "play":
        # Same shape for a hand minion: the plan says "Play X", the log says
        # which minions actually entered PLAY from hand.
        named = row.get("card")
        played = row.get("plays") or []
        if not named:
            return "not graded (play, card unresolved)", "ungraded"
        if named in played:
            return "played as planned", "taken"
        if played:
            return "played something else", "ignored"
        return "not played", "ignored"
    # swap / hold / pick — and a card-less `discard`, which is an Activate step
    # (see outcome_audit._plan_shape): a real plan this row cannot grade.
    return f"not graded ({lead})", "ungraded"


def _fmt_board(board, names):
    """One board as text: "Locked-up Mutineer 6/3, Crackling Cyclone 2/1*".

    A trailing `*` marks a golden minion. Text rather than tiles on purpose: the
    standalone report is readable with no server running, and the card art it
    would need lives behind the overlay's /img route.
    """
    if not board:
        return ""
    return ", ".join(
        f"{names.get(m.get('card'), m.get('card'))} {m.get('atk')}/"
        f"{m.get('health')}" + ("*" if m.get("golden") else "")
        for m in board)


def _removed_note(n):
    """One line, in the report and in the page's words: a board that reads
    shorter than the raw snapshot says why it does.

    `turn_review._opening_board` drops the previous fight's leftover summons
    from the opening and surviving boards (trap 3.6 of
    `analysis/SETTLE_UP_BOARDS.md`); the count rides on the row so every
    renderer can say it rather than silently showing a shorter board.
    """
    return (f"{n} leftover summon(s) from the fight were removed from the "
            f"surviving board — a board holds 7")


def _timeline(log_path, game_index, names):
    """The per-turn board timeline, formatted for the report.

    Wrapped rather than allowed to raise: this is a SECOND full replay of the
    game (about 5 s on a 15-turn game) and the phase rows above are the part
    that must survive its failure. A failure is recorded in the report as
    `timeline_error` rather than swallowed — a review missing its boards should
    say so, not look like a review of a game with no boards.
    """
    try:
        import turn_review
        tl = turn_review.timeline(log_path, game_index)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    for row in tl["turns"]:
        row["buy_end_text"] = _fmt_board(row["buy_end"], names)
        row["combat_ours_text"] = _fmt_board(row["combat_start"]["ours"], names)
        row["combat_theirs_text"] = _fmt_board(row["combat_start"]["theirs"], names)
        row["battle_end_text"] = _fmt_board(row["battle_end"], names)
        # The sell questions were ids; name them here, where the name DB is.
        for q in row["sell_questions"]:
            q["sold_name"] = names.get(q["sold"], q["sold"])
            q["kept_filler_names"] = [names.get(c, c) for c in q["kept_fillers"]]
            q["also_names"] = [names.get(a["card"], a["card"])
                               for a in q.get("also_sold") or []]
        row["took_names"] = {
            "bought": [names.get(c, c) for c in row["took"]["bought"]],
            "sold": [names.get(c, c) for c in row["took"]["sold"]],
        }
    return tl, None


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
    timeline, timeline_error = _timeline(log_path, game_index, names)
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
        "timeline": timeline,
        "timeline_error": timeline_error,
        "caveat": CAVEAT,
    }


def _totals(phases, head):
    """Counts and the followed/ignored split. No score, deliberately."""
    counts = {"phases": len(phases), "taken": 0, "ignored": 0, "none": 0,
              "pass": 0, "ungraded": 0}
    bled = 0
    graded = 0
    graded_by_lead = {}
    taken_hp, ignored_hp = [], []
    for p in phases:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
        o = p["outcome"]
        if o is None:
            continue
        graded += 1
        lead = p.get("lead") or "?"
        graded_by_lead[lead] = graded_by_lead.get(lead, 0) + 1
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
        # Which CLASS of lead each graded phase had. Cast-led phases are now
        # gradable, and they are NOT interchangeable with buy-led ones: a turn
        # that casts several spells can satisfy "Cast X" incidentally, so a
        # cast-led `taken` is weaker evidence of following the plan than a
        # buy-led one. The renderer says so when any are present, because a
        # split that silently mixes the two overstates the stronger one.
        "graded_by_lead": graded_by_lead,
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

    # TURN BY TURN — the board, three times per turn. This is the part no
    # in-game screen can show you: what you went in with, what they brought, and
    # what survived.
    tl = rep.get("timeline")
    if rep.get("timeline_error"):
        out.append(f"(the turn-by-turn boards could not be built: "
                   f"{rep['timeline_error']})")
        out.append("")
    elif tl and tl.get("turns"):
        out.append("TURN BY TURN")
        out.append("")
        for r in tl["turns"]:
            s, sp = r["stats"], r["spend"]
            out.append(f"t{r['turn']}  {r['gold']}g  board {s['buy_end']} stats"
                       f"{' (' + format(s['growth'], '+d') + ')' if s['growth'] is not None else ''}"
                       f"  spent {sp['total']}g"
                       + (f"  comp {r['commitment']['target']}" if r["commitment"]["target"] else ""))
            out.append(f"   you brought     : {r['combat_ours_text'] or r['buy_end_text'] or '(no board read)'}")
            if r["combat_theirs_text"]:
                out.append(f"   they brought    : {r['combat_theirs_text']}")
            out.append(f"   survived        : {r['battle_end_text'] or '(not readable)'}")
            # The survivor board drops the fight's leftover summons
            # (turn_review._opening_board); a report that shows a shorter board
            # than the log wrote has to say so, here as on the page.
            if r.get("battle_end_removed"):
                out.append(f"   note: {_removed_note(r['battle_end_removed'])}")
            for q in r.get("sell_questions") or []:
                if q.get("rebuild"):
                    out.append(f"   ~ rebuilt the board: sold {q['sold_count']} "
                               f"({q.get('sold_name')} and others) — a "
                               f"repositioning, not a one-for-one choice")
                else:
                    out.append(f"   ? sold {q.get('sold_name')} ({q['role']}) while "
                               f"keeping {', '.join(q.get('kept_filler_names') or [])}")
            for n in r["notes"]:
                out.append(f"   note: {n}")
            out.append("")
        out.append("")

    out.append("PHASE BY PHASE")
    out.append("")
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
                   f"move this review cannot grade (swap/hold/pick) - it "
                   f"makes no claim about those.")
    cast_graded = (t.get("graded_by_lead") or {}).get("cast", 0)
    if cast_graded:
        out.append(f"({cast_graded} graded phase(s) led with a cast. A turn that "
                   f"casts several spells can satisfy \"Cast X\" incidentally, so "
                   f"those count for less than a buy-led phase.)")
    out.append("")
    out.append("NOTE: " + rep["caveat"])
    return "\n".join(out)


def _timeline_html(rep):
    """The turn-by-turn board section of the report page.

    This is the part no in-game screen can show: the board as it went into the
    fight, what the opponent brought, and what survived. Rendered as text
    boards rather than card tiles because the page is standalone — card art
    lives behind the overlay's /img route and would leave the report broken the
    moment the coach is closed.
    """
    e = html.escape
    tl = rep.get("timeline")
    if rep.get("timeline_error"):
        return ('<div class=caveat>The turn-by-turn boards could not be built '
                f'({e(str(rep["timeline_error"]))}). The phase list below is '
                'unaffected.</div>')
    if not tl or not tl.get("turns"):
        return ""

    blocks = []
    for r in tl["turns"]:
        s, sp = r["stats"], r["spend"]
        growth = (f'<span class=grw>{s["growth"]:+d}</span>'
                  if s["growth"] is not None else "")
        comp = (f'<span class=comp>{e(r["commitment"]["target"])}</span>'
                if r["commitment"]["target"] else "")
        flags = []
        for q in r.get("sell_questions") or []:
            if q.get("rebuild"):
                flags.append(
                    f'<div class=note>~ rebuilt the board: sold {q["sold_count"]} '
                    f'({e(str(q.get("sold_name")))} and others) &mdash; a '
                    f'repositioning, not a one-for-one choice</div>')
            else:
                flags.append(
                    f'<div class=q>? sold <b>{e(str(q.get("sold_name")))}</b> '
                    f'({e(q["role"])}) while keeping '
                    f'{e(", ".join(q.get("kept_filler_names") or []))} '
                    f'&mdash; worth a look, not a verdict</div>')
        for n in r["notes"]:
            flags.append(f'<div class=note>{e(n)}</div>')
        # The survivor board drops the fight's leftover summons
        # (turn_review._opening_board); the report says so, as the page does.
        if r.get("battle_end_removed"):
            flags.append(f'<div class=note>'
                         f'{e(_removed_note(r["battle_end_removed"]))}</div>')
        went_in = r["combat_ours_text"] or r["buy_end_text"] or "(no board read)"
        blocks.append(
            f'  <section class=turn>\n'
            f'    <div class=thead><span class=tturn>Turn {r["turn"]}</span>'
            f'<span class=tmeta>{r["gold"]}g &middot; board {s["buy_end"]} stats '
            f'{growth} &middot; spent {sp["total"]}g</span>{comp}</div>\n'
            f'    <div class=brow><span class=blbl>You brought</span>'
            f'<span>{e(went_in)}</span></div>\n'
            f'    <div class=brow><span class=blbl>Opponent brought</span>'
            f'<span class=them>{e(r["combat_theirs_text"]) or "&mdash;"}</span></div>\n'
            f'    <div class=brow><span class=blbl>Survived</span>'
            f'<span>{e(r["battle_end_text"]) or "&mdash;"}</span></div>\n'
            f'    {"".join(flags)}\n'
            f'  </section>')
    return ('<h2 class=sect>TURN BY TURN</h2>'
            '<div class=sub>What you brought into each fight, what the '
            'opponent brought, and what survived &mdash; the board at three '
            'points in every turn.</div>'
            + "\n".join(blocks))


def _summarise(rep):
    """One game as a single row, for the session view. Pure.

    Everything comes off the full report, which already holds both the phase
    rows and the timeline — so the session view is an aggregation, not a second
    reconstruction.
    """
    tl = rep.get("timeline") or {}
    turns = tl.get("turns") or []
    boards = [t["stats"]["buy_end"] for t in turns if t["buy_end"]]
    c = rep["totals"]["counts"]
    return {
        "game": rep["game"], "hero": rep["hero"], "placement": rep["placement"],
        "phases": c["phases"], "taken": c["taken"], "ignored": c["ignored"],
        "ungraded": c["ungraded"],
        "phases_tracked": c["phases"] - c["ungraded"],
        "bled": rep["totals"]["bled_total"],
        "turns": len(turns),
        "spent": sum(t["spend"]["total"] for t in turns),
        "peak_board": max(boards) if boards else None,
        "final_board": boards[-1] if boards else None,
        "sell_questions": sum(len(t["sell_questions"]) for t in turns),
        "timeline_error": rep.get("timeline_error"),
    }


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else round((xs[mid - 1] + xs[mid]) / 2, 1)


def _session_totals(summaries):
    """The aggregate across games. Pure. No score, deliberately.

    It counts and it sums; it does not rank the player. Placements are reported
    as they came, with the median, because a session is far too small a sample
    to call a trend — and the same observational caveat rides along.
    """
    if not summaries:
        return {"games": 0, "placements": [], "best": None, "median_placement": None,
                "phases": 0, "taken": 0, "ignored": 0, "ungraded": 0, "bled": 0,
                "spent": 0, "sell_questions": 0, "median_final_board": None,
                "caveat": CAVEAT}
    places = [s["placement"] for s in summaries if s["placement"]]
    finals = [s["final_board"] for s in summaries if s["final_board"]]
    return {
        "games": len(summaries),
        "placements": places,
        "best": min(places) if places else None,
        "median_placement": _median(places),
        "phases": sum(s["phases"] for s in summaries),
        "taken": sum(s["taken"] for s in summaries),
        "ignored": sum(s["ignored"] for s in summaries),
        "ungraded": sum(s["ungraded"] for s in summaries),
        "bled": sum(s["bled"] for s in summaries),
        "spent": sum(s["spent"] for s in summaries),
        "sell_questions": sum(s["sell_questions"] for s in summaries),
        "median_final_board": _median(finals),
        "caveat": CAVEAT,
    }


def build_session(log_path, limit=None):
    """Every game in one log, summarised. One full review per game.

    Cost, stated rather than hidden: each game runs the same two replays a
    single-game review does (about 7 s for a 15-turn game), so a five-game
    session is roughly half a minute. There is no caching layer here — the
    maintainer's `review_kit.py` caches per-session replays for its own use, and
    borrowing that machinery is a separate piece of work.
    """
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    from decision_log import session_stem
    session = session_stem(log_path)
    bounds = list(split_game_chunks(lines))
    count = len(bounds) if limit is None else min(limit, len(bounds))
    summaries = [_summarise(build(log_path, gi)) for gi in range(1, count + 1)]
    return {
        "schema": SCHEMA,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "session": session,
        "log": os.path.basename(log_path),
        "games": summaries,
        "totals": _session_totals(summaries),
        "caveat": CAVEAT,
    }


def build_history(log_paths, limit_games=None):
    """Several sessions, aggregated. One full review per game.

    The same aggregation as the session view, applied across logs — so the
    numbers mean the same thing whether you are looking at one night or ten.
    COST, stated: every game is replayed twice (about 7 s each), so five games
    per session over three sessions is minutes, not seconds. It takes an
    explicit flag for that reason and never runs on the game-end path.
    """
    games, logs = [], []
    for path in log_paths:
        s = build_session(path, limit=limit_games)
        games.extend(s["games"])
        logs.append({"log": s["log"], "session": s["session"],
                     "games": len(s["games"])})
    return {
        "schema": SCHEMA,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "logs": logs,
        "games": games,
        "totals": _session_totals(games),
        "caveat": CAVEAT,
    }


def recent_logs(count):
    """The newest `count` session logs, newest first."""
    paths = [p for p in glob.glob(HS_LOG_GLOB) if os.path.getsize(p)]
    paths.sort(key=os.path.getmtime, reverse=True)
    return paths[:count]


def _games_table_text(games):
    out = ["game  hero            place  turns  phases  took  left  ungraded"
           "  spent  peak board  final board  ?sells"]
    for s in games:
        out.append(
            f"{s['game']:<5} {(s['hero'] or '?')[:15]:<15} "
            f"{str(s['placement'] or '?'):<6} {s['turns']:<6} {s['phases']:<7} "
            f"{s['taken']:<5} {s['ignored']:<5} {s['ungraded']:<9} "
            f"{s['spent']:<6} {str(s['peak_board'] or '?'):<11} "
            f"{str(s['final_board'] or '?'):<12} {s['sell_questions']}")
        if s["timeline_error"]:
            out.append(f"      (boards unavailable: {s['timeline_error']})")
    return out


def render_history_text(rep):
    """The cross-session view: which logs, then the same table and aggregate."""
    out = [f"SETTLE UP — {len(rep['logs'])} session(s), "
           f"{rep['totals']['games']} game(s)", ""]
    for lg in rep["logs"]:
        out.append(f"  {lg['session']}: {lg['games']} game(s)")
    out.append("")
    out.extend(_games_table_text(rep["games"]))
    t = rep["totals"]
    out.append("")
    out.append(f"{t['games']} game(s): placements {t['placements'] or 'unknown'}"
               f" (best {t['best']}, median {t['median_placement']})")
    out.append(f"{t['phases']} advised phases, {t['taken']} taken, "
               f"{t['ignored']} not taken, {t['ungraded']} ungraded")
    out.append(f"bled {t['bled']} effective HP; {t['spent']} gold countable spend")
    if t["sell_questions"]:
        out.append(f"{t['sell_questions']} sell question(s)")
    out.append("")
    out.append("NOTE: " + rep["caveat"])
    return "\n".join(out)


def render_session_text(rep):
    """The session view as console text: one line per game, then the aggregate."""
    out = [f"SETTLE UP — session {rep['session']}  ({len(rep['games'])} game(s))",
           ""]
    if not rep["games"]:
        out.append("No game in this log could be reviewed.")
        return "\n".join(out)
    out.extend(_games_table_text(rep["games"]))
    t = rep["totals"]
    out.append("")
    out.append(f"{t['games']} game(s): placements {t['placements'] or 'unknown'}"
               f" (best {t['best']}, median {t['median_placement']})")
    out.append(f"{t['phases']} advised phases, {t['taken']} taken, "
               f"{t['ignored']} not taken, {t['ungraded']} ungraded")
    out.append(f"bled {t['bled']} effective HP across the session; "
               f"{t['spent']} gold countable spend")
    if t["sell_questions"]:
        out.append(f"{t['sell_questions']} sell question(s) - a key card sold "
                   f"while a filler stayed")
    out.append("")
    out.append("NOTE: " + rep["caveat"])
    return "\n".join(out)


def render_session_html(rep):
    """The session page: a table of games, then the aggregate."""
    e = html.escape
    t = rep["totals"]
    rows = []
    for s in rep["games"]:
        warn = (f'<div class=note>boards unavailable: '
                f'{e(str(s["timeline_error"]))}</div>' if s["timeline_error"] else "")
        rows.append(
            f'  <tr><td>{s["game"]}</td><td>{e(s["hero"] or "?")}</td>'
            f'<td>{e(str(s["placement"] or "?"))}</td><td>{s["turns"]}</td>'
            f'<td>{s["taken"]}/{s["phases_tracked"] - s["taken"]}</td>'
            f'<td>{s["spent"]}g</td><td>{s["final_board"] or "?"}</td>'
            f'<td>{s["sell_questions"] or ""}</td></tr>{warn}')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Settle Up — session</title>
<style>
  :root {{ --bg:#0d0d0d; --panel:#1a1a19; --panel2:#242422; --text:#fff;
    --text-2:#c3c2b7; --dim:#898781; --border:rgba(255,255,255,.10);
    --good:#0ca30c; --warn:#fab219; --bad:#ec835a; --gold:#ffd97a;
    --gridline:#2c2c2a; }}
  body {{ margin:0; background:var(--bg); color:var(--text); padding:24px;
    font:14px/1.5 "Segoe UI", system-ui, sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:24px; color:var(--gold); margin:0 0 2px; }}
  .sub {{ color:var(--dim); font-size:12px; }}
  .caveat {{ border-left:3px solid var(--warn); padding:6px 10px; margin:14px 0;
    color:var(--text-2); background:var(--panel); font-size:12px; }}
  table {{ border-collapse:collapse; width:100%; margin-top:12px;
    background:var(--panel); border:1px solid var(--border); border-radius:6px; }}
  th, td {{ text-align:left; padding:5px 8px; font-size:13px;
    border-bottom:1px solid var(--gridline); }}
  th {{ color:var(--dim); font-size:11px; text-transform:uppercase;
    letter-spacing:.06em; font-weight:700; }}
  td:nth-child(n+3) {{ font-variant-numeric:tabular-nums; }}
  .totals {{ display:flex; gap:18px; flex-wrap:wrap; margin:16px 0 4px;
    padding:10px 12px; background:var(--panel); border:1px solid var(--border);
    border-radius:6px; }}
  .totals b {{ color:var(--gold); font-variant-numeric:tabular-nums; }}
  .note {{ color:var(--dim); font-size:12px; font-style:italic; }}
</style></head><body><div class=wrap>
<h1>Settle Up</h1>
<div class=sub>session {e(rep['session'])} &middot; {e(rep['log'])} &middot; {len(rep['games'])} game(s)</div>
<div class=totals>
  <span><b>{t['games']}</b> games</span>
  <span>placements {e(str(t['placements'] or 'unknown'))}</span>
  <span><b>{t['phases']}</b> advised phases</span>
  <span><b>{t['taken']}</b> taken</span>
  <span><b>{t['ignored']}</b> not taken</span>
  <span><b>{t['bled']}</b> effective HP bled</span>
  <span><b>{t['spent']}g</b> spend</span>
</div>
<div class=caveat>{e(rep['caveat'])}</div>
<table><tr><th>game</th><th>hero</th><th>place</th><th>turns</th>
  <th>took/skipped</th><th>spend</th><th>final board</th><th>?</th></tr>
{chr(10).join(rows)}
</table>
<div class=sub style="margin-top:14px">Generated by Bob's Ledger &middot; schema {SCHEMA} &middot; {e(rep['created'])}</div>
</div></body></html>
"""


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
  /* Turn-by-turn boards. This section is the one thing the game itself never
     shows: what you went in with, what they brought, what survived. */
  .sect {{ font-size:13px; letter-spacing:.14em; text-transform:uppercase;
    color:var(--gold); margin:26px 0 2px; border-top:1px solid var(--gridline);
    padding-top:14px; }}
  .turn {{ background:var(--panel); border:1px solid var(--border);
    border-radius:6px; padding:8px 11px; margin:8px 0; }}
  .thead {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .tturn {{ font-weight:700; }}
  .tmeta {{ color:var(--dim); font-size:12px; }}
  .grw {{ color:var(--good); }}
  .comp {{ margin-left:auto; color:var(--gold); font-size:12px; }}
  .brow {{ display:flex; gap:9px; align-items:baseline; margin-top:3px; }}
  .blbl {{ color:var(--dim); font-size:11px; text-transform:uppercase;
    letter-spacing:.06em; flex:none; width:56px; }}
  .them {{ color:var(--bad); }}
  .q {{ color:var(--warn); font-size:12px; margin:3px 0 0 65px; }}
  .note {{ color:var(--dim); font-size:12px; font-style:italic;
    margin:2px 0 0 65px; }}
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
{_timeline_html(rep)}
<h2 class=sect>PHASE BY PHASE</h2>
<div class=sub>What the model would have played, and what the log says you did.</div>
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
    ap.add_argument("--session", action="store_true",
                    help="review EVERY game in the log, summarised (one full "
                         "review per game, so it costs ~7s per game)")
    ap.add_argument("--history", type=int, metavar="N", default=None,
                    help="aggregate the newest N session logs across games. "
                         "SLOW: every game is replayed twice (~7s each)")
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

    if args.history:
        paths = recent_logs(args.history)
        if not paths:
            print("No session logs found to build a history from.")
            return 2
        rep = build_history(paths)
        if args.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        else:
            print(render_history_text(rep))
        return 0

    if args.session:
        rep = build_session(log)
        if args.html:
            with open(args.html, "w", encoding="utf-8") as fh:
                fh.write(render_session_html(rep))
            print(f"wrote {args.html}")
        if args.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        elif not args.html:
            print(render_session_text(rep))
        return 0

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
