"""Minion value function for the coach.

Scores a board minion in the context of the current comp, hero power, trinkets,
and opponent board. Higher score = more valuable to keep. Used to answer "which
card is safest to sell?" via marginal contribution.

Design: analysis/VALUE_FUNCTION.md. The weights (W_*) are initial guesses,
intended to be tuned against real games.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Role weights: scaling engines > buff targets/utility > plain bodies > filler.
ROLE_VALUE = {"scaling": 2.0, "engine": 3.0, "utility": 1.0,
              "buff_target": 0.5, "plain": 0.0, "filler": -2.0}

# Rough term weights (tunable).
W_STATS = 0.1       # per point of (atk+hp)
W_BUFFS = 0.2       # per point of buffed-over-base stats
W_CORE = 3.0        # core card of the comp
W_ADDON = 1.5       # addon card of the comp
W_TRIBE = 1.0       # matches the comp's tribe
W_HERO = 1.5        # synergizes with the hero power
W_TRINKET = 1.0     # synergizes with a trinket
W_ENGINE_MULT = 0.05  # per point of scaling-minion stats it amplifies

# Keywords/phrases that mark a scaling/engine minion vs a plain body.
_SCALING_MARKERS = ("end of turn", "whenever you play", "improves", "each",
                    "triggers twice", "reborn", "deathrattle", "battlecry")
_ENGINE_MARKERS = ("double", "twice", "each turn", "each", "improve",
                   "scales", "compounding")


def _load_card_db():
    """card id -> {name, race, attack, health, mechanics, text} from the full DB."""
    path = os.path.join(_HERE, ".cards_full.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cards = json.load(f)
    out = {}
    for c in cards:
        out[c.get("id")] = {
            "name": c.get("name"),
            "race": c.get("race"),
            "attack": c.get("attack"),
            "health": c.get("health"),
            "mechanics": c.get("mechanics", []),
            "text": (c.get("text") or "").lower(),
        }
    return out


def _detect_role(minion, card):
    text = (card or {}).get("text") or ""
    mech = (card or {}).get("mechanics") or []
    # A compounding engine (scales with itself / each summon).
    if any(m in text for m in _ENGINE_MARKERS):
        return "engine"
    # Ongoing scaling (end-of-turn, whenever, buffs each turn).
    if any(m in text for m in _SCALING_MARKERS):
        return "scaling"
    # Utility keywords (taunt, divine shield, reborn, windfury, venomous, etc.).
    if any(k in mech for k in ("TAUNT", "DIVINE_SHIELD", "REBORN", "WINDFURY",
                               "VENOMOUS", "POISONOUS", "STEALTH")):
        return "utility"
    return "plain" if (minion.get("atk") or 0) >= 5 else "filler"


def _is_multiplier(card):
    """True if the card multiplies other minions' effects (Drakkari etc.)."""
    text = (card or {}).get("text") or ""
    return any(p in text for p in ("triggers twice", "trigger twice", "double",
                                   "extra time"))


def _is_scaling(card):
    text = (card or {}).get("text") or ""
    return any(m in text for m in _SCALING_MARKERS)


def minion_value(minion, card=None, comp=None, hero_power=None, trinkets=None,
                 board_scaling=0):
    """Score a board minion (higher = more valuable to keep).

    `board_scaling` is the number of scaling minions on the board; an effect
    multiplier (e.g. Drakkari doubling end-of-turn effects) is worth more the
    more scaling minions it amplifies.
    """
    atk = minion.get("atk") or 0
    hp = minion.get("health") or 0
    score = W_STATS * (atk + hp)

    # Engine potential: a multiplier amplifies every scaling minion on the board.
    if board_scaling and _is_multiplier(card):
        score += W_ENGINE_MULT * board_scaling

    if card:
        base_atk = card.get("attack") or 0
        base_hp = card.get("health") or 0
        buffed = (atk - base_atk) + (hp - base_hp)
        score += W_BUFFS * buffed

    if comp:
        if minion["card"] in comp.get("core", []):
            score += W_CORE
        elif minion["card"] in comp.get("addons", []):
            score += W_ADDON
        if comp.get("tribe") and minion.get("tribe") == comp["tribe"]:
            score += W_TRIBE

    # Role (scaling engine > utility > filler).
    score += ROLE_VALUE.get(_detect_role(minion, card), 0.0)

    # Hero power synergy (best-effort: shared tribe/keyword).
    if hero_power and card:
        hp_text = hero_power.lower()
        if card.get("race") and card["race"].lower() in hp_text:
            score += W_HERO
        for k in ("taunt", "divine shield", "reborn", "venomous"):
            if k in hp_text and k.replace(" ", "_").upper() in (card.get("mechanics") or []):
                score += W_HERO

    # Trinket synergy (best-effort: trinket mentions the tribe).
    if trinkets and card:
        for t in trinkets:
            if card.get("race") and card["race"].lower() in t.lower():
                score += W_TRINKET

    return score


def sell_recommendation(board_minions, comps, allowed_tribes=None):
    """Rank board minions from safest-to-sell to most-valuable.

    `board_minions`: list from board_state (each has card, atk, health, tribe).
    `comps`: dict of availabe comps (slug -> comp) already filtered by the ban.
    `allowed_tribes`: set of allowed tribes (for a weak ban penalty on banned-tribe
    minions that somehow remain).
    Returns a list of (card_id, score) sorted asecending (best to sell first).
    """
    card_db = _load_card_db()
    # Pick the comp whose tribe most overlaps the board (a crude comp fit).
    comp = _best_comp(board_minions, comps)
    hero_power = None
    trinkets = []
    # Total stats of the scaling minions on the board (a multiplier amplifies this).
    board_scaling = sum((m.get("atk") or 0) + (m.get("health") or 0)
                        for m in board_minions if _is_scaling(card_db.get(m["card"])))

    scored = []
    for m in board_minions:
        card = card_db.get(m["card"])
        val = minion_value(m, card, comp, hero_power, trinkets,
                           board_scaling=board_scaling)
        # Banned-tribe minions on the board are worth less (can't grow).
        if allowed_tribes and m.get("tribe") and m["tribe"] not in allowed_tribes:
            val -= 2.0
        scored.append((m["card"], val, comp))
    scored.sort(key=lambda x: (x[1], x[0]))
    return [(c, v) for c, v, _ in scored]


def _best_comp(board_minions, comps):
    """Pick the comp whose tribe best matches the board (crude fit)."""
    if not comps:
        return None
    tribes = {}
    for m in board_minions:
        t = m.get("tribe")
        if t:
            tribes[t] = tribes.get(t, 0) + 1
    best = None
    best_score = -1
    for slug, comp in comps.items():
        ct = comp.get("tribe")
        fit = tribes.get(ct, 0)
        if fit > best_score:
            best_score = fit
            best = comp
    return best


if __name__ == "__main__":
    # Smoke test: a small synthetic board.
    demo = [
        {"card": "BG_TTN_401", "atk": 178, "health": 168, "tribe": "MECHANICAL"},  # engine
        {"card": "BG29_503", "atk": 57, "health": 57, "tribe": "MECHANICAL"},      # filler
        {"card": "BG36_851", "atk": 148, "health": 153, "tribe": "MECHANICAL"},    # scaling
    ]
    ranked = sell_recommendation(demo, [])
    for c, v in ranked:
        print(f"  {c}: {v:.1f}")
