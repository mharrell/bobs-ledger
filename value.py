"""Minion value function for the coach.

Scores a board minion in the context of the current comp, hero power, trinkets,
and opponent board. Higher score = more valuable to keep. Used to answer "which
card is safest to sell?" via marginal contribution.

Design: analysis/VALUE_FUNCTION.md. The weights (W_*) are initial guesses,
intended to be tuned against real games.
"""
import collections
import functools
import json
import os
import re

import meta
import pool
from player_actions import _load_bg_magnetic_ids
from simulate_growth import _MULTIPLIERS, _load_engines, simulate_growth
from tribes import is_banned, matches, normalize, overlaps, parts

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
W_COMBAT_ENGINE = 8.0  # self-improving combat engines (Tasty Lobster/Lurking
                       # Leviathan): gains evaporate each fight but the grant
                       # count/size compounds permanently — above a flat
                       # combat buffer, below a stat-persisting engine
W_ENGINE_SIM = 0.05  # per stat of simulated growth the board's engine drives
W_ENGINE_OFF_TRIBE = 0.4  # engine whose tribe fights the board's dominant
                          # tribe: its scaling lands on minions you're about
                          # to stop buying (Deflect-o-Bot atop a beast shop,
                          # 2026-09-06 Reno game t7) — credit damped, not erased
W_GROWTH = 2.0      # per point of growth potential (how much a minion can scale)
W_SHOP_GOLDEN = 25.0  # a GOLDEN shop minion (player-confirmed 2026-09-08): still
                      # costs the flat 3, and playing it pays the triple reward
                      # immediately — the golden body (3 copies stacked) plus the
                      # reward outranks a missing comp core (+14). Matches the
                      # hand plan's play-now golden score (hand_plan +25.0).
W_SPELL_FUEL = 0.3  # per stat of marginal engine growth one spell cast buys
W_OFF_COMP = -2.0   # shop card whose tribe fights a COMMITTED comp (damping)
W_MULT = 4.0        # multiplier glue (Balinda/Drakkari-class): worth what it
                    # amplifies, not its stats — never "safest to sell" glue
W_SELL_FLOOR = 16.0  # comp glue can't rank into "safe to sell" (below the
                     # 15 filler threshold shared with top_move and the UI)
W_RECIPE_FUEL = 10.0  # shop card that fuels an ACTIVE engine recipe (analysis/
                      # engine_coaching.md Plan 1: hero power x trinket engines,
                      # e.g. Shudderwock + Sous Chef Sticker -> every Battlecry
                      # minion is repeatable value). Sized BETWEEN addon (+7)
                      # and comp core (+14) inside the existing family — loud
                      # at play time, but it can't outrank a missing core.
W_OUT_OF_PLAY = 8.0   # shop card that is OUT OF PLAY entirely (removed by a
                      # patch, or a tribe rotated out of the pool — see
                      # meta/out_of_play.json + playable.py). Deliberately
                      # heavier than the banned-tribe penalty (-2): "banned in
                      # this game" still exists next game, "out of play" does
                      # not exist at all. Only reachable from a stale shop, i.e.
                      # a historical replay reviewed under current rules.

# Hand-charge kits (2026-09-10 replay, curatively encoded per the card-text
# discipline): a charger gains stats WHILE IN HAND and needs a deployer to
# reach the board — holding it is the plan, not a stall, and the advice must
# flip the turn the deployer leaves. From the cards' own text:
#   Bream Counter: "While this is in your hand, after you play a Murloc,
#     gain +6/+6."
#   Diremuck Forager: "Start of Combat: When you have space, summon the
#     highest-Attack Murloc from hand for this combat only."
# (2026-09-10 Cariel game: two counters charged to 78/78 in hand; the
# Forager died t7 and the second was sold t9, nothing re-bought it, and the
# coach kept saying "Play Bream Counter x2" — right only AFTER the engine
# died, never modeling the hold that was correct while it lived.)
HAND_DEPLOY_KITS = {
    "BG26_137": {  # Bream Counter
        "deployer": "BG27_556",  # Diremuck Forager
        "deployer_name": "Diremuck Forager",
        "summons": "summons the highest-Attack Murloc from hand at start of combat",
        "needs_space": True,  # "When you have space" — a full board blocks it
    },
}

W_ENGINE_DEPLOY = 8.0  # shop deployer for a charger sitting in hand
SELL_FILLER_SCORE = 15.0  # a board/shop value under this reads as clear filler
                          # (top_move; the overlay keys its coloring off it too)
DYING_HEALTH = 12  # effective health (hp+armor) at/below this = "dying" —
                   # leveling beats board (top_move's Q0 gate)
FAVOR_HP_CEILING = 10  # at <= this effective HP the forecast never says
                       # "favored" — "ahead on paper" (2026-09-16 evening:
                       # 'favored — 895 vs 165' one minute before dying)

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

# Combat-phase gains vs persistence (player rule 2026-09-11): stat increases
# gained DURING a battle evaporate at combat end unless the card text says
# they persist. A minion that buffs only during that battle is combat POWER
# (W_COMBAT_SCALE), not a growth engine — crediting evaporating buffs as
# persistent growth inflated combat helpers over real engines (Tasty Lobster
# scored growth 6.5 / role "engine"). Summons and generated CARDS from combat
# triggers DO persist (tokens stay on the board) — only stat gains evaporate.
_GAIN_PERSISTS_MARKERS = ("permanently", "this game", "wherever", "keep")
# ...and gains granted TO a card in the hand persist even mid-combat (rule
# follow-up, same day): the hand card didn't fight, so nothing reverts
# (Winterfinner's hand-buff, Tide Oracle's kill-transfer). Gains FROM the
# hand ONTO a board minion (Choral Mrrrglr, Costume Enthusiast) are NOT
# covered — the receiving side decides.
_HAND_GAIN_PERSISTS_MARKERS = ("give a minion in your hand",
                               "give the left-most minion in your hand",
                               "to a minion in your hand")
_EXPLICIT_TEMPORARY_MARKERS = ("until next turn", "this combat only",
                               "rest of this combat", "for this combat")
_COMBAT_GAIN_TRIGGERS = ("start of combat", "during combat", "in combat",
                         "when this attacks", "after this attacks",
                         "whenever this attacks", "avenge", "deathrattle",
                         # Rally fires at the start of combat (Deathstrider:
                         # "After a friendly Rally minion attacks"); bare
                         # "attacks" covers "Whenever a friendly X attacks"
                         # shapes (Cage Gnawer, Roaring Recruiter); "is
                         # Reborn" procs in combat (Barrier Banshee);
                         # "this takes damage" is combat (Winterfinner) —
                         # "your hero takes damage" is NOT, the demon loop
                         # self-damages in the tavern too.
                         "rally", "attacks", "is reborn",
                         "this takes damage")
# What a card's text must say for the trigger to be delivering a STAT gain
# (vs a summon / a generated card / removal, which persist or don't grow).
# "plays a blood gem" counts: gems granted mid-combat evaporate — Razorfen
# Vineweaver's "3 permanent Blood Gems" is the text saying otherwise.
_COMBAT_STAT_GAIN_MARKERS = ("give ", "gain +", "have +", "gain its",
                             "gain the stats", "gain the attack",
                             "double its attack", "plays a blood gem")
# Cards whose prose defeats the markers, decided by hand (the Butchering
# pattern: literally read the card). Matched by NAME — log ids patch-drift.
COMBAT_ONLY_GAIN_OVERRIDES = {
    # "Improves permanently" — but what improves is the start-of-combat buff,
    # which still evaporates each combat.
    "Fire-forged Evoker": True,
    # "...improved by every 3 spells you've cast this game" — "this game"
    # counts the casts (the improvement), it does NOT persist the buff.
    "Showy Cyclist": True,
    # "give it +3 Attack and improve this permanently" — "permanently"
    # improves the CARD's grant, not the summoned beast's stats; combat
    # grants still evaporate (player rule follow-up 2026-09-11).
    "Lurking Leviathan": True,
    # No persistence wording in the text, BUT the gains persist when the
    # trigger fires in the tavern (self-damage/knight deaths) — the curated
    # undead-attack-scaling engine entry (player-corrected 2026-09-08) says
    # the transfer lands "in combat and in the shop". Dual-phase, so NOT
    # combat-only.
    "Snazzy Phantom": False,
}

# Self-improving combat engines (player rule follow-up 2026-09-11): the stats
# they grant evaporate at combat end, but the card PERMANENTLY scales its own
# output — Tasty Lobster's "Improve your future Tasty Lobsters" makes each
# future grant fire once more (player-confirmed: the grant COUNT compounds),
# and Lurking Leviathan's grant size grows. Their own class: not growth
# engines (no stats persist) and not flat combat buffers — the per-fight
# contribution compounds. Recognized at W_COMBAT_ENGINE; shop-path summons
# (buying a beast with Leviathan aboard) DO stick.
SELF_IMPROVING_COMBAT_ENGINES = {
    "Tasty Lobster": "each grant makes future grants fire once more",
    "Lurking Leviathan": "the per-summon grant grows permanently",
}


def _is_self_improving_combat(card):
    """True for self-improving combat engines (SELF_IMPROVING_COMBAT_ENGINES)."""
    return ((card or {}).get("name") or "") in SELF_IMPROVING_COMBAT_ENGINES


def _flat_text(card):
    """Card text with line wraps collapsed. DB text wraps mid-phrase
    ("+5/+5 this\ngame"), which breaks substring marker matching — the
    first pass flagged Ravaging Scorpid combat-only because its persist
    marker "this game" straddled a newline (2026-09-11)."""
    return " ".join(((card or {}).get("text") or "").split())


def _combat_only_gain(card):
    """True if the card's stat gains happen in battle and don't persist.

    Player rule 2026-09-11: combat buffs revert at combat end unless the text
    says otherwise — these minions are one-fight power, not growth engines.
    """
    text = _flat_text(card)
    if not text:
        return False
    name = (card or {}).get("name") or ""
    if name in COMBAT_ONLY_GAIN_OVERRIDES:
        return COMBAT_ONLY_GAIN_OVERRIDES[name]
    if any(m in text for m in _EXPLICIT_TEMPORARY_MARKERS):
        return True   # text says the gain expires
    if any(m in text for m in _GAIN_PERSISTS_MARKERS):
        return False  # text says the gain stays
    if any(m in text for m in _HAND_GAIN_PERSISTS_MARKERS):
        return False  # the buff lands on a hand card — it didn't fight
    shaped = (any(m in text for m in _COMBAT_STAT_GAIN_MARKERS)
              or bool(re.search(r"\+\d+/\+\d+", text)))
    if not shaped:
        return False  # summons / generated cards / removal — not a stat gain
    return any(m in text for m in _COMBAT_GAIN_TRIGGERS)

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
    """card id -> {name, tier, cost, text, effects?} from meta/tavern_spells.json.

    `effects` carries the curated card-read (meta/spell_effects.json, the
    2026-09-08 card-text pass) when the spell has one.
    """
    curated = meta.spell_effects()
    out = {}
    for s in meta.spells():
        sid = s.get("id")
        if not sid:
            continue
        rec = dict(s)
        ann = curated.get(sid)
        if ann:
            rec["effects"] = ann.get("effects") or []
        out[sid] = rec
    return out


def _curated_effect_points(effects, board_size=0):
    """Deterministic points from the curated card-read (spell_effects.json).

    The card-text discipline (2026-09-08, player rule: "literally read the
    text of each card and each spell"): each spell's text was read and
    encoded ONCE — scope multipliers, recurring/delayed factors, gold and
    utility values are decided at read time per card, not guessed at
    decision time by the regex parser (which stays as the fallback for
    unannotated spells).
    """
    def one(eff):
        k = eff.get("kind")
        if k == "stats":
            scope = eff.get("scope", "target")
            mult = min(max(board_size, 1), 7) if scope == "all" else 1
            if scope == "tavern":
                mult = 2  # the shop's minions you'll buy across the turn
            stat = (eff.get("atk", 0) + eff.get("hp", 0)) * eff.get("count", 1) * mult
            if eff.get("recurring"):
                stat *= 2.0
            if eff.get("delayed"):
                stat *= 0.5
            return stat
        if k == "gold":
            return eff.get("n", 0) * 2.0
        if k == "max_gold":
            return eff.get("n", 1) * 4.0  # recurring income
        if k == "summon":
            pts = (eff.get("atk", 0) + eff.get("hp", 0)) * eff.get("n", 1)
            if eff.get("recurring"):
                pts *= 2.0
            return pts + 2.0
        if k == "discover":
            return eff.get("points", 2.0)
        if k == "golden":
            return 8.0
        if k == "spellcraft":
            return 2.0  # the direct read; the fuel term is computed separately
        if k == "utility":
            return eff.get("points", 0.0)
        if k == "choose_one":
            return max(sum(one(e) for e in branch)
                       for branch in eff.get("branches", []))
        return 0.0
    return sum(one(e) for e in effects)


def _spell_effect(spell, board_size=0):
    """Direct-effect points of a tavern spell from its text.

    Annotated spells (meta/spell_effects.json — the curated card-text pass)
    score deterministically from the encoded effects. Unannotated spells
    fall back to the regex read: +N/+N (and bare +N) grants count their stat
    points; a whole-board scope multiplies by the current board size (capped
    at 7); recurring/scaling text doubles; one-shot utility effects the stat
    parse can't see (discover, summon, triple, steal) add flat amounts.
    Rough by design — the terms get honed against the replay corpus.
    """
    text = (spell.get("text") or "").lower()
    curated = spell.get("effects")
    if curated:
        return _curated_effect_points(curated, board_size)
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
    # Gold grants (economy spells — Tavern Coin, Wealthy Bounty, the
    # tie/win Overconfidence; player-flagged 2026-09-08, every one parsed
    # to 0 before this): a gold is liquid tempo, ~2 direct-effect points.
    # "Gain N Gold next turn" keeps full value (it IS next turn's purse).
    for m in re.finditer(r"gain (\d+) gold", text):
        points += int(m.group(1)) * 2.0
    # "Increase your maximum gold by 1" is recurring income — it pays every
    # turn from here, worth double per point.
    m = re.search(r"maximum gold by (\d+)", text)
    if m:
        points += int(m.group(1)) * 4.0
    return points


def _is_shop_turn_buff(spell):
    """A ONE-SHOT buff on the Tavern's minions (Them Apples-class).

    Its stats live and die with THIS shop (player rule 2026-09-08: the
    coach said "Cast Them Apples", then LEVEL and no purchases — the
    spell was wasted). It is only worth casting when this turn's plan
    BUYS shop minions before any refresh: leveling keeps the shop, a
    roll wipes it, a pass wastes it. Refresh-scaling tavern spells
    (recurring: "every Refresh this game buffs the Tavern") re-apply on
    future refreshes, so a no-buy turn doesn't waste them. Unannotated
    spells fall back to the text read; recurring language keeps them
    exempt the same way.
    """
    if not spell:
        return False
    for eff in spell.get("effects") or []:
        if (eff.get("kind") == "stats" and eff.get("scope") == "tavern"
                and not eff.get("recurring")):
            return True
    if spell.get("effects"):
        return False
    text = (spell.get("text") or "").lower()
    return (bool(re.search(r"minions in (bob's |the )?tavern", text))
            and "every" not in text and "each" not in text)


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
    # Combat-only gains are one-fight power, not engine/scaling roles
    # (player rule 2026-09-11): Banana Slamma's in-combat "double" and a
    # deathrattle stat buff don't make a growth role.
    combat_only = _combat_only_gain(card)
    # A compounding engine (scales with itself / each summon).
    if not combat_only and any(m in text for m in _ENGINE_MARKERS):
        return "engine"
    # Ongoing scaling (end-of-turn, whenever, buffs each turn).
    if not combat_only and any(m in text for m in _SCALING_MARKERS):
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
    """True if the card is a whole-board/comp scaling engine (e.g. Nomi).
    Combat-only buff-givers are NOT engines — their buffs evaporate at
    combat end (player rule 2026-09-11); they'd otherwise ride the
    "give "/"your " markers to W_ENGINE credit (Humming Bird, Amber
    Guardian, Goldrinn)."""
    if _combat_only_gain(card):
        return False
    text = (card or {}).get("text") or ""
    return any(m in text for m in _ENGINE_TEXT_MARKERS)


def _is_combat_scaling(card):
    """True if the card scales during combat (invisible to the snapshot).
    Includes combat-only gains — helpful for one fight, but not growth
    (player rule 2026-09-11)."""
    text = (card or {}).get("text") or ""
    return (any(m in text for m in _COMBAT_SCALE_MARKERS)
            or _combat_only_gain(card))


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

    Combat-only gains (player rule 2026-09-11) are not growth at all: a buff
    that evaporates at combat end keeps only its persistent halves
    (battlecry/magnetize). The one-fight power itself is W_COMBAT_SCALE.
    """
    text = (card or {}).get("text") or ""
    if _combat_only_gain(card):
        # The repeating-gain terms below describe one combat's power, not
        # persistent stats — keep only the persistent halves.
        flat = _flat_text(card)
        return ((1.0 if "battlecry" in flat else 0.0)
                + (4.0 if "magnetize" in flat else 0.0))
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
    # its small stats suggest. The DB tribe lookup is the certain answer
    # (compound- and Amalgam-aware via tribes.matches); the text naming the
    # tribe stays only as the fallback for a genuinely untribed card whose
    # text scales it — _is_engine's "give your"-shaped markers gate that, so
    # kill/destroy text can't ride along.
    if dominant_tribe and card and _is_engine(card):
        if (matches(card.get("race"), dominant_tribe)
                or dominant_tribe.lower() in (card.get("text") or "")):
            score += W_ENGINE
    # Combat-time scaling is invisible to the pre-combat snapshot; flag as +value.
    # Self-improving combat engines (Lobster/Leviathan) compound their per-fight
    # output — worth more than a flat buffer, less than a stat-persisting engine.
    if _is_combat_scaling(card):
        score += W_COMBAT_ENGINE if _is_self_improving_combat(card) \
            else W_COMBAT_SCALE
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
        if overlaps(minion.get("tribe"), comp.get("tribe")):
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

    # Trinket synergy: curated reads (trinket_effects.json) match a card's
    # tribe/mechanics precisely; plain description strings fall back to the
    # old substring read.
    if trinkets and card:
        race = normalize(card.get("race")) or card.get("race")
        text = (card.get("text") or "").lower()
        mechanics = {m.lower() for m in (card.get("mechanics") or [])}
        for t in trinkets:
            if _trinket_synergy_hit(t, race, text, mechanics):
                score += W_TRINKET

    # Growth-aware engine value: how much the board's engine grows per turn.
    score += engine_bonus

    return score


def _trinket_synergy_hit(trinket, race, card_text, mechanics=()):
    """Does this trinket reward holding THIS card?

    `trinket` is a merged record (meta.trinkets() + trinket_effects.json:
    carries a "synergy" dict of tribes/keywords) or a plain description
    string (legacy callers — the old tribe-substring read).
    """
    if isinstance(trinket, str):
        return bool(race and race.lower() in trinket.lower())
    syn = trinket.get("synergy") or {}
    if syn.get("note"):  # the Compass-style free-text entry
        return False
    for tribe in syn.get("tribes") or []:
        if overlaps(race, tribe):
            return True
    for kw in syn.get("keywords") or []:
        k = kw.lower()
        if k in mechanics or (k in card_text and k in (
                "deathrattle", "battlecry", "taunt", "divine shield",
                "reborn", "magnetic", "blood gem")):
            return True
    return False


#: "Skip your first turn" / "Skip your first two turns" — the count is
#: optional in the wording (Ambassador Faelin omits it, A. F. Kay says "two").
_SKIP_TURNS_RE = re.compile(
    r"skip your first(?:\s+(one|two|three|four|\d+))?\s+turns?", re.I)
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4}


def _skipped_turn_count(hero_power):
    """How many opening turns this hero power skips (0 = it skips none).

    Read from the curated power text in meta/heroes.json — a wording read, not
    a behaviour guess — so a hero that skips two turns is not silently treated
    as skipping one.
    """
    m = _SKIP_TURNS_RE.search(hero_power or "")
    if not m:
        return 0
    token = (m.group(1) or "").lower()
    if not token:
        return 1
    return int(token) if token.isdigit() else _WORD_NUMBERS.get(token, 0)


def _out_of_play_reason(card_id, card):
    """Out-of-play explanation for a shop card, or None (fail-open).

    Thin wrapper over `playable.out_of_play_reason` so `value.py` has no hard
    dependency on the registry being present, and honours the
    `HEARTH_OUT_OF_PLAY=0` kill switch (used by historical replay reviews, which
    must be judged under the rules the game was played with).
    """
    try:
        import playable
    except ImportError:  # pragma: no cover
        return None
    card = card or {}
    return playable.out_of_play_reason(
        card_id, card.get("name"), card.get("tribe"))


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


def active_recipes(hero_name, trinkets=None):
    """Mechanical engine recipes live for THIS hero + held trinkets.

    `trinkets`: held-trinket records — the DB records live_coach resolves
    ("id"/"name"), the raw sighting dicts board_state returns ("cid"/
    "name"), or plain id/name strings. A recipe activates only when ALL of
    these hold: confidence == "mechanical" (observed rows sit inert until
    corpus data justifies them), the hero matches by name, and every
    trinket the recipe requires is held (matched by id or by name —
    pick-block ids drift across patches, the same rule as choices.py).
    Recipes modulate, never originate (analysis/engine_coaching.md): the
    output is a shop boost + an advice naming, never a comp target or a
    gate override.
    """
    held = set()
    for t in trinkets or []:
        if isinstance(t, str):
            held.add(t)
        else:
            for k in ("id", "cid", "name"):
                if t.get(k):
                    held.add(t[k])
    out = []
    # Required trinkets expand to every string that identifies them — the
    # DB id plus its stable name — so a sighting under a drifted log id
    # (BG35_MagicItem_801) still completes a recipe written with the DB id
    # (BG35_MagicItem_8012) via the name.
    db_names = {t.get("id"): t.get("name") for t in meta.trinkets()}
    for rid, rec in meta.engine_recipes().items():
        if rid.startswith("_"):  # the _comment prose row
            continue
        if rec.get("confidence") != "mechanical":
            continue
        if rec.get("hero") != hero_name:
            continue
        need = set()
        for tid in rec.get("trinkets") or []:
            need.add(tid)
            if db_names.get(tid):
                need.add(db_names[tid])
        if need and not need & held:
            continue
        out.append(dict(rec, id=rec.get("id", rid)))
    return out


def recipe_fuel_hit(card, recipe):
    """Does THIS card's literal text match a recipe's fuel spec?

    Mechanical only: the fuel keyword must appear in the card's own text
    (the Butchering-fix pattern — quoted keyword in, no runtime inference),
    so "Battlecry: Get a random Elemental." matches fuel {"keyword":
    "battlecry"} while a plain body can't ride along.
    """
    if not card or not recipe:
        return False
    kw = (recipe.get("fuel") or {}).get("keyword")
    if not kw:
        return False
    return kw.lower() in (card.get("text") or "").lower()


def shop_ranking(shop_cards, comps, board_minions=None, allowed_tribes=None,
                 hero_power=None, trinkets=None, scenario=None,
                 recent_cards=None, comp=None, hand=None, recipes=None):
    """Rank the shop's tavern cards (minions AND spells) by value.

    `shop_cards`: list of card ids currently offered. `comps`: the playable comps
    (slug -> comp). `board_minions`: the current board, used to pick the best-fit
    comp. `allowed_tribes`: canonical allowed tribes, or None when unknown (no
    penalty). `hero_power`/`trinkets`: the W_HERO / W_TRINKET synergy inputs.
    `scenario`: real per-turn trigger counts (feeds the spell fuel term).
    `recipes`: ACTIVE engine recipes (value.active_recipes output) — a card
    whose text feeds one gets its shop_boost (the loud play-time term).
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
    # A hand-charge kit wants its deployer back (2026-09-10: the Forager
    # died, the chargers kept growing in hand, and no shop advice ever
    # pointed at re-buying the engine).
    deployers_wanted = {k["deployer"] for c, k in HAND_DEPLOY_KITS.items()
                        if any(m.get("card") == c for m in (hand or []))}
    scored = []
    for cid in shop_cards:
        if cid in spell_db:
            # A tavern spell: effect-per-gold + cast-spell engine fuel, not the
            # minion value function (spells have no stats, comp role, or tribe).
            scored.append((cid, _spell_score(spell_db[cid], board_minions,
                                             names, scenario)))
            continue
        raw_cid = cid
        # A GOLDEN shop offer carries the "_G" id suffix: resolve to the base
        # card (comps, DB, board lookups key on base ids) but keep the raw id
        # in the ranking so the overlay/affordability walk still see the
        # golden. Without this the golden was dropped from the ranking
        # entirely (card_db has base ids only, 2026-09-08 audit).
        golden = cid.endswith("_G")
        if golden:
            cid = cid[:-2]
        card = card_db.get(cid)
        if not card:
            continue
        # A shop minion at base stats (un-bought); a golden's stats are the
        # stacked 3 copies (the merge), so score the golden body at 3x.
        atk, health = (card.get("attack") or 0), (card.get("health") or 0)
        if golden:
            atk, health = atk * 3, health * 3
        m = {"card": cid, "atk": atk, "health": health, "tribe": card.get("race")}
        val = minion_value(m, card, comp, hero_power, trinkets,
                           engine_bonus=engine_bonus.get(cid, 0))
        if golden:
            # ...and playing it pays the triple reward NOW — super-duper high
            # value (player rule), above a missing comp core (+14).
            val += W_SHOP_GOLDEN
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
            # Tribe overlap via lookup (compounds + Amalgams fit any comp
            # part); untribed stays off-comp here — it can't grow with the
            # build even when it doesn't fight it.
            if ct and not overlaps(m.get("tribe"), ct):
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
            if dt and tribe and not overlaps(tribe, dt):
                growth = growth_potential(card)
                if growth >= 2.0:
                    val -= W_GROWTH * growth * 0.75
        if is_banned(m.get("tribe"), allowed_tribes):
            val -= 2.0  # banned-tribe minion can't grow
        if W_OUT_OF_PLAY and _out_of_play_reason(cid, m):
            # Out of play entirely (removed by a patch, or a rotated-out tribe):
            # the card cannot be bought, so it must never headline a shop.
            # Sized above the banned-tribe penalty because "banned in this game"
            # still leaves the card existing elsewhere, while this does not.
            # Only reachable from a stale shop (a historical replay reviewed
            # under current rules) — the live game never offers these.
            val -= W_OUT_OF_PLAY
        if cid in deployers_wanted:
            # The deployer re-arms the engine: chargers in hand turn back
            # into per-combat bodies (plus the free-slot rule — the plan
            # text carries that).
            val += W_ENGINE_DEPLOY
        # Active engine recipes (analysis/engine_coaching.md Plan 1): a card
        # whose text feeds a live recipe (e.g. any Battlecry minion under
        # Shudderwock + Sous Chef Sticker) is build fuel. Applied AFTER the
        # committed-comp damp — the hero power re-fires the Battlecry
        # regardless of tribe, so a fuel card the build doesn't share a
        # tribe with still surfaces. The boost is sized under the core
        # bonus: fuel never displaces a missing comp core.
        for rec in recipes or []:
            if recipe_fuel_hit(card, rec):
                val += rec.get("shop_boost") or W_RECIPE_FUEL
                break
        scored.append((raw_cid, val))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def hand_engine(hand, board_minions):
    """Live status of a hand-charge kit, or None when no charger is in hand.

    The three facts the player needs at a glance (the 2026-09-10 game died
    on exactly these): is the deployer on board, is there a free board slot
    for its start-of-combat summon, and how many chargers are waiting.
    """
    board_ids = [b.get("card") for b in (board_minions or [])]
    hand_ids = [m.get("card") for m in (hand or []) if m.get("card")]
    for cid in dict.fromkeys(hand_ids):  # unique, hand order
        kit = HAND_DEPLOY_KITS.get(cid)
        if kit:
            return {"charger": cid,
                    "deployer": kit["deployer"],
                    "deployer_name": kit["deployer_name"],
                    "on_board": kit["deployer"] in board_ids,
                    "space": len(board_ids) < 7,
                    "charging": hand_ids.count(cid)}
    return None


def sell_reason(minion, card, comp=None, core=(), addons=(), banned_tribes=()):
    """WHY a board minion sits where the sell ranking put it.

    The 2026-09-10 ask: the Sell box must say whether a row is safe because
    it has no comp role ("off-comp filler", "stats only") or valuable for a
    REASON ("comp core" — that's a keep, not a stats read). Same inputs as
    the scoring: comp membership, banned tribe, scaling text, raw stats.
    `comp` is the target comp dict; `core`/`addons` the resolved target's
    card-id sets; `banned_tribes` the canonical banned display names.
    """
    cid = minion.get("card")
    if cid in core:
        return "comp core"
    if cid in addons:
        return "comp addon"
    if _is_multiplier(card):
        return "comp glue"
    tribe = normalize(minion.get("tribe"))
    if banned_tribes and tribe and tribe in banned_tribes:
        return "banned tribe — can't grow"
    if _is_scaling(card):
        return "scaler"
    if _is_engine(card):
        return "engine piece"
    stats = (minion.get("atk") or 0) + (minion.get("health") or 0)
    comp_tribe = comp.get("tribe") if comp else None
    off_comp = bool(tribe and comp_tribe
                    and not overlaps(minion.get("tribe"), comp_tribe))
    if stats >= 25:
        # Big body, no comp role — the "big stats so it's valuable" read the
        # 2026-09-10 ask wanted named distinctly from comp-piece keeps.
        return "off-comp body" if off_comp else "stats only — no comp role"
    return "off-comp filler" if off_comp else "filler"


def hand_plan(hand, board_minions=None, scenario=None, pool_held=None):
    """What to do with cards ALREADY in hand — plays the coach never made
    (2026-09-04: five spells sat in hand that would 10x the board's stats
    while the coach said nothing about them).

    pool_held (pool.own_holdings output) gates the golden hunt: holding for
    a 3rd copy is only advice while the shared pool can still produce one —
    when our own holdings already drained it, the hand copy plays instead.
    None (old callers, fixtures) keeps the evidence-free hold.

    Playing a minion stuck in hand (full board) costs no gold — a free
    body. Casting a spell from hand is also FREE (player rule 2026-09-19,
    confirmed by log ground truth: BlockType=PLAY blocks sourced from a
    HAND-zone spell contain no RESOURCES_USED change, while shop-side
    actions charge — the spell's price is paid when it is BOUGHT from the
    tavern). The 2026-09-16 evening "cast gold gate" that priced hand
    casts was a misdiagnosis of that evening's real complaint (a
    low-effect Tavern Coin leading a gold-0 plan): gold-gain spells
    already score ~2 points in _spell_effect, so they can't lead a real
    plan, and no gold gate is needed. Spells rank by
    direct effect + cast-engine fuel (each cast
    feeds end-of-turn compounding, which counts casts made THIS turn);
    hand minions rank by their value as a free play — with triple
    awareness over REGULAR copies only (a golden never combines): 2 on
    board = play NOW (golden), 1 on board = hold the hand copy and hunt
    a 3rd; and hand-charge kits (HAND_DEPLOY_KITS): hold the charger
    while its deployer is on board, play it the turn the deployer is
    gone. Returns a list of
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
                             if matches(b.get("tribe"), "Undead"))
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
            # the hand copy IS the triple — play it now). A GOLDEN never
            # combines (player rule, 2026-09-10 Buttons game: a Dark-Gift
            # golden + 1 regular read as "2 on board, buy the 3rd" — that
            # buy made nothing): only regular copies count toward a triple,
            # and a golden hand copy plays as a golden body, period.
            on_board = sum(1 for b in board
                           if b.get("card") == cid and not b.get("golden"))
            # Hand-charge kit awareness (2026-09-10 Cariel game): a charger
            # gains stats in hand and a DEPLOYER summons it at combat — hold
            # while the deployer lives (keeping it a summon slot), flip to
            # "play it" the turn the deployer is gone.
            kit = HAND_DEPLOY_KITS.get(cid)
            deployer_up = bool(kit) and any(b.get("card") == kit["deployer"]
                                            for b in board)
            verb, why = "play", None
            if on_board >= 2 and not m.get("golden"):
                # counted over REGULAR copies above — completing the golden
                # outranks holding for a deployer (Cariel-game decision)
                why = "triples golden!" + (" — sell to make room"
                                           if len(board) >= 7 else "")
            elif m.get("golden"):
                # a golden hand copy can't be part of a triple; playing it
                # as a golden body is the value (nothing left to charge)
                why = "golden body — goldens never combine" \
                    + (" — sell to make room" if len(board) >= 7 else "")
            elif on_board == 1:
                # Pool gate (phase 1, analysis/pool_availability.md): the
                # 3rd copy has to come from a future roll, and a drained
                # pool never rolls it — holding is a lost slot.
                if pool_held is not None and pool.left(cid, pool_held) == 0:
                    why = ("no 3rd copy left in the pool — play it "
                           "(a golden can't complete)")
                else:
                    verb = "hold"
                    why = ("hold — 1 regular on board; a 3rd copy "
                           "turns it golden")
            elif kit and deployer_up:
                verb = "hold"
                why = ("hold — " + kit["deployer_name"] + " " +
                       kit["summons"]
                       + (" — SELL a body: the summon needs a free slot"
                          if len(board) >= 7 else " — keep a board slot free"))
            elif kit:
                why = ("no " + kit["deployer_name"] + " on board — play it "
                       "(nothing will summon it)"
                       + ("; sell to make room first" if len(board) >= 7
                          else ""))
            elif len(board) >= 7:
                why = "board is full — sell to make room"
            score = minion_value(m, card)
            if on_board >= 2 and not m.get("golden"):
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


def _board_tribe_units(board, tribe):
    """Board minions sharing the comp's tribe — a cross-tribe flip needs
    more than one (the 2026-09-16 evening t16 flip fired on a single
    Naga). Same matching rule as _board_tribe_share."""
    t = normalize(tribe or "")
    if not t or not board:
        return 0
    return sum(1 for m in board
               if normalize(m.get("tribe")) in t.split("/"))


def sticky_comp_target(prev, new, prev_hits, new_hits, board=None,
                       dying=False):
    """Which comp to SHOW as the build direction.

    The 2026-09-06 Guff game churned 'Summon Beetles' -> 'Tasty Lobstah'
    phase-to-phase on identical tribe evidence — same build, different
    name, reading to the player as 'which build am I actually doing?'.
    When the new target shares the previous target's TRIBE, keep the
    previous comp unless the new one carries strictly more core evidence
    (board + recent hits, copies included — the caller computes both with
    _core_hits). Cross-tribe pivots pass through — stickiness must never
    fight the pivot override — EXCEPT the two 2026-09-16 evening t16
    rules: (a) no flip inside the DYING gate — the last phases of a dying
    game don't swap builds; (b) a flip that isn't carried by strictly
    more core evidence needs more than one tribe unit on board (the t16
    flip fired with the board's ONLY Naga being Fauna Whisperer).

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
        if dying:
            # The 2026-09-16 t16 rule: no flip while DYING. But a dying
            # board that genuinely BECAME another build must still be
            # recognized (2026-09-18: triple-golden Mech core stuck on
            # "Nagas" at 4 HP — the flip freeze outlived its evidence).
            # A flip passes when it is strictly better evidenced, or is a
            # board-dominant takeover (majority tribe vs the prev's
            # minority): those are commit corrections, not churn.
            stronger = new_hits > prev_hits
            takeover = (
                new_hits == prev_hits and new_hits >= 2
                and board is not None
                and _board_tribe_share(new, board) > 0.5
                and not _board_tribe_share(prev, board) > 0.5)
            if not (stronger or takeover):
                return prev
            return new
        if new_hits <= prev_hits and board is not None \
                and _board_tribe_units(board, new.get("tribe")) < 2:
            return prev
        return new  # a cross-tribe pivot is shown
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
    if analysis.get("never_won") and (analysis.get("turn") or 0) >= 3:
        # 2026-09-19 Reno game: bled in every fight from t2 and died 8th
        # — no line ever said the one true thing. A loss streak resets
        # and armor-soaked hits read as noise; zero wins does not.
        # Subsumes the streak clause (when never_won, streak == fights).
        bits.append(f"0 wins in {(analysis.get('turn') or 0) - 1} fights "
                    "— every fight has cost you HP; buy stats, not tiers")
    elif streak >= 2:
        bits.append(f"lost {streak} straight")
    health = analysis.get("health")
    armor = analysis.get("armor") or 0
    # The mortality clock keys on the REAL lobby (fought/announced boards),
    # never the historical baseline — a high baseline median at a late turn
    # is not the lobby you're about to fight.
    lobby = analysis.get("opp_stats") or analysis.get("lobby_opp")
    cap = analysis.get("damage_cap")
    if health is not None and lobby:
        eff = health + armor
        if cap and eff <= cap:
            # This season caps per-combat damage (BACON_COMBAT_DAMAGE_CAP,
            # escalating by round) — "one bad fight can end it" is literally
            # true only at or under the cap.
            bits.append(f"{eff} HP vs a {cap} damage cap — "
                        "one bad fight ends it, buy board now")
        elif cap and eff <= 2 * cap and lobby >= 100:
            bits.append(f"{eff} HP vs a {cap} damage cap — "
                        "two lost fights end it")
        elif eff <= DYING_HEALTH:
            bits.append(f"DYING at {health}"
                        + (f"+{armor}" if armor else "") + " — buy board now")
        elif eff <= 30 and lobby >= 100:
            # Armor is just extra health (player-corrected 2026-09-08) — the
            # signal is TOTAL effective HP vs the lobby's damage output
            # (t7-t12 of the Guff game were all wins, then one fight ended
            # it).
            bits.append(f"{eff} HP left — one bad fight can end it")
    if not bits:
        return None
    return " · ".join(bits[:3])


def _buy_prices(analysis):
    """Buy prices for the shop overlay/affordability walk.

    Minions cost a FLAT 3 (the current patch's default for ALL tiers,
    GOLDEN SHOP MINIONS INCLUDED — player-confirmed 2026-09-08: a golden
    in the shop still buys at 3 and still pays the triple reward when
    played) — the shop entities' tag=479 values are stale legacy tier
    costs: the 2026-09-06 23:00 log charged RESOURCES_USED=3 for Buzzing
    Vermin and Decoy Conjurer whose tags said 1. The DB's `tier` was never
    a price. Tavern spells keep their own per-spell price: the log's COST
    tag for spell entities, else the spell DB. Golden minion offers carry
    the "_G" id, priced identically to the base.

    Held-trinket price overrides (2026-09-20 ruling: the coach models the
    text-stated exceptions to flat-3): Electrode Attractor makes MAGNETIC
    minions cost 2. Bazaar Sticker's health-cost spell is NOT priced here
    — one spell per turn at a health price can't live in a flat map; the
    plan walk discounts the one spell it would buy (see _top_move_text).
    """
    spell_db = _load_spell_db()
    costs = {c: MINION_BUY_PRICE for c in _load_card_db()}
    costs.update({c + "_G": MINION_BUY_PRICE for c in list(costs)})
    costs.update({c: (v or {}).get("cost") for c, v in spell_db.items()})
    costs.update({c: v for c, v in (analysis.get("shop_costs") or {}).items()
                  if c in spell_db})
    held = (analysis.get("scenario") or {}).get("trinkets") or []
    if "Electrode Attractor" in held:
        for cid in _load_bg_magnetic_ids():
            if cid in costs:
                costs[cid] = 2
                costs[cid + "_G"] = 2
    return costs


def _health_cost_spell(analysis, cid, spell_db):
    """(why, 0-price?) for Bazaar Sticker's health-cost spell, or None.

    '1 Tavern spell/turn costs Health instead of Gold': the FIRST spell the
    plan would buy this turn costs no gold (its price is paid in health
    instead). Modeled in the walk only — a second spell buys at gold like
    normal. Not while DYING: advising a health spend at <=12 effective HP
    is how runs end (the same fragility that defers levels).
    """
    held = (analysis.get("scenario") or {}).get("trinkets") or []
    if "Bazaar Sticker" not in held or cid not in spell_db:
        return None
    health = analysis.get("health")
    if health is not None and health + (analysis.get("armor") or 0) \
            <= DYING_HEALTH:
        return None
    return ("costs Health instead of gold (Bazaar Sticker)", True)


def _shop_name(cid, names):
    """Display name for a shop card id — goldens resolve to the base card's
    name (the names DB has base ids) and carry a "(golden)" tag."""
    if cid.endswith("_G"):
        base = cid[:-2]
        return f"{names.get(base, base)} (golden)"
    return names.get(cid, cid)


def _fuel_line(analysis, card_db, spell_db, names, costs, spare):
    """'feed the engine' advice (Plan 2 Layer B) or None.

    Fires when a fuel engine (meta/fuel_specs.json) is ON BOARD, the
    tavern is past the early tempo window (tier >= 4), and gold is idle
    after the plan's real buys (spare >= 3 — every conversion costs at
    least the flat 3). Conversions are the shop's fuel-tribe bodies (1
    body per 3g) and body-generating spells (its live price), ranked
    bodies-per-gold. A spend recommendation inside the committed build —
    never a comp-target override; the caller never lets it displace a
    real buy or an active hunt.
    """
    tier = analysis.get("tier")
    if not tier or tier < 4 or spare is None or spare < MINION_BUY_PRICE:
        return None
    specs = meta.fuel_specs()
    live = [specs[m["card"]] for m in analysis.get("board", [])
            if m.get("card") in specs]
    if not live:
        return None
    spec = live[0]
    tribe = spec.get("fuel_tribe")
    best = None  # (bodies_per_gold, text)
    for cid, _score in analysis.get("shop_rank") or []:
        price = costs.get(cid, MINION_BUY_PRICE)
        if price > spare:
            continue
        if cid in spell_db:
            # A body-generating spell: "summon"/"get a random"/Chef's
            # Choice's "get a different minion" — mechanical text markers,
            # one body per cast.
            text = (spell_db[cid].get("text") or "").lower()
            if any(k in text for k in ("summon", "get a random",
                                       "get a different minion")):
                cand = (1.0 / max(price, 1),
                        f"cast {_shop_name(cid, names)} ({price}g)")
                if best is None or cand[0] > best[0]:
                    best = cand
            continue
        base = cid[:-2] if cid.endswith("_G") else cid
        card = card_db.get(base)
        if card and overlaps(normalize(card.get("race")
                                       or card.get("tribe")), tribe):
            cand = (1.0 / max(price, 1),
                    f"buy {_shop_name(base, names)} ({price}g)")
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    return (f"feed the engine — {best[1]}, {spec.get('why')} "
            f"(quantity beats quality)")


def _fuel_roll_mode(analysis):
    """Plan 3's roll-for-fuel dial: does a live engine make rerolling beat
    LEVEL this phase? Returns the live fuel spec or None.

    Conservative gates (the design guardrail: recognized engines or
    near-complete comps only): a fuel engine (meta/fuel_specs.json) ON
    BOARD, tier >= 4 (the P2-B tempo floor), not dying, no loss streak and
    no heavy recent hit (stabilize first), and — when a comp direction
    exists — no more than 2 missing cores (near-complete). The engine
    itself is a direction when the target is None: a banned-tribe build
    rides its engine too (the 09-15 game-4 Elemental engine with no
    targetable comp).
    """
    tier = analysis.get("tier")
    if not tier or tier < 4:
        return None
    health = analysis.get("health")
    if health is not None and health + (analysis.get("armor") or 0) \
            <= DYING_HEALTH:
        return None
    if analysis.get("loss_streak"):
        return None
    if (analysis.get("damage_last") or 0) >= 10:
        return None
    specs = meta.fuel_specs()
    live = [specs[m["card"]] for m in analysis.get("board", [])
            if m.get("card") in specs]
    if not live:
        return None
    if analysis.get("target_state") == "committing":
        tc = analysis.get("target_cards") or {}
        missing = [r for r in (tc.get("core") or [])
                   if not r.get("owned") and not r.get("banned")]
        if len(missing) > 2:
            return None
    return live[0]


def _hunt_feasible(analysis, tier):
    """Feasibility-evaluated missing cores of the target comp (Plan 3):
    (feasible_rows, evaluated) — the one evaluation both the hunt block and
    the roll-filler (pieces mode / anti-roll) consume. Empty when there is
    no committing target."""
    if analysis.get("target_state") != "committing" or not tier:
        return [], []
    tc = analysis.get("target_cards") or {}
    missing = [r for r in (tc.get("core") or [])
               if not r.get("owned") and not r.get("banned")]
    if not missing:
        return [], []
    evaluated = [
        (r, *_hunt_check(r, tier, analysis.get("turn"),
                         analysis.get("shop_seen"),
                         "shop_seen" in analysis,
                         analysis.get("own_pool"),
                         reach=analysis.get("reach_sources")))
        for r in missing]
    feasible = [r for r, ok, _w in evaluated if ok]
    return feasible, evaluated


def _level_price_clause(analysis):
    """The price of taking the level this turn, or None when normal.

    2026-09-20 design (analysis/level_pricing.md, Mike-approved: clause
    only when pricey, inform-only, verdict + evidence). Silence means the
    curve level is normal — recurring no-information clauses train the
    player to skip the line. Pricey = behind the lobby's boards (>=25%),
    a committing comp 2+ missing cores, or real recent damage (>=5):
    the fight AFTER a level is the one you skip, and those are the
    stalls the corpus loop priced at -9..-15 (outcome_audit, 09-20).
    Deliberately NO damage forecast — the forecast still prices raw
    stat totals, so a "~N next fight" number would be false precision.
    """
    ours = analysis.get("board_stats")
    anchor = analysis.get("lobby_opp") or analysis.get("baseline_opp")
    bits = []
    if ours is not None and anchor and ours < 0.75 * anchor:
        bits.append(f"boards ~{ours:.0f} vs lobby ~{anchor:.0f}")
    tc = analysis.get("target_cards")
    if tc and analysis.get("target_state") == "committing":
        n = sum(1 for r in (tc.get("core") or [])
                if not r.get("owned") and not r.get("banned"))
        if n >= 2:
            bits.append(f"the comp is {n} pieces short")
    dmg = analysis.get("damage_last")
    if (dmg or 0) >= 5:
        bits.append(f"took {dmg} last fight and lobbies scale up")
    if not bits:
        return None
    return ("prices high — " + "; ".join(bits)
            + " — and the fight after a level is the one you skip")


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

    # Turn-structure hero powers lead: a power that skips opening turns means
    # those turns don't exist — the power IS the turn. The old planner read
    # "LEVEL (access to tier 2) / Buy Flighty Scout" for a turn that doesn't
    # exist (2026-09-11 Faelin game t1; gold is also unparseable there — a
    # skipped turn writes no RESOURCES tag at all).
    #
    # The COUNT is parsed from the power text, never hardcoded. The guard used
    # to be `turn == 1 and "skip your first turn" in hp.lower()`, which A. F.
    # Kay's wording ("Skip your first TWO turns, then Discover...") does not
    # contain — so both of her skipped turns rendered a full plan:
    # "1. LEVEL (access to tier 2) · 2. Buy Buzzing Vermin" on t1 and
    # "1. LEVEL (access to tier 2)" again on t3 (2026-09-21 live decision log,
    # decision_Power.log.jsonl). It also means the "Q1 pass held" note in
    # analysis/replay_review_2026-09-18.md was wrong: that session shows the
    # same unexecutable t1 LEVEL line.
    hp = analysis.get("hero_power") or ""
    turn = analysis.get("turn") or 0
    skip = _skipped_turn_count(hp)
    if turn and turn <= skip:
        return (f"pass — {analysis.get('hero') or 'this hero'} skips "
                f"turn {turn} (hero power)")

    # 0. The hand (free actions, in ranked order): cast spells, play stuck
    #    minions. Copies group ("x2"); beyond three the rest summarize so the
    #    level/buy steps stay visible. Rendered AFTER the buy step settles —
    #    one-shot tavern buffs demote on the plan's actual buy (below).
    hand_entries = analysis.get("hand_plan") or []
    hand_parts = []

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
    fuel_priority = None  # (tier, level_cost): the roll-lead's trailing step
    budget = gold
    level_next = None      # a LEVEL step that trails the buy instead of leading
    level_flip_why = None  # the stated reason the level deferred to the buy
    stay_note = None       # staying ON this tier is itself a decision (Q1)
    if tier and tier < 6:
        # Real upgrade price: the live TechUp button COST (tier+3 base,
        # dropping 1 per turn you wait) — tier+1 was the old wrong model.
        # An analysis without a price gets NO level step: an unpriced
        # upgrade is not advice, never a guessed number.
        level_cost = analysis.get("level_cost")
        if gold is None:
            level_lead = f"LEVEL (access to tier {tier + 1})"
        elif level_cost is not None and gold >= level_cost:
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
            next_core, here_core, next_any, here_any, above_core, above_any \
                = _comp_needs_by_tier(analysis, card_db,
                                      reach=analysis.get("reach_sources"))
            # Scout (gates 3+4): "their" = the LOBBY PACE (Plan 3) — the
            # stronger of the announced next opponent's fresh preview and
            # the recent lobby median — never the next seat alone. The
            # 2026-09-15 game-1 t9/t12 "you're strong" fired against a
            # stale preview while the lobby had doubled (~51); a tier is
            # only a conversion when the lobby can't punish it. The corpus
            # baseline stays the last fallback, and the "~" estimate mark
            # follows the anchor (a lobby median is an estimate too).
            board_stats = analysis.get("board_stats")
            preview = analysis.get("opp_stats")
            lobby = analysis.get("lobby_opp")
            their = max((v for v in (preview, lobby) if v is not None),
                        default=None)
            if their is None:
                their = analysis.get("baseline_opp")
            approx = their is None or their != preview
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
            elif analysis.get("never_won") and (analysis.get("turn") or 0) >= 3:
                # The 2026-09-19 Reno game: bled in every fight from t2 and
                # the plan LEVELed through it (streak of 1 didn't trip the
                # stabilize rules). Zero wins is the louder, simpler read:
                # until a fight stops costing HP, the board comes first —
                # at any tier (5k-MMR conservative stance).
                flip_why = "0 wins so far — every fight has cost you HP; " \
                           "buy stats first"
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
            elif tier >= 4 and board_stats is not None and their \
                    and board_stats < 0.7 * their:
                # Plan 3 lobby-pace flip: a board behind the LOBBY (not just
                # the next seat) buys stats before tiers from tier 4 up —
                # no loss streak required (the 09-15 game-1 t9 won fights
                # against a weak next seat and leveled into the Buzz-saw).
                # Tier 3 and below stay curve-driven: early leveling is
                # nearly always right (the 09-15 game-2 under-level guard).
                flip_why = "your board is behind the lobby pace — buy stats first"
            if flip_why and opp_note(board_stats, their, approx):
                flip_why += f"; {opp_note(board_stats, their, approx)}"
            if flip_why:
                # A flip defers the LEVEL outright, not just when the buy
                # locks the level out — "buy stats first" is the advice even
                # when both would fit, and the buy section renders the level
                # right after the buy when the purse covers both.
                budget = gold  # the buy comes first, from the full purse
                level_next = True
                level_flip_why = flip_why
            elif core_pick and locked_out:
                budget = gold  # the buy comes first, from the full purse
                level_next = True
                level_flip_why = "the shop's top card is a comp core"
            elif (here_core > 0 and next_core == 0 and above_core == 0) or \
                    (here_core == 0 and next_core == 0 and above_any == 0
                     and here_any > 0):
                # Q1: what the comp is MISSING lives on THIS tier — and
                # nothing of it is out of reach above, so leveling would
                # lower the odds of finding it WITHOUT unlocking anything.
                # Below-tier pieces don't count (2026-09-20 ruling: they
                # stay findable after leveling, so they never hold the
                # ladder back). Cores dominate; addons only carry the
                # stay when they're all the shopping left. The old gate
                # required tier+1 to hold NOTHING: any single addon there
                # pulled LEVEL while missing cores sat here (2026-09-08) —
                # but it also counted tier+1 cores against here-cores on a
                # flat tie and ignored pieces beyond tier+1 entirely
                # (2026-09-10: a 2-vs-2 tie said 'stay on tier 5 — your
                # comp's missing cores are on this tier or below' while the
                # comp's payoff core sat at tier 6). Leveling is the ONLY
                # path to anything above the current tier; here-pieces stay
                # findable after leveling, so any missing piece above vetoes
                # the stay.
                budget = gold
                stay_note = True
            else:
                fuel = _fuel_roll_mode(analysis)
                if fuel is not None and next_core > here_core:
                    fuel = None  # leveling UNLOCKS pieces — it stays first
                if fuel is not None:
                    # Plan 3 roll-for-fuel: a live engine on board beats
                    # converting strength into a tier NOW — rolling produces
                    # the bodies the build consumes (and pool-weighted
                    # missing pieces). The dual output: the roll line leads,
                    # the level trails as an explicit next-priority with its
                    # exit condition (rendered after the buy section).
                    level_lead = (f"consider rerolling for "
                                  f"{(fuel.get('fuel_tribe') or 'fuel').lower()} "
                                  f"bodies — {fuel.get('why')}")
                    budget = gold  # rolls/buys spend the full purse
                    fuel_priority = (tier, analysis.get("level_cost"))
                else:
                    if next_core > here_core:
                        why = "the comp's next pieces live there"
                    elif strong:
                        why = "you're strong — convert it into a tier"
                    else:
                        why = "standard curve"
                    level_lead = (f"LEVEL to tier {tier + 1} ({why})"
                                  + (f" — {spare} left" if spare else ""))
                    price = _level_price_clause(analysis)
                    if price:
                        level_lead += f" — {price}"
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
    # An UNRANKED pick (no data — score None) is never blessed: recommending
    # the first listed option read as advice (2026-09-08: "PICK Upstart
    # Embers" for a Trip Vouchers discover, Entities[0] with no reason).
    # The Choose-1 box still lists the options.
    choice = analysis.get("choice")
    if choice and choice.get("ranked") and choice["ranked"][0][2] is not None:
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
    hunted = False  # a hunt step claimed the spare gold (the fuel line yields)
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
        # A one-shot tavern buff bought from the SHOP is only worth its gold
        # when a minion buy can FOLLOW it this turn — the buff dies with the
        # shop (2026-09-08 player report: cast, level, no purchases). No room
        # for a minion after it: buy the best affordable minion instead, else
        # roll and say why.
        if _is_shop_turn_buff(spell_db.get(cid)) and budget is not None:
            buff_cost = costs.get(cid)
            if buff_cost is not None and budget - buff_cost < MINION_BUY_PRICE:
                alt_minion = next((alt for alt, _v in shop_rank
                                   if alt not in spell_db
                                   and costs.get(alt) is not None
                                   and budget >= costs.get(alt)), None)
                if alt_minion is None and budget:
                    wasted = (f"roll — casting {_shop_name(cid, names)} with no "
                              f"gold left for a shop minion wastes it "
                              f"(the buff dies with the shop)")
                    parts.append(wasted)
                    analysis["buy_step_roll"] = wasted
                    cid = None
                else:
                    cid = alt_minion
        cost = costs.get(cid)
        # Bazaar Sticker (2026-09-20 ruling: model the text-stated price
        # exceptions): the ONE spell this plan would buy costs Health
        # instead of gold — discount it here so the budget checks treat it
        # as free, and say so in the buy line (the overlay's per-card price
        # stays the gold figure; a flat map can't carry a once-per-turn
        # discount honestly).
        health_why = _health_cost_spell(analysis, cid, spell_db) \
            if cid is not None else None
        if health_why:
            cost = 0
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
                    # last gold beats passing. Plan 3 gives the filler a
                    # target when one exists (pieces: the hunt; fuel: the
                    # engine) and says the anti-roll state OUT LOUD when
                    # neither exists — the player's stated leak is gold
                    # rolled away with no target, and the plan should name
                    # that state every time it blesses a target-less roll.
                    when = " after the level" if level_next else ""
                    feasible, _ev = _hunt_feasible(analysis, tier)
                    fuel = _fuel_roll_mode(analysis)
                    if feasible:
                        specific = [r for r in feasible
                                    if r["card"] not in _shared_utility_cores(
                                        analysis.get("playable_comps") or {})]
                        nm = ", ".join(r["name"]
                                       for r in (specific or feasible)[:2])
                        roll = (f"roll — hunting {nm} (best shop card "
                                f"{_shop_name(cid, names)}, {cost}g, doesn't "
                                f"fit your {budget} gold left{when})")
                    elif fuel is not None:
                        roll = (f"roll — feed the engine: "
                                f"{(fuel.get('fuel_tribe') or 'fuel').lower()} "
                                f"bodies ({fuel.get('why')})")
                    else:
                        tc = analysis.get("target_cards") or {}
                        n_missing = sum(1 for r in (tc.get("core") or [])
                                        if not r.get("owned")
                                        and not r.get("banned")) \
                            if analysis.get("target_state") == "committing" \
                            else None
                        if n_missing:
                            target = (f"comp is {n_missing} "
                                      f"{'piece' if n_missing == 1 else 'pieces'} "
                                      f"short on tier {tier}")
                        elif n_missing == 0:
                            target = "comp complete, no engine live"
                        else:
                            target = "no comp direction yet"
                        roll = (f"no reroll target — {target} · roll the "
                                f"leftover anyway, gold doesn't carry")
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
            no_hunt_note = None
            if missing and off_build \
                    and analysis.get("target_state") == "committing" \
                    and (budget or 0) >= 1 \
                    and eff_health > DYING_HEALTH \
                    and (analysis.get("turn") or 99) > 2:
                # Feasibility first (2026-09-11): hunt only cores the tavern
                # can actually produce at this tier, with recent evidence
                # they're showing. Among the huntable, name comp-SPECIFIC
                # cores first: a shared-utility card (Balinda-class) is still
                # on the shopping list, but it's a generic-good card, not
                # this build's win condition — the hunt names what the BUILD
                # is missing (2026-09-08: the hunt's second target read
                # 'Balinda Stonehearth').
                feasible, evaluated = _hunt_feasible(analysis, tier)
                if feasible:
                    specific = [r for r in feasible
                                if r["card"] not in _shared_utility_cores(
                                    analysis.get("playable_comps") or {})]
                    nm = ", ".join(r["name"] for r in (specific or feasible)[:2])
                    parts.append(f"roll — hunting {nm} "
                                 f"({_shop_name(cid, names)} is off-build)")
                    analysis["buy_step_roll"] = parts[-1]
                    analysis["buy_step_card"] = None
                    cid = None
                    hunted = True
                else:
                    # Every missing core is above the tavern or gone cold:
                    # the buy stands. Say why the hunt stopped, AFTER the buy
                    # step — the 2026-09-11 Morchie game said "roll — hunting
                    # Gem Rat" 11 turns running while the tier-3 core showed
                    # up twice all game; the plan needs to explain its change
                    # of mind, not just silently buy. A tier/pool-blocked
                    # piece gets the weak-mention footnote when a live
                    # random generator of its tribe exists (Plan 2: RNG is
                    # weak for a named hunt — mentioned, never gated on).
                    nm = ", ".join(r["name"] for r, _ok, _w in evaluated[:2])
                    why = evaluated[0][2] or "not showing"
                    weak = ""
                    if why.startswith(("needs tier", "pool dry")):
                        weak = _weak_reach_note(analysis.get("reach_sources"),
                                                missing)
                    no_hunt_note = f"no hunt — {nm} ({why}{weak})"
        if cid is not None:
            bought = cid
            analysis["buy_step_card"] = cid
            recipes = analysis.get("engine_recipes") or []
            why = _buy_intention(cid, comp, card_db, spell_db,
                                 board=analysis.get("board"),
                                 pool_held=analysis.get("own_pool"),
                                 recipes=recipes)
            if health_why:
                why = f"{why}; {health_why[0]}"
            parts.append(f"Buy {_shop_name(cid, names)} ({why})")
            # Name the engine once, right after the fuel buy (the 2026-09-15
            # Shudderwock game's miss: the coach ranked Tavern Tempest but
            # never said the hero power x trinket loop was the build).
            for rec in recipes:
                if recipe_fuel_hit(card_db.get(cid), rec):
                    parts.append((rec.get("line") or "").format(
                        card=_shop_name(cid, names)))
                    break
            if level_next and tier and analysis.get("level_cost") is not None:
                level_cost = analysis.get("level_cost")
                leftover = (gold or 0) - (costs.get(cid) or 0)
                _h_now = analysis.get("health")
                _eff_now = (_h_now + (analysis.get("armor") or 0)
                            if _h_now is not None else None)
                if leftover >= level_cost and _eff_now is not None \
                        and _eff_now <= DYING_HEALTH:
                    # Hard DYING gate (2026-09-16 evening t16, 8 HP): the
                    # level is AFFORDABLE and the flip ladder still refuses
                    # it — but the deferred emission then rendered the
                    # actionable "LEVEL to tier 6 — 1 left after" because
                    # the purse covered both. At <=12 effective HP a
                    # spendable tier is never advice; the gold buys stats.
                    # Rendered as the deferred form, never the actionable
                    # one, whatever the comp wants.
                    why = level_flip_why or "too fragile to level first"
                    parts.append(f"LEVEL next turn ({why}) — roll meanwhile")
                elif leftover >= level_cost:
                    trail = (f"LEVEL to tier {tier + 1} — "
                             f"{leftover - level_cost} left after")
                    price = _level_price_clause(analysis)
                    if price:
                        trail += f"; {price}"
                    parts.append(trail)
                else:
                    short = f"{level_cost - leftover} short after the buy"
                    parts.append((f"LEVEL next turn ({level_flip_why}) — "
                                  f"{short}; roll meanwhile")
                                 if level_flip_why else
                                 f"LEVEL next turn — {short}; roll meanwhile")
            if no_hunt_note:
                parts.append(no_hunt_note)
        # Feed the engine (Plan 2 Layer B): a live fuel engine on board +
        # idle gold past the early tempo window -> explicit conversion
        # advice. An active hunt owns the spare gold — the line yields to
        # it (never two competing "spend it here" steps).
        if not hunted:
            spare_gold = (budget or 0) - (costs.get(bought) or 0) \
                if bought is not None else None
            fuel = _fuel_line(analysis, card_db, spell_db, names, costs,
                              spare_gold)
            if fuel:
                parts.append(fuel)
        if fuel_priority is not None:
            p_tier, p_cost = fuel_priority
            parts.append(f"next priority: LEVEL to tier {p_tier + 1} "
                         f"({p_cost}g) — after the next triple or when the "
                         f"shop stops producing")
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
    # 0. The hand, rendered now that the plan's buy is known: a one-shot
    #    tavern buff ("Them Apples") lives and dies with THIS shop, so its
    #    cast is only advice when the plan BUYS a shop minion this turn
    #    (2026-09-08 player report: cast, LEVEL, no purchases — the spell
    #    was wasted). No minion buy: the cast demotes to a hold, stated so
    #    the player knows to cast it the turn they actually shop. With one:
    #    the cast stays, warning that the buffed minions must be bought
    #    before any refresh. (Leveling doesn't refresh the shop, so
    #    Cast → LEVEL → Buy is a fine order; a roll or pass wipes the buff.)
    #    The demotion mutates the shared hand-plan entries in place, so the
    #    overlay's hand box agrees with the plan; demoted holds move last.
    demoted = []
    for s in hand_entries:
        if s.get("verb") != "cast":
            continue
        if not _is_shop_turn_buff(spell_db.get(s.get("card"))):
            continue
        if bought is not None and bought not in spell_db:
            s["why"] = ("buff dies with this shop — buy the buffed "
                        "minions this turn")
        else:
            # No minion buy in the plan — the cast only survives if one can
            # still FOLLOW it this turn (spare gold after the level and the
            # named buy, and an affordable minion in the shop). Otherwise the
            # buff dies with the shop: hold it.
            spare = None
            if budget is not None:
                spare = budget - ((costs.get(bought) or 0) if bought else 0)
            if spare is not None and spare >= MINION_BUY_PRICE \
                    and any(alt not in spell_db
                            and costs.get(alt) is not None
                            and spare >= costs.get(alt)
                            for alt, _v in shop_rank):
                s["why"] = ("buff dies with this shop — buy the buffed "
                            "minions this turn")
            else:
                s["verb"] = "hold"
                s["why"] = ("cast it the turn you buy shop minions — "
                            "the buff dies with this shop")
                demoted.append(s)
    if demoted:
        demoted_ids = {id(s) for s in demoted}
        hand_entries[:] = [s for s in hand_entries
                           if id(s) not in demoted_ids] + demoted
    # Hand casts are FREE (player rule + log ground truth, 2026-09-19: a
    # BlockType=PLAY block sourced from a HAND-zone spell moves no
    # RESOURCES_USED; the spell's price is charged at the tavern BUY). The
    # 2026-09-16 evening gate that demoted casts the purse couldn't cover
    # was a misdiagnosis of "Cast Tavern Coin led a gold-0 plan": the real
    # fix is ranking, and gold-gain spells already score ~2 effect points
    # in _spell_effect, so a low-value cast can't lead a real plan. No gold
    # gating here — the shop-buff demotion above stays (that one is an
    # effect-level rule: the buff dies with the shop, not a price).
    # t16's Cast Repair Job x3 with a funded purse remains correct advice;
    # so is casting at gold 0 when the spell is in hand.
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
# The stay decision (Q1) trails the buys: what the comp is missing
# lives here (this tier or below), and the player should know the
# level was declined on purpose.
    if stay_note and tier:
        parts.append(f"stay on tier {tier} — your comp's missing cores are "
                     f"on this tier or below; leveling would lower the odds")
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


def _triple_note(cid, board, pool_held=None):
    """The buy's triple state, or '' when there's nothing to say.

    A golden on board is NOT one of the three copies — goldens never
    combine (player rule; the 2026-09-10 Buttons game advised 'buy it
    for the triple' with a Dark-Gift golden + 1 regular on board, and
    the buy made nothing). The note rides on the buy step so neither
    the plan nor the LLM reading it can miscount a golden.
    With pool_held (pool.own_holdings), the "still needed" branch also
    says when the shared pool can't produce the remaining copies.
    """
    if not board:
        return ""
    regulars = sum(1 for b in board
                   if b.get("card") == cid and not b.get("golden"))
    if regulars >= 2:
        return "this buy completes a golden triple"
    if any(b.get("card") == cid and b.get("golden") for b in board):
        need = 3 - regulars
        txt = (f"the golden on board doesn't combine — "
               f"{need} more regular {'' if need == 1 else 'copies'}"
               f" still needed for a triple")
        if pool_held is not None:
            avail = pool.left(cid, pool_held)
            if avail is not None and avail < need:
                txt += (f" — pool can't produce them "
                        f"({avail or 'none'} left beyond your holdings)")
        return txt
    return ""


def _buy_intention(cid, comp, card_db, spell_db=None, board=None,
                   pool_held=None, recipes=None):
    """Why the coach recommends buying this card (a pre-set intention)."""
    note = _triple_note(cid, board, pool_held)
    note = f"; {note}" if note else ""
    if comp and cid in comp.get("core", []):
        return f"committing to {comp.get('tribe') or comp.get('name')}{note}"
    # Active engine recipes name themselves BEFORE the generic reads (the
    # 2026-09-15 Shudderwock game: "Buy Tavern Tempest (growth engine)"
    # never said WHY it was an engine — the hero power + trinket loop was
    # the whole point). Only comp core outranks it.
    for rec in recipes or []:
        if recipe_fuel_hit(card_db.get(cid), rec):
            return f"{rec.get('why') or 'hero-power engine fuel'}{note}"
    if comp and cid in comp.get("addons", []):
        return f"part of growth cycle{note}"
    card = card_db.get(cid)
    if card and _is_self_improving_combat(card):
        return f"scaling combat engine{note}"
    if card and _is_engine(card):
        return f"growth engine{note}"
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
    return f"surviving until we can commit{note}"


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

    Honesty marks (2026-09-16 evening §3.1: 'favored — 895 vs 165' one
    minute before a 19-damage fight): an estimate anchor (lobby median /
    baseline, not the fresh preview) renders with the '~' mark; a stale
    anchor carries its age ('seen 2 rounds ago'); and at <=10 effective
    HP the 'favored' label is capped to 'ahead on paper' — one bad fight
    ends the game however far ahead the board reads.
    """
    bs = analysis.get("board_stats")
    theirs = analysis.get("opp_stats") or analysis.get("lobby_opp") \
        or analysis.get("baseline_opp")
    if bs is None or not theirs:
        return None
    fresh = analysis.get("opp_stats")
    approx = theirs != fresh
    age = analysis.get("opp_age")
    theirs_disp = f"{'~' if approx else ''}{int(theirs)}"
    if age:
        theirs_disp += (f", seen {age} round"
                        f"{'s' if age != 1 else ''} ago")
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
    _h = analysis.get("health")
    eff = _h + (analysis.get("armor") or 0) if _h is not None else None
    fragile = eff is not None and eff <= FAVOR_HP_CEILING
    # Next-opponent pressure (2026-09-19, 5k stance): a silent hero is a
    # scaling one — rounds since their last bleed reads as their win run.
    quiet = analysis.get("opp_quiet")
    run = f" · they haven't taken damage in {quiet} rounds" \
        if quiet and quiet >= 2 else ""
    if ratio >= 1.3:
        label = ("ahead on paper" if fragile else "favored")
        return f"{label} — {bs} vs {theirs_disp}{edge}{run}"
    if ratio >= 0.8:
        return f"close fight — {bs} vs {theirs_disp}{edge}{run}"
    return f"behind — {bs} vs {theirs_disp}; don't take this fight{edge}{run}"


def _comp_needs_by_tier(analysis, card_db, reach=None):
    """Unowned pieces of the target comp, split by tavern tier relative to
    the current one: (next_core, here_core, next_any, here_any, above_core,
    above_any) (Q1, analysis/LEVELING_MODEL.md — leveling lowers the odds of
    finding the CURRENT tier's cards, so where the missing pieces live
    decides).

    CORES drive the decision; addons only matter when they're ALL the
    shopping that's left (a lone addon at tier+1 used to pull LEVEL past
    missing cores on the current tier — the 2026-09-08 report: 'keeps
    saying to upgrade even if there are minions at this tier we still
    need'). 'Here' = THIS tier only: below-tier pieces are neutral
    (findable before and after leveling — they justify neither a stay
    nor a level; 2026-09-20 ruling on the 09-11 review's objection). The
    old 'this tier or below' let a tier-3 core hold the ladder back at
    tier 4.

    'Above' = beyond tier+1 (tier-6 Fauna Whisperer while at tier 4). It
    used to be counted NOWHERE, and a missing core AT tier+1 tied evenly
    against here-cores (2026-09-10: a 2-vs-2 tie said 'stay on tier 5'
    while the comp's payoff core sat at tier 6) — but leveling is the ONLY
    path to any piece above the current tier, while here-pieces stay
    findable after leveling. Missing pieces above therefore veto the stay;
    they never drive a level by themselves (they're not findable at
    tier+1 yet either — the curve handles that). Plan 2 Layer A exception
    (`reach` = live reachability sources): a piece above that a live
    DISCOVER/token source reaches from HERE no longer vetoes — leveling is
    then not the only path (the 2026-09-15 Shudderwock game held tier 5
    for a tier-6 payoff). Random generators do NOT lift the veto — a
    pool-weighted maybe is not a path."""
    tc = analysis.get("target_cards")
    tier = analysis.get("tier")
    if not tc or tier is None:
        return 0, 0, 0, 0, 0, 0
    next_core = here_core = next_any = here_any = 0
    above_core = above_any = 0
    for section in ("core", "addons"):
        for row in tc.get(section) or []:
            if row.get("owned") or row.get("banned"):
                continue  # owned, or banned this game (never findable)
            t = (card_db.get(row.get("card")) or {}).get("tier")
            if t is None:
                continue
            if t == tier + 1:
                if section == "core":
                    next_core += 1
                next_any += 1
            elif t == tier:
                if section == "core":
                    here_core += 1
                here_any += 1
            elif t < tier:
                pass  # below-tier: findable here AND after leveling — it
                # justifies neither a stay nor a level (2026-09-20 ruling:
                # the old "here = this tier or below" let a sub-tier core
                # hold the ladder back; Mike confirmed the 09-11 review's
                # objection)
            else:  # beyond tier+1: unfindable here, unfindable at tier+1 —
                # unless a live discover/token source reaches it from here.
                if any(_src_reaches(s, row.get("card"), t, tier)
                       for s in reach or []):
                    continue
                if section == "core":
                    above_core += 1
                above_any += 1
    return (next_core, here_core, next_any, here_any,
            above_core, above_any)


def _core_hits(board, rc, cores):
    """Core-card hits for one comp: board minions plus recent acquisitions
    (copies count — a commit is often 2x/3x one core).

    A copy that is BOTH on board and in the recent stream (bought, then
    played) is ONE physical card and counts once: board_count +
    max(0, recent_count - board_count). Counting it twice committed a
    comp off a single core (2026-09-18 live: one Tasty Lobster, bought
    and played, read as 2 hits — the whole commit threshold)."""
    board_counts = collections.Counter(
        c["card"] for c in board if c["card"] in cores)
    rc_counts = collections.Counter(c for c in rc if c in cores)
    total = 0
    for cid in set(board_counts) | set(rc_counts):
        b = board_counts.get(cid, 0)
        r = rc_counts.get(cid, 0)
        total += b + max(0, r - b)
    return total


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


@functools.lru_cache(maxsize=1)
def _minion_tiers():
    """card id -> tavern tier (comp cores are minions; meta/minions.json)."""
    return {m.get("id"): m.get("tier") for m in meta.minions()}


def live_reach_sources(board=None, hand=None, trinkets=None, hero_name=None):
    """Live reachability sources (Plan 2 Layer A, analysis/engine_coaching.md).

    A source in meta/discover_sources.json is LIVE when its card is on the
    board or in hand, held as a trinket (DB records — ids already resolved
    from drifted log ids by live_coach), or when the hero entry matches the
    current hero. Only mechanical-confidence entries come back; observed
    rows sit inert (the recipes rule).
    """
    table = meta.discover_sources()
    out = []
    seen = set()

    def _add(key, label):
        if key in seen:
            return  # the same card on board and in hand is one source
        rec = table.get(key)
        if rec and rec.get("confidence") == "mechanical":
            seen.add(key)
            out.append(dict(rec, source=key, name=rec.get("name") or label))

    for m in list(board or []) + list(hand or []):
        if isinstance(m, dict) and m.get("card"):
            _add(m["card"], m.get("card"))
    for t in trinkets or []:
        _add(t.get("id") if isinstance(t, dict) else t, "trinket")
    if hero_name:
        _add(f"hero:{hero_name}", hero_name)
    return out


def _src_reaches(src, card_id, ctier, tavern_tier):
    """Can THIS discover/token source produce the named piece?

    Returns None for random_generate (a weak mention lives elsewhere —
    never a gate) and bool otherwise. tier_cap 'tier+1'/'current' resolve
    against the live tavern tier.
    """
    kind = src.get("kind")
    if kind == "token":
        return src.get("grants") == card_id
    if kind != "discover":
        return None
    cap = src.get("tier_cap")
    if cap == "tier+1":
        cap = (tavern_tier or 0) + 1
    elif cap == "current":
        cap = tavern_tier
    if isinstance(cap, int):
        return ctier is not None and ctier <= cap
    return None


def _src_weak_hit(src, card_id, ctier):
    """Could THIS random_generate source drop the piece (a mention, never
    a gate)? True for unfiltered generators; tribe-filtered generators
    need the piece's tribe to match."""
    if src.get("kind") != "random_generate":
        return False
    cap = src.get("tier_cap")
    if cap is not None and ctier is not None and ctier > cap:
        return False
    tribes = src.get("tribes") or []
    if not tribes:
        return True
    card = _load_card_db().get(card_id) or {}
    race = normalize(card.get("race") or card.get("tribe") or "")
    return any(overlaps(race, tr) for tr in tribes)


def _weak_reach_note(reach, missing_rows):
    """Random-generator footnote for a blocked hunt: '...; Tavern Tempest
    can still drop it'. Mention only — the hunt stays blocked (RNG identity
    is weak for a named card), but the plan shouldn't pretend the piece is
    unreachable while a live generator of its tribe exists."""
    gens = []
    for r in missing_rows:
        ctier = _minion_tiers().get(r["card"])
        for src in reach or []:
            nm = src.get("name")
            if nm and nm not in gens \
                    and _src_weak_hit(src, r["card"], ctier):
                gens.append(nm)
    return f"; {', '.join(gens[:2])} can still drop it" if gens else ""


# Buy phases a hunt stays alive after the missing core's last shop sighting.
HUNT_SEEN_WINDOW = 4


def _hunt_check(row, tavern_tier, turn, shop_seen, tracked, pool_held=None,
                reach=None):
    """(ready, reason) — can the tavern actually produce this missing core?

    Four gates (the 2026-09-11 Morchie game: the coach hunted the tier-3 Gem
    Rat from a tier-5 tavern for 11 straight buy phases while its shop
    offered that card exactly twice all game — the player bought on-tier
    pieces, tripled four goldens and won):
    - TIER: a core above the tavern can't appear at all — UNLESS a live
      discover/token source reaches it from here (Plan 2 Layer A: discover
      menus are tier-limited and trustworthy; a token generator is
      deterministic). "needs tier N" then becomes a reachability why.
    - POOL: when we already hold every copy the pool has (own-side ledger,
      pool.own_holdings — phase 1), no roll can ever produce it. Discover/
      token sources bypass this — they don't roll the shared pool.
    - RECENCY: when the session tracks shop sightings (live_coach records
      every shop generation it sees), a core unseen for HUNT_SEEN_WINDOW buy
      phases is a lottery ticket, not a plan. Never-offered cores are the
      strongest possible "don't hunt". Applies to reachability too —
      Layer A must not resurrect hunt-every-turn (the Morchie rule).
    Analyses without a shop_seen key (unit fixtures, the coach.py path) keep
    the old evidence-free hunt — the tier and pool gates still apply.
    """
    ctier = _minion_tiers().get(row["card"])
    if tavern_tier and ctier and ctier > tavern_tier:
        for src in reach or []:
            if _src_reaches(src, row["card"], ctier, tavern_tier):
                return True, (f"reachable via your "
                              f"{src.get('name') or 'discover sources'}")
        return False, f"needs tier {ctier}"
    if pool_held is not None and pool.left(row["card"], pool_held) == 0:
        for src in reach or []:
            if _src_reaches(src, row["card"], ctier, tavern_tier):
                return True, (f"reachable via your "
                              f"{src.get('name') or 'discover sources'}")
        return False, "pool dry — you hold every copy"
    if not tracked:
        return True, None
    seen = (shop_seen or {}).get(row["card"])
    if seen is None:
        return False, "hasn't shown in the tavern"
    if turn is not None and turn - seen > HUNT_SEEN_WINDOW:
        return False, f"last shown {turn - seen} turns ago"
    return True, None


def _board_tribe_share(comp, board):
    """The fraction of the current board that shares the comp's tribe —
    the 'is this build the board' signal used to break evidence ties."""
    tribe = normalize(comp.get("tribe") or "")
    if not tribe or not board:
        return 0.0
    hits = sum(1 for m in board
               if normalize(m.get("tribe")) in tribe.split("/"))
    return hits / len(board)


def _trinket_nudge(comp, trinkets):
    """Held-trinket comp-direction nudge (analysis/engine_coaching.md Plan 1's
    reverse edge: trinket <-> comp is two-way). A trinket whose curated
    synergy rewards a comp's tribe nudges that comp by HALF a core hit —
    enough to tip a 1-hit tie, never to manufacture direction from nothing
    (the meter still needs real board/recent evidence). Modulates, never
    originates."""
    tribe = (comp or {}).get("tribe")
    if not tribe or not trinkets:
        return 0.0
    for t in trinkets:
        if not isinstance(t, dict):
            continue
        for tr in (t.get("synergy") or {}).get("tribes") or []:
            if overlaps(tr, tribe):
                return 0.5
    return 0.0


def comp_progress(board, comps, recent_cards=None, top=4, trinkets=None):
    """Commit readiness per candidate comp — the meter behind comp_target's
    rule (UI: the "Comp direction" box shows how close each candidate is to
    the 2-core-hit commit threshold BEFORE comp_target declares a target).

    Same evidence semantics as comp_target: board minions + recent
    acquisitions, copies count. Comps with >=1 direct core hit are listed
    (hits desc, then meta tier, capped at `top`); each row also carries
    `tribe_hits`, the tribe's total across its comps — the comp_target
    tribe rule (>=2 spread across comps of one tribe) is visible as tribe
    momentum on the row even when no single comp hits alone. A held
    trinket rewarding the comp's tribe adds a half-hit nudge to the ORDER
    (rows carry trinket_fit for display) — never to `ready`, which stays
    hits >= 2 of real evidence.
    Returns [{name, tribe, meta_tier, hits, ready, needs, tribe_hits,
    trinket_fit}] — needs is the unowned core (the shopping list that
    moves the meter).
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
                "trinket_fit": bool(_trinket_nudge(comp, trinkets)),
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
    # Trinket nudge orders ties (1-hit rows), never flips `ready`.
    rows.sort(key=lambda r: (-(r["hits"] + (0.5 if r.get("trinket_fit")
                                            else 0.0)),
                             tier_rank.get(r["meta_tier"], 3),
                             r["name"] or ""))
    return rows[:top]


def comp_target(board, comps, recent_cards=None, trinkets=None):
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
    comp-agnostic, headlining Naga cards, all game). `trinkets` (held
    trinket records) add the Plan-1 reverse edge: a trinket rewarding a
    comp's tribe is a HALF-HIT nudge on ties — it can tip equal-evidence
    comps, never create the >=2-hit evidence itself. Returns comp or
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
        key = (overlap + _trinket_nudge(comp, trinkets), dominant)
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
        tribe_total[tribe] = tribe_total.get(tribe, 0) + hits \
            + _trinket_nudge(comp, trinkets)
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
        # Canonical parts (compounds split); Amalgams count toward every
        # tribe — the game treats them as each tribe.
        for part in parts(m.get("tribe")):
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
