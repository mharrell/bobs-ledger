"""Regression tests for the 36.6.1 discard / Deity mechanic.

Three things are under test, and the distinction matters:

1. **The engine chain** (`meta/engines.json` -> `aberrations-discard-deity`) —
   every magnitude hand-computed from the card text quoted in its `note`
   fields.
2. **Outlet recognition by CARD TEXT** — an outlet is a card whose own printed
   ability is `Activate (N): Discard a card ...`. Cards that merely mention
   discard (the "discard this and it casts twice" spells, the
   "whenever you discard" payoffs, Mysterious K'Thir's self-discard) must NOT
   count, or the modelled discard rate would inflate.
3. **The value seam** (`value._discard_fuel_bonus` into `shop_ranking`) —
   the marginal per-discard growth credited to an outlet card in the shop.

NOTHING here is measured from a game: no Power.log records a discard event, so
the discard RATE is a model (one discard per outlet per turn). See
analysis/discard_mechanic.md for the log evidence and every assumption.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value
from simulate_growth import _load_engines, simulate_growth

ENGINE = _load_engines()["aberrations-discard-deity"]

# Real card ids (meta/minions.json) so the tests exercise the same id -> text
# lookups the coach uses.
GHURSHA = "BG36_097"     # Mindbender Ghur'sha    3/9  Aberration
KTHIR = "BG36_106"       # Cutthroat K'Thir       4/4  Aberration
APHLASS = "BGFYM_005"    # Harbinger Aph'lass     3/6  Aberration
ROTTER = "BG36_099"      # Brain Rotter           3/4  Aberration (outlet)
SAPPER = "BG36_103"      # N'raqi Sapper          6/3  Aberration
ENVOY = "BG36_311"       # Abyssal Envoy          3/4  Aberration (outlet)
BANDIT = "BG28_582"      # Mangled Bandit         3/3  Quilboar   (outlet)
RECRUITER = "BG36_312"   # Mindbending Recruiter  6/2  Aberration (outlet)
FROSTCALLER = "BG36_300"  # N'raqi Frostcaller    6/3  Aberration (outlet)
MYSTKTHIR = "BG36_320"   # Mysterious K'Thir      8/8  Aberration
SACRIFICE = "BG36_113"   # Drifting Sacrifice     2/1  Aberration
CONVERTER = "BG36_318"   # Faceless Converter     5/5  Aberration
TITUS = "BG25_354"       # Titus Rivendare        1/7  All (multiplier)

_STATS = {GHURSHA: (3, 9), KTHIR: (4, 4), APHLASS: (3, 6), ROTTER: (3, 4),
          SAPPER: (6, 3), ENVOY: (3, 4), BANDIT: (3, 3), RECRUITER: (6, 2),
          FROSTCALLER: (6, 3), MYSTKTHIR: (8, 8), SACRIFICE: (2, 1),
          CONVERTER: (5, 5), TITUS: (1, 7)}
_TRIBE = {BANDIT: "Quilboar", TITUS: "All"}


def board(*cards):
    """A board snapshot from card ids (stats from the DB, tribe defaulted)."""
    out = []
    for cid in cards:
        atk, hp = _STATS[cid]
        out.append({"card": cid, "atk": atk, "health": hp,
                    "tribe": _TRIBE.get(cid, "Aberration")})
    return out


def sim(cards, scenario):
    """Run the discard engine the way value.py does: names resolved from the
    BG pool (simulate_growth matches engine pieces by name)."""
    names = value._load_bg_names()
    b = [dict(m, name=names.get(m["card"], "")) for m in board(*cards)]
    return simulate_growth(b, scenario, ENGINE)


def points(result):
    return value._sim_points(result)


class TestDiscardEngineChain(unittest.TestCase):
    """The chain, hand-computed (meta/engines.json notes are the source)."""

    def test_zero_with_no_discards(self):
        """No trigger, no growth — and no Deity pool either."""
        r = sim((GHURSHA, KTHIR, ROTTER, SAPPER), {"discard": 0})
        self.assertEqual(r["gain"], {"atk": 0, "hp": 0})
        self.assertEqual(r["deity"]["atk"], 0)
        self.assertEqual(r["deity"]["realised"], {"atk": 0, "hp": 0})

    def test_golden_chain_hand_computed(self):
        """Five Aberrations, 2 discards, both discard trinkets — by hand.

        Mindbender Ghur'sha 3+3 x 2 discards x 5 minions    = +30/+30
        Cutthroat K'Thir    4+4 x 2 discards x target(1)    =  +8/ +8
        Hammer of Twilight  2/+1 x 2 discards x 5 minions   = +20/+10
          -> gain +58/+48 (the board's PERSISTENT stats)
        Deity pool: K'Thir 4/4 x2 = 8/8; Rotter min(1 copy, 2 discards) x2/2
                    = 2/2; Aph'lass 1/1 x2 = 2/2; Sapper min(1, 2) x14/14
                    = 14/14; Baton min(1 trinket, 2 discards) x4/4 = 4/4
                    -> +30/+30 banked
        Awakening: 1 (an Aberration is on the board) x payoff_share 0.5
                    -> realised +15/+15, which is NOT part of `gain`
        """
        r = sim((GHURSHA, KTHIR, APHLASS, ROTTER, SAPPER),
                {"discard": 2, "trinkets": ["Hammer of Twilight",
                                            "Corrupted Baton"]})
        self.assertEqual(r["gain"], {"atk": 58, "hp": 48})
        self.assertEqual(r["deity"]["atk"], 30)
        self.assertEqual(r["deity"]["hp"], 30)
        self.assertEqual(r["deity"]["awakenings"], 1)
        self.assertEqual(r["deity"]["realised"], {"atk": 15.0, "hp": 15.0})
        self.assertEqual(r["deity_breakdown"]["Brain Rotter"], (2, 2))
        self.assertEqual(r["deity_breakdown"]["N'raqi Sapper"], (14, 14))

    def test_more_discards_grow_the_engine(self):
        """Monotone in the discard count: 1 < 2 < 3."""
        totals = [points(sim((GHURSHA, KTHIR, ROTTER), {"discard": n}))
                  for n in (0, 1, 2, 3)]
        self.assertEqual(totals[0], 0.0)
        self.assertLess(totals[0], totals[1])
        self.assertLess(totals[1], totals[2])
        self.assertLess(totals[2], totals[3])
        # discard=1: Ghur'sha 1x3x3=+9/+9, K'Thir 4/4, pool 6/6 -> 3/3 realised
        self.assertAlmostEqual(totals[1], 18 + 8 + 1.5, places=2)
        # discard=2: Ghur'sha 2x3x3=+18/+18, K'Thir 8/8, pool 10/10 -> 5/5
        self.assertAlmostEqual(totals[2], 36 + 16 + 2.5, places=2)

    def test_outlet_own_discards_are_capped_by_the_turn(self):
        """Brain Rotter's Activate power is once per turn (count_from "self").

        One copy with 3 discards available still banks ONE +2/+2 — the other
        discards come from other outlets, which don't buff the Deity.
        """
        one = sim((ROTTER,), {"discard": 3})
        self.assertEqual(one["deity"]["atk"], 2)
        self.assertEqual(one["deity"]["hp"], 2)
        none = sim((ROTTER,), {"discard": 0})
        self.assertEqual(none["deity"]["atk"], 0)
        two = sim((ROTTER, ROTTER), {"discard": 3})
        self.assertEqual(two["deity"]["atk"], 4)  # min(2 copies, 3 discards)

    def test_deity_pool_is_never_board_gain(self):
        """The Deity's stats are per-combat: they must not enter `gain`."""
        r = sim((ROTTER, ENVOY, SACRIFICE), {"discard": 2})
        self.assertEqual(r["gain"], {"atk": 0, "hp": 0})
        self.assertGreater(r["deity"]["atk"], 0)

    def test_deity_gated_on_an_aberration_on_the_board(self):
        """Three sacrifices need Aberrations to die; no Aberration, no payoff.

        The pool still accumulates (the cards bank it), but nothing is realised
        — which is what keeps the pool out of the board's stats.
        """
        aberrations = sim((ROTTER, SAPPER), {"discard": 1})
        self.assertEqual(aberrations["deity"]["awakenings"], 1)
        self.assertGreater(aberrations["deity"]["realised"]["atk"], 0)
        no_aberration = simulate_growth(
            [{"card": ROTTER, "name": "Brain Rotter", "atk": 3, "health": 4,
              "tribe": "BEAST"},
             {"card": SAPPER, "name": "N'raqi Sapper", "atk": 6, "health": 3,
              "tribe": "BEAST"}],
            {"discard": 1}, ENGINE)
        self.assertEqual(no_aberration["deity"]["awakenings"], 0)
        self.assertEqual(no_aberration["deity"]["realised"], {"atk": 0, "hp": 0})
        self.assertEqual(no_aberration["deity"]["atk"],
                         aberrations["deity"]["atk"])

    def test_mysterious_kthir_discards_without_an_outlet(self):
        """Its own end-of-turn discard is self-contained (count_from "turn")."""
        r = sim((MYSTKTHIR,), {"discard": 0})
        self.assertEqual(r["counters"]["primary"], 0)
        self.assertEqual(r["gain"], {"atk": 24, "hp": 24})  # +8/+8 x printed 3

    def test_hammer_of_twilight_needs_the_trinket(self):
        no = sim((GHURSHA, ROTTER), {"discard": 1})
        yes = sim((GHURSHA, ROTTER),
                  {"discard": 1, "trinkets": ["Hammer of Twilight"]})
        self.assertEqual(no["gain"], {"atk": 6, "hp": 6})
        # + one printed +2/+1 application per discard across 2 minions.
        self.assertEqual(yes["gain"], {"atk": 10, "hp": 8})

    def test_corrupted_baton_needs_the_trinket(self):
        no = sim((ROTTER,), {"discard": 1})
        yes = sim((ROTTER,), {"discard": 1, "trinkets": ["Corrupted Baton"]})
        self.assertEqual(yes["deity"]["atk"] - no["deity"]["atk"], 4)


class TestDiscardOutlets(unittest.TestCase):
    """Outlet recognition reads the card's text — narrow on purpose."""

    OUTLETS = (ROTTER, ENVOY, BANDIT, RECRUITER, FROSTCALLER)

    def test_activate_discard_cards_are_outlets(self):
        db = value._load_card_db()
        for cid in self.OUTLETS:
            self.assertTrue(value._is_discard_outlet(db[cid]),
                            f"{db[cid]['name']} should be an outlet")

    def test_mentioning_discard_is_not_an_outlet(self):
        """The three shapes that mention discard without spending it."""
        db = value._load_card_db()
        spells = value._load_spell_db()
        pure_mentions = [
            KTHIR,        # "Whenever you discard a card, give this and ..."
            GHURSHA,      # "Whenever you discard a card, give your other ..."
            APHLASS,      # counter/payoff
            MYSTKTHIR,    # "discard your 3 left-most Tavern spells" (own, EOT)
            "BG36_114",   # Parasitic Fleshling: "improved by each card
                          # you've discarded this game!"
            "BG36_100",   # Wandering Willbreaker: "when you play one, discard
                          # the other"
            "BG36_308",   # Faceless Operative: same pair shape
        ]
        for cid in pure_mentions:
            self.assertFalse(value._is_discard_outlet(db[cid]),
                             f"{db[cid]['name']} only MENTIONS discard")
        for cid in ("BG36_371", "BG36_301t", "BG36_303"):
            self.assertIn("discard", spells[cid]["text"].lower())
            self.assertFalse(value._is_discard_outlet(spells[cid]),
                             f"{spells[cid]['name']} wants to be discarded")

    def test_printed_shapes(self):
        self.assertTrue(value._is_discard_outlet(
            {"text": "Activate (1): Discard a card to gain 2 Gold."}))
        self.assertTrue(value._is_discard_outlet(
            {"text": "Taunt. Activate (0): Discard a card, then draw."}))
        self.assertFalse(value._is_discard_outlet(
            {"text": "If you discard this, cast it twice."}))
        self.assertFalse(value._is_discard_outlet({"text": ""}))
        self.assertFalse(value._is_discard_outlet(None))

    def test_board_outlets_are_counted_per_copy(self):
        b = board(ROTTER, ROTTER, ENVOY, KTHIR, MYSTKTHIR)
        self.assertEqual(value._discard_outlets(b),
                         [ROTTER, ROTTER, ENVOY])
        self.assertEqual(len(value._discard_outlets(board(KTHIR, GHURSHA))), 0)

    def test_outlet_set_is_reviewed_when_the_pool_changes(self):
        """Guard: the DB's Activate-discard cards are a known, reviewed set.

        A 36.6.1+ patch that adds another one must update this list (and the
        model's outlet-per-turn rate) rather than silently changing the
        modelled discard count.
        """
        found = {cid for cid, c in value._load_card_db().items()
                 if value._is_discard_outlet(c)}
        self.assertEqual(found, set(self.OUTLETS))


class TestDiscardScenario(unittest.TestCase):
    """The discard RATE is board-derived, never a magic constant."""

    def test_default_scenario_leaves_discard_to_the_board(self):
        self.assertEqual(value._DEFAULT_SCENARIO["discard"], 0)
        self.assertEqual(value._scenario_for_engine(ENGINE, [], {})["discard"], 0)

    def test_derived_from_the_outlets_on_the_board(self):
        self.assertEqual(
            value._discard_scenario(board(ROTTER, GHURSHA))["discard"], 1)
        self.assertEqual(
            value._discard_scenario(board(ROTTER, ENVOY, BANDIT))["discard"], 3)
        self.assertEqual(
            value._discard_scenario(board(GHURSHA, KTHIR))["discard"], 0)

    def test_explicit_scenario_wins(self):
        """The only way to count sources the board cannot show (hero powers,
        held cards, trinkets)."""
        sc = value._discard_scenario(board(ROTTER), {"discard": 5})
        self.assertEqual(sc["discard"], 5)

    def test_other_engines_keep_the_tunable_default(self):
        cast = _load_engines()["mechs-magnetics-spells"]
        sc = value._scenario_for_engine(cast, board(ROTTER), {})
        self.assertEqual(sc, {"cast_spell": 4})


class TestDiscardFuelBonus(unittest.TestCase):
    """The marginal value of one more discard per turn."""

    def setUp(self):
        self.names = value._load_bg_names()
        self.engine_board = board(GHURSHA, ROTTER, KTHIR, SAPPER)

    def test_empty_board_zero(self):
        self.assertEqual(value._discard_fuel_bonus([], self.names), 0.0)

    def test_board_with_no_engine_pieces_zero(self):
        """No outlet, no payoff, no trinket: nothing to fuel."""
        self.assertEqual(
            value._discard_fuel_bonus(board(TITUS), self.names), 0.0)
        self.assertEqual(
            value._discard_fuel_bonus(board(SACRIFICE, CONVERTER),
                                      self.names), 0.0)

    def test_golden_marginal_value_one_outlet(self):
        """Hand-computed: the delta from 1 discard a turn to 2.

        discard=1: Ghur'sha 1x3x4=+12/+12, K'Thir +4/+4, pool 10/10 -> 5/5
                   = 24 + 8 + (5+5)*W_DEITY_COMBAT = 37.0 points
        discard=2: Ghur'sha 2x3x4=+24/+24, K'Thir +8/+8, pool 14/14 -> 7/7
                   = 48 + 16 + (7+7)*W_DEITY_COMBAT = 70.0 points
        marginal  = 33.0 board-stat-equivalent points.
        """
        self.assertEqual(
            value._discard_scenario(self.engine_board)["discard"], 1)
        self.assertAlmostEqual(
            value._discard_fuel_bonus(self.engine_board, self.names), 33.0,
            places=2)

    def test_more_outlets_more_total_growth(self):
        """A second outlet raises both the engine's output and the marginal."""
        two = board(GHURSHA, ROTTER, KTHIR, SAPPER, ENVOY)
        self.assertEqual(value._discard_scenario(two)["discard"], 2)
        one_delta = value._discard_fuel_bonus(self.engine_board, self.names)
        two_delta = value._discard_fuel_bonus(two, self.names)
        self.assertGreater(two_delta, 0)
        self.assertGreater(two_delta, one_delta)
        # ...and the engine really is producing more at 2 discards than at 1.
        total = [points(sim((GHURSHA, ROTTER, KTHIR, SAPPER), {"discard": n}))
                 for n in (1, 2, 3)]
        self.assertLess(total[0], total[1])
        self.assertLess(total[1], total[2])

    def test_no_double_count_of_the_deity_pool(self):
        """The fuel counts the pool once, discounted — never at board weight."""
        r = sim((ROTTER, SAPPER), {"discard": 1})
        pool = r["deity"]["realised"]["atk"] + r["deity"]["realised"]["hp"]
        gain = r["gain"]["atk"] + r["gain"]["hp"]
        self.assertEqual(gain, 0)
        self.assertAlmostEqual(points(r), value.W_DEITY_COMBAT * pool,
                               places=2)
        self.assertLess(value.W_DEITY_COMBAT, value.W_DISCARD_FUEL)


class TestDiscardShopSeam(unittest.TestCase):
    """The one integration seam: shop_ranking, where the spell fuel term lives."""

    def setUp(self):
        self.names = value._load_bg_names()
        # Ghur'sha (payoff) + Sapper (a Deity feeder) — no outlet on the board,
        # so the next outlet is the FIRST one and still worth its marginal.
        self.engine_board = board(GHURSHA, SAPPER)
        self.plain_board = board(TITUS)

    def test_outlet_card_is_credited_the_marginal_fuel(self):
        with_engine = dict(value.shop_ranking([ROTTER], {}, self.engine_board))
        without = dict(value.shop_ranking([ROTTER], {}, self.plain_board))
        expected = value.W_DISCARD_FUEL * value._discard_fuel_bonus(
            self.engine_board, self.names)
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(with_engine[ROTTER] - without[ROTTER],
                               expected, places=2)

    def test_card_that_merely_mentions_discard_gets_nothing(self):
        with_engine = dict(value.shop_ranking([KTHIR], {}, self.engine_board))
        without = dict(value.shop_ranking([KTHIR], {}, self.plain_board))
        self.assertAlmostEqual(with_engine[KTHIR], without[KTHIR], places=2)

    def test_engine_pieces_are_credited_comp_independently(self):
        """No Aberration comp exists in comps.json (by design) — the engine must
        still be reachable from a board, which is what _engine_growth_bonus and
        _discard_fuel_bonus give us."""
        bonus = value._engine_growth_bonus(board(GHURSHA, ROTTER), self.names)
        self.assertGreater(bonus.get(GHURSHA, 0), 0)
        self.assertGreater(bonus.get(ROTTER, 0), 0)


if __name__ == "__main__":
    unittest.main()
