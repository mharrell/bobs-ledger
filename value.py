"""Minion value function for the coach.

Scores a board minion in the context of the current comp, hero power, trinkets,
and opponent board. Higher score = more valuable to keep. Used to answer "which
card is safest to sell?" via marginal contribution.

Design: analysis/VALUE_FUNCTION.md. The weights (W_*) are initial guesses,
intended to be tuned against real games.
"""
import functools
import json
import os
import re

import meta
from simulate_growth import _MULTIPLIERS, _load_engines, simulate_growth
from tribes import is_banned, normalize

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
W_ENGINE = 15.0     # bonus for the board's engine piece (e.g. Nomi, Glambot)
W_COMBAT_SCALE = 4.0  # bonus for combat-time scaling minions (e.g. Flaming Enforcer)
W_ENGINE_SIM = 0.05  # per stat of simulated growth the board's engine drives
W_ENGINE_OFF_TRIBE = 0.4  # engine whose tribe fights the board's dominant
                          # tribe: its scaling lands on minions you're about
                          # to stop buying (Deflect-o-Bot atop a beast shop,
                          # 2026-09-06 Reno game t7) — credit damped, not erased
W_GROWTH = 2.0      # per point of growth potential (how much a minion can scale)
W_SPELL_FUEL = 0.3  # per stat of marginal engine growth one spell cast buys
W_OFF_COMP = -2.0   # shop card whose tribe fights a COMMITTED comp (damping)
W_MULT = 4.0        # multiplier glue (Balinda/Drakkari-class): worth what it
                    # amplifies, not its stats — never "safest to sell" glue
W_SELL_FLOOR = 16.0  # comp glue can't rank into "safe to sell" (below the
                     # SELL_FILLER_SCORE threshold shared with top_move and the UI)
SELL_FILLER_SCORE = 15.0  # a board/shop value under this reads as clear filler
                          # (top_move; the overlay keys its coloring off it too)
DYING_HEALTH = 12  # effective health (hp+armor) at/below this = "dying" —
                   # leveling beats board (top_move's Q0 gate)

# Keywords/phrases that mark a scaling/engine minion vs a plain body.
_SCALING_MARKERS = ("end of turn", "whenever you play", "improves", "each",
                    "triggers twice", "reborn", "deathrattle", "battlecry",
                    "spellcraft")
_ENGINE_MARKERS = ("double", "twice", "each turn", "each", "improve",
                   "scales", "compounding")
# Whole-board/comp scaling engines (buff the whole board or a tribe).
_ENGINE_TEXT_MARKERS = ("give ", "your ", "play a ", "play an ", "gain +",
                        "after you buy", "each turn", "whenever you summon",
                        "whenever you cast", "whenever you play", "scales")
# Combat-time scaling (invisible to the pre-combat board snapshot).
_COMBAT_SCALE_MARKERS = ("in combat", "start of combat", "during combat",
                         "when this attacks", "this gains")

# Spell-scope markers: the effect hits every board minion, not one target.
_SPELL_SCOPE_ALL = ("your minions", "all minions", "give minions", "all friendly")
# One-shot utility effects the stat-grant parse can't see (rough point values).
_SPELL_UTILITY = (("discover", 2.0), ("summon", 2.0), ("triple", 3.0),
                  ("steal", 2.0), ("copy of", 2.0), ("freeze", 1.0))
# Spell text markers for a value that repeats over the game (scaling spells).
_SPELL_SCALING_MARKERS = ("each turn", "end of turn", "this game",
                          "whenever you", "after you")


@functools.lru_cache(maxsize=1)
def _load_card_db():
    """card id -> {name, race, attack, health, mechanics, text} from the BG pool.

    Loads from meta/minions.json (the 245-minion Battlegrounds pool), NOT the
    full hearthstonejson DB (.cards_full.json) which doesn't carry BG card IDs —
    the value function was blind to BG card text (e.g. Ravaging Scorpid's Beetle
    scaling) and underrated them. See VALUE_FUNCTION.md "BG-pool guardrail".
    """
    out = {}
    for c in meta.minions():
        out[c.get("id")] = {
            "name": c.get("name"),
            "race": c.get("tribe"),  # minions.json uses 'tribe', not 'race'
            "attack": c.get("attack"),
            "health": c.get("health"),
            "tier": c.get("tier"),  # pool tier — NOT the buy price since 36.4.x
            "mechanics": c.get("mechanics", []),
            "text": (c.get("text") or "").lower(),
        }
    return out


@functools.lru_cache(maxsize=1)
def _load_spell_db():
    """card id -> {name, tier, cost, text} from meta/tavern_spells.json."""
    return {s.get("id"): s for s in meta.spells() if s.get("id")}


def _spell_effect(spell, board_size=0):
    """Rough direct-effect points of a tavern spell from its text.

    +N/+N (and bare +N) grants count their stat points; a whole-board scope
    multiplies by the current board size (capped at 7). Recurring/scaling
    text doubles the value; one-shot utility effects the stat parse can't see
    (discover, summon, triple, steal) add flat amounts. Rough by design —
    the terms get honed against the replay corpus like every other weight.
    """
    text = (spell.get("text") or "").lower()
    scope_all = any(p in text for p in _SPELL_SCOPE_ALL)
    n_targets = min(max(board_size, 1), 7) if scope_all else 1
    pairs = [(int(m.group(1)) + int(m.group(2)))
             for m in re.finditer(r"\+(\d+)/\+(\d+)", text)]
    # Bare "+N" grants (one-sided buffs, gold) count half — no stat pairing.
    bares = [int(m.group(1)) * 0.5 for m in
             re.finditer(r"\+(\d+)", re.sub(r"\+\d+/\+\d+", "", text))]
    # A Choose One spell resolves ONE branch — take the best, not the sum.
    if "choose one" in text:
        points = max(pairs + bares, default=0.0) * 1.0
    else:
        points = sum(pairs) + sum(bares)
    points *= n_targets
    # The effect repeats or improves over the game ("end of YOUR turn" included).
    if "end of" in text and "turn" in text:
        points *= 2.0
    elif any(m in text for m in _SPELL_SCALING_MARKERS):
        points *= 2.0
    for kw, v in _SPELL_UTILITY:
        if kw in text:
            points += v
    return points


def _spell_fuel_bonus(board_minions, names, scenario=None, extra_casts=0):
    """Marginal growth one extra spell cast buys on the board's cast-spell engines.

    For each running engine whose trigger is cast_spell, run the simulator at
    the current per-turn cast count and at +1; the delta is exactly what one
    bought spell is worth as engine fuel. Returns the best single-engine delta
    (one gold buys one cast — spells don't stack). `extra_casts`: spells that
    GENERATE cast events (Spellcraft grants) add their k to the +1 — the Naga
    losing-game report: Spitescale Special (Get 3 random Spellcraft spells)
    produced 4 triggers, not 1, which is what kept the board alive.
    """
    if not board_minions:
        return 0.0
    sc = dict(scenario or _DEFAULT_SCENARIO)
    n = sc.get("cast_spell", 0)
    best = 0.0
    for slug, engine in _load_engines().items():
        if slug.startswith("_") or engine.get("trigger") != "cast_spell":
            continue
        core_steps = [s for s in engine["chain"] if s.get("counts_as")] or engine["chain"]
        if not any(_has_card(board_minions, s["source"], names) for s in core_steps):
            continue
        enriched = [dict(m, name=names.get(m["card"], "")) for m in board_minions]
        base = simulate_growth(enriched, dict(sc, cast_spell=n), engine)["gain"]
        plus = simulate_growth(
            enriched, dict(sc, cast_spell=n + 1 + extra_casts), engine)["gain"]
        delta = (plus["atk"] + plus["hp"]) - (base["atk"] + base["hp"])
        best = max(best, delta)
    return best


_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _extra_casts(spell):
    """How many extra cast events this spell generates beyond itself.

    Parsed from text: Spellcraft grants ("Get 3 random Spellcraft spells") and
    explicit extra-cast phrasing. Each generated cast feeds cast-spell engines
    exactly like another bought spell.
    """
    text = (spell or {}).get("text") or ""
    text = text.lower()
    k = 0
    m = re.search(r"get (\d+|\w+) random spellcraft", text)
    if m:
        w = m.group(1)
        k += _WORD_NUM.get(w) or (int(w) if w.isdigit() else 1)
    if "extra cast" in text or "additional cast" in text:
        k += 1
    return k


def _spell_score(spell, board_minions, names, scenario=None):
    """Value of buying a tavern spell now — comparable to minion shop scores.

    Direct effect per gold (a 1-cost +3/+1 competes with a tier-1 body), plus
    the engine-fuel bonus when the board runs a cast-spell engine: the spell
    converts spare gold into the engine's per-cast growth.
    """
    cost = spell.get("cost") or spell.get("tier") or 1
    points = _spell_effect(spell, len(board_minions or []))
    fuel = _spell_fuel_bonus(board_minions, names, scenario,
                             extra_casts=_extra_casts(spell))
    return points / max(cost, 1) + W_SPELL_FUEL * fuel


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
    """True if the card multiplies other effects (Drakkari, Balinda, Brann,
    Titus — the comp's glue; "cast twice" is Balinda, which the 2026-09-04
    1st-place game sold three phases running because only the "trigger
    twice" forms were recognized)."""
    text = (card or {}).get("text") or ""
    return any(p in text for p in ("triggers twice", "trigger twice",
                                   "cast twice", "casts twice", "double",
                                   "extra time", "twice"))


def _is_scaling(card):
    text = (card or {}).get("text") or ""
    return any(m in text for m in _SCALING_MARKERS)


def _is_engine(card):
    """True if the card is a whole-board/comp scaling engine (e.g. Nomi)."""
    text = (card or {}).get("text") or ""
    return any(m in text for m in _ENGINE_TEXT_MARKERS)


def _is_combat_scaling(card):
    """True if the card scales during combat (invisible to the snapshot)."""
    text = (card or {}).get("text") or ""
    return any(m in text for m in _COMBAT_SCALE_MARKERS)


def growth_potential(card):
    """Estimate a minion's growth potential from its text.

    The value function sees current stats; this estimates how much a minion can
    *scale* over the game. It scores the growth mechanism (how often the trigger
    fires) and the magnitude (the buff size). A 4/4 Glambot that magnetizes a
    4/4 Satellite per spell has high growth potential even though its stats are
    small.

    A one-time effect (battlecry, a single deathrattle proc) is TEMPO, not
    growth: its +N/+N magnitude is discounted 4x, so a +10/+10 battlecry can't
    outrank a real repeating scaler (this inflated one-shot battlecries like
    En-Djinn Blazer above genuine comp engines — the 2026-09-01 inconsistency).
    """
    text = (card or {}).get("text") or ""
    score = 0.0
    # Growth triggers — how often the effect fires.
    if "end of" in text and "turn" in text:  # "end of YOUR turn" included
        score += 2.0
    if "whenever you play" in text or "whenever you summon" in text:
        score += 3.0
    if "whenever you cast" in text or "after you cast" in text:
        score += 4.0  # spell comps cast a lot
    if "magnetize" in text:
        score += 4.0
    if "battlecry" in text:
        score += 1.0  # one-shot: plays once (was 2.0 — treated as scaling)
    if "spellcraft" in text:
        score += 2.0  # a per-turn generator (Rimescale-class stat spells)
    if "deathrattle" in text:
        score += 2.0
    if "improve" in text:
        score += 3.0  # compounding
    if "gain its stats" in text or "consume" in text:
        score += 3.0  # eat-growth
    # Magnitude — the buff size (+N/+N). Only a REPEATING trigger's magnitude
    # compounds over the game; one-shot effects don't.
    m = re.search(r"\+(\d+)/\+(\d+)", text)
    if m:
        mag = (int(m.group(1)) + int(m.group(2))) / 2.0
        repeating = any(m2 in text for m2 in (
            "whenever you", "after you", "each turn",
            "improve", "consume", "gain its stats", "magnetize")) \
            or ("end of" in text and "turn" in text)
        score += mag if repeating else mag / 4.0
    return score


def minion_value(minion, card=None, comp=None, hero_power=None, trinkets=None,
                 board_scaling=0, dominant_tribe=None, engine_bonus=0):
    """Score a board minion (higher = more valuable to keep).

    `board_scaling` is the combined stats of scaling minions on the board (an
    effect multiplier amplifies them). `dominant_tribe` is the board's most
    common tribe; the board's engine piece is the most valuable card even when
    its own stats are small. `engine_bonus` is the simulated growth the board's
    engine drives, attributed to this minion if it's an engine piece.
    """
    atk = minion.get("atk") or 0
    hp = minion.get("health") or 0
    score = W_STATS * (atk + hp)

    # Engine potential: a multiplier amplifies every scaling minion on the board.
    if board_scaling and _is_multiplier(card):
        score += W_ENGINE_MULT * board_scaling
    # Multiplier glue: Balinda/Drakkari/Brann-class cards are worth what they
    # AMPLIFY, not their own stats (the 2026-09-04 1st-place game sold
    # Balinda three phases running). The board_scaling term only counts
    # on-board scaling stats, which misses spell multipliers (Balinda
    # doubles every stat spell cast); this modest floor helps everywhere,
    # and sell_recommendation adds a comp-glue floor on top.
    if _is_multiplier(card):
        score += W_MULT

    # Engine recognition: the board's engine (e.g. Nomi) is worth far more than
    # its small stats suggest. Match by race OR by the text naming the tribe
    # (Nomi has race=None but its text scales Elementals).
    if dominant_tribe and card and _is_engine(card):
        if (normalize(card.get("race")) == normalize(dominant_tribe)
                or dominant_tribe.lower() in (card.get("text") or "")):
            score += W_ENGINE
    # Combat-time scaling is invisible to the pre-combat snapshot; flag as +value.
    if _is_combat_scaling(card):
        score += W_COMBAT_SCALE
    # Growth potential: how much the minion can scale (not just current stats).
    # Engine pieces (core/addon of the comp) grow far more in their comp, so
    # amplify their growth potential.
    growth = growth_potential(card)
    if comp and minion["card"] in comp.get("core", []):
        growth *= 2.0
    elif comp and minion["card"] in comp.get("addons", []):
        growth *= 1.5
    score += W_GROWTH * growth

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
        if normalize(comp.get("tribe")) and \
                normalize(minion.get("tribe")) == normalize(comp.get("tribe")):
            score += W_TRIBE

    # Role (scaling engine > utility > filler).
    score += ROLE_VALUE.get(_detect_role(minion, card), 0.0)

    # Hero power synergy (best-effort: shared tribe/keyword).
    if hero_power and card:
        hp_text = hero_power.lower()
        race = normalize(card.get("race")) or card.get("race")
        if race and race.lower() in hp_text:
            score += W_HERO
        for k in ("taunt", "divine shield", "reborn", "venomous"):
            if k in hp_text and k.replace(" ", "_").upper() in (card.get("mechanics") or []):
                score += W_HERO

    # Trinket synergy (best-effort: trinket mentions the tribe).
    if trinkets and card:
        for t in trinkets:
            race = normalize(card.get("race")) or card.get("race")
            if race and race.lower() in t.lower():
                score += W_TRINKET

    # Growth-aware engine value: how much the board's engine grows per turn.
    score += engine_bonus

    return score


def sell_recommendation(board_minions, comps, allowed_tribes=None, scenario=None,
                        hero_power=None, trinkets=None, comp=None):
    """Rank board minions from safest-to-sell to most-valuable.

    `board_minions`: list from board_state (each has card, atk, health, tribe).
    `comps`: dict of availabe comps (slug -> comp) already filtered by the ban.
    `allowed_tribes`: canonical allowed tribes, or None when the ban is unknown
    (no penalty is then applied).
    `scenario`: {trigger_type: count} real per-turn trigger counts for the growth
    simulator (from player_actions.trigger_counts); defaults to _DEFAULT_SCENARIO.
    `hero_power`: the friendly hero's hero-power TEXT (meta.hero_power), feeding
    the W_HERO synergy term.
    `trinkets`: list of trinket texts/descriptions (W_TRINKET), when known.
    `comp`: the SAME evidence-based target the buy ranking and display use —
    without it the comp-glue floor keys on a crude tribe-overlap comp, which
    can be the WRONG naga comp and leave the real payoff card sellable (the
    2026-09-04 1st-place game: "sell Fauna Whisperer", the comp's own
    end-of-turn scaler, while Balinda — in the wrong-picked comp's core —
    was floored).
    Returns a list of (card_id, score) sorted asecending (best to sell first).
    """
    card_db = _load_card_db()
    # Pick the comp whose tribe most overlaps the board (a crude comp fit)
    # unless the caller already resolved the evidence-based target.
    comp = comp if comp is not None else _best_comp(board_minions, comps)
    trinkets = trinkets or []
    # Total stats of the scaling minions on the board (a multiplier amplifies this).
    board_scaling = sum((m.get("atk") or 0) + (m.get("health") or 0)
                        for m in board_minions if _is_scaling(card_db.get(m["card"])))
    # Board's dominant tribe (for engine recognition and fit).
    dominant_tribe = _dominant_tribe(board_minions)

    # Growth-aware engine value: run the simulator for the board's best-fit
    # engine and attribute the growth it drives to the engine pieces.
    engine_bonus = _engine_growth_bonus(board_minions, _load_bg_names(),
                                        scenario=scenario)

    scored = []
    for m in board_minions:
        card = card_db.get(m["card"])
        val = minion_value(m, card, comp, hero_power, trinkets,
                           board_scaling=board_scaling, dominant_tribe=dominant_tribe,
                           engine_bonus=engine_bonus.get(m["card"], 0))
        # Banned-tribe minions on the board are worth less (can't grow).
        if is_banned(m.get("tribe"), allowed_tribes):
            val -= 2.0
        # Comp glue is never "safe to sell" (floor above the 15 filler
        # threshold): multipliers amplify the comp's effects, the fit comp's
        # own pieces ARE the build, and Spellcraft generators feed it a
        # stat spell every turn. (2026-09-04 1st-place game: "sell Balinda
        # (making room)" fired three phases in a row — she IS nagas core;
        # Rimescale Priestess was the earlier report.)
        text = (card.get("text") or "").lower() if card else ""
        glue = _is_multiplier(card) or "spellcraft" in text or (comp and (
            m["card"] in comp.get("core", [])
            or m["card"] in comp.get("addons", [])))
        if glue:
            val = max(val, W_SELL_FLOOR)
        scored.append((m["card"], val, comp))
    scored.sort(key=lambda x: (x[1], x[0]))
    return [(c, v) for c, v, _ in scored]


def shop_ranking(shop_cards, comps, board_minions=None, allowed_tribes=None,
                 hero_power=None, trinkets=None, scenario=None,
                 recent_cards=None, comp=None):
    """Rank the shop's tavern cards (minions AND spells) by value.

    `shop_cards`: list of card ids currently offered. `comps`: the playable comps
    (slug -> comp). `board_minions`: the current board, used to pick the best-fit
    comp. `allowed_tribes`: canonical allowed tribes, or None when unknown (no
    penalty). `hero_power`/`trinkets`: the W_HERO / W_TRINKET synergy inputs.
    `scenario`: real per-turn trigger counts (feeds the spell fuel term).
    `recent_cards`/`comp`: the SAME comp evidence the target display uses —
    without them the ranking scored against an ARBITRARY comp (dict order)
    when there was no evidence yet, blessing that comp's core with +10 (the
    2026-09-04 1st-place game: Banana Slamma, a Beast, headlined a Naga game
    at t9). No evidence now means NO comp bonus — cards score on their own
    merits — and a caller that already computed the target passes it so the
    buy headline and the "committing to" display can't disagree.
    Returns a list of (card_id, score) sorted most-valuable first, so the
    coach can headline "Buy this".
    """
    card_db = _load_card_db()
    spell_db = _load_spell_db()
    names = _load_bg_names()
    if comp is None and comps:
        # Score shop cards against the TARGET comp (what you're building toward),
        # not the current board's implied comp — so the buy recommendation guides
        # the pivot/commit rather than just matching the current board.
        # comp stays None without evidence — never an arbitrary dict-order
        # comp (the old `next(iter(comps.values()))` fallback).
        comp = comp_target(board_minions or [], comps, recent_cards=recent_cards)
    engine_bonus = _engine_growth_bonus(board_minions, names) if board_minions else {}
    board_ids = {m["card"] for m in (board_minions or [])}
    scored = []
    for cid in shop_cards:
        if cid in spell_db:
            # A tavern spell: effect-per-gold + cast-spell engine fuel, not the
            # minion value function (spells have no stats, comp role, or tribe).
            scored.append((cid, _spell_score(spell_db[cid], board_minions,
                                             names, scenario)))
            continue
        card = card_db.get(cid)
        if not card:
            continue
        # A shop minion at base stats (un-bought).
        m = {"card": cid, "atk": card.get("attack") or 0,
             "health": card.get("health") or 0, "tribe": card.get("race")}
        val = minion_value(m, card, comp, hero_power, trinkets,
                           engine_bonus=engine_bonus.get(cid, 0))
        # Committed mode (2026-09-07, user principle: "once committed to a
        # comp, the calculation changes — we're maximizing this comp, not
        # just purchasing the best card from whatever is available"): the
        # bonuses are sized so a comp piece outranks a strong generic body
        # (an 11.5-score Deflect-o-Bot class card loses to missing core),
        # and a MISSING core piece outranks a dupe (the dupe still scores —
        # copies are triples — but completing the build leads).
        comp_card = False
        if comp:
            if cid in comp.get("core", []):
                val += 14.0 if cid not in board_ids else 10.0
                comp_card = True
            elif cid in comp.get("addons", []):
                val += 7.0
                comp_card = True
        # Committed to the comp (>=2 core on board): a shop minion whose tribe
        # fights the comp won't fit the board's growth — damp it so comp cards
        # and neutral pieces win ties (the player's complaint: off-comp growth
        # cards recommended over the established comp). The damp discounts the
        # card's own GROWTH term, not just a flat penalty: off-comp growth
        # doesn't compound in this build (Twilight Tidehunter scored 21 vs
        # the comp piece's 6.3 — the 2026-09-04 beasts game, "recommended
        # Naga cards every time"). Untribed cards (race=None in the DB —
        # Rimescale-class) count as off-comp when they carry real growth;
        # low-growth utility neutrals (Drakkari) stay exempt from the
        # growth discount.
        if comp and not comp_card and \
                target_state(comp, board_minions or []) == "committing":
            ct = normalize(comp.get("tribe"))
            tribe = normalize(m.get("tribe"))
            if ct and (not tribe or tribe not in ct.split("/")):
                val += W_OFF_COMP
                growth = growth_potential(card)
                if tribe or growth >= 2.0:
                    val -= W_GROWTH * growth * 0.75
        elif comp is None:
            # Pre-commit engine fit (2026-09-06 Reno game t7, placement 6):
            # with no target yet but the board already one tribe, an
            # off-tribe GROWTH card scales minions the player is leaving —
            # Deflect-o-Bot (mech, growth 3.0) headlined a beast board at
            # 11.5 with NO engine bonus (the "(growth engine)" why-label is
            # text-based). Same growth discount as the committed damp, but
            # no flat penalty (a pivot is still legal pre-commit) and
            # untribed cards are exempt (they fit any build).
            dt = _dominant_tribe(board_minions or [])
            tribe = normalize(m.get("tribe"))
            if dt and tribe and tribe not in dt.split("/"):
                growth = growth_potential(card)
                if growth >= 2.0:
                    val -= W_GROWTH * growth * 0.75
        if is_banned(m.get("tribe"), allowed_tribes):
            val -= 2.0  # banned-tribe minion can't grow
        scored.append((cid, val))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def hand_plan(hand, board_minions=None, scenario=None):
    """What to do with cards ALREADY in hand — plays the coach never made
    (2026-09-04: five spells sat in hand that would 10x the board's stats
    while the coach said nothing about them).

    Casting a spell from hand costs NO gold and playing a minion stuck in
    hand (full board) costs none either, so each card's whole effect is
    profit. Spells rank by direct effect + cast-engine fuel (each cast
    feeds end-of-turn compounding, which counts casts made THIS turn);
    hand minions rank by their value as a free play — with triple
    awareness: 2 on board = play NOW (golden), 1 on board = hold the hand
    copy and hunt a 3rd. Returns a list of
    {"card", "name", "verb": "cast"|"play"|"hold", "score", "why"} — one
    entry per hand card, most valuable first.
    """
    spell_db = _load_spell_db()
    card_db = _load_card_db()
    names = _load_bg_names()
    board = board_minions or []
    steps = []
    destroy_casts = 0  # Butchering-class casts advised so far (target cap)
    for m in hand:
        cid = m.get("card")
        if not cid:
            continue
        if m.get("locked"):
            continue  # condition-locked (Thorim's 60-gold pick): no play or
                      # cast is possible, and advising one sold real minions
                      # to make room for it (2026-09-05)
        spell = spell_db.get(cid)
        if m.get("type") == "spell" or (spell and m.get("type") is None):
            if not spell:
                continue  # generated/unknown spell entity — can't advise
            points = _spell_effect(spell, len(board))
            fuel = _spell_fuel_bonus(board, names, scenario,
                                     extra_casts=_extra_casts(spell))
            why = "each cast feeds your cast engine" if fuel > 0 else None
            # Destroy-cost casts (Butchering-class) consume a TARGET: each
            # cast kills a friendly Undead, and Reborn covers ONE death per
            # body — it is not a repeat cycle (player-corrected 2026-09-08:
            # 'Cast Butchering x4' with 5 minions / 3 reborns, where the
            # 4th cast eats a permanent minion). The castable count is
            # capped at the board's Undead, and the targeting rule is
            # stated: Reborn minions first (each reborn is one extra cast).
            if "destroy a friendly" in (spell.get("text") or "").lower():
                undead = sum(1 for b in board
                             if normalize(b.get("tribe")) == "Undead")
                if destroy_casts >= undead:
                    continue  # no Undead left to destroy — uncastable
                destroy_casts += 1
                # The targeting rule + the comp page's generator combos: no
                # Reborn targets? Handless Forsaken / Mummifier / Eternal
                # Summoner make one (the Bellringer+Mummifier loop is the
                # page's "best variation" — a renewable target engine).
                if any("REBORN" in (b.get("keywords") or []) for b in board):
                    why = ("each cast: +5 Attack to ALL Undead, permanent — "
                           "target a Reborn minion first (each reborn "
                           "covers one cast)")
                else:
                    why = ("each cast: +5 Attack to ALL Undead, permanent — "
                           "no Reborn targets: Handless Forsaken / Mummifier "
                           "/ Eternal Summoner generate one")
            steps.append({"card": cid, "verb": "cast", "score": points
                          + W_SPELL_FUEL * fuel,
                          "name": names.get(cid, cid), "why": why})
        else:
            card = card_db.get(cid)
            if not card:
                continue
            # Triple awareness (2026-09-05: the coach said "Play Balinda" —
            # but with 1 on board the hand copy is the golden-hunt piece:
            # hold it, buy a 3rd, THEN play for the golden. With 2 on board
            # the hand copy IS the triple — play it now).
            on_board = sum(1 for b in board if b.get("card") == cid)
            verb, why = "play", None
            if on_board >= 2:
                why = "triples golden!" + (" — sell to make room"
                                           if len(board) >= 7 else "")
            elif on_board == 1:
                verb = "hold"
                why = "hold — 1 on board; a 3rd copy turns it golden"
            elif len(board) >= 7:
                why = "board is full — sell to make room"
            score = minion_value(m, card)
            if on_board >= 2:
                score += 25.0  # a golden now outranks nearly any free play
            steps.append({"card": cid, "verb": verb,
                          "score": score,
                          "name": names.get(cid, cid), "why": why})
    steps.sort(key=lambda s: (-s["score"], s["name"]))
    return steps


_STEP_KINDS = (("LEVEL", "level"), ("PICK ", "pick"), ("Buy ", "buy"),
               ("sell ", "sell"), ("roll", "roll"), ("Cast ", "cast"),
               ("Play ", "play"), ("Hold ", "hold"), ("stay on tier", "note"),
               ("wait for end of turn", "note"), ("pass", "note"),
               ("stabilize", "note"))


def top_move(analysis):
    """A one-line decision call as numbered priority steps.

    CONTRACT (the audit's "formatting used as data" finding, in transition):
    returns the rendered line — "1. LEVEL to tier 5 — 3 left · 2. PICK Baller
    Portrait (pick 25%) · 3. Buy Glambot (committing to Mech)" — AND
    side-writes into `analysis`:
      buy_step_card / buy_step_roll  the Buy box's resolved card / roll text
      top_move_steps                 [{text, kind, card}] — the same steps as
                                     structured data, so the overlay can
                                     render from data instead of re-parsing
                                     the strings (it still does today).
    Kind is one of level/pick/buy/sell/roll/cast/play/note; `card` is the
    resolved buy card (buy_step_card) when the step is the buy.
    """
    text = _top_move_text(analysis)
    steps = []
    for p in text.split(" · "):
        body = re.sub(r"^\d+\. ", "", p)
        kind = next((k for prefix, k in _STEP_KINDS if body.startswith(prefix)),
                    "note")
        card = analysis.get("buy_step_card") if kind == "buy" else None
        steps.append({"text": body, "kind": kind, "card": card})
    analysis["top_move_steps"] = steps
    return text


MINION_BUY_PRICE = 3   # the patch's flat default for ALL tiers of minions

_ACTIVATE_RE = re.compile(r"Activate \((\d+)\):\s*(.+)", re.S | re.I)


def activation_of(card):
    """Parse 'Activate (N): effect' from a card's text.

    Returns {"cost", "effect"} or None. Board-minion activations are a
    spend-the-last-gold action the coach ignored: the 2026-09-06 live game
    advised a useless reroll at 1 gold while Suspicious Prisonguard
    ("Activate (1): Give another minion +3/+3") sat on the board — +3/+3
    of real stats beats a refresh that can only find 1-cost spells.
    """
    if not card:
        return None
    text = (card.get("text") or "").replace("[x]", "").strip()
    m = _ACTIVATE_RE.match(text)
    if not m:
        return None
    return {"cost": int(m.group(1)),
            "effect": m.group(2).strip().replace("\n", " ").rstrip(".")}


def _affordable_activation(analysis, budget):
    """The best available board activation the budget covers, as
    (cid, name, cost, effect) — None when none fits. `budget` None means
    unknown gold: don't promise an activation."""
    card_db = _load_card_db()
    names = _load_bg_names()
    seen = set()
    for act in analysis.get("activations") or []:
        cid = act.get("cid")
        if cid in seen:
            continue
        seen.add(cid)
        info = activation_of(card_db.get(cid))
        if info and budget is not None and info["cost"] <= budget:
            return (cid, names.get(cid, cid), info["cost"], info["effect"])
    return None


def _tribe_of(comp_name):
    """'Beasts - Tasty Lobstah' -> 'Beasts' — the display-level tribe half
    of a comp name (comp_target's tribe field is canonical, this is the
    label)."""
    return (comp_name or "").split(" - ")[0]


def sticky_comp_target(prev, new, prev_hits, new_hits):
    """Which comp to SHOW as the build direction.

    The 2026-09-06 Guff game churned 'Summon Beetles' -> 'Tasty Lobstah'
    phase-to-phase on identical tribe evidence — same build, different
    name, reading to the player as 'which build am I actually doing?'.
    When the new target shares the previous target's TRIBE, keep the
    previous comp unless the new one carries strictly more core evidence
    (board + recent hits, copies included — the caller computes both with
    _core_hits). Cross-tribe pivots always pass through — stickiness must
    never fight the pivot override.

    Sub-threshold dips hold too (2026-09-07 Chromie game: a sold core
    dropped the target to None at t11-t14 — 'surviving until we can
    commit' on a full naga build): with no new target anywhere, the
    previous comp keeps showing while it still has >=1 core hit on board
    or in recent buys, and dies only at zero evidence.
    """
    if prev is None:
        return new
    if new is None:
        return prev if prev_hits >= 1 else None
    if prev.get("tribe") != new.get("tribe"):
        return new  # a cross-tribe pivot is always shown
    return new if new_hits > prev_hits else prev


def situation_line(analysis):
    """One-line situation read, rendered above the plan steps.

    The Guff game (2026-09-06, 3rd place) had the pieces on screen — 240
    stats vs a ~140 lobby, 30 HP with ZERO armor since t7 — but no panel
    ever said "one bad fight kills". This is the plan's thread: direction,
    strength, danger, in that order, at most ~3 clauses.
    """
    bits = []
    target = analysis.get("target_comp")
    if target:
        tribe = _tribe_of(target)
        state = analysis.get("target_state")
        bits.append(f"{tribe} build — "
                    + ("scaling" if state == "committing" else "hunting pieces"))
    bs = analysis.get("board_stats")
    theirs = analysis.get("opp_stats")
    source_is_baseline = False
    if theirs is None:
        theirs = analysis.get("lobby_opp")
    if theirs is None:
        theirs = analysis.get("baseline_opp")
        source_is_baseline = True
    if bs and theirs:
        # "~" marks an estimate; the corpus baseline is labelled as such —
        # calling 240 stats "behind" a historical median while the real
        # lobby sits at 140 would be the wrong alarm.
        mark = "~" if theirs != analysis.get("opp_stats") else ""
        ratio = bs / max(theirs, 1)
        if ratio >= 1.5:
            bits.append(f"strong ({bs} vs {mark}{int(theirs)})")
        elif ratio < 0.75:
            label = "behind baseline" if source_is_baseline else "behind"
            bits.append(f"{label} ({bs} vs {mark}{int(theirs)})")
    streak = analysis.get("loss_streak") or 0
    if streak >= 2:
        bits.append(f"lost {streak} straight")
    health = analysis.get("health")
    armor = analysis.get("armor") or 0
    # The mortality clock keys on the REAL lobby (fought/announced boards),
    # never the historical baseline — a high baseline median at a late turn
    # is not the lobby you're about to fight.
    lobby = analysis.get("opp_stats") or analysis.get("lobby_opp")
    if health is not None and lobby:
        eff = health + armor
        if eff <= 12:
            bits.append(f"DYING at {health}"
                        + (f"+{armor}" if armor else "") + " — buy board now")
        elif eff <= 30 and lobby >= 100:
            # Armor is just extra health (player-corrected 2026-09-08) — the
            # signal is TOTAL effective HP vs the lobby's damage output:
            # boards big enough that one lost fight can take 30+ while
            # you're down to your base pool (the silent mortality clock —
            # t7-t12 of the Guff game were all wins, then one fight ended
            # it).
            bits.append(f"{eff} HP left — one bad fight can end it")
    if not bits:
        return None
    return " · ".join(bits[:3])


def _buy_prices(analysis):
    """Buy prices for the shop overlay/affordability walk.

    Minions cost a FLAT 3 (the current patch's default for ALL tiers) — the
    shop entities' tag=479 values are stale legacy tier costs: the
    2026-09-06 23:00 log charged RESOURCES_USED=3 for Buzzing Vermin and
    Decoy Conjurer whose tags said 1, and the player confirmed the rule
    ("the default price for all minions of all tiers is THREE GOLD"). The
    DB's `tier` was never a price. Tavern spells keep their own per-spell
    price: the log's COST tag for spell entities, else the spell DB.
    """
    spell_db = _load_spell_db()
    costs = {c: MINION_BUY_PRICE for c in _load_card_db()}
    costs.update({c: (v or {}).get("cost") for c, v in spell_db.items()})
    costs.update({c: v for c, v in (analysis.get("shop_costs") or {}).items()
                  if c in spell_db})
    return costs


def _top_move_text(analysis):
    """Render top_move's numbered steps (the planner proper; see top_move)."""
    names = _load_bg_names()
    card_db = _load_card_db()
    spell_db = _load_spell_db()
    costs = _buy_prices(analysis)
    comp = _best_comp(analysis.get("board", []), analysis.get("playable_comps") or {})
    tier = analysis.get("tier")
    gold = analysis.get("gold")
    parts = []

    # 0. The hand (free actions, in ranked order): cast spells, play stuck
    #    minions. Copies group ("x2"); beyond three the rest summarize so the
    #    level/buy steps stay visible.
    hand_entries = analysis.get("hand_plan") or []
    hand_parts = []
    if hand_entries:
        counts, order = {}, []
        for s in hand_entries:
            key = (s["verb"], s["card"])
            if key not in counts:
                counts[key] = [0, s]
                order.append(key)
            counts[key][0] += 1
        for key in order:
            n, s = counts[key]
            label = {"cast": "Cast ", "play": "Play ",
                     "hold": "Hold "}.get(s["verb"], "Play ") + s["name"]
            if n > 1:
                label += f" x{n}"
            if s.get("why"):
                label += f" ({s['why']})"
            hand_parts.append(label)
        if len(hand_parts) > 3:
            extra = len(hand_parts) - 3
            hand_parts = hand_parts[:3] + [f"then the rest of your hand "
                                           f"({extra} more)"]

    # 1. LEVEL — the tier gates the whole shop, so it leads whenever relevant.
    #    The gates and their reasons follow analysis/LEVELING_MODEL.md:
    #    Q0 flow (armor/HP dropped last combat = losing, stabilize first),
    #    Q1 payoff (the shopping list filtered by tier — leveling LOWERS the
    #    odds of finding the current tier's cards, so staying is a decision,
    #    not an omission), Q2 stock (effective health), and the curve prior
    #    as the default. EXCEPT when leveling would cost the board (dying,
    #    loss streak, or the shop's top card is a comp core and both don't
    #    fit — "we can't upgrade the board if we're going to die / miss
    #    important minions as a result", 2026-09-03), the BUY leads and the
    #    level trails with its reason.
    level_lead = None
    budget = gold
    level_next = None      # a LEVEL step that trails the buy instead of leading
    level_flip_why = None  # the stated reason the level deferred to the buy
    stay_note = None       # staying ON this tier is itself a decision (Q1)
    if tier and tier < 6:
        # Real upgrade price: the live TechUp button COST (tier+3 base,
        # dropping 1 per turn you wait) — tier+1 was the old wrong model.
        level_cost = analysis.get("level_cost") or tier + 1
        if gold is None:
            level_lead = f"LEVEL (access to tier {tier + 1})"
        elif gold >= level_cost:
            spare = gold - level_cost
            health = analysis.get("health")
            armor = analysis.get("armor") or 0
            eff = health + armor if health is not None else None
            dying = eff is not None and eff <= DYING_HEALTH
            damage_last = analysis.get("damage_last")
            loss_streak = analysis.get("loss_streak") or 0
            close = analysis.get("close_losses")
            headline = analysis.get("buy_this")
            h_cost = costs.get(headline) if headline else None
            core_ids = {c.get("card")
                        for c in ((analysis.get("target_cards") or {})
                                  .get("core") or [])}
            core_pick = bool(headline and headline in core_ids)
            # Can't have both the level and the shop's top card.
            locked_out = (h_cost is not None and gold >= h_cost
                          and spare < h_cost)
            # Q1 payoff: unowned pieces of the target comp, split by which
            # tavern tier holds them (copies of what we own don't count).
            needs_next, needs_here = _comp_needs_by_tier(analysis, card_db)
            # Scout (gates 3+4): "their" = the next opponent's last-known
            # board when we've fought them (the exact buy-phase preview),
            # else the lobby median, else the corpus baseline. The "~" marks
            # an estimate; the exact number is a last-known board.
            board_stats = analysis.get("board_stats")
            their = analysis.get("opp_stats")
            approx = their is None
            if their is None:
                their = analysis.get("lobby_opp")
            if their is None:
                their = analysis.get("baseline_opp")
            strong = (board_stats is not None and their
                      and board_stats >= 1.5 * their
                      and not damage_last and not loss_streak)
            # Q0 flow: armor/HP drops are the loss streak. Early-game losses
            # (tiers 1-2) are normal — the flow gate is a tier-3+ (mid-game)
            # concept, matching the shop-driven vs board-driven split. BUT a
            # losing streak with a far-behind board defers the level at ANY
            # tier (the 2026-09-08 Loh game: the coach said 'standard curve'
            # at t2/t4 through four straight losses with a 2-minion, 7-stat
            # board vs ~23, then the review blamed the player for falling
            # behind — a paradox. Losing AND far behind the turn-appropriate
            # board means the last gold buys stats, not a tier. Tier 1 stays
            # curve-driven: turn-1/2 leveling is nearly always right and the
            # losses are cheap.)
            flip_why = None
            if dying:
                flip_why = "too fragile to level first"
            elif tier >= 2 and loss_streak >= 2 and board_stats is not None \
                    and their and board_stats < 0.7 * their:
                flip_why = (f"lost {loss_streak} straight and your board is "
                            f"behind — buy stats first")
            elif tier >= 3 and loss_streak >= 2:
                flip_why = (f"lost {loss_streak} straight fights"
                            + (" (close) — " if close else " — ")
                            + "stabilize first")
            elif tier >= 3 and damage_last and damage_last >= 10:
                flip_why = f"took {damage_last} last fight — stabilize first"
            if flip_why and opp_note(board_stats, their, approx):
                flip_why += f"; {opp_note(board_stats, their, approx)}"
            if (flip_why or core_pick) and locked_out:
                budget = gold  # the buy comes first, from the full purse
                level_next = True
                level_flip_why = flip_why or "the shop's top card is a comp core"
            elif needs_here and not needs_next:
                # Q1: what the comp needs is ON this tier — leveling would
                # lower the odds of finding it. Stay and buy.
                budget = gold
                stay_note = True
            else:
                if needs_next:
                    why = "the comp's next pieces live there"
                elif strong:
                    why = "you're strong — convert it into a tier"
                else:
                    why = "standard curve"
                level_lead = (f"LEVEL to tier {tier + 1} ({why})"
                              + (f" — {spare} left" if spare else ""))
                budget = spare  # buys come out of the leftover, not the purse
        # else: the level is out of reach this turn. It stays OUT of the
        # numbered list — an upgrade the player can't make is not advice
        # (2026-09-04: "shouldn't be recommending I upgrade if it's
        # impossible"); the tier gap is already visible in the Build column.
    if level_lead:
        parts.append(level_lead)

    # 2. The forced pick (hero / trinket / discover) — the shop doesn't gate it.
    # Hero picks carry a fallback: the log doesn't expose ownership, so the
    # top pick might be season-pass locked — name the next-best too.
    choice = analysis.get("choice")
    if choice and choice.get("ranked"):
        best = choice["ranked"][0]
        why = f" ({best[3]})" if best[3] else ""
        pick = f"PICK {best[0]}{why}"
        if choice.get("kind") == "hero" and len(choice["ranked"]) > 1:
            pick += f" — if locked, {choice['ranked'][1][0]}"
        parts.append(pick)

    # 3. Buy: the headline pick if the budget covers it, else the best card
    # that does, else roll. The resolved card is written back into the
    # analysis (buy_step_card / buy_step_roll) so the UI's Buy box shows the
    # plan's actual buy instead of the raw shop #1 (they differ whenever the
    # headline pick doesn't fit the post-level budget).
    shop_rank = analysis.get("shop_rank") or []
    bought = None
    analysis["buy_step_card"] = None
    analysis["buy_step_roll"] = None
    if analysis.get("buy_this"):
        cid = analysis["buy_this"]
        # Early game (turns 1-2) buys a MINION when one is affordable —
        # board presence beats spell value while the board is being born
        # (2026-09-04 live note: "turn 1 recommended a spell over a
        # minion... no."). The usual ranking still applies when no minion
        # fits the budget.
        if (analysis.get("turn") or 99) <= 2 and cid in spell_db:
            for alt, _v in shop_rank:
                alt_cost = costs.get(alt)
                if (alt not in spell_db and alt_cost is not None
                        and (budget is None or budget >= alt_cost)):
                    cid = alt
                    break
        cost = costs.get(cid)
        if budget is not None and cost is not None and budget < cost:
            # Can't afford the headline pick — walk the ranking for one the
            # budget covers (known prices only; unknown = can't promise).
            fallback = None
            for alt, _v in shop_rank:
                alt_cost = costs.get(alt)
                if alt_cost is not None and budget >= alt_cost:
                    fallback = alt
                    break
            if fallback is None:
                act = _affordable_activation(analysis, budget)
                if act:
                    # A board activation beats a reroll: +3/+3 of real stats
                    # vs a refresh that can only find 1-cost spells (the
                    # 2026-09-06 live game: Prisonguard sat unused at 1
                    # gold while the coach said roll).
                    parts.append(f"Activate {act[1]} ({act[3]}) — beats a reroll")
                    analysis["buy_step_roll"] = parts[-1]
                    analysis["activation_step"] = act[0]
                elif budget:  # a roll costs 1 — with nothing left it isn't advice
                    # Gold doesn't carry over between turns, so spending the
                    # last gold on a refresh beats passing; say WHAT didn't
                    # fit, not "costs 3, 1 left" (read as "buy it" — the
                    # 2026-09-06 user question).
                    when = " after the level" if level_next else ""
                    roll = (f"roll — best shop card ({names.get(cid, cid)}, "
                            f"{cost}g) doesn't fit your {budget} gold left"
                            f"{when}")
                    parts.append(roll)
                    analysis["buy_step_roll"] = roll
                cid = None  # nothing affordable — don't also say "Buy X"
            else:
                cid = fallback
        if cid is not None:
            # Hunt mode (2026-09-07, the player's roll-x10 style): committed
            # with missing core, the affordable shop top is OFF-BUILD — the
            # gold rolls for the missing pieces instead of blessing a buy
            # that doesn't advance the build. Skipped while dying (a body
            # beats a hunt) and early-game (board presence first).
            tc = analysis.get("target_cards") or {}
            missing = [r for r in (tc.get("core") or [])
                       if not r.get("owned") and not r.get("banned")]
            build_ids = {r["card"] for r in (tc.get("core") or [])} | \
                {r["card"] for r in (tc.get("addons") or [])}
            off_build = cid not in build_ids
            eff_health = (analysis.get("health") or 0) \
                + (analysis.get("armor") or 0)
            if missing and off_build \
                    and analysis.get("target_state") == "committing" \
                    and (budget or 0) >= 1 and eff_health > 12 \
                    and (analysis.get("turn") or 99) > 2:
                # Name comp-SPECIFIC cores first: a shared-utility card
                # (Balinda-class) is still on the shopping list, but it's a
                # generic-good card, not this build's win condition — the
                # hunt names what the BUILD is missing (2026-09-08: the
                # hunt's second target read 'Balinda Stonehearth').
                specific = [r for r in missing
                            if r["card"] not in _shared_utility_cores(
                                analysis.get("playable_comps") or {})]
                nm = ", ".join(r["name"] for r in (specific or missing)[:2])
                parts.append(f"roll — hunting {nm} "
                             f"({names.get(cid, cid)} is off-build)")
                analysis["buy_step_roll"] = parts[-1]
                analysis["buy_step_card"] = None
                cid = None
        if cid is not None:
            bought = cid
            analysis["buy_step_card"] = cid
            parts.append(f"Buy {names.get(cid, cid)} "
                         f"({_buy_intention(cid, comp, card_db, spell_db)})")
            if level_next and tier:
                level_cost = analysis.get("level_cost") or tier + 1
                leftover = (gold or 0) - (costs.get(cid) or 0)
                if leftover >= level_cost:
                    parts.append(f"LEVEL to tier {tier + 1} — "
                                 f"{leftover - level_cost} left after")
                else:
                    short = f"{level_cost - leftover} short after the buy"
                    parts.append((f"LEVEL next turn ({level_flip_why}) — "
                                  f"{short}; roll meanwhile")
                                 if level_flip_why else
                                 f"LEVEL next turn — {short}; roll meanwhile")
    # 4. Sell only to make room: board full AND buying something that needs
    # the slot. If there's space, selling is unnecessary. Held cards are
    # exempt: the hand plan said "hold — a 3rd copy turns it golden", and
    # the same panel must not also say to sell it (2026-09-06 Guff t12:
    # "3. Hold Sewer Lord" + "6. sell Sewer Lord" in one plan). If the only
    # filler is held, the golden hunt outranks the slot — no sell step.
    if bought is not None and len(analysis.get("board", [])) >= 7 \
            and analysis.get("sell_rank"):
        held = {s["card"] for s in (analysis.get("hand_plan") or [])
                if s.get("verb") == "hold"}
        for worst in analysis["sell_rank"]:
            if worst[0] in held:
                continue  # the golden hunt outranks the slot
            if worst[1] < SELL_FILLER_SCORE:  # a clear filler (low value)
                parts.append(f"sell {names.get(worst[0], worst[0])} "
                             f"(making room)")
            break
    # The stay decision (Q1) trails the buys: what the comp needs is ON this
    # tier, and the player should know the level was declined on purpose.
    if stay_note and tier:
        parts.append(f"stay on tier {tier} — your comp's missing pieces are "
                     f"on this tier; leveling would lower the odds")
    # Nothing pressing: if the board is full and has end-of-turn scaling, the
    # right move is to pass and let the engine grow — casting the hand first
    # (end-of-turn effects count the casts made this turn).
    if not parts and len(analysis.get("board", [])) >= 7 \
            and _has_end_of_turn(analysis.get("board", []), card_db):
        parts.append("wait for end of turn — let the engine scale")
        if not hand_parts:
            analysis["buy_step_roll"] = parts[-1]  # the Buy box mirrors it
    if parts or hand_parts:
        return " · ".join(f"{i}. {p}"
                          for i, p in enumerate(hand_parts + parts, 1))
    # Nothing affordable and nothing to level: roll unless there's no gold at all.
    # Committed and hunting pieces is the endgame (2026-09-04: "we committed,
    # we have it, now we scale it to kingdom come") — say so instead of a
    # generic roll.
    target = analysis.get("target_comp")
    scaling = target and analysis.get("target_state") == "committing"
    act = _affordable_activation(analysis, gold)
    if act and gold is not None and gold >= act[2]:
        msg = f"Activate {act[1]} ({act[3]}) — beats a reroll"
        analysis["buy_step_roll"] = msg
        analysis["activation_step"] = act[0]
        return msg
    if gold is not None and gold >= 1:
        msg = ("roll — hunt more " + target + " to scale it"
               if scaling else
               "roll — nothing in the shop beats your gold; level needs saving")
        analysis["buy_step_roll"] = msg
        return msg
    # Otherwise point at the comp so the advice stays actionable instead of
    # going stale — with the endgame framing once committed.
    if target:
        msg = (f"scale {target} — buy its scalers, cast everything, sell "
               f"nothing that grows"
               if scaling else
               f"hold — look for {target} core cards")
    elif gold == 0:
        msg = "pass — out of gold"
    else:
        msg = "stabilize / roll for your comp"
    analysis["buy_step_roll"] = msg
    return msg


def _has_end_of_turn(board, card_db):
    """True if any board minion has an end-of-turn scaling effect."""
    for m in board:
        text = (card_db.get(m["card"]) or {}).get("text", "")
        if "end of" in text and "turn" in text:
            return True
    return False


def _buy_intention(cid, comp, card_db, spell_db=None):
    """Why the coach recommends buying this card (a pre-set intention)."""
    if comp and cid in comp.get("core", []):
        return f"committing to {comp.get('tribe') or comp.get('name')}"
    if comp and cid in comp.get("addons", []):
        return "part of growth cycle"
    card = card_db.get(cid)
    if card and _is_engine(card):
        return "growth engine"
    spell = (spell_db or {}).get(cid)
    if spell:
        text = (spell.get("text") or "").lower()
        if any(m in text for m in _SPELL_SCALING_MARKERS):
            return "part of growth cycle"
        if any(kw in text for kw, _v in _SPELL_UTILITY):
            return "utility"
        if re.search(r"\+\d+/\+\d+", text):
            return "tempo"
        return "spare gold into value"
    return "surviving until we can commit"


def opp_note(board_stats, their, approx):
    """The scout comparison, or '' when either side is unknown (gates 3+4,
    analysis/LEVELING_MODEL.md): 'your 47 vs their ~90'."""
    if board_stats is None or not their:
        return ""
    return f"your {board_stats} vs their {'~' if approx else ''}{int(their)}"


def combat_forecast(analysis):
    """A one-line next-fight verdict: favored / close / behind from the
    stat ratio, with OUR keyword edges named (divine shields absorb a hit
    each, venomous removes a minion each — the 'my guys evaporated' class
    of surprise). v1 limits: the opponent's keywords aren't tracked yet
    (their board reaches us as stat totals), and the estimate is a ratio,
    not a combat simulation.
    """
    bs = analysis.get("board_stats")
    theirs = analysis.get("opp_stats") or analysis.get("lobby_opp") \
        or analysis.get("baseline_opp")
    if bs is None or not theirs:
        return None
    board = analysis.get("board") or []
    shields = sum(1 for m in board
                  if "DIVINE_SHIELD" in (m.get("keywords") or []))
    venom = sum(1 for m in board
                if "VENOMOUS" in (m.get("keywords") or [])
                or "POISONOUS" in (m.get("keywords") or []))
    edges = []
    if shields:
        edges.append(f"{shields} divine shield{'s' if shields > 1 else ''}")
    if venom:
        edges.append("venomous")
    edge = f" (yours: {', '.join(edges)})" if edges else ""
    ratio = bs / max(theirs, 1)
    if ratio >= 1.3:
        return f"favored — {bs} vs {int(theirs)}{edge}"
    if ratio >= 0.8:
        return f"close fight — {bs} vs {int(theirs)}{edge}"
    return f"behind — {bs} vs {int(theirs)}; don't take this fight{edge}"


def _comp_needs_by_tier(analysis, card_db):
    """Unowned pieces of the target comp, split by which tavern tier holds
    them relative to the current tier: (needs_next, needs_here) (Q1,
    analysis/LEVELING_MODEL.md — leveling lowers the odds of finding the
    CURRENT tier's cards, so where the missing pieces live decides)."""
    tc = analysis.get("target_cards")
    tier = analysis.get("tier")
    if not tc or tier is None:
        return 0, 0
    nxt = here = 0
    for section in ("core", "addons"):
        for row in tc.get(section) or []:
            if row.get("owned") or row.get("banned"):
                continue  # owned, or banned this game (never findable)
            t = (card_db.get(row.get("card")) or {}).get("tier")
            if t is None:
                continue
            if t == tier + 1:
                nxt += 1
            elif t == tier:
                here += 1
    return nxt, here


def _core_hits(board, rc, cores):
    """Core-card hits for one comp: board minions plus recent acquisitions
    (copies count — a commit is often 2x/3x one core)."""
    return (sum(1 for m in board if m["card"] in cores)
            + sum(1 for c in rc if c in cores))


def _shared_utility_cores(comps, min_tribes=4):
    """Core cards shared across comps of >= min_tribes are SHARED UTILITY:
    their presence says 'good player', not 'this build', and they are
    excluded from commit evidence.

    The 2026-09-07 dragon game manufactured 'Nagas - Groundbreaker'
    direction at t7-t9 from Balinda + one dragon piece on a board that was
    never naga — Balinda is core of 7 comps across 5 tribes, so any board
    holding her is one incidental piece away from fake evidence in five
    directions. Brann (3 tribes) deliberately stays: battlecry comps
    genuinely share him and excluding him gutted the dragon commit in
    testing. These cards stay in the shopping lists and glue floors — the
    card is still part of the comp, it just can't MANUFACTURE the
    direction.
    """
    from collections import defaultdict
    spread = defaultdict(set)
    for comp in comps.values():
        for cid in set(comp.get("core", [])):
            spread[cid].add(comp.get("tribe"))
    return {cid for cid, tribes in spread.items()
            if len({t for t in tribes if t}) >= min_tribes}


def _evidence_core_ids(comp, comps):
    """The comp's core MINUS shared-utility cards (see
    _shared_utility_cores) — the ids that count toward commit evidence."""
    return set(comp.get("core", [])) - _shared_utility_cores(comps)


def _board_tribe_share(comp, board):
    """The fraction of the current board that shares the comp's tribe —
    the 'is this build the board' signal used to break evidence ties."""
    tribe = normalize(comp.get("tribe") or "")
    if not tribe or not board:
        return 0.0
    hits = sum(1 for m in board
               if normalize(m.get("tribe")) in tribe.split("/"))
    return hits / len(board)


def comp_progress(board, comps, recent_cards=None, top=4):
    """Commit readiness per candidate comp — the meter behind comp_target's
    rule (UI: the "Comp direction" box shows how close each candidate is to
    the 2-core-hit commit threshold BEFORE comp_target declares a target).

    Same evidence semantics as comp_target: board minions + recent
    acquisitions, copies count. Comps with >=1 direct core hit are listed
    (hits desc, then meta tier, capped at `top`); each row also carries
    `tribe_hits`, the tribe's total across its comps — the comp_target
    tribe rule (>=2 spread across comps of one tribe) is visible as tribe
    momentum on the row even when no single comp hits alone.
    Returns [{name, tribe, meta_tier, hits, ready, needs, tribe_hits}] —
    needs is the unowned core (the shopping list that moves the meter).
    """
    rc = list(recent_cards or [])
    board_cards = {m["card"] for m in board}
    shared = _shared_utility_cores(comps)
    rows = []
    for comp in comps.values():
        cores = set(comp.get("core", [])) - shared
        hits = _core_hits(board, rc, cores)
        if hits:
            blocked = set(comp.get("_blocked_core") or [])
            rows.append({
                "name": comp.get("name"),
                "tribe": comp.get("tribe"),
                "meta_tier": comp.get("meta_tier"),
                "hits": hits,
                "ready": hits >= 2,
                "needs": [cid for cid in comp.get("core", [])
                          if cid in cores and cid not in board_cards
                          and cid not in blocked],
            })
    # Tribe evidence across comps (the comp_target tribe rule): a row whose
    # TRIBE gathers >=2 hits total is closer to a real direction than its
    # own hit count alone reads.
    tribe_total = {}
    for comp in comps.values():
        tribe = comp.get("tribe")
        if not tribe:
            continue
        hits = _core_hits(board, rc, set(comp.get("core", [])))
        if hits:
            tribe_total[tribe] = tribe_total.get(tribe, 0) + hits
    for r in rows:
        r["tribe_hits"] = tribe_total.get(r["tribe"])
    tier_rank = {"S": 0, "A": 1, "B": 2}
    rows.sort(key=lambda r: (-r["hits"], tier_rank.get(r["meta_tier"], 3),
                             r["name"] or ""))
    return rows[:top]


def comp_target(board, comps, recent_cards=None):
    """The comp to build toward, given evidence only.

    Commit requires EVIDENCE (2026-09-04 live note: "already has a
    recommended comp listed from the beginning of the game, which is
    unrealistic" — a checklist comp picked from nothing is exactly what
    Shadybunny warns against: build a strong board, not a comp):
    >=2 core cards on the board, or >=2 core cards among the last turn or
    two of acquisitions (copies count — a pivot is often 3x one core; the
    board alone is backward-looking, the 2026-09-04 Varden game pushed
    LEVEL for five phases while the player built Demons). A recent-hits
    override beats a board commit from a DIFFERENT comp only with strictly
    more evidence — on a tie the board wins (2026-09-07: 2 recent beast
    buys yanked the direction off a five-dragon board). Below a comp
    commit, TRIBE-level evidence counts: >=2 core hits spread across comps
    of one tribe point at the tribe (the 2026-09-04 beasts game built
    Tasty Lobster + Banana Slamma — two beasts comps — and the coach stayed
    comp-agnostic, headlining Naga cards, all game). Returns comp or
    None — None is meaningful ("no direction yet").
    """
    rc = list(recent_cards or [])  # copies count: a pivot is often 3x one core
    shared = _shared_utility_cores(comps)

    def core_hits(comp):
        return _core_hits(board, rc,
                          set(comp.get("core", [])) - shared)

    committed = None   # (comp, overlap, board_dominant)
    for comp in comps.values():
        # Copies count (a commit is often 2x/3x one core, same as a pivot).
        # Ties break on BOARD DOMINANCE: a comp whose tribe is a strict
        # majority of the board is the live build (2026-09-07: a five-dragon
        # board with a 278/212 Tarecgosa), while remnants are a minority of
        # a mixed board being sold off (the 2026-09-04 Varden pivot).
        overlap = core_hits(comp)
        if overlap < 2:
            continue
        dominant = _board_tribe_share(comp, board) > 0.5
        key = (overlap, dominant)
        if committed is None or key > (committed[1], committed[2]):
            committed = (comp, overlap, dominant)
    if rc:
        best_recent = None
        for comp in comps.values():
            if committed and comp is committed[0]:
                continue  # more of the same comp is not a pivot
            cores = set(comp.get("core", [])) - shared
            hits = sum(1 for c in rc if c in cores)
            if hits >= 2 and (best_recent is None or hits > best_recent[1]):
                best_recent = (comp, hits)
        if best_recent and (committed is None
                            or best_recent[1] > committed[1]
                            or not committed[2]):
            # A recent-acquisition override beats the board commit when it
            # carries strictly more evidence, or when the board commit is a
            # MINORITY remnant of a mixed board (a real pivot: the board
            # lags, the buys lead). A board-dominant commit holds on a tie
            # — the thing actually fighting stays the direction.
            return best_recent[0]
    if committed:
        return committed[0]
    # Tribe-level evidence: core hits spread across comps of one tribe.
    tribe_best = {}
    tribe_total = {}
    for comp in comps.values():
        hits = core_hits(comp)
        if not hits:
            continue
        tribe = comp.get("tribe")
        if not tribe:
            continue
        tribe_total[tribe] = tribe_total.get(tribe, 0) + hits
        cur = tribe_best.get(tribe)
        if cur is None or hits > cur[1]:
            tribe_best[tribe] = (comp, hits)
    for tribe, total in sorted(tribe_total.items(), key=lambda kv: -kv[1]):
        if total >= 2:
            return tribe_best[tribe][0]
    return None  # no evidence yet — "no direction" beats a made-up pick


def target_state(target, board):
    """'committing' if the target comp's core cards are on the board, else 'pivot'."""
    if not target:
        return None
    core = set(target.get("core", []))
    board_cards = {m["card"] for m in board}
    return "committing" if core & board_cards else "pivot"


def comp_cards(target, board):
    """The target comp's cards, named and flagged by board presence.

    Returns {"name", "core": [...], "addons": [...]} where each card is
    {card, name, owned, banned} — so the UI/console can show the comp's
    shopping list without opening comps.json, and the player sees at a
    glance which pieces they already have and which are banned this game
    (hybrid comps keep a banned-tribe piece in core; it can't be bought).
    """
    if not target:
        return None
    board_ids = {m["card"] for m in board}
    names = _load_bg_names()
    blocked = set(target.get("_blocked_core") or [])

    def rows(ids):
        return [{"card": cid, "name": names.get(cid, cid),
                 "owned": cid in board_ids, "banned": cid in blocked}
                for cid in ids]

    return {
        "name": target.get("name"),
        "core": rows(target.get("core", [])),
        "addons": rows(target.get("addons", [])),
    }


# Default per-turn trigger counts for the growth simulator when the caller
# doesn't supply a scenario (tunable; ideally from the actual game state).
_DEFAULT_SCENARIO = {
    "cast_spell": 4,
    "play_elemental": 3,
    "play_mech": 3,
    "play_naga": 3,
    "deathrattle": 4,
    "play_tier3_or_lower": 4,
}


@functools.lru_cache(maxsize=1)
def _load_bg_names():
    """card id -> name from the BG pools (meta/minions.json + tavern_spells.json).

    The engine matching needs BG card names; `.cards_full.json` (the full
    hearthstonejson DB) doesn't carry the BG card IDs. Spell names are included
    so shop/buy advice can display tavern spells (their ids never collide with
    minion ids).
    """
    names = {m.get("id"): m.get("name") for m in meta.minions()}
    names.update({sid: s.get("name") for sid, s in _load_spell_db().items()})
    return names


def _has_card(board_minions, source, names):
    """True if any board minion is the named card (by name substring)."""
    return any(source.lower() in (names.get(m["card"]) or "").lower()
               for m in board_minions)


def _best_engine(board_minions, names):
    """Pick the engine whose chain source cards are most present on the board.

    Requires the engine's core step (the one producing a derived counter, or the
    only step) to be present, so a lone Utility Drone doesn't match the Glambot
    engine. Matches by card name, robust to comps.json/engines.json slug drift.
    """
    engines = _load_engines()
    best = None
    best_score = 0
    for slug, engine in engines.items():
        if slug.startswith("_"):
            continue
        core_steps = [s for s in engine["chain"] if s.get("counts_as")] or engine["chain"]
        if not any(_has_card(board_minions, s["source"], names) for s in core_steps):
            continue
        score = sum(1 for s in engine["chain"]
                    if _has_card(board_minions, s["source"], names))
        if score > best_score:
            best_score = score
            best = engine
    return best


def _dominant_tribe(board_minions):
    """The board's most common (normalized) tribe, or None for a mixed/
    untried board — the "what build does this look like" signal."""
    from collections import Counter
    tribes = Counter(normalize(m.get("tribe")) for m in board_minions
                     if normalize(m.get("tribe")))
    return tribes.most_common(1)[0][0] if tribes else None


def _engine_growth_bonus(board_minions, names, scenario=None):
    """Run the growth simulator for every engine whose core is present on the
    board and return {card_id: value_bonus} for the engine pieces.

    Each engine piece gets a bonus proportional to the total simulated growth the
    engine drives per turn — so a low-stats engine (Nomi, Glambot) ranks high
    because it's what makes the board grow. Crediting all running engines (not
    just the best-fit one) handles hybrid boards (e.g. Mana Surge + Unbound).

    Engine FIT: an engine whose tribe fights the board's dominant tribe is
    damped (W_ENGINE_OFF_TRIBE) — the growth lands on minions the player is
    pivoting away from, so crediting it in full put Deflect-o-Bot (mech)
    atop a beast-leaning shop (2026-09-06 Reno game t7). A card credited by
    several engines keeps its best credit (max, not last-write).
    """
    engines = _load_engines()
    bonus = {}
    dominant = _dominant_tribe(board_minions)
    for slug, engine in engines.items():
        if slug.startswith("_"):
            continue
        core_steps = [s for s in engine["chain"] if s.get("counts_as")] or engine["chain"]
        if not any(_has_card(board_minions, s["source"], names) for s in core_steps):
            continue
        sc = scenario or {engine["trigger"]: _DEFAULT_SCENARIO.get(engine["trigger"], 3)}
        # simulate_growth matches engine pieces by name; board_state minions only
        # carry card IDs, so enrich the board with names from the BG pool.
        enriched = [dict(m, name=names.get(m["card"], "")) for m in board_minions]
        result = simulate_growth(enriched, sc, engine)
        total = result["gain"]["atk"] + result["gain"]["hp"]
        if total <= 0:
            continue
        factor = 1.0
        et = normalize(engine.get("tribe"))
        if dominant and et and dominant not in et.split("/"):
            factor = W_ENGINE_OFF_TRIBE
        credit = W_ENGINE_SIM * total * factor
        # Chain source cards (the engine pieces).
        for step in engine["chain"]:
            for m in board_minions:
                if step["source"].lower() in (names.get(m["card"]) or "").lower():
                    bonus[m["card"]] = max(bonus.get(m["card"], 0.0), credit)
            # The shop-buff engine (e.g. Nomi) that makes a compounding step
            # compound is as critical as the payoff; credit it too.
            if step.get("buff_source"):
                for m in board_minions:
                    if step["buff_source"].lower() in (names.get(m["card"]) or "").lower():
                        bonus[m["card"]] = max(bonus.get(m["card"], 0.0), credit)
        # Multiplier cards (Balinda/Drakkari/Brann/Titus) amplify the engine;
        # they're not chain sources but are just as critical to keep.
        for cards in _MULTIPLIERS.values():
            for card_name in cards:
                for m in board_minions:
                    if card_name.lower() in (names.get(m["card"]) or "").lower():
                        bonus[m["card"]] = max(bonus.get(m["card"], 0.0), credit)
    return bonus


def _best_comp(board_minions, comps):
    """Pick the comp whose tribe best matches the board (crude fit)."""
    if not comps:
        return None
    tribes = {}
    for m in board_minions:
        t = normalize(m.get("tribe"))
        if t:
            for part in t.split("/"):
                tribes[part] = tribes.get(part, 0) + 1
    best = None
    best_score = 0
    for slug, comp in comps.items():
        ct = normalize(comp.get("tribe"))
        if not ct:
            continue
        # Compound comps (Demon/Dragon) fit if either half matches.
        fit = max(tribes.get(part, 0) for part in ct.split("/"))
        if fit > best_score:
            best_score = fit
            best = comp
    return best


if __name__ == "__main__":
    # Smoke test: a Glambot engine board. The engine pieces (Glambot, Utility
    # Drone) should rank high despite modest stats, because the simulator credits
    # them with the growth the engine drives.
    demo = [
        {"card": "BG36_853", "atk": 4, "health": 4, "tribe": "MECHANICAL"},    # Glambot (engine)
        {"card": "BG26_152", "atk": 4, "health": 6, "tribe": "MECHANICAL"},    # Utility Drone (payoff)
        {"card": "BG35_883", "atk": 6, "health": 6, "tribe": None},            # Balinda (multiplier)
        {"card": "BG29_503", "atk": 57, "health": 57, "tribe": "MECHANICAL"},  # filler
    ]
    ranked = sell_recommendation(demo, [])
    for c, v in ranked:
        print(f"  {c}: {v:.1f}")
