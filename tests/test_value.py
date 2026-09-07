"""Regression tests for the value function's tribe handling.

The historical bug: comps.json ("Elementals"), minions.json ("ELEMENTAL") and
bans.canon() ("Elemental") never intersected, so W_TRIBE never fired, the
banned-tribe penalty hit every minion, and _best_comp returned the first comp
in the file. These tests pin the corrected behavior.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value
import simulate_growth
from value import _best_comp, minion_value, sell_recommendation

EL = "BG33_886"   # Tusked Camper (Beast, t1) — present in the real BG pool
MECH = "BG29_503"  # a real mech in minions.json if present; tests skip if not


def _card(cid, atk=3, health=4):
    return value._load_card_db().get(cid) or {
        "name": cid, "race": "Beast", "attack": atk, "health": health,
        "mechanics": [], "text": "",
    }


class TestBestComp(unittest.TestCase):
    COMPS = {
        "mech-ladder": {"name": "Mech", "tribe": "Mech", "core": [], "addons": []},
        "beast-pack": {"name": "Beast", "tribe": "Beast", "core": [], "addons": []},
    }

    def test_matches_board_tribes_not_dict_order(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, self.COMPS), self.COMPS["beast-pack"])

    def test_no_fit_returns_none(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": None}]
        self.assertIsNone(_best_comp(board, self.COMPS))

    def test_legacy_plural_comps_still_match(self):
        comps = {"beast-pack": {"name": "Beast", "tribe": "Beasts",
                                "core": [], "addons": []}}
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, comps), comps["beast-pack"])


class TestWTribe(unittest.TestCase):
    def test_w_tribe_fires_for_matching_comp(self):
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        # Card NOT in the comp's core/addons: the only difference is W_TRIBE.
        same = minion_value(m, card, {"tribe": "Beast", "core": [], "addons": []})
        other = minion_value(m, card, {"tribe": "Mech", "core": [], "addons": []})
        self.assertEqual(same - base, value.W_TRIBE)
        self.assertEqual(other - base, 0.0)

    def test_traditionally_failing_legacy_comp_tribe(self):
        """A comp still carrying the legacy plural must still get the bonus
        (normalize handles it) — and the raw-log board minion matches it."""
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        legacy = minion_value(m, card, {"tribe": "Beasts", "core": [], "addons": []})
        self.assertEqual(legacy - base, value.W_TRIBE)


class TestBannedPenalty(unittest.TestCase):
    def test_penalty_only_for_actually_banned_tribes(self):
        """Same minion, two games: Beast allowed vs Beast banned. Delta is
        exactly the penalty."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        allowed = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        banned = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        self.assertEqual(banned[EL] - allowed[EL], -2.0)

    def test_no_penalty_without_ban_info(self):
        """allowed_tribes=None (= no ban data) must not penalize anyone — the
        old fail-closed behavior penalized every minion in every game."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        ranked = sell_recommendation(board, [], allowed_tribes=None)
        ranked_empty = sell_recommendation(board, [], allowed_tribes=[])
        self.assertEqual(ranked, ranked_empty)

    def test_compound_tribe_playable_if_either_half_allowed(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "DEMON/BEAST"}]
        penalized = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        clean = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        self.assertEqual(penalized[EL] - clean[EL], -2.0)


class TestNoEvidenceNoComp(unittest.TestCase):
    """A target comp requires EVIDENCE (2026-09-04 live note: "already has
    a recommended comp listed from the beginning of the game, which is
    unrealistic"). No board commit and no recent core buys -> None — the
    coach says nothing instead of inventing a checklist comp."""

    def test_no_evidence_no_comp(self):
        comps = {"a": {"name": "A", "meta_tier": "A", "core": [], "addons": []},
                 "b": {"name": "B", "meta_tier": "B", "core": [], "addons": []}}
        self.assertIsNone(value.comp_target([], comps))

    def test_one_board_core_is_not_a_commit(self):
        comps = {"nagas": {"name": "Nagas", "core": ["BG33_140"], "addons": []}}
        self.assertIsNone(value.comp_target([{"card": "BG33_140"}], comps))

    def test_board_copies_commit(self):
        """2x one core is a commit (copies count, same as a pivot)."""
        comps = {"nagas": {"name": "Nagas", "core": ["BG33_140"], "addons": []}}
        board = [{"card": "BG33_140"}, {"card": "BG33_140"}]
        self.assertIs(value.comp_target(board, comps), comps["nagas"])

    def test_board_plus_recent_hits_commit(self):
        """One core on the board + one among recent acquisitions is a commit
        (a buy IS intention)."""
        comps = {"nagas": {"name": "Nagas", "core": ["BG33_140"], "addons": []}}
        board = [{"card": "BG33_140"}]
        self.assertIs(value.comp_target(board, comps,
                                        recent_cards=["BG33_140"]),
                      comps["nagas"])

    def test_tribe_evidence_across_comps(self):
        """A build straddling two comps of one tribe (2026-09-04 beasts game:
        Tasty Lobster + Banana Slamma) still points at the tribe — the coach
        must stop headlining off-tribe cards."""
        comps = {"lobstah": {"name": "Lobstah", "tribe": "Beast",
                             "core": ["BG36_208"], "addons": []},
                 "beetles": {"name": "Beetles", "tribe": "Beast",
                             "core": ["BG26_802"], "addons": []},
                 "nagas": {"name": "Nagas", "tribe": "Naga",
                           "core": ["BG32_821"], "addons": []}}
        board = [{"card": "BG36_208"}]
        recent = ["BG26_802"]
        target = value.comp_target(board, comps, recent_cards=recent)
        self.assertIsNotNone(target)
        self.assertEqual(target["tribe"], "Beast")


class TestCompProgress(unittest.TestCase):
    """The commit-readiness meter (comp_progress) mirrors comp_target's
    evidence rule per candidate, so the UI can show direction BEFORE the
    2-core-hit commit threshold fires."""

    def test_no_evidence_no_rows(self):
        comps = {"nagas": {"name": "Nagas", "tribe": "Naga",
                           "core": ["BG33_140"], "addons": []}}
        self.assertEqual(value.comp_progress([], comps), [])

    def test_one_hit_is_visible_but_not_ready(self):
        """The pre-commit blind spot: 1 core hit is not a commit, but the
        meter must still show the candidate and how far it is."""
        comps = {"nagas": {"name": "Nagas", "tribe": "Naga",
                           "core": ["BG33_140"], "addons": []}}
        rows = value.comp_progress([{"card": "BG33_140"}], comps)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hits"], 1)
        self.assertFalse(rows[0]["ready"])

    def test_two_hits_ready_and_needs_exclude_owned(self):
        comps = {"nagas": {"name": "Nagas", "tribe": "Naga",
                           "core": ["BG33_140", "BG32_821"], "addons": []}}
        board = [{"card": "BG33_140"}]
        rows = value.comp_progress(board, comps, recent_cards=["BG32_821"])
        self.assertTrue(rows[0]["ready"])
        # needs = unowned core ON THE BOARD; the copied core in hand isn't
        # there yet (a needs row for a card you just bought is noise).
        self.assertEqual(rows[0]["needs"], ["BG32_821"])
        rows = value.comp_progress([{"card": "BG33_140"},
                                    {"card": "BG32_821"}], comps)
        self.assertEqual(rows[0]["needs"], [])

    def test_recent_hits_count(self):
        comps = {"nagas": {"name": "Nagas", "tribe": "Naga",
                           "core": ["BG33_140"], "addons": []}}
        rows = value.comp_progress([], comps, recent_cards=["BG33_140"])
        self.assertEqual(rows[0]["hits"], 1)

    def test_sorted_by_hits_then_meta_tier(self):
        comps = {"a": {"name": "A", "tribe": "T", "meta_tier": "B",
                       "core": ["c1"], "addons": []},
                 "b": {"name": "B", "tribe": "T", "meta_tier": "S",
                       "core": ["c2"], "addons": []}}
        board = [{"card": "c1"}, {"card": "c2"}]
        rows = value.comp_progress(board, comps)
        self.assertEqual([r["name"] for r in rows], ["B", "A"])

    def test_tribe_signal_annotates_rows(self):
        """Tribe evidence spread across comps (1 + 1 hits, one tribe) —
        neither comp commits alone, but comp_target's tribe rule fires, so
        each Beast row carries the tribe total for the meter to show."""
        comps = {"lobstah": {"name": "Lobstah", "tribe": "Beast",
                             "meta_tier": "A", "core": ["BG36_208"],
                             "addons": []},
                 "beetles": {"name": "Beetles", "tribe": "Beast",
                             "meta_tier": "B", "core": ["BG26_802"],
                             "addons": []},
                 "nagas": {"name": "Nagas", "tribe": "Naga",
                           "meta_tier": "S", "core": ["BG32_821"],
                           "addons": []}}
        board = [{"card": "BG36_208"}]
        recent = ["BG26_802"]
        rows = value.comp_progress(board, comps, recent_cards=recent)
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["Lobstah"]["tribe_hits"], 2)
        self.assertEqual(by_name["Beetles"]["tribe_hits"], 2)
        # Zero-hit comps are not rows at all (the meter shows candidates,
        # not the full comp list — that's the "Playable comps" box).
        self.assertNotIn("Nagas", by_name)
        self.assertFalse(by_name["Lobstah"]["ready"])  # 1 hit each, not a commit


class TestSituationLine(unittest.TestCase):
    """The plan's one-line thread above the steps (the 2026-09-06 Guff game
    had 240 stats vs a ~140 lobby and 30 HP with zero armor — every panel
    stayed silent about the one thing that mattered: one bad fight kills)."""

    def test_zero_armor_mortality(self):
        a = {"target_comp": "Beasts - Tasty Lobstah", "target_state": "committing",
             "board_stats": 240, "lobby_opp": 140, "health": 30, "armor": 0}
        line = value.situation_line(a)
        self.assertIn("Beasts build", line)
        self.assertIn("strong (240 vs ~140)", line)
        self.assertIn("no armor at 30 — one bad fight can end it", line)

    def test_dying_overrides(self):
        a = {"target_comp": None, "board_stats": 40, "lobby_opp": 200,
             "health": 8, "armor": 2, "loss_streak": 3}
        line = value.situation_line(a)
        self.assertIn("DYING at 8+2 — buy board now", line)
        self.assertIn("lost 3 straight", line)

    def test_quiet_when_nothing_to_say(self):
        # Early game, armor up, no direction: no invented drama.
        a = {"board_stats": 6, "lobby_opp": 8, "health": 30, "armor": 12,
             "target_comp": None}
        self.assertIsNone(value.situation_line(a))


class TestStickyCompTarget(unittest.TestCase):
    """Same-tribe target churn (Summon Beetles -> Tasty Lobstah phase to
    phase) read as 'which build am I doing?' — the previous comp sticks
    unless the new one carries strictly more core evidence."""

    BEETLES = {"name": "Beasts - Summon Beetles", "tribe": "Beast"}
    LOBSTAH = {"name": "Beasts - Tasty Lobstah", "tribe": "Beast"}
    NAGAS = {"name": "Nagas - Groundbreaker", "tribe": "Naga"}

    def test_same_tribe_sticks(self):
        self.assertIs(
            value.sticky_comp_target(self.BEETLES, self.LOBSTAH, 2, 2),
            self.BEETLES)

    def test_more_evidence_switches(self):
        self.assertIs(
            value.sticky_comp_target(self.BEETLES, self.LOBSTAH, 2, 3),
            self.LOBSTAH)

    def test_cross_tribe_pivot_always_passes(self):
        self.assertIs(
            value.sticky_comp_target(self.BEETLES, self.NAGAS, 3, 1),
            self.NAGAS)


class TestUndeadEngine(unittest.TestCase):
    """The undead-attack-scaling engine (added 2026-09-06: the comp is
    S-tier but had no model — the coach drifted while the player built it).
    Butchering: destroy a friendly Undead -> ALL Undead +5 Attack this
    game, one cast at a time; the Phantom's reborn transfer is approximated."""

    def test_butchering_growth(self):
        eng = simulate_growth._load_engines()["undead-attack-scaling"]
        board = [{"card": "BG32_324", "name": "Drustfallen Butcher",
                  "atk": 6, "health": 6, "tribe": "UNDEAD"},
                 {"card": "BG36_515", "name": "Snazzy Phantom",
                  "atk": 5, "health": 5, "tribe": "UNDEAD"},
                 {"card": "BG36_511", "name": "Dead Bellringer",
                  "atk": 4, "health": 4, "tribe": "UNDEAD"},
                 {"card": "BG34_925", "name": "Seafloor Recruiter",
                  "atk": 3, "health": 3, "tribe": "NAGA"}]
        r = simulate_growth.simulate_growth(board, {"cast_spell": 3}, eng)
        # 3 casts x 5 atk x 3 undead (tribe scope) + 3 casts x ~3 atk (Phantom)
        self.assertEqual(r["gain"]["atk"], 45 + 9)
        self.assertEqual(r["gain"]["hp"], 3)

    def test_engine_pieces_credited(self):
        names = value._load_bg_names()
        board = [{"card": "BG32_324", "name": "Drustfallen Butcher",
                  "atk": 6, "health": 6, "tribe": "UNDEAD"},
                 {"card": "BG36_515", "name": "Snazzy Phantom",
                  "atk": 5, "health": 5, "tribe": "UNDEAD"},
                 {"card": "BG36_511", "name": "Dead Bellringer",
                  "atk": 4, "health": 4, "tribe": "UNDEAD"}]
        bonus = value._engine_growth_bonus(board, names,
                                           scenario={"cast_spell": 3})
        self.assertGreater(bonus.get("BG32_324", 0), 0)  # Butcher
        self.assertGreater(bonus.get("BG36_515", 0), 0)  # Phantom

    def test_best_engine_picked_on_undead_board(self):
        names = value._load_bg_names()
        board = [{"card": "BG32_324", "name": "Drustfallen Butcher",
                  "atk": 6, "health": 6, "tribe": "UNDEAD"},
                 {"card": "BG36_511", "name": "Dead Bellringer",
                  "atk": 4, "health": 4, "tribe": "UNDEAD"}]
        best = value._best_engine(board, names)
        self.assertEqual((best or {}).get("name"), "Undead - Attack Scaling")


class TestEngineFit(unittest.TestCase):
    """Engine credit must fit the board: an engine whose tribe fights the
    board's dominant tribe is growing minions the player is pivoting away
    from — raw credit put Deflect-o-Bot (mech) atop a beast-leaning shop
    (2026-09-06 Reno game t7, placement 6)."""

    def test_off_dominant_engine_damped(self):
        names = value._load_bg_names()
        snapper = "BG36_851"   # Spark Snapper — mechs-magnetics core (MECH)
        lobster = "BG36_202"   # Tasty Lobster — beasts engine core (BEAST)
        automaton = "BG_TTN_401"  # Ancestral Automaton, a mech body
        mech_board = [{"card": snapper, "atk": 2, "health": 2, "tribe": "MECH"},
                      {"card": automaton, "atk": 3, "health": 3, "tribe": "MECH"},
                      {"card": automaton, "atk": 3, "health": 3, "tribe": "MECH"}]
        beast_board = [{"card": snapper, "atk": 2, "health": 2, "tribe": "MECH"},
                       {"card": lobster, "atk": 4, "health": 4, "tribe": "BEAST"},
                       {"card": lobster, "atk": 4, "health": 4, "tribe": "BEAST"}]
        full = value._engine_growth_bonus(mech_board, names).get(snapper, 0)
        damped = value._engine_growth_bonus(beast_board, names).get(snapper, 0)
        self.assertGreater(full, 0)   # the engine still runs and is credited
        self.assertGreater(damped, 0)
        self.assertLess(damped, full * 0.5)  # damped, not erased

    def test_tribe_engine_undamped_on_its_board(self):
        names = value._load_bg_names()
        lobster = "BG36_202"
        barnstormer = "BG26_162"   # Dancing Barnstormer, a beast body
        beast_board = [{"card": lobster, "atk": 4, "health": 4, "tribe": "BEAST"},
                       {"card": barnstormer, "atk": 3, "health": 3, "tribe": "BEAST"},
                       {"card": barnstormer, "atk": 3, "health": 3, "tribe": "BEAST"}]
        credit = value._engine_growth_bonus(beast_board, names).get(lobster, 0)
        self.assertGreater(credit, 0)  # a fit engine keeps full credit

    def test_precommit_off_tribe_growth_damped(self):
        """No target yet, but the board is already one tribe: an off-tribe
        GROWTH card is scaling minions the player is leaving — its growth
        term is discounted (Deflect-o-Bot, mech, growth 3.0, headlined a
        beast board at 11.5 with no engine bonus at all; 2026-09-06 Reno
        t7). Milder than the committed damp: no flat penalty, and untribed
        cards are exempt (they fit any build)."""
        deflect = "BGS_071"    # Deflect-o-Bot (MECH, growth 3.0)
        board_beast = [{"card": "BG36_202", "atk": 4, "health": 4, "tribe": "BEAST"},
                       {"card": "BG26_162", "atk": 3, "health": 3, "tribe": "BEAST"},
                       {"card": "BG26_162", "atk": 3, "health": 3, "tribe": "BEAST"}]
        board_mech = [{"card": deflect, "atk": 3, "health": 2, "tribe": "MECH"},
                      {"card": "BG_TTN_401", "atk": 3, "health": 3, "tribe": "MECH"},
                      {"card": "BG_TTN_401", "atk": 3, "health": 3, "tribe": "MECH"}]
        damped = dict(value.shop_ranking([deflect], {}, board_beast))
        undamped = dict(value.shop_ranking([deflect], {}, board_mech))
        self.assertLess(damped[deflect], undamped[deflect])

    def test_precommit_untribed_growth_exempt(self):
        """Untribed cards fit any build — no pre-commit damp."""
        deflect = "BGS_071"
        board = [{"card": "BG36_202", "atk": 4, "health": 4, "tribe": "BEAST"},
                 {"card": "BG26_162", "atk": 3, "health": 3, "tribe": "BEAST"}]
        amalgam = "BG36_640"   # Gatekeeper Amalgam, all-tribe
        scored = dict(value.shop_ranking([deflect, amalgam], {}, board))
        # the mech is damped relative to the all-tribe card of similar growth
        self.assertGreater(scored[amalgam], scored[deflect] - 20)


class TestBlockedCore(unittest.TestCase):
    """Hybrid comps survive the ban with _blocked_core set (bans.py
    degraded-keep); the shopping list must mark those pieces banned, never
    hunt them, and count them findable for the leveling note."""

    def test_comp_cards_marks_banned(self):
        target = {"name": "Nagas - Groundbreaker",
                  "core": ["BG31_035", "BG36_243"],
                  "addons": [], "_blocked_core": ["BG36_243"]}
        board = [{"card": "BG31_035"}]
        tc = value.comp_cards(target, board)
        by_card = {r["card"]: r for r in tc["core"]}
        self.assertTrue(by_card["BG31_035"]["owned"])
        self.assertFalse(by_card["BG31_035"]["banned"])
        self.assertFalse(by_card["BG36_243"]["owned"])
        self.assertTrue(by_card["BG36_243"]["banned"])

    def test_progress_needs_exclude_blocked(self):
        comps = {"nagas": {"name": "Nagas", "tribe": "Naga", "meta_tier": "A",
                           "core": ["BG31_035", "BG36_243"], "addons": [],
                           "_blocked_core": ["BG36_243"]}}
        rows = value.comp_progress([{"card": "BG31_035"}], comps)
        self.assertEqual(rows[0]["needs"], ["BG31_035"] and [])


class TestHandPlan(unittest.TestCase):
    """Hand plays the coach never made (2026-09-04: five spells sat in hand
    that would 10x the board's stats while the coach said nothing). Casting
    from hand is free, a stuck minion plays free — each is pure profit."""

    BANANA = "BG28_897"   # Tavern Dish Banana: give a minion +2/+2 (t1 spell)
    MINION = "BG33_140"   # River Skipper, a tier-1 body

    def test_casts_and_plays_carry_verbs(self):
        hand = [{"card": self.BANANA, "type": "spell"},
                {"card": self.MINION, "type": "minion",
                 "atk": 2, "health": 2}]
        steps = value.hand_plan(hand, board_minions=[])
        self.assertTrue(steps)
        self.assertEqual(steps[0]["verb"], "cast")
        self.assertEqual(steps[0]["card"], self.BANANA)
        self.assertIn("play", [s["verb"] for s in steps])

    def test_engine_fuel_boosts_a_cast(self):
        """A running cast-spell engine turns every cast into compounding
        growth — the spell scores higher and says so."""
        spell = [{"card": self.BANANA, "type": "spell"}]
        plain = value.hand_plan(spell, board_minions=[],
                                scenario={"cast_spell": 0})
        glambot_board = [{"card": "BG36_853", "name": "Glambot",
                          "atk": 4, "health": 4}]
        fueled = value.hand_plan(spell, board_minions=glambot_board,
                                 scenario={"cast_spell": 10})
        self.assertGreater(fueled[0]["score"], plain[0]["score"])
        self.assertTrue(fueled[0]["why"])

    def test_unknown_spell_skipped(self):
        """Generated spell entities without a real id can't be advised."""
        self.assertEqual(value.hand_plan(
            [{"card": "UNKNOWN_SPELL_X", "type": "spell"}]), [])

    def test_make_room_never_sells_a_held_card(self):
        """One plan, one direction (2026-09-06 Guff t12): the hand said
        'Hold Sewer Lord — a 3rd copy turns it golden' and the same panel's
        make-room step said 'sell Sewer Lord'. The make-room walk must skip
        held cards; if the only filler is held, the golden hunt outranks
        the slot and no sell step appears."""
        a = {"board": [{"card": "BG33_140", "atk": 2, "health": 2}] * 7,
             "sell_rank": [("BG33_140", 8.0), ("BG36_511", 30.0)],
             "hand_plan": [{"card": "BG33_140", "verb": "hold",
                            "name": "Sewer Lord", "score": 8.0}],
             "buy_this": "BG36_202", "shop_rank": [("BG36_202", 9.0)],
             "gold": 3, "tier": 5, "playable_comps": {}, "hand_plan": None}
        line = value.top_move(a)
        self.assertNotIn("sell BG33_140", line)
        self.assertNotIn("sell Sewer", line)

    def test_triple_awareness(self):
        """2 on board: the hand copy IS the triple — play now. 1 on board:
        hold it and hunt a 3rd (2026-09-05: the coach said "Play Balinda"
        when the right move was holding her for the golden)."""
        hand = [{"card": self.MINION, "type": "minion",
                 "atk": 2, "health": 2}]
        two = value.hand_plan(hand, board_minions=[
            {"card": self.MINION, "atk": 2, "health": 2}] * 2)
        self.assertEqual(two[0]["verb"], "play")
        self.assertIn("golden", two[0]["why"])
        one = value.hand_plan(hand, board_minions=[
            {"card": self.MINION, "atk": 2, "health": 2}])
        self.assertEqual(one[0]["verb"], "hold")
        self.assertIn("golden", one[0]["why"])

    def test_triple_play_outranks_a_bigger_free_play(self):
        two = value.hand_plan(
            [{"card": self.MINION, "type": "minion", "atk": 2, "health": 2}],
            board_minions=[{"card": self.MINION, "atk": 2, "health": 2}] * 2)
        plain = value.hand_plan(
            [{"card": self.MINION, "type": "minion", "atk": 2, "health": 2}])
        self.assertGreater(two[0]["score"], plain[0]["score"])


class TestTopMoveHand(unittest.TestCase):
    """The hand leads the numbered plan (free actions, execution order)."""

    def _analysis(self, hand_entries=None):
        return {"tier": 2, "gold": 6, "level_cost": 5, "health": 30,
                "armor": 0, "turn": 7, "damage_last": None, "loss_streak": 0,
                "board": [], "shop_rank": [], "buy_this": None,
                "playable_comps": {}, "choice": None, "sell_rank": [],
                "target_comp": None, "target_cards": None,
                "hand_plan": hand_entries or []}

    def test_hand_casts_lead_the_plan(self):
        tm = value.top_move(self._analysis([
            {"card": "BG28_897", "verb": "cast", "name": "Tavern Dish Banana",
             "score": 4, "why": None}]))
        self.assertTrue(tm.startswith("1. Cast Tavern Dish Banana"), tm)
        self.assertIn("2. LEVEL to tier 3 (standard curve)", tm)

    def test_copies_group_and_rest_summarize(self):
        entries = ([{"card": "BG28_897", "verb": "cast",
                     "name": "Tavern Dish Banana", "score": 4, "why": None}]
                   * 2
                   + [{"card": "BG28_810", "verb": "cast",
                       "name": "Tavern Coin", "score": 1, "why": None}])
        tm = value.top_move(self._analysis(entries))
        self.assertIn("1. Cast Tavern Dish Banana x2", tm)
        self.assertIn("2. Cast Tavern Coin", tm)
        self.assertIn("3. LEVEL", tm)

    def test_more_than_three_kinds_summarize(self):
        entries = [{"card": f"BG28_80{i}", "verb": "cast", "name": f"Spell {i}",
                    "score": 5 - i, "why": None} for i in range(4)]
        tm = value.top_move(self._analysis(entries))
        self.assertIn("then the rest of your hand (1 more)", tm)

    def test_hand_minion_on_full_board_says_make_room(self):
        entries = [{"card": "BG33_140", "verb": "play", "name": "River Skipper",
                    "score": 10, "why": "board is full — sell to make room"}]
        tm = value.top_move(self._analysis(entries))
        self.assertIn("Play River Skipper (board is full — sell to make room)",
                      tm)

    def test_wait_for_end_of_turn_casts_first(self):
        """End-of-turn compounding counts casts made THIS turn — the hand
        goes before the pass."""
        a = self._analysis([
            {"card": "BG28_897", "verb": "cast",
             "name": "Tavern Dish Banana", "score": 4, "why": None}])
        a["tier"] = 6  # nothing left to level — the pass is the only spend move
        a["board"] = [{"card": "BG32_235"}] * 7  # end-of-turn scaler, full board
        tm = value.top_move(a)
        self.assertTrue(tm.startswith("1. Cast Tavern Dish Banana"), tm)
        self.assertIn("wait for end of turn", tm)

    def test_committed_endgame_says_scale(self):
        """Once committed the endgame is enriching what we have (2026-09-04:
        "we committed, we have it, now we scale it to kingdom come") — the
        stale fallback says scale, not hold."""
        a = self._analysis()
        a["gold"] = 0
        a["target_comp"] = "Nagas - Groundbreaker"
        a["target_state"] = "committing"
        tm = value.top_move(a)
        self.assertIn("scale Nagas - Groundbreaker", tm)
        self.assertIn("sell nothing that grows", tm)


class TestMultiplierProtect(unittest.TestCase):
    """Comp glue is never 'safest to sell' (2026-09-04 1st-place game: 'sell
    Balinda Stonehearth (making room)' fired three phases in a row — she IS
    nagas core; Rimescale Priestess was the earlier report)."""

    BALINDA = "BG35_883"       # "Your spells that target friendly minions
    RIMESCALE = "BG33_319"     # cast twice." / Spellcraft generator
    FILLER = "BG33_140"        # River Skipper, a plain tier-1 body

    def test_balinda_is_recognized_as_a_multiplier(self):
        self.assertTrue(value._is_multiplier(
            value._load_card_db().get(self.BALINDA)))

    def test_spellcraft_generators_are_scaling(self):
        card = value._load_card_db().get(self.RIMESCALE)
        self.assertEqual(value._detect_role({"card": self.RIMESCALE}, card),
                         "scaling")

    def test_glue_never_ranks_safest(self):
        board = [{"card": self.BALINDA, "atk": 4, "health": 6, "tribe": "NAGA"},
                 {"card": self.RIMESCALE, "atk": 2, "health": 6,
                  "tribe": "NAGA"},
                 {"card": self.FILLER, "atk": 2, "health": 2, "tribe": "NAGA"}]
        ranked = value.sell_recommendation(board, [])
        self.assertNotEqual(ranked[0][0], self.BALINDA)
        self.assertNotEqual(ranked[0][0], self.RIMESCALE)
        self.assertEqual(ranked[0][0], self.FILLER)
        scores = dict(ranked)
        self.assertGreaterEqual(scores[self.BALINDA], 16)
        self.assertLess(scores[self.FILLER], 16)


class TestCompFilteredBuy(unittest.TestCase):
    """The buy ranking uses the SAME comp evidence as the target display —
    no evidence means NO comp bonus (the old fallback blessed an arbitrary
    dict-order comp's core with +10: Banana Slamma, a Beast, headlined the
    Naga game at t9 of the 2026-09-04 1st-place run)."""

    SLAMMA = "BG26_802"         # Banana Slamma (Beast)
    PERCUSSIONIST = "BG26_525"  # Imposing Percussionist
    COMPS = {
        "beasts": {"name": "Beasts", "tribe": "Beast",
                   "core": [SLAMMA], "addons": []},
        "nagas": {"name": "Nagas", "tribe": "Naga",
                  "core": [PERCUSSIONIST], "addons": []},
    }

    def test_no_evidence_no_arbitrary_comp_bonus(self):
        plain = dict(value.shop_ranking([self.SLAMMA], {},
                                        board_minions=[]))
        with_comps = dict(value.shop_ranking([self.SLAMMA], self.COMPS,
                                             board_minions=[]))
        self.assertAlmostEqual(with_comps[self.SLAMMA], plain[self.SLAMMA])

    def test_recent_evidence_blesses_only_that_comp(self):
        recent = [self.PERCUSSIONIST, self.PERCUSSIONIST]  # copies commit
        blessed = dict(value.shop_ranking(
            [self.SLAMMA, self.PERCUSSIONIST], self.COMPS,
            board_minions=[], recent_cards=recent))
        base = dict(value.shop_ranking(
            [self.SLAMMA, self.PERCUSSIONIST], self.COMPS,
            board_minions=[]))
        self.assertGreater(blessed[self.PERCUSSIONIST],
                           base[self.PERCUSSIONIST] + 9)  # the +10 core bonus
        self.assertAlmostEqual(blessed[self.SLAMMA], base[self.SLAMMA])


if __name__ == "__main__":
    unittest.main()
