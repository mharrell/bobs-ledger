"""Deterministic growth simulator for the coach's value function.

The value function's `growth_potential(card)` is a flat heuristic — it can't
answer "if I cast 4 spells, how much do I actually gain?" This module models the
trigger chain deterministically: count the engine pieces on the board, apply the
multipliers, propagate the chain, and sum the stat gain.

This is the FIRST hard-coded engine (the Glambot / mechs-magnetics-spells comp)
to prove the shape before generalizing to a machine-readable engine model
(see memory `hearth-value-function`). The engine is a plain dict so it can be
lifted into `meta/engines.json` later.

Design: analysis/VALUE_FUNCTION.md. The numbers come from the card text in
`meta/minions.json` and the trinket text in `meta/trinkets.json`.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# The hard-coded engine model (first of many; to be generalized).
#
# The chain: cast a spell on a Mech -> Glambot magnetizes a 4/4 Satellite ->
# Copper Coil improves it -> Utility Drone scales per magnetization at end of
# turn. Balinda doubles the spell casts.
# ---------------------------------------------------------------------------
_GLAMBOT_ENGINE = {
    "name": "mechs-magnetics-spells",
    "trigger": "cast_spell_on_mech",   # the action that fires the chain
    "multipliers": {
        # Cards that double the trigger count. Balinda doubles spell casts.
        "spell_cast": {"Balinda": 2},
    },
    "chain": [
        # Each step: {source, per_trigger, applies_to}.
        # applies_to: "target_mech" (the minion being magnetized) or "all_minions".
        {"source": "Glambot", "per_trigger": {"atk": 4, "hp": 4},
         "applies_to": "target_mech",
         "note": "Magnetize a 4/4 Satellite per spell cast"},
        {"source": "Copper Coil", "per_trigger": {"atk": 1, "hp": 1},
         "applies_to": "target_mech",
         "note": "Trinket: +1/+1 per Magnetization"},
        {"source": "Utility Drone", "per_trigger": {"atk": 4, "hp": 4},
         "applies_to": "all_minions",
         "note": "End of turn: +4/+4 per Magnetization to all minions"},
    ],
}


def _count(board, name):
    """How many board minions are the named card (by name substring)."""
    return sum(1 for m in board if name.lower() in (m.get("name") or "").lower())


def _has(board, name):
    return _count(board, name) > 0


def simulate_growth(board, scenario, engine=None):
    """Deterministically propagate a trigger chain and sum the stat gain.

    `board`: list of minions from board_state (each has card, atk, health, tribe,
    and a `name` for engine-piece matching).
    `scenario`: {"spells_cast": N, "copper_coil": bool} — the input action count
    and whether the Copper Coil trinket is held.
    `engine`: the engine model (defaults to the hard-coded Glambot engine).

    Returns a dict with the total stat gain, a per-source breakdown, and the
    intermediate trigger counts — so the coach can explain *why*.
    """
    engine = engine or _GLAMBOT_ENGINE

    # 1. Count the engine pieces on the board.
    glambots = _count(board, "Glambot")
    balinda = _has(board, "Balinda")
    drone = _has(board, "Utility Drone")
    copper_coil = scenario.get("copper_coil", False)
    board_size = len(board)

    # 2. Trigger count. Each spell cast is doubled by Balinda; each Glambot
    #    magnetizes once per cast.
    spells = scenario.get("spells_cast", 0)
    casts = spells * engine["multipliers"]["spell_cast"].get("Balinda", 1) if balinda \
        else spells
    magnetizations = casts * glambots

    # 3. Propagate the chain, summing stat gain per source.
    gain = {"atk": 0, "hp": 0}
    breakdown = {}
    for step in engine["chain"]:
        src = step["source"]
        if src == "Glambot" and glambots:
            g = magnetizations * step["per_trigger"]["atk"]
            gain["atk"] += g
            gain["hp"] += g
            breakdown[step["note"]] = (g, g)
        elif src == "Copper Coil" and copper_coil:
            c = magnetizations * step["per_trigger"]["atk"]
            gain["atk"] += c
            gain["hp"] += c
            breakdown[step["note"]] = (c, c)
        elif src == "Utility Drone" and drone:
            d = magnetizations * step["per_trigger"]["atk"] * board_size
            gain["atk"] += d
            gain["hp"] += d
            breakdown[step["note"]] = (d, d)

    return {
        "engine": engine["name"],
        "spells_cast": spells,
        "casts": casts,
        "magnetizations": magnetizations,
        "gain": gain,
        "breakdown": breakdown,
    }


if __name__ == "__main__":
    # Demo: a synthetic Glambot board. Names are matched by substring, so the
    # board_state minions need a `name` field (the card DB provides it).
    board = [
        {"card": "BG36_853", "name": "Glambot", "atk": 4, "health": 4, "tribe": "MECHANICAL"},
        {"card": "BG36_853", "name": "Glambot", "atk": 4, "health": 4, "tribe": "MECHANICAL"},
        {"card": "BG35_883", "name": "Balinda Stonehearth", "atk": 6, "health": 6, "tribe": None},
        {"card": "BG26_152", "name": "Utility Drone", "atk": 4, "health": 6, "tribe": "MECHANICAL"},
        {"card": "BG26_152", "name": "Utility Drone", "atk": 4, "health": 6, "tribe": "MECHANICAL"},
        {"card": "BG26_ICC_901", "name": "Drakkari Enchanter", "atk": 1, "health": 5, "tribe": None},
        {"card": "BG_LOE_077", "name": "Brann Bronzebeard", "atk": 2, "health": 4, "tribe": None},
    ]
    for n in (1, 4):
        r = simulate_growth(board, {"spells_cast": n, "copper_coil": True})
        print(f"\n=== {n} spell(s) cast, Copper Coil held ===")
        print(f"  casts (Balinda x2): {r['casts']}  magnetizations: {r['magnetizations']}")
        for src, (a, h) in r["breakdown"].items():
            print(f"  {src}: +{a}/+{h}")
        print(f"  TOTAL: +{r['gain']['atk']}/+{r['gain']['hp']} "
              f"({r['gain']['atk'] + r['gain']['hp']} stats)")
