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


class TestActivations(unittest.TestCase):
    """Board-minion activations are a spend-the-last-gold action class: the
    2026-09-06 live game advised a useless reroll at 1 gold while Suspicious
    Prisonguard ('Activate (1): Give another minion +3/+3') sat on board."""

    PRISON = "BG36_345"

    def test_activation_parsed(self):
        info = value.activation_of(value._load_card_db().get(self.PRISON))
        self.assertEqual(info["cost"], 1)
        self.assertIn("+3/+3", info["effect"])

    def test_activation_beats_useless_reroll(self):
        """1 gold, everything in the shop costs 3, a usable activation on
        the board -> 'Activate', not 'roll'."""
        a = {"tier": 3, "gold": 1, "board": [],
             "shop_rank": [("BG_TTN_401", 9.0)], "buy_this": "BG_TTN_401",
             "activations": [{"cid": self.PRISON}],
             "playable_comps": {}, "choice": None, "target_comp": None,
             "sell_rank": []}
        line = value.top_move(a)
        self.assertIn("1. Activate", line)
        self.assertFalse(line.startswith("roll"))

    def test_unaffordable_activation_still_rolls(self):
        a = {"tier": 3, "gold": 1, "board": [],
             "shop_rank": [("BG_TTN_401", 9.0)], "buy_this": "BG_TTN_401",
             "activations": [{"cid": self.PRISON}],
             "playable_comps": {}, "choice": None, "target_comp": None,
             "sell_rank": []}
        a["activations"] = [{"cid": "BG32_324"}]  # Drustfallen Butcher: no Activate
        line = value.top_move(a)
        self.assertIn("roll", line)
        self.assertNotIn("Activate", line)

    def test_live_capture(self):
        """The friendly's usable activation rides the settled options block;
        opponent-owned, hand-zone, and error!=NONE options don't count."""
        from live_coach import LiveCoach
        c = LiveCoach()
        c.friendly = 5
        OPT = "D 12:00:00.0000000 GameState.DebugPrintOptions() - "
        for line in [
            "x STEP MAIN_ACTION",
            f"{OPT}  id=1",
            f"{OPT}  option 0 type=POWER mainEntity=[entityName=Refresh id=9 "
            f"zone=PLAY zonePos=0 cardId=TB_BaconShop_8p_Reroll_Button "
            f"player=5] error=NONE errorParam=",
            f"{OPT}  option 1 type=POWER mainEntity=[entityName=Suspicious "
            f"Prisonguard id=406 zone=PLAY zonePos=3 cardId=BG36_345 "
            f"player=5] error=NONE errorParam=",
        ]:
            c.feed(line)
        c.tavern_offers()  # settles the block (the live loop polls this)
        self.assertIn("BG36_345", c.activations)
        # exhausted / unaffordable / hand-zone / opponent-owned are excluded
        for line in [
            f"{OPT}  id=2",
            f"{OPT}  option 0 type=POWER mainEntity=[entityName=Refresh id=9 "
            f"zone=PLAY zonePos=0 cardId=TB_BaconShop_8p_Reroll_Button "
            f"player=5] error=NONE errorParam=",
            f"{OPT}  option 1 type=POWER mainEntity=[entityName=Suspicious "
            f"Prisonguard id=406 zone=PLAY zonePos=3 cardId=BG36_345 "
            f"player=5] error=REQ_ENOUGH_MANA errorParam=",
            f"{OPT}  option 2 type=POWER mainEntity=[entityName=Suspicious "
            f"Prisonguard id=500 zone=HAND zonePos=1 cardId=BG36_345 "
            f"player=5] error=NONE errorParam=",
            f"{OPT}  option 3 type=POWER mainEntity=[entityName=Suspicious "
            f"Prisonguard id=406 zone=PLAY zonePos=3 cardId=BG36_345 "
            f"player=11] error=NONE errorParam=",
        ]:
            c.feed(line)
        c.tavern_offers()  # settle block 2
        self.assertNotIn("BG36_345", c.activations)


class TestCommittedMaximizes(unittest.TestCase):
    """Committed mode (2026-09-07, user principle): once committed to a
    comp, the shop calculation maximizes THAT comp — a missing core piece
    outranks a dupe, and both outrank a strong generic body."""

    def test_missing_core_outranks_a_strong_generic(self):
        # Committed (a core on board): an unowned core card beats an
        # 11.5-score generic body.
        comp = {"name": "Beasts - Tasty Lobstah", "tribe": "Beast",
                "core": ["BG36_202", "BG36_208"], "addons": []}
        board = [{"card": "BG36_202", "atk": 4, "health": 4,
                  "tribe": "BEAST"}]
        ranked = dict(value.shop_ranking(
            ["BG36_208", "BGS_071"], {"b": comp}, board, comp=comp))
        self.assertGreater(ranked["BG36_208"], ranked["BGS_071"])

    def test_missing_core_outscores_dupe_by_the_completion_gap(self):
        """Equal-raw core cards: the missing one (+14) outscores the dupe
        (+10) by the 4-point completion gap — completing the build leads,
        copies still score (triples)."""
        barnstormer = "BG26_162"   # beast body, no engine chain
        camper = "BG33_886"        # beast body, no engine chain
        comp = {"name": "Beasts - Test", "tribe": "Beast",
                "core": [barnstormer, camper], "addons": []}
        missing = dict(value.shop_ranking(
            [camper], {"b": comp},
            [{"card": barnstormer, "atk": 3, "health": 3, "tribe": "BEAST"}],
            comp=comp))
        dupe = dict(value.shop_ranking(
            [camper], {"b": comp},
            [{"card": barnstormer, "atk": 3, "health": 3, "tribe": "BEAST"},
             {"card": camper, "atk": 3, "health": 3, "tribe": "BEAST"}],
            comp=comp))
        self.assertAlmostEqual(missing[camper], dupe[camper] + 4.0, places=2)


class TestSharedUtilityCores(unittest.TestCase):
    """Core cards shared across comps of >=4 tribes are utility, not build
    evidence (2026-09-07 dragon game: Balinda — core of 7 comps across 5
    tribes — plus one dragon piece manufactured 'Nagas - Groundbreaker'
    direction at t7-t9 on a board that was never naga). Brann (3 tribes)
    deliberately stays: battlecry comps genuinely share him."""

    BALINDA = "BG35_883"
    SKYHATCH = "BG36_243"

    # Balinda core of comps across 4+ tribes — the shared-utility trigger.
    def _comps(self):
        return {
            "groundbreaker": {
                "name": "Nagas - Groundbreaker", "tribe": "Naga",
                "core": ["BG31_035", self.SKYHATCH, self.BALINDA],
                "addons": []},
            "demons": {"name": "Demons - Test", "tribe": "Demon",
                       "core": ["BG34_500", self.BALINDA], "addons": []},
            "mechs": {"name": "Mechs - Test", "tribe": "Mech",
                      "core": ["BG21_000", self.BALINDA], "addons": []},
            "pirates": {"name": "Pirates - Test", "tribe": "Pirate",
                        "core": ["BG19_000", self.BALINDA], "addons": []},
        }

    def test_balinda_does_not_manufacture_direction(self):
        board = [{"card": self.BALINDA, "atk": 4, "health": 4},
                 {"card": self.SKYHATCH, "atk": 4, "health": 4}]
        # Balinda + Sky-hatch used to read 2 hits = a naga commit; with
        # Balinda excluded it's 1 specific hit — no direction, and the
        # meter row reads 1 hit (not 2).
        self.assertIsNone(value.comp_target(board, self._comps()))
        rows = value.comp_progress(board, self._comps())
        self.assertEqual(rows[0]["hits"], 1)

    def test_specific_cores_still_commit(self):
        board = [{"card": "BG31_035", "atk": 4, "health": 4},
                 {"card": self.SKYHATCH, "atk": 4, "health": 4}]
        target = value.comp_target(board, self._comps())
        self.assertEqual(target["name"], "Nagas - Groundbreaker")

    def test_shared_card_stays_in_shopping_list(self):
        comps = self._comps()
        tc = value.comp_cards(comps["groundbreaker"], [])
        by_card = {r["card"]: r for r in tc["core"]}
        self.assertIn(self.BALINDA, by_card)  # the list keeps it
        self.assertFalse(by_card[self.BALINDA]["owned"])


class TestRollHunt(unittest.TestCase):
    """Hunt mode (2026-09-07, the player's roll-x10 style): committed with
    missing core, an off-build shop top isn't 'the best card' — the gold
    rolls for the pieces. Skipped while dying and early-game."""

    LOBSTAHC = {"name": "Beasts - Tasty Lobstah", "tribe": "Beast",
                "core": ["BG36_202", "BG36_208"], "addons": []}

    def _analysis(self, gold, health=20, turn=9):
        return {"tier": 5, "gold": gold, "level_cost": None, "board": [],
                "shop_rank": [("BGS_071", 9.0)], "buy_this": "BGS_071",
                "playable_comps": {}, "choice": None,
                "target_comp": "Beasts - Tasty Lobstah",
                "target_state": "committing",
                "target_cards": {
                    "name": "Beasts - Tasty Lobstah",
                    "core": [{"card": "BG36_202", "name": "Tasty Lobster",
                              "owned": True, "banned": False},
                             {"card": "BG36_208", "name": "Deathstrider",
                              "owned": False, "banned": False}],
                    "addons": []},
                "health": health, "armor": 0, "turn": turn,
                "comp": self.LOBSTAHC, "sell_rank": []}

    def test_off_build_buy_becomes_a_hunt(self):
        # Deflect-o-Bot (mech) affordable on a committed beast board with a
        # missing core: the plan rolls and names the hunt.
        line = value.top_move(self._analysis(4))
        self.assertIn("roll — hunting Deathstrider", line)
        self.assertNotIn("Buy", line)

    def test_comp_piece_still_buys(self):
        a = self._analysis(4)
        a["shop_rank"] = [("BG36_208", 9.0)]
        a["buy_this"] = "BG36_208"
        line = value.top_move(a)
        self.assertIn("Buy", line)
        self.assertNotIn("hunting", line)

    def test_dying_buys_a_body(self):
        line = value.top_move(self._analysis(4, health=10))
        self.assertIn("Buy", line)

    def test_no_hunt_without_missing_core(self):
        a = self._analysis(4)
        a["target_cards"]["core"][1]["owned"] = True
        line = value.top_move(a)
        self.assertIn("Buy", line)

    def test_hunt_names_specific_cores_first(self):
        """A shared-utility card (Balinda) is still on the shopping list,
        but the hunt names the build's win condition first (2026-09-08:
        the hunt's second target read 'Balinda Stonehearth')."""
        a = self._analysis(4)
        a["target_cards"]["core"].append(
            {"card": "BG35_883", "name": "Balinda Stonehearth",
             "owned": False, "banned": False})
        # Balinda must read as SHARED UTILITY for the hunt to skip her —
        # core of 4 comps across 4 tribes (_shared_utility_cores's gate).
        a["playable_comps"] = {
            t: {"name": t, "tribe": t, "core": ["BG35_883"], "addons": []}
            for t in ("Beast", "Dragon", "Mech", "Murloc")}
        line = value.top_move(a)
        self.assertIn("hunting Deathstrider", line)
        self.assertNotIn("Balinda", line)


class TestShopGolden(unittest.TestCase):
    """A GOLDEN shop offer (2026-09-08, player-confirmed): costs the flat 3,
    and playing it pays the triple reward NOW — super-duper high value. It
    used to be invisible: the ranking dropped the "_G" id (card_db has base
    ids only) and the price walk couldn't price it either."""

    CID = "BG33_140"   # River Skipper — any base minion id

    def test_golden_shop_offer_is_ranked_not_dropped(self):
        scored = dict(value.shop_ranking([self.CID + "_G"], {}))
        self.assertIn(self.CID + "_G", scored)

    def test_golden_scores_golden_body_plus_reward(self):
        plain = dict(value.shop_ranking([self.CID], {}))
        gold = dict(value.shop_ranking([self.CID + "_G"], {}))
        # 3x the stacked body on top of the triple-reward weight.
        self.assertGreater(gold[self.CID + "_G"],
                           plain[self.CID] + value.W_SHOP_GOLDEN)

    def test_golden_outranks_missing_core(self):
        comp = {"name": "Beasts", "tribe": "Beast", "core": [self.CID],
                "addons": []}
        scored = dict(value.shop_ranking(
            [self.CID, self.CID + "_G"], {"b": comp}, board_minions=[]))
        # The plain copy is the comp's MISSING core (+14); the golden still
        # wins — an immediate triple beats a future one.
        self.assertGreater(scored[self.CID + "_G"], scored[self.CID])

    def test_golden_priced_flat_three(self):
        costs = value._buy_prices({})
        self.assertEqual(costs.get(self.CID + "_G"), 3)

    def test_top_move_buys_a_golden_at_three(self):
        a = {"gold": 3, "buy_this": self.CID + "_G",
             "shop_rank": [[self.CID + "_G", 30.0]], "board": [], "turn": 9}
        line = value.top_move(a)
        self.assertEqual(a["buy_step_card"], self.CID + "_G")
        self.assertIn("Buy River Skipper (golden)", line)


class TestCombatForecast(unittest.TestCase):
    """The next-fight verdict: favored / close / behind from the stat
    ratio, with our keyword edges named (divine shields, venomous). The
    opponent's keywords aren't tracked yet — v1 limit."""

    def test_favored_with_edges(self):
        a = {"board_stats": 300, "opp_stats": 140,
             "board": [{"card": "X", "keywords": ["DIVINE_SHIELD"]},
                       {"card": "Y", "keywords": ["VENOMOUS"]}]}
        line = value.combat_forecast(a)
        self.assertIn("favored — 300 vs 140", line)
        self.assertIn("1 divine shield", line)
        self.assertIn("venomous", line)

    def test_close_and_behind(self):
        self.assertIn("close fight", value.combat_forecast(
            {"board_stats": 100, "opp_stats": 110, "board": []}))
        self.assertIn("behind", value.combat_forecast(
            {"board_stats": 100, "opp_stats": 200, "board": []}))
        self.assertIn("don't take this fight", value.combat_forecast(
            {"board_stats": 100, "opp_stats": 200, "board": []}))

    def test_none_without_opponent(self):
        self.assertIsNone(value.combat_forecast(
            {"board_stats": 100, "opp_stats": None, "board": []}))


class TestStrengthGapLevelGate(unittest.TestCase):
    """Losing AND far behind the turn-appropriate board defers the level at
    any tier >=2 (2026-09-08 Loh game: the coach said 'standard curve' at
    t2/t4 through four straight losses with a 2-minion, 7-stat board vs
    ~23, then the review blamed the player for following it — a paradox).
    Tier 1 stays curve-driven."""

    def _analysis(self, tier, streak, board_stats, baseline, gold=10,
                  level_cost=5):
        return {"tier": tier, "gold": gold, "level_cost": level_cost,
                "board": [{"card": "BG33_140", "atk": 1, "health": 1}],
                "board_stats": board_stats, "baseline_opp": baseline,
                "loss_streak": streak, "damage_last": 2,
                "close_losses": False, "shop_rank": [("BG33_140", 9.0)],
                "buy_this": "BG33_140", "playable_comps": {},
                "choice": None, "target_comp": None, "sell_rank": [],
                "turn": 9}

    def test_losing_and_far_behind_buys_stats(self):
        # Gold 6, level 5, buy 3 — they can't both fit (the Loh t4 shape):
        # the strength gap defers the level behind the board buy.
        line = value.top_move(self._analysis(2, 3, 7, 15, gold=6))
        self.assertIn("buy stats first", line)
        self.assertIn("Buy", line)  # the board-building buy leads
        self.assertFalse(line.startswith("1. LEVEL"))

    def test_losing_but_on_curve_levels(self):
        # Not far behind: the standard curve stands.
        line = value.top_move(self._analysis(2, 2, 13, 15))
        self.assertNotIn("buy stats first", line)

    def test_tier1_stays_curve_driven(self):
        line = value.top_move(self._analysis(1, 3, 2, 15, gold=10,
                                             level_cost=5))
        self.assertNotIn("buy stats first", line)


class TestButcheringTargets(unittest.TestCase):
    """Destroy-cost casts consume a target: Reborn is one-shot (covers a
    single death per body — the player-corrected 2026-09-08 point), so the
    cast advice caps at the board's Undead and states the targeting rule.
    Sustain comes from generating NEW reborn bodies (Forsaken's hands,
    Eternal Summoner's knights), not from re-killing one body forever."""

    BUTCHER = "BG28_604"
    UNDEAD = {"card": "BG36_511", "name": "Dead Bellringer", "atk": 4,
              "health": 4, "tribe": "UNDEAD", "keywords": ["REBORN"]}

    def _hand(self, n):
        return [{"card": self.BUTCHER, "type": "spell"}] * n

    def test_casts_capped_at_board_undead(self):
        # 4 Butcherings, 2 Undead on board: only 2 castable.
        steps = value.hand_plan(self._hand(4), board_minions=[self.UNDEAD,
                                                              self.UNDEAD])
        casts = [s for s in steps if s["card"] == self.BUTCHER]
        self.assertEqual(len(casts), 2)

    def test_no_targets_no_casts(self):
        steps = value.hand_plan(self._hand(2), board_minions=[])
        self.assertEqual([s for s in steps if s["card"] == self.BUTCHER], [])

    def test_why_says_reborn_first(self):
        steps = value.hand_plan(self._hand(1), board_minions=[self.UNDEAD])
        self.assertIn("Reborn minion first", steps[0]["why"])

    def test_no_reborn_names_generators(self):
        """With no Reborn targets, the why points at the comp page's
        generators (Handless Forsaken / Mummifier / Eternal Summoner) —
        the loop's sustain is producing new reborn bodies, not re-killing
        one body forever."""
        plain = dict(self.UNDEAD, keywords=[])
        steps = value.hand_plan(self._hand(1), board_minions=[plain])
        self.assertIn("generate one", steps[0]["why"])


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
        # Armor is just extra health (player-corrected 2026-09-08): the
        # signal is TOTAL effective HP, not the armor's absence.
        self.assertIn("30 HP left — one bad fight can end it", line)

    def test_dying_overrides(self):
        a = {"target_comp": None, "board_stats": 40, "lobby_opp": 200,
             "health": 8, "armor": 2, "loss_streak": 3}
        line = value.situation_line(a)
        self.assertIn("DYING at 8+2 — buy board now", line)
        self.assertIn("lost 3 straight", line)

    def test_damage_cap_bands(self):
        """This season caps per-combat damage (BACON_COMBAT_DAMAGE_CAP,
        escalating by round): 'one bad fight ends it' is literally true only
        at or under the cap (2026-09-08: the coach said '30 HP, one bad
        fight can end it' at 19 HP with the cap at 15)."""
        a = {"board_stats": 100, "lobby_opp": 140, "health": 19,
             "armor": 0, "damage_cap": 15}
        line = value.situation_line(a)
        self.assertIn("19 HP vs a 15 damage cap — two lost fights end it",
                      line)
        a["health"] = 14
        line = value.situation_line(a)
        self.assertIn("one bad fight ends it, buy board now", line)

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

    def test_subthreshold_dip_holds(self):
        """No new target anywhere, the previous comp still has 1 core hit —
        the direction holds (2026-09-07 Chromie game: a sold core dropped
        the target to None at t11-t14 on a full naga build)."""
        self.assertIs(
            value.sticky_comp_target(self.BEETLES, None, 1, 0),
            self.BEETLES)

    def test_zero_evidence_drops_the_direction(self):
        self.assertIsNone(
            value.sticky_comp_target(self.BEETLES, None, 0, 0))


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
        """Untribed cards fit any build — no pre-commit damp, on any board."""
        deflect = "BGS_071"
        board_beast = [{"card": "BG36_202", "atk": 4, "health": 4, "tribe": "BEAST"},
                       {"card": "BG26_162", "atk": 3, "health": 3, "tribe": "BEAST"}]
        board_mech = [{"card": deflect, "atk": 3, "health": 2, "tribe": "MECH"},
                      {"card": "BG_TTN_401", "atk": 3, "health": 3, "tribe": "MECH"}]
        amalgam = "BG36_640"   # Gatekeeper Amalgam, no tribe in the DB
        on_beast = dict(value.shop_ranking([deflect, amalgam], {}, board_beast))
        on_mech = dict(value.shop_ranking([deflect, amalgam], {}, board_mech))
        # The untribed card scores identically on both boards (exempt);
        # the mech takes the damp on the beast board.
        self.assertAlmostEqual(on_mech[amalgam], on_beast[amalgam])
        self.assertLess(on_beast[deflect], on_mech[deflect])


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
        # BG31_035 is owned; BG36_243 is blocked-core, never "needed".
        self.assertEqual(rows[0]["needs"], [])


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
             "gold": 3, "tier": 5, "level_cost": None, "playable_comps": {}}
        line = value.top_move(a)
        self.assertIn("Hold Sewer Lord", line)
        self.assertNotIn("sell", line.lower())

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
