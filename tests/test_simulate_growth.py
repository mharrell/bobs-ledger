"""Regression tests for the deterministic growth simulator (simulate_growth).

Before 2026-09-08 the ONLY test was one standard step of one engine
(test_value.TestUndeadEngine) — compounding shop-eat steps, tribe scaling,
multiplier cards, golden multipliers/sources, the magnetize chain and the
requires_trinket gate all had zero coverage. Every assertion here is
hand-computed from the engine chains in meta/engines.json.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulate_growth import simulate_growth, _load_engines

ENGINES = _load_engines()


def minion(name, tribe=None, golden=False, atk=1, health=1):
    return {"card": name, "name": name, "tribe": tribe, "atk": atk,
            "health": health, "golden": golden}


class TestMechsMagnetics(unittest.TestCase):
    """mechs-magnetics-spells: cast_spell -> Glambot magnetizes -> Copper
    Coil (trinket) and Utility Drone (all-scope, end_of_turn multiplier)
    consume the magnetize counter."""

    ENGINE = ENGINES["mechs-magnetics-spells"]

    def board(self, glambots=1, drones=2, balinda=False, drakkari=False):
        b = [minion("Glambot", "MECHANICAL")] * glambots
        b += [minion("Utility Drone", "MECHANICAL")] * drones
        if balinda:
            b.append(minion("Balinda Stonehearth"))
        if drakkari:
            b.append(minion("Drakkari Enchanter"))
        return b

    def test_standard_chain_hand_computed(self):
        # cast 4: Glambot magnetizes 4x (4/4 each -> +16/+16); the Drone step
        # consumes magnetize=4, 2 Drones, no Drakkari, all-scope = 3 minions
        # -> 4*2*1*(4/4)*3 = +96/+96. Copper Coil skipped (no trinket).
        r = simulate_growth(self.board(), {"cast_spell": 4}, self.ENGINE)
        self.assertEqual(r["counters"]["magnetize"], 4)
        self.assertEqual(r["gain"], {"atk": 16 + 96, "hp": 16 + 96})

    def test_balinda_doubles_the_trigger(self):
        # multiplier "cast_spell" x2: magnetize = 8; the drone step consumes
        # it across the 4-minion board (Glambot + 2 Drones + Balinda).
        r = simulate_growth(self.board(balinda=True), {"cast_spell": 4},
                            self.ENGINE)
        self.assertEqual(r["counters"]["magnetize"], 8)
        self.assertEqual(r["gain"], {"atk": 32 + 256, "hp": 32 + 256})

    def test_golden_balinda_triples_the_trigger(self):
        r = simulate_growth(
            self.board() + [minion("Balinda Stonehearth", golden=True)],
            {"cast_spell": 4}, self.ENGINE)
        self.assertEqual(r["counters"]["magnetize"], 12)
        self.assertEqual(r["gain"], {"atk": 48 + 384, "hp": 48 + 384})

    def test_drakkari_doubles_the_end_of_turn_step(self):
        # Glambot step unchanged (16/16); the drone step doubles on the
        # 4-minion board: 4*2*2*(4/4)*4 = 256.
        r = simulate_growth(self.board(drakkari=True), {"cast_spell": 4},
                            self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 16 + 256, "hp": 16 + 256})

    def test_golden_glambot_doubles_its_buff(self):
        # A golden source doubles its per-trigger buff (4/4 -> 8/8) but the
        # magnetize COUNTER stays 4 (counters count triggers, not magnitude).
        r = simulate_growth([minion("Glambot", "MECHANICAL", golden=True),
                             minion("Utility Drone", "MECHANICAL")],
                            {"cast_spell": 4}, self.ENGINE)
        self.assertEqual(r["counters"]["magnetize"], 4)
        # glambot 4*4*2 = 32; drone 4*1*1*(4/4)*2 = 32.
        self.assertEqual(r["gain"], {"atk": 64, "hp": 64})

    def test_no_drone_no_downstream_gain(self):
        r = simulate_growth([minion("Glambot", "MECHANICAL")],
                            {"cast_spell": 4}, self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 16, "hp": 16})

    def test_copper_coil_fires_only_with_the_trinket(self):
        # magnetize=4 -> Copper Coil +1/+1 each, target scope 1.
        board = [minion("Glambot", "MECHANICAL"),
                 minion("Utility Drone", "MECHANICAL")]
        no = simulate_growth(board, {"cast_spell": 4}, self.ENGINE)
        yes = simulate_growth(board, {"cast_spell": 4,
                                      "trinkets": ["Copper Coil"]},
                              self.ENGINE)
        self.assertEqual(yes["gain"]["atk"] - no["gain"]["atk"], 4)
        self.assertEqual(yes["gain"]["hp"] - no["gain"]["hp"], 4)

    def test_zero_trigger_zero_gain(self):
        r = simulate_growth(self.board(), {"cast_spell": 0}, self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 0, "hp": 0})


class TestElementalsCompounding(unittest.TestCase):
    """elementals-stat-scaling: a standard tribe-scope step plus the
    compounding shop-eat step (cumulative trigger, eat_every payoff,
    Nomi as the buff_source)."""

    ENGINE = ENGINES["elementals-stat-scaling"]

    def board(self, nomi=False, golden_nomi=False):
        b = [minion("Unleashed Mana Surge", "ELEMENTAL"),
             minion("Flaming Enforcer", "ELEMENTAL")]
        if nomi:
            b.append(minion("Nomi, Kitchen Nightmare"))
        if golden_nomi:
            b.append(minion("Nomi, Kitchen Nightmare", golden=True))
        return b

    def test_tribe_scope_step_hand_computed(self):
        # play 3 this turn (9 cumulative): Mana Surge 3 triggers x (4/4) x
        # tribe scope (2 elementals) = +24/+24. Enforcer: cumulative 9,
        # eat_every 2 -> 4 eats, NO Nomi -> buff zero -> 4 eats x base 8
        # = +32/+32.
        r = simulate_growth(self.board(),
                            {"play_elemental": 3, "play_elemental_total": 9},
                            self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 24 + 32, "hp": 24 + 32})

    def test_nomi_buffs_the_eaten_tavern_minions(self):
        # buff (4/4) per play: eats j=1..4 pay 8 + 4*(2,4,6,8) stat points
        # each = (16+24+32+40) = 112.
        r = simulate_growth(self.board(nomi=True),
                            {"play_elemental": 3, "play_elemental_total": 9},
                            self.ENGINE)
        self.assertEqual(r["gain"]["atk"], 24 + 112)

    def test_golden_nomi_doubles_the_shop_buff(self):
        # golden buff (8/8): eats pay 8 + 8*(2,4,6,8) = 24,40,56,72 = 192.
        r = simulate_growth(self.board(golden_nomi=True),
                            {"play_elemental": 3, "play_elemental_total": 9},
                            self.ENGINE)
        self.assertEqual(r["gain"]["atk"], 24 + 192)

    def test_cumulative_defaults_to_primary_when_absent(self):
        # No *_total in the scenario: the compounding step falls back to
        # the per-turn count (3 -> 1 eat = base 8).
        r = simulate_growth(self.board(), {"play_elemental": 3}, self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 24 + 8, "hp": 24 + 8})

    def test_enforcer_absent_no_compounding(self):
        r = simulate_growth([minion("Unleashed Mana Surge", "ELEMENTAL")],
                            {"play_elemental": 3, "play_elemental_total": 9},
                            self.ENGINE)
        # 3 triggers x (4/4) x ONE tribe minion on board.
        self.assertEqual(r["gain"], {"atk": 12, "hp": 12})


class TestTribeScaling(unittest.TestCase):
    """beasts-beetles: Ravaging Scorpid — cumulative trigger count, else
    the ~once-per-minion-per-turn attack proxy; buffs land on tribe
    minions only."""

    ENGINE = ENGINES["beasts-beetles"]

    def board(self):
        return [minion("Ravaging Scorpid", "BEAST"),
                minion("Tasty Lobster", "BEAST"),
                minion("Brann Bronzebeard")]

    def test_cumulative_count_used(self):
        # 4 attacks x (5/5) x 2 beasts = +40/+40.
        r = simulate_growth(self.board(), {"attack": 1, "attack_total": 4},
                            self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 40, "hp": 40})

    def test_attack_proxy_fallback(self):
        # No trigger count in the scenario: n = len(board) * turns.
        r = simulate_growth(self.board(), {"turns": 2}, self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 60, "hp": 60})

    def test_no_source_no_gain(self):
        r = simulate_growth([minion("Tasty Lobster", "BEAST")],
                            {"attack_total": 4}, self.ENGINE)
        self.assertEqual(r["gain"], {"atk": 0, "hp": 0})


if __name__ == "__main__":
    unittest.main()