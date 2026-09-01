"""Minion value function for the coach.

Scores a board minion in the context of the current comp, hero power, trinkets,
and opponent board. Higher score = more valuable to keep. Used to answer "which
card is safest to sell?" via marginal contribution.

Design: analysis/VALUE_FUNCTION.md. The weights (W_*) are initial guesses,
intended to be tuned against real games.
"""
import json
import os
import re

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
W_GROWTH = 2.0      # per point of growth potential (how much a minion can scale)
W_SPELL_FUEL = 0.3  # per stat of marginal engine growth one spell cast buys

# Keywords/phrases that mark a scaling/engine minion vs a plain body.
_SCALING_MARKERS = ("end of turn", "whenever you play", "improves", "each",
                    "triggers twice", "reborn", "deathrattle", "battlecry")
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


def _load_card_db():
    """card id -> {name, race, attack, health, mechanics, text} from the BG pool.

    Loads from meta/minions.json (the 245-minion Battlegrounds pool), NOT the
    full hearthstonejson DB (.cards_full.json) which doesn't carry BG card IDs —
    the value function was blind to BG card text (e.g. Ravaging Scorpid's Beetle
    scaling) and underrated them. See VALUE_FUNCTION.md "BG-pool guardrail".
    """
    path = os.path.join(_HERE, "meta", "minions.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        minions = json.load(f)
    out = {}
    for c in minions:
        out[c.get("id")] = {
            "name": c.get("name"),
            "race": c.get("tribe"),  # minions.json uses 'tribe', not 'race'
            "attack": c.get("attack"),
            "health": c.get("health"),
            "mechanics": c.get("mechanics", []),
            "text": (c.get("text") or "").lower(),
        }
    return out


def _load_spell_db():
    """card id -> {name, tier, cost, text} from meta/tavern_spells.json."""
    path = os.path.join(_HERE, "meta", "tavern_spells.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else list(data.values())
    return {s.get("id"): s for s in items
            if isinstance(s, dict) and s.get("id")}


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


def _spell_fuel_bonus(board_minions, names, scenario=None):
    """Marginal growth one extra spell cast buys on the board's cast-spell engines.

    For each running engine whose trigger is cast_spell, run the simulator at
    the current per-turn cast count and at +1; the delta is exactly what one
    bought spell is worth as engine fuel. Returns the best single-engine delta
    (one gold buys one cast — spells don't stack).
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
        plus = simulate_growth(enriched, dict(sc, cast_spell=n + 1), engine)["gain"]
        delta = (plus["atk"] + plus["hp"]) - (base["atk"] + base["hp"])
        best = max(best, delta)
    return best


def _spell_score(spell, board_minions, names, scenario=None):
    """Value of buying a tavern spell now — comparable to minion shop scores.

    Direct effect per gold (a 1-cost +3/+1 competes with a tier-1 body), plus
    the engine-fuel bonus when the board runs a cast-spell engine: the spell
    converts spare gold into the engine's per-cast growth.
    """
    cost = spell.get("cost") or 1
    points = _spell_effect(spell, len(board_minions or []))
    fuel = _spell_fuel_bonus(board_minions, names, scenario)
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
    """True if the card multiplies other minions' effects (Drakkari etc.)."""
    text = (card or {}).get("text") or ""
    return any(p in text for p in ("triggers twice", "trigger twice", "double",
                                   "extra time"))


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
    """
    text = (card or {}).get("text") or ""
    score = 0.0
    # Growth triggers — how often the effect fires.
    if "end of turn" in text:
        score += 2.0
    if "whenever you play" in text or "whenever you summon" in text:
        score += 3.0
    if "whenever you cast" in text or "after you cast" in text:
        score += 4.0  # spell comps cast a lot
    if "magnetize" in text:
        score += 4.0
    if "battlecry" in text:
        score += 2.0
    if "deathrattle" in text:
        score += 2.0
    if "improve" in text:
        score += 3.0  # compounding
    if "gain its stats" in text or "consume" in text:
        score += 3.0  # eat-growth
    # Magnitude — the buff size (+N/+N).
    m = re.search(r"\+(\d+)/\+(\d+)", text)
    if m:
        score += (int(m.group(1)) + int(m.group(2))) / 2.0
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
                        hero_power=None, trinkets=None):
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
    Returns a list of (card_id, score) sorted asecending (best to sell first).
    """
    card_db = _load_card_db()
    # Pick the comp whose tribe most overlaps the board (a crude comp fit).
    comp = _best_comp(board_minions, comps)
    trinkets = trinkets or []
    # Total stats of the scaling minions on the board (a multiplier amplifies this).
    board_scaling = sum((m.get("atk") or 0) + (m.get("health") or 0)
                        for m in board_minions if _is_scaling(card_db.get(m["card"])))
    # Board's dominant tribe (for engine recognition).
    from collections import Counter
    tribes = Counter(normalize(m.get("tribe")) for m in board_minions
                     if normalize(m.get("tribe")))
    dominant_tribe = tribes.most_common(1)[0][0] if tribes else None

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
        scored.append((m["card"], val, comp))
    scored.sort(key=lambda x: (x[1], x[0]))
    return [(c, v) for c, v, _ in scored]


def shop_ranking(shop_cards, comps, board_minions=None, allowed_tribes=None,
                 hero_power=None, trinkets=None, scenario=None):
    """Rank the shop's tavern cards (minions AND spells) by value.

    `shop_cards`: list of card ids currently offered. `comps`: the playable comps
    (slug -> comp). `board_minions`: the current board, used to pick the best-fit
    comp. `allowed_tribes`: canonical allowed tribes, or None when unknown (no
    penalty). `hero_power`/`trinkets`: the W_HERO / W_TRINKET synergy inputs.
    `scenario`: real per-turn trigger counts (feeds the spell fuel term).
    Returns a list of (card_id, score) sorted most-valuable first, so the
    coach can headline "Buy this".
    """
    card_db = _load_card_db()
    spell_db = _load_spell_db()
    names = _load_bg_names()
    comp = None
    if comps:
        # Score shop cards against the TARGET comp (what you're building toward),
        # not the current board's implied comp — so the buy recommendation guides
        # the pivot/commit rather than just matching the current board.
        if board_minions:
            comp = comp_target(board_minions, comps)
        if comp is None:
            comp = next(iter(comps.values()))
    engine_bonus = _engine_growth_bonus(board_minions, names) if board_minions else {}
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
        # Strongly prefer the target comp's core/addon cards, so the buy
        # recommendation actually guides the build rather than just matching stats.
        if comp:
            if cid in comp.get("core", []):
                val += 10.0
            elif cid in comp.get("addons", []):
                val += 5.0
        if is_banned(m.get("tribe"), allowed_tribes):
            val -= 2.0  # banned-tribe minion can't grow
        scored.append((cid, val))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def top_move(analysis):
    """A one-line decision call with the *intention* behind each part.

    `analysis` is the coach dict (hero, tier, gold, buy_this, sell_rank, ...).
    Returns a short actionable line like "Buy Air Baller (committing to
    Elementals) · sell Surfing Sylvar (making room) · level (access to tier 5)",
    or a fallback when there's nothing pressing.

    Every suggestion is affordability-aware: a "level" you can't pay for is
    replaced by the save/next-step version, and "buy this" falls back down the
    shop ranking to the first card actually affordable this turn.
    """
    names = _load_bg_names()
    card_db = _load_card_db()
    spell_db = _load_spell_db()
    # Buy costs come from either pool (minions and tavern spells carry `cost`).
    costs = {**{c: (v or {}).get("cost") for c, v in card_db.items()},
             **{c: (v or {}).get("cost") for c, v in spell_db.items()}}
    comp = _best_comp(analysis.get("board", []), analysis.get("playable_comps") or {})
    tier = analysis.get("tier")
    gold = analysis.get("gold")
    parts = []

    # Buy: the headline pick, or the best card we can actually afford, or roll.
    shop_rank = analysis.get("shop_rank") or []
    bought = None
    if analysis.get("buy_this"):
        cid = analysis["buy_this"]
        cost = costs.get(cid)
        if gold is not None and cost is not None and gold < cost:
            # Can't afford the headline pick — walk the ranking for one we can.
            fallback = None
            for alt, _v in shop_rank:
                alt_cost = costs.get(alt)
                if alt_cost is None or gold >= alt_cost:
                    fallback = alt
                    break
            if fallback is None:
                parts.append(f"roll — {names.get(cid, cid)} costs {cost}, "
                             f"you have {gold}")
                cid = None  # nothing affordable — don't also say "Buy X"
            else:
                cid = fallback
        if cid is not None:
            bought = cid
            parts.append(f"Buy {names.get(cid, cid)} "
                         f"({_buy_intention(cid, comp, card_db, spell_db)})")
    # Only suggest selling to "make room" when the board is full AND we're buying
    # something that needs the slot. If there's space, selling is unnecessary.
    if bought is not None and len(analysis.get("board", [])) >= 7 \
            and analysis.get("sell_rank"):
        worst = analysis["sell_rank"][0]  # safest to sell
        if worst[1] < 15:  # a clear filler (low value)
            parts.append(f"sell {names.get(worst[0], worst[0])} (making room)")
    # Level: only when affordable; otherwise say WHAT's missing and what to do
    # with the gold meanwhile. When affordable it LEADS the line — replay
    # review showed the player's real leveling tempo was the winning move the
    # coach kept demoting below a generic buy pick.
    level_lead = None
    if tier and tier < 6:
        level_cost = tier + 1  # BG upgrade cost approximation
        if gold is None:
            level_lead = f"level (access to tier {tier + 1})"
        elif gold >= level_cost:
            spare = gold - level_cost
            level_lead = (f"level (access to tier {tier + 1})"
                          + (f" — {spare} left for a buy/roll" if spare else ""))
        else:
            level_lead = (f"level NEXT turn — {level_cost - gold} short; "
                          f"spend the rest on buys/rolls")
    if level_lead and not level_lead.startswith("level NEXT"):
        if parts:
            lead = level_lead.split(" — ")[0]  # the "· Buy X" parts say it
            return lead + " · " + " · ".join(parts)
        return level_lead
    if parts:
        if level_lead:
            parts.append(level_lead)
        return " · ".join(parts)
    # Nothing pressing: if the board is full and has end-of-turn scaling, the
    # right move is to pass and let the engine grow.
    if len(analysis.get("board", [])) >= 7 \
            and _has_end_of_turn(analysis.get("board", []), card_db):
        return "wait for end of turn — let the engine scale"
    # Nothing affordable and nothing to level: roll unless there's no gold at all.
    if gold is not None and gold >= 1:
        return "roll — nothing in the shop beats your gold; level needs saving"
    # Otherwise point at the target comp so the advice stays actionable instead
    # of going stale ("committing to X" with no next step).
    target = analysis.get("target_comp")
    if target:
        return f"hold — look for {target} core cards"
    return "stabilize / roll for your comp"


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


_TIER_SCORE = {"S": 3, "A": 2, "B": 1}

_CORPUS_PATH = os.path.join(_HERE, "meta", "corpus_stats.json")
_CORPUS = None


def _corpus_scores():
    """comp name -> shrunk placement strength from the player's own replays.

    strength = (4.5 - avg_place) — BG mean placement on a 1..8 board is ~4.5 —
    shrunk toward 0 by sample size (n/(n+3)) so a lucky single game barely
    moves the needle. Missing corpus file or comp -> 0.0. Observational data
    (placement is confounded); see DESIGN.md "Honest caveats".
    """
    global _CORPUS
    if _CORPUS is None:
        scores = {}
        if os.path.exists(_CORPUS_PATH):
            with open(_CORPUS_PATH, encoding="utf-8") as f:
                stats = json.load(f)
            for name, s in (stats.get("comps") or {}).items():
                n = s.get("games") or 0
                if n <= 0 or s.get("avg_place") is None:
                    continue
                strength = 4.5 - s["avg_place"]
                scores[name] = strength * n / (n + 3)
        _CORPUS = scores
    return _CORPUS


def _corpus_bonus(comp_name, weight=0.5):
    """Corpus placement bonus for a comp name (sample-shrunk, tier-equivalents).
    A comp placing 1.0 on a large sample scores +1.5, i.e. S-tier-equivalent."""
    return weight * _corpus_scores().get(comp_name, 0.0)


def _tier_score(t):
    return _TIER_SCORE.get((t or "").upper(), 1)


def comp_target(board, comps):
    """The best comp to build toward, given the board and playable comps.

    If you're deep into a comp (>=2 core cards on the board), commit to it. Else
    pivot to the best comp by meta tier + the comp's placement in the player's
    own replay corpus (sample-shrunk; see _corpus_scores). Returns comp or None.
    """
    board_cards = {m["card"] for m in board}
    committed = None
    for comp in comps.values():
        overlap = len(set(comp.get("core", [])) & board_cards)
        if overlap >= 2 and (committed is None or overlap > committed[1]):
            committed = (comp, overlap)
    if committed:
        return committed[0]
    if not comps:
        return None
    return max(comps.values(), key=lambda c: _tier_score(c.get("meta_tier"))
               + _corpus_bonus(c.get("name")))


def target_state(target, board):
    """'committing' if the target comp's core cards are on the board, else 'pivot'."""
    if not target:
        return None
    core = set(target.get("core", []))
    board_cards = {m["card"] for m in board}
    return "committing" if core & board_cards else "pivot"


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


def _load_bg_names():
    """card id -> name from the BG pools (meta/minions.json + tavern_spells.json).

    The engine matching needs BG card names; `.cards_full.json` (the full
    hearthstonejson DB) doesn't carry the BG card IDs. Spell names are included
    so shop/buy advice can display tavern spells (their ids never collide with
    minion ids).
    """
    path = os.path.join(_HERE, "meta", "minions.json")
    names = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            minions = json.load(f)
        names = {m.get("id"): m.get("name") for m in minions}
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


def _engine_growth_bonus(board_minions, names, scenario=None):
    """Run the growth simulator for every engine whose core is present on the
    board and return {card_id: value_bonus} for the engine pieces.

    Each engine piece gets a bonus proportional to the total simulated growth the
    engine drives per turn — so a low-stats engine (Nomi, Glambot) ranks high
    because it's what makes the board grow. Crediting all running engines (not
    just the best-fit one) handles hybrid boards (e.g. Mana Surge + Unbound).
    """
    engines = _load_engines()
    bonus = {}
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
        # Chain source cards (the engine pieces).
        for step in engine["chain"]:
            for m in board_minions:
                if step["source"].lower() in (names.get(m["card"]) or "").lower():
                    bonus[m["card"]] = W_ENGINE_SIM * total
            # The shop-buff engine (e.g. Nomi) that makes a compounding step
            # compound is as critical as the payoff; credit it too.
            if step.get("buff_source"):
                for m in board_minions:
                    if step["buff_source"].lower() in (names.get(m["card"]) or "").lower():
                        bonus[m["card"]] = W_ENGINE_SIM * total
        # Multiplier cards (Balinda/Drakkari/Brann/Titus) amplify the engine;
        # they're not chain sources but are just as critical to keep.
        for cards in _MULTIPLIERS.values():
            for card_name in cards:
                for m in board_minions:
                    if card_name.lower() in (names.get(m["card"]) or "").lower():
                        bonus[m["card"]] = W_ENGINE_SIM * total
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
