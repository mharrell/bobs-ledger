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

Design: analysis/VALUE_FUNCTION.md. Buff magnitudes come from card text in
`meta/minions.json` and `meta/trinkets.json`.
"""
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


def _load_engines():
    path = os.path.join(_HERE, "meta", "engines.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _count(board, name):
    """How many board minions are the named card (by name substring)."""
    return sum(1 for m in board if name.lower() in (m.get("name") or "").lower())


def _multiplier_for(trigger_type, board):
    """2 if a doubling card for this trigger type is on the board, else 1."""
    for card in _MULTIPLIERS.get(trigger_type, []):
        if _count(board, card):
            return 2
    return 1


def _scope_size(applies_to, board, tribe):
    """How many minions a step's buff lands on."""
    if applies_to == "all":
        return len(board)
    if applies_to == "tribe" and tribe:
        return sum(1 for m in board if (m.get("tribe") or "") == tribe)
    return 1  # "target"


def simulate_growth(board, scenario, engine):
    """Deterministically propagate a trigger chain and sum the stat gain.

    `board`: list of minions from board_state (each has card, atk, health, tribe,
    and a `name` for engine-piece matching).
    `scenario`: {engine["trigger"]: N} — how many times the primary action fires
    this turn (e.g. {"cast_spell": 4}).
    `engine`: the engine model dict from meta/engines.json.

    Returns a dict with the total stat gain, a per-source breakdown, and the
    intermediate trigger counts — so the coach can explain *why*.
    """
    primary_count = scenario.get(engine["trigger"], 0)
    counters = {"primary": primary_count}
    gain = {"atk": 0, "hp": 0}
    breakdown = {}
    tribe = engine.get("tribe")

    for step in engine["chain"]:
        # A step may require a held trinket (e.g. Copper Coil) rather than a
        # board minion; skip it if the trinket isn't in the scenario.
        if step.get("requires_trinket") and \
                step["requires_trinket"] not in scenario.get("trinkets", []):
            continue
        # How many times this step fires: its count source (default the primary
        # trigger) x how many of the source card are on the board. A trinket is
        # held once, so its source count is 1, not a board count.
        base = counters.get(step.get("count_from", "primary"), 0)
        source_count = 1 if step.get("requires_trinket") else _count(board, step["source"])
        count = base * source_count
        # A multiplier (Balinda/Drakkari/Brann/Titus) doubles this step's trigger.
        if step.get("multiplier"):
            count *= _multiplier_for(step["multiplier"], board)
        # This step may produce a derived counter for downstream steps.
        if step.get("counts_as"):
            counters[step["counts_as"]] = count

        scope = _scope_size(step.get("applies_to", "target"), board, tribe)
        a = count * step["per_trigger"]["atk"] * scope
        h = count * step["per_trigger"]["hp"] * scope
        gain["atk"] += a
        gain["hp"] += h
        breakdown[step["source"]] = (a, h)

    return {
        "engine": engine["name"],
        "trigger": engine["trigger"],
        "primary_count": primary_count,
        "counters": counters,
        "gain": gain,
        "breakdown": breakdown,
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
