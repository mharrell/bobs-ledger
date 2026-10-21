#!/usr/bin/env python3
"""The model-vs-player comparison, derived ONCE at build (2026-10-20).

WHY THIS IS A MODULE AND NOT A FUNCTION IN settle_up
`settle_up.build` owns the review's shape; this owns one derived artifact that
every coaching surface reads (the Summary rail, the turn strip, the Step-through
callout). Four renderers re-deriving it would drift — this project has been bitten
twice by exactly that (the `shop_rank`/entity dedupe, the two coach cadences), so
the derivation has one home and the page only renders.

THE WALL
Build-time only. Nothing here may be imported by `live.py`, `live_coach.py`,
`value.py`, or the live path of `coach_ui`: the live page ships STATE, the review
ships the verdict, and `coach_ui.LIVE_VERDICT_KEYS` is what enforces it. A
coaching row reaches a page only through a SAVED replay.

WHAT A ROW IS
One row per phase per KIND of move, in a fixed display order (level, buy, sell,
play, cast, roll, pick) — the mockups' order, and the order the plan's own
vocabulary reads in. A kind appears when either side has something to say: the
model's plan asked for it, or the player did it. ONE EXCEPTION, measured: `play`
and `cast` rows appear only where the PLAN asked for one, because their action
records are too broad to compare (a bought minion also "plays", and a hero power
also "casts" — `_cards_kind` carries the numbers).

  "model":  {"asked": bool, "cards": [id, ...]}   the plan's steps of that kind
  "player": {"did": bool, "cards": [id, ...]}     the log's own records
  "state":  same | differs | not_reached | not_comparable
  "margin": model-best minus player-best ON THE COACH'S OWN RANKING (buy only)
  "tier":   {"from": 4, "to": 5} on a level row, when the tier is known
  "reason": the plan step's own prose reason, when it wrote one
  "why":    the one-line number behind a `differs`, built here so it cannot drift

FOUR STATES, AND THE ONE THAT IS EASY TO GET WRONG

* `same` — the model asked and the player did it. For a buy that means EVERY
  card the plan named was bought: a turn that took the model's card and also
  bought a second thing is NOT a difference (the `taken` lesson,
  settle_up.py:224-230), but a turn that skipped one of two named cards is.
* `differs` — the player's action for that kind does not cover the ask.
* `not_reached` — the plan's own PRIORITY LIST could not pay for the step, so
  "you didn't do it" would be an accusation about a move the purse never
  allowed. This is about the MODEL's order, not the player's: if the player
  bought the card anyway, the row is `same`, because they evidently paid for it.
* `not_comparable` — the two sides cannot be matched at all: a sell step names
  its victim only in prose (no id), a pick names a hero power or trinket the shop
  ranking never prices, or the player bought only cards from a shop the coach no
  longer holds (they rolled before buying). Say so; never default to `differs` —
  `outcome_audit.disagreement_rows`' own docstring is the rule.

THE MARGIN IS SIGNED, AND NEVER NEGATIVE IN PRACTICE FOR A BUY
Measured 2026-10-20 over the saved games that still have their source log (10 of
18; 112 advised phases, 66 of them with a buy step): `disagreement_rows` reports
ZERO rows, and that is structural, not a data problem — its `delta > 0` asks
whether the player bought something the coach ranked ABOVE the card it
recommended, and the plan's buy card is the top of that same ranking, so the
delta is never positive. The comparison this feature draws is therefore the plain
signed margin `score(model card) - score(best card the player bought)`.

Of those 66 buy phases only 20 are scorable at all: the other 46 bought after a
roll, so the card the player took is not on the ranking the coach settled with.
That is why the row's STATE is decided by the LISTS (which always exist) and the
margin is an enrichment — 20 of 66 gets a number, the rest still say what each
side did. On the 20: median +2.8, 55% at or above 1.5, 40% at or above 3.0, max
+10.5, and the six 0.0s are the cases where the player bought the named card.
A NEGATIVE margin is possible in principle and is not a fault either: the plan
ranks by the score PLUS reasons the score does not carry (synergy, tier curve, a
held triple), which is why `reason` rides the row beside the number and why only
a POSITIVE margin can raise `confidence`.

`MARGIN_CLEAR` is where a positive margin is worth calling a preference; it is a
display threshold on a number the review prints anyway, never a claim about who
is right. See analysis/COACHING_PLAN_2026_10_20.md §10.1.
"""
import os

import replay_store

#: Display order of the kinds a row may exist for. Hold/swap/discard/note are
#: deliberately absent: `settle_up._verdict` already refuses to grade them.
KIND_ORDER = ("level", "buy", "sell", "play", "cast", "roll", "pick")

#: A positive buy margin at or above this is "the model preferred its card".
#: MEASURED 2026-10-20 on the 20 scorable buy phases: the median gap is +2.8,
#: 55% sit at or above 1.5 and 40% at or above 3.0, with a gap between 1.0 and
#: 2.5 — so 1.5 keeps the `why` line for the cases with a number worth reading
#: and leaves the close ones silent. A display threshold, not a verdict.
MARGIN_CLEAR = 1.5
#: A positive margin this large is a strong preference. Below MARGIN_CLEAR the
#: two picks are close enough that the row should say nothing about preferring.
MARGIN_STRONG = 3.0

#: The plural the evidence line prints ("we differed on 9 level-ups").
EVIDENCE_PLURALS = {"level": "level-ups", "buy": "buys", "sell": "sells",
                    "play": "plays", "cast": "casts", "roll": "rolls",
                    "pick": "picks"}


def _unique(xs):
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def _indexed(steps, kind):
    return [(i, s) for i, s in enumerate(steps) if s.get("kind") == kind]


def _first_reason(indexed):
    for _i, s in indexed or []:
        if s.get("reason"):
            return s["reason"]
    return None


def _cost(step, row):
    """What one plan step would cost, for the not_reached walk.

    DELIBERATELY CONSERVATIVE, and for the reason `outcome_audit`'s asymmetry
    note gives: `shop_costs` carries raw COST tags that are STALE legacy tier
    costs for MINIONS and real prices for SPELLS, and telling the two apart
    needs a card-type lookup this module does not have. Reading a stale 27 as a
    minion's price would manufacture `not_reached` on ordinary advice, so a buy
    costs the flat 3 (the patch's real minion price) unless the cost map prices
    it at most that — a spell's 2-3 is safe, a legacy 27/28 is ignored.
    Everything else counts as free: the walk only ever claims a step was out of
    reach when the plan's own PURCHASES already could not be paid for.
    """
    kind = step.get("kind")
    if kind == "level":
        cost = row.get("level_cost")
        return cost if isinstance(cost, int) and cost >= 0 else 0
    if kind == "buy":
        priced = (row.get("shop_costs") or {}).get(step.get("card"))
        if isinstance(priced, int) and 0 <= priced <= 3:
            return priced
        return 3
    if kind == "roll":
        return 1
    return 0


def _reached(steps, row):
    """step index -> could the plan's own priority list have paid for it.

    Walks in the plan's order with the gold at open. A step that does not fit
    consumes nothing, and the walk goes on — a FREE step after an unaffordable
    one is still reachable in its own right.
    """
    gold = row.get("gold")
    if not isinstance(gold, int):
        # An unknown purse is not evidence of anything (the 2026-10-03 bug was
        # `gold: None` on every row). Make no claim rather than a wrong one.
        return {i: True for i in range(len(steps))}
    spent, out = 0, {}
    for i, step in enumerate(steps):
        cost = _cost(step, row)
        fits = spent + cost <= gold
        out[i] = fits
        if fits:
            spent += cost
    return out


def _row(kind, state, asked, did, model=(), player=(), reason=None,
         margin=None, why=None, tier=None):
    out = {
        "kind": kind,
        "state": state,
        "model": {"asked": bool(asked), "cards": list(model)},
        "player": {"did": bool(did), "cards": list(player)},
        "reason": reason,
        "margin": margin,
        "why": why,
    }
    if tier is not None:
        out["tier"] = tier
    return out


def _margin(row, model, player):
    """(margin, why) on the coach's own ranking, or (None, None).

    Only cards the coach PRICED count: a card from a shop it no longer holds is
    not evidence of anything (`disagreement_rows`' rule), and one unpriced side
    makes the subtraction meaningless.
    """
    rank = dict(row.get("shop_rank") or [])
    m = [rank[c] for c in model if c in rank]
    p = [rank[c] for c in player if c in rank]
    if not m or not p:
        return None, None
    out = round(max(m) - max(p), 1)
    if out >= MARGIN_CLEAR:
        why = f"its ranking gives {max(m):.1f} against {max(p):.1f}"
    else:
        # Zero, close, or negative: either no preference worth naming, or the
        # plan chose a lower-scored card for a reason the score cannot carry —
        # which rides the row as `reason`.
        why = None
    return out, why


def _buy(row, steps, reached):
    buy = _indexed(steps, "buy")
    model = _unique([s.get("card") for _i, s in buy])
    bought = list((row.get("player_buys") or []))
    if not buy and not bought:
        return None
    asked, did = bool(buy), bool(bought)
    reason = _first_reason(buy)
    fits = reached.get(buy[0][0], True) if buy else True
    if buy and not model:
        # A buy step the plan could not resolve to a card id.
        return _row("buy", "not_comparable", asked=True, did=did,
                    player=bought, reason=reason)
    if not buy:
        # The player bought something the plan never asked for.
        return _row("buy", "differs", asked=False, did=True, player=bought)
    if did and set(model) <= set(bought):
        return _row("buy", "same", asked=True, did=True, model=model,
                    player=bought, reason=reason)
    if not did and fits:
        return _row("buy", "differs", asked=True, did=False, model=model,
                    reason=reason)
    if not fits:
        # Whatever the player did, the plan's own order could not pay for this
        # step; "you didn't follow it" would be a claim about gold, not choice.
        return _row("buy", "not_reached", asked=True, did=did, model=model,
                    player=bought, reason=reason)
    margin, why = _margin(row, model, bought)
    return _row("buy", "differs", asked=True, did=True, model=model,
                player=bought, reason=reason, margin=margin, why=why)


def _level(row, steps, reached):
    level = _indexed(steps, "level")
    asked = bool(level)
    did = bool((row.get("player_actions") or {}).get("upgrades"))
    if not asked and not did:
        return None
    tier = row.get("tier")
    fits = reached.get(level[0][0], True) if level else True
    state = "same" if asked == did else "differs"
    if asked and not did and not fits:
        state = "not_reached"
    return _row("level", state, asked=asked, did=did,
                reason=_first_reason(level),
                tier={"from": tier, "to": tier + 1} if isinstance(tier, int)
                else None)


def _sell(row, steps):
    sell = _indexed(steps, "sell")
    sold = list((row.get("player_actions") or {}).get("sells") or [])
    asked, did = bool(sell), bool(sold)
    if not asked and not did:
        return None
    if asked and did:
        # A sell step names its victim only in prose — there is no id to match
        # the log's sell against, and guessing from the rendered text is
        # "formatting used as data". Say it cannot be compared.
        return _row("sell", "not_comparable", asked=True, did=True,
                    player=sold, reason=_first_reason(sell))
    return _row("sell", "differs", asked=asked, did=did, player=sold,
                reason=_first_reason(sell))


def _roll(row, steps):
    roll = _indexed(steps, "roll")
    asked = bool(roll)
    did = bool((row.get("player_actions") or {}).get("refreshes"))
    if not asked and not did:
        return None
    return _row("roll", "same" if asked == did else "differs",
                asked=asked, did=did, reason=_first_reason(roll))


def _cards_kind(kind, row, steps):
    """play / cast / pick: the plan names a card, the log names its own."""
    plan = _indexed(steps, kind)
    model = _unique([s.get("card") for _i, s in plan])
    if kind == "play":
        mine = list(row.get("plays") or [])
    elif kind == "cast":
        mine = list(row.get("spells_cast") or [])
    else:
        mine = []
    if not plan and not mine:
        return None
    if kind in ("play", "cast") and not plan:
        # PLAYER-ONLY play/cast rows are NOT emitted, and this is a measurement
        # (2026-10-20, the Reno game): `player_actions.plays` fires when an
        # entity moves HAND -> PLAY, which a BOUGHT minion does on its way to
        # the board — so a "play" row read "it asked for nothing, you played 2"
        # on almost every phase, double-counting the buy. `spells_cast` is
        # broader still: the parser counts any id that is not a known minion, so
        # hero powers and triple rewards ride it (`TB_BaconShop_HP_046`,
        # `TB_BaconShop_Triples_01`). The player-only row would therefore be
        # noise dressed as a comparison; a row appears only where the PLAN named
        # a play/cast, which is also what §5.1 first said.
        return None
    asked, did = bool(plan), bool(mine)
    reason = _first_reason(plan)
    if kind == "pick":
        # A pick's card is never in the shop ranking (a hero power or trinket)
        # and the audit row carries no player pick to match it with.
        return _row("pick", "not_comparable", asked=True, did=False,
                    model=model, reason=reason)
    if plan and not model:
        # A cast/play step whose card did not resolve (a token the DB cannot
        # name). "Something else" would be a guess.
        return _row(kind, "not_comparable", asked=True, did=did, player=mine,
                    reason=reason)
    if not did:
        return _row(kind, "differs", asked=True, did=False, model=model,
                    reason=reason)
    if set(model) <= set(mine):
        return _row(kind, "same", asked=True, did=True, model=model,
                    player=mine, reason=reason)
    return _row(kind, "differs", asked=True, did=True, model=model,
                player=mine, reason=reason)


def for_phase(row):
    """The comparison rows for one advised phase (an `outcome_audit` row).

    Pure. Returns [] for a phase with no plan and no actions — the caller's
    "nothing to compare" is an empty list, not a row of dashes.
    """
    steps = list(row.get("steps") or [])
    reached = _reached(steps, row)
    return [r for r in (
        _level(row, steps, reached),
        _buy(row, steps, reached),
        _sell(row, steps),
        _cards_kind("play", row, steps),
        _cards_kind("cast", row, steps),
        _roll(row, steps),
        _cards_kind("pick", row, steps),
    ) if r is not None]


def confidence(rows):
    """High / medium / None for a phase, from the best positive margin.

    Only a POSITIVE margin can raise it: a phase where the model named a
    lower-scored card has no confidence ABOUT PREFERRING it, whatever its reason
    — the row still says what it said, and the reason is on the row.
    """
    margins = [r["margin"] for r in rows
               if r.get("margin") is not None and r["margin"] > 0]
    if not margins:
        return None
    top = max(margins)
    if top >= MARGIN_STRONG:
        return "high"
    if top >= MARGIN_CLEAR:
        return "medium"
    return None


# ---------------------------------------------------------------- the evidence

#: One entry per store signature; a rebuilt store changes the signature and the
#: count is redone once. Never per page-open (18 files, ~2.2 MB measured).
_EVIDENCE = {}


def _signature(root):
    d = replay_store.store_dir(root)
    try:
        rows = [e for e in os.scandir(d)
                if e.name.endswith(".json") and not e.name.endswith(".tmp")]
    except OSError:
        return (d, 0, 0.0, 0)
    return (d, len(rows),
            max((e.stat().st_mtime for e in rows), default=0.0),
            sum(e.stat().st_size for e in rows))


def saved_evidence(root=None):
    """How often the player and the model differed, across the SAVED games.

    A DIFFERENCE COUNT, never a claim that the model was right (decision 3 of the
    plan): "we differed on 9 level-ups across your 18 saved games". Computed at
    build from the store and cached on its file count + mtime + byte size.

    Two rules, because the store holds two vintages:
      * a replay carrying `coach_diff` contributes one count per DIFFERING kind
        in the phase;
      * an older save carries no rows, so it contributes its phase LEAD when
        that lead was graded and not taken (`kind == "ignored"`) — the same
        question asked with the data it has.
    Counts therefore rise when an old save is Rebuilt. The line is a floor, not
    a census, and the wording says "differed", never "the model was right".
    """
    key = _signature(root)
    hit = _EVIDENCE.get(key)
    if hit is not None:
        return hit
    by_kind, games = {}, 0
    for entry in replay_store.list(root=root):
        stored = replay_store.load(entry["id"], root=root) or {}
        rep = stored.get("rep") or {}
        phases = rep.get("phases")
        if not phases:
            continue
        games += 1
        for ph in phases:
            diff = ph.get("coach_diff")
            if diff is not None:
                for r in diff:
                    if r.get("state") == "differs":
                        k = r.get("kind")
                        by_kind[k] = by_kind.get(k, 0) + 1
                continue
            if ph.get("kind") != "ignored":
                continue
            k = ph.get("lead")
            if k == "hunt-roll":
                k = "roll"
            if k in KIND_ORDER:
                by_kind[k] = by_kind.get(k, 0) + 1
    out = {"games": games, "by_kind": by_kind}
    _EVIDENCE.clear()
    _EVIDENCE[key] = out
    return out


def evidence_line(ev, kind=None):
    """The sentence a surface prints, or None when there is nothing to say.

    One place, so the wording cannot drift between the surfaces that show it.
    Counts only — `settle_up.CAVEAT` is the limits line and lives in settle_up.
    """
    if not ev or not ev.get("games"):
        return None
    counts = ev.get("by_kind") or {}
    n = counts.get(kind) if kind else sum(counts.values())
    if not n:
        return None
    what = EVIDENCE_PLURALS.get(kind, kind) if kind else "moves"
    return (f"we differed on {n} {what} across your {ev['games']} saved "
            f"game{'s' if ev['games'] != 1 else ''}")
