"""Deterministic growth simulator for the coach's value function.

The value function's `growth_potential(card)` is a flat heuristic — it can't
answer "if I cast 4 spells, how much do I actually gain?" This module models the
trigger chain deterministically: count the engine pieces on the board, apply the
multipliers, propagate the chain, and sum the stat gain.

The engine model is machine-readable (`meta/engines.json`): each engine declares
a primary trigger, a chain of steps (source card, buff per trigger, scope), and
which multiplier doubles each trigger type. Derived counters (e.g. "magnetize")
let one step's output feed another (Glambot produces magnetizations that Utility
Drone consumes). See memory `hearth-value-function`.

Step count conventions (`count_from`), besides the default "another counter x
how many of the source card are on the board":
  - `"self"`  — the source's OWN uses of the trigger: each copy is usable once
    per turn, so it can never exceed the turn's total trigger count (a discard
    outlet Activates once per turn, so its own discards = min(copies,
    discards)).
  - `"turn"`  — once per source copy per turn times `per_turn`, whatever the
    primary count is (Mysterious K'Thir discards its own 3 left-most Tavern
    spells at end of turn, no outlet needed).

Step type `deity_pool` (patch 36.6.1, analysis/discard_mechanic.md) banks stats
on the Deity instead of the board. The Deity joins ONE combat after three
sacrifices and then leaves, so its stats are per-combat power: they are returned
apart from `gain` (which stays "persistent board stats") in the result's
`deity` block — `deity` is the pool this turn's triggers banked, `realised` is
the expected per-turn swing once it awakens (C'Thun's split pays the pool out;
Y'Shaarj's deathrattle doesn't use it).

Design: analysis/VALUE_FUNCTION.md. Buff magnitudes come from card text in
`meta/minions.json` and `meta/trinkets.json`.
"""
import functools
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Multiplier cards: trigger type -> card names that double it when on the board.
_MULTIPLIERS = {
    "cast_spell": ["Balinda Stonehearth"],
    "end_of_turn": ["Drakkari Enchanter"],
    "battlecry": ["Brann Bronzebeard"],
    "deathrattle": ["Titus Rivendare"],
}


@functools.lru_cache(maxsize=1)
def _load_engines():
    path = os.path.join(_HERE, "meta", "engines.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _count(board, name):
    """How many board minions are the named card (by name substring)."""
    return sum(1 for m in board if name.lower() in (m.get("name") or "").lower())


def _is_golden(board, name):
    """True if a golden copy of the named card is on the board."""
    return any(name.lower() in (m.get("name") or "").lower() and m.get("golden")
               for m in board)


def _multiplier_for(trigger_type, board):
    """2 (or 3 if golden) if a doubling card for this trigger type is on the board."""
    for card in _MULTIPLIERS.get(trigger_type, []):
        if _count(board, card):
            return 3 if _is_golden(board, card) else 2
    return 1


def _scope_size(applies_to, board, tribe):
    """How many minions a step's buff lands on."""
    if applies_to == "all":
        return len(board)
    if applies_to == "tribe" and tribe:
        return sum(1 for m in board if (m.get("tribe") or "") == tribe)
    return 1  # "target"


def _tribe_units(board, tribe):
    """How many board minions are of `tribe` (case-insensitive substring).

    The meta DB prints display-case tribes ("Aberration"), the log's CARDRACE
    tag is upper-case ("ABERRATION"), and a compound tribe prints both parts —
    so the comparison is a case-insensitive containment, not equality.
    """
    if not tribe:
        return 0
    t = tribe.upper()
    return sum(1 for m in board if t in (m.get("tribe") or "").upper())


def simulate_growth(board, scenario, engine):
    """Deterministically propagate a trigger chain and sum the stat gain.

    `board`: list of minions from board_state (each has card, atk, health, tribe,
    and a `name` for engine-piece matching).
    `scenario`: {engine["trigger"]: N} — how many times the primary action fires
    this turn (e.g. {"cast_spell": 4}).
    `engine`: the engine model dict from meta/engines.json.

    Returns a dict with the total stat gain, a per-source breakdown, and the
    intermediate trigger counts — so the coach can explain *why*. A `deity`
    block (empty for engines with no "deity" section) carries the Deity pool
    banked by this turn's triggers and its expected per-turn realisation; it is
    deliberately NOT part of `gain`.
    """
    primary_count = scenario.get(engine["trigger"], 0)
    counters = {"primary": primary_count}
    gain = {"atk": 0, "hp": 0}
    breakdown = {}
    deity = {"atk": 0, "hp": 0}
    deity_breakdown = {}
    tribe = engine.get("tribe")

    for step in engine["chain"]:
        # Compounding shop-eat step (Nomi/Unbound, Felboar): each trigger buffs
        # the Tavern; every `eat_every` triggers the payoff eats the biggest
        # Tavern minion, whose stats have compounded (base + buff per play so far).
        if step.get("type") == "compounding":
            if not _count(board, step["source"]):
                continue
            # The Tavern buffs accumulate over the whole game, so a compounding
            # step uses the cumulative trigger count (scenario "<trigger>_total"),
            # not just this turn's count.
            if step.get("cumulative"):
                n = scenario.get(engine["trigger"] + "_total", primary_count)
            else:
                n = primary_count
            if step.get("multiplier"):
                n *= _multiplier_for(step["multiplier"], board)
            eat_every = step.get("eat_every", 3)
            buff = dict(step["buff_per_play"])
            if step.get("buff_source"):
                if _count(board, step["buff_source"]):
                    if _is_golden(board, step["buff_source"]):
                        buff = {k: v * 2 for k, v in buff.items()}  # golden Nomi
                else:
                    buff = {"atk": 0, "hp": 0}  # no shop-buff engine -> no compounding
            base = step["tavern_base"]
            eats = n // eat_every
            a = h = 0
            for j in range(1, eats + 1):
                plays = j * eat_every
                a += base["atk"] + buff["atk"] * plays
                h += base["hp"] + buff["hp"] * plays
            gain["atk"] += a
            gain["hp"] += h
            breakdown[step["source"]] = (a, h)
            continue

        # Tribe-scaling step (Ravaging Scorpid, Hooktusk): each trigger gives
        # +N/+N to all tribe minions, compounding over the game. Uses the step's
        # trigger count if the scenario provides it (e.g. discover_total); else
        # falls back to ~once per minion per turn (the attack proxy).
        if step.get("type") == "tribe_scaling":
            if not _count(board, step["source"]):
                continue
            trigger = step.get("trigger", engine["trigger"])
            n = scenario.get(trigger + "_total", scenario.get(trigger, 0))
            if n <= 0:
                n = len(board) * scenario.get("turns", 1)  # ~once/minion/turn
            buff = step["buff_per_trigger"]
            tribe_count = sum(1 for m in board if (m.get("tribe") or "") == engine.get("tribe"))
            a = n * buff["atk"] * tribe_count
            h = n * buff["hp"] * tribe_count
            gain["atk"] += a
            gain["hp"] += h
            breakdown[step["source"]] = (a, h)
            continue

        # A step may require a held trinket (e.g. Copper Coil) rather than a
        # board minion; skip it if the trinket isn't in the scenario.
        if step.get("requires_trinket") and \
                step["requires_trinket"] not in scenario.get("trinkets", []):
            continue
        # How many times this step fires. Default: its count source (the primary
        # trigger unless the step names a derived counter) x how many of the
        # source card are on the board. A trinket is held once, so its source
        # count is 1, not a board count. Two named conventions override that
        # (see the module docstring): "self" and "turn".
        source_count = 1 if step.get("requires_trinket") \
            else _count(board, step["source"])
        count_from = step.get("count_from", "primary")
        if count_from == "self":
            count = min(source_count, counters.get("primary", 0))
        elif count_from == "turn":
            count = source_count * step.get("per_turn", 1)
        else:
            count = counters.get(count_from, 0) * source_count
        # A multiplier (Balinda/Drakkari/Brann/Titus) doubles this step's trigger.
        if step.get("multiplier"):
            count *= _multiplier_for(step["multiplier"], board)
        # This step may produce a derived counter for downstream steps.
        if step.get("counts_as"):
            counters[step["counts_as"]] = count

        # A golden source card doubles its per-trigger buff.
        mult = 2 if _is_golden(board, step["source"]) else 1

        # A Deity-pool step BANKS stats on the Deity instead of the board. The
        # Deity joins one combat after three sacrifices and then leaves, so
        # these stats are per-combat power: summing them into `gain` would
        # report one-fight power as persistent board growth (the exact error
        # player rule 2026-09-11 exists to prevent). They accumulate in their
        # own bank and are realised separately.
        if step.get("type") == "deity_pool":
            a = count * step["per_trigger"]["atk"] * mult
            h = count * step["per_trigger"]["hp"] * mult
            deity["atk"] += a
            deity["hp"] += h
            deity_breakdown[step["source"]] = (a, h)
            continue

        scope = _scope_size(step.get("applies_to", "target"), board, tribe)
        a = count * step["per_trigger"]["atk"] * scope * mult
        h = count * step["per_trigger"]["hp"] * scope * mult
        gain["atk"] += a
        gain["hp"] += h
        breakdown[step["source"]] = (a, h)

    # The Deity's per-combat payoff, kept apart from `gain`. `awakenings` is 0
    # unless the board can actually make the three sacrifices the card text
    # requires (a friendly Aberration has to die for each one) — the engine's
    # "deity" block declares what it takes.
    out_deity = {"atk": deity["atk"], "hp": deity["hp"], "awakenings": 0,
                 "realised": {"atk": 0, "hp": 0}}
    block = engine.get("deity")
    if block and (deity["atk"] or deity["hp"]):
        if _tribe_units(board, block.get("requires_tribe")):
            out_deity["awakenings"] = block.get("awakenings_per_turn", 0)
        k = out_deity["awakenings"]
        share = block.get("payoff_share", 0.0)
        out_deity["realised"] = {"atk": deity["atk"] * k * share,
                                 "hp": deity["hp"] * k * share}

    return {
        "engine": engine["name"],
        "trigger": engine["trigger"],
        "primary_count": primary_count,
        "counters": counters,
        "gain": gain,
        "breakdown": breakdown,
        "deity": out_deity,
        "deity_breakdown": deity_breakdown,
    }


if __name__ == "__main__":
    engines = _load_engines()
    # Demo: a synthetic Glambot board (2 Glambots, Balinda, 2 Drones, Drakkari).
    glambot_board = [
        {"card": "BG36_853", "name": "Glambot", "atk": 4, "health": 4, "tribe": "MECHANICAL"},
        {"card": "BG36_853", "name": "Glambot", "atk": 4, "health": 4, "tribe": "MECHANICAL"},
        {"card": "BG35_883", "name": "Balinda Stonehearth", "atk": 6, "health": 6, "tribe": None},
        {"card": "BG26_152", "name": "Utility Drone", "atk": 4, "health": 6, "tribe": "MECHANICAL"},
        {"card": "BG26_152", "name": "Utility Drone", "atk": 4, "health": 6, "tribe": "MECHANICAL"},
        {"card": "BG26_ICC_901", "name": "Drakkari Enchanter", "atk": 1, "health": 5, "tribe": None},
        {"card": "BG_LOE_077", "name": "Brann Bronzebeard", "atk": 2, "health": 4, "tribe": None},
    ]
    for n in (1, 4):
        r = simulate_growth(glambot_board,
                            {"cast_spell": n, "trinkets": ["Copper Coil"]},
                            engines["mechs-magnetics-spells"])
        print(f"\n=== {r['engine']} — {n} spell(s) cast ===")
        print(f"  magnetizations: {r['counters'].get('magnetize')}")
        for src, (a, h) in r["breakdown"].items():
            print(f"  {src}: +{a}/+{h}")
        print(f"  TOTAL: +{r['gain']['atk']}/+{r['gain']['hp']} "
              f"({r['gain']['atk'] + r['gain']['hp']} stats)")

    # Demo: a Mana Surge Elemental board.
    ele_board = [
        {"card": "BG32_846", "name": "Unleashed Mana Surge", "atk": 6, "health": 5, "tribe": "ELEMENTAL"},
        {"card": "BG36_352", "name": "Unbound Tempest", "atk": 3, "health": 12, "tribe": "ELEMENTAL"},
        {"card": "BGS_104", "name": "Nomi, Kitchen Nightmare", "atk": 6, "health": 6, "tribe": None},
        {"card": "BG32_842", "name": "Glowing Cinder", "atk": 4, "health": 1, "tribe": "ELEMENTAL"},
        {"card": "BG_LOE_077", "name": "Brann Bronzebeard", "atk": 2, "health": 4, "tribe": None},
    ]
    r = simulate_growth(ele_board, {"play_elemental": 3},
                        engines["elementals-stat-scaling"])
    print(f"\n=== {r['engine']} — 3 Elementals played ===")
    for src, (a, h) in r["breakdown"].items():
        print(f"  {src}: +{a}/+{h}")
    print(f"  TOTAL: +{r['gain']['atk']}/+{r['gain']['hp']} "
          f"({r['gain']['atk'] + r['gain']['hp']} stats)")

    # Demo: a real Aberration board (the Faelin win, 2026-09-22: Faceless
    # Converter x2, Drifting Sacrifice, N'raqi Sapper, Mysterious K'Thir,
    # Titus Rivendare) with and without a discard OUTLET. The scenario's
    # `discard` count is the board's outlets — value._discard_scenario derives
    # it in the coach (not importable here: value imports this module), so the
    # demo passes it by hand, which is also the seam for counting discard
    # sources the board cannot show (hero powers, held cards, trinkets).
    aberration_board = [
        {"card": "BG36_318", "name": "Faceless Converter", "atk": 5, "health": 5, "tribe": "Aberration"},
        {"card": "BG36_318", "name": "Faceless Converter", "atk": 5, "health": 5, "tribe": "Aberration"},
        {"card": "BG36_113", "name": "Drifting Sacrifice", "atk": 2, "health": 1, "tribe": "Aberration"},
        {"card": "BG36_103", "name": "N'raqi Sapper", "atk": 6, "health": 3, "tribe": "Aberration"},
        {"card": "BG36_320", "name": "Mysterious K'Thir", "atk": 8, "health": 8, "tribe": "Aberration"},
        {"card": "BG25_354", "name": "Titus Rivendare", "atk": 1, "health": 7, "tribe": "All"},
    ]
    outlet = {"card": "BG36_099", "name": "Brain Rotter", "atk": 3, "health": 4, "tribe": "Aberration"}
    previous = None
    for label, extra, n in (("no outlet", [], 0),
                            ("1 outlet (Brain Rotter)", [outlet], 1)):
        r = simulate_growth(aberration_board + extra,
                            {"discard": n}, engines["aberrations-discard-deity"])
        print(f"\n=== {r['engine']} — Faelin board, {label}, "
              f"{n} discard(s)/turn ===")
        for src, (a, h) in r["breakdown"].items():
            if a or h:
                print(f"  board  {src}: +{a}/+{h}")
        for src, (a, h) in r["deity_breakdown"].items():
            if a or h:
                print(f"  Deity  {src}: +{a}/+{h}")
        d = r["deity"]
        print(f"  persistent board gain: +{r['gain']['atk']}/+{r['gain']['hp']}")
        print(f"  Deity pool banked: +{d['atk']}/+{d['hp']}  "
              f"awakenings {d['awakenings']}  -> realised "
              f"+{d['realised']['atk']:g}/+{d['realised']['hp']:g} "
              f"(per combat, NOT board stats)")
        total = r["gain"]["atk"] + r["gain"]["hp"] + \
            d["realised"]["atk"] + d["realised"]["hp"]
        print(f"  TOTAL per turn (board + realised Deity): {total:g} stats")
        if previous is not None:
            print(f"  marginal value of the outlet this turn: "
                  f"{total - previous:g} stats")
        previous = total
