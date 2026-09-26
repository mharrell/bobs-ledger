"""Play steps that execute into a full board must NAME their sell victim.

The 2026-09-26 E.T.C. game: the plan queued three plays from board 5 and the
third executed into a full board with no sell named at all (hand_plan's
plan-time len(board) check only saw 5). The projection in
value._name_sell_victims names the victim from the same sell_rank the Sell
box uses — the 2026-09-03 audit's "16 of 34 said 'sell to make room' without
naming a card" finding, closed for the hand-deploy queue.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value  # noqa: E402


class TestNamedSellVictims(unittest.TestCase):
    def test_third_play_from_board_five_names_the_sell(self):
        entries = [{"verb": "play", "card": "A", "name": "K'Thir", "why": None},
                   {"verb": "play", "card": "B", "name": "Gearfin", "why": None},
                   {"verb": "cast", "card": "C", "name": "Chamber", "why": None},
                   {"verb": "play", "card": "D", "name": "Recruiter", "why": None}]
        out = value._name_sell_victims(entries, 5, [("BG36_114", 0.5)],
                                       {"BG36_114": "Parasitic Fleshling"})
        self.assertNotIn("sell", (out[0]["why"] or ""))
        self.assertEqual(out[3]["why"],
                         "board is full — sell Parasitic Fleshling first")

    def test_already_full_board_replaces_the_unnamed_clause(self):
        entries = [{"verb": "play", "card": "A", "name": "X",
                    "why": "triples golden! — sell to make room"}]
        out = value._name_sell_victims(entries, 7, [("BG36_114", 0.5)],
                                       {"BG36_114": "Parasitic Fleshling"})
        self.assertEqual(out[0]["why"],
                         "triples golden! — sell Parasitic Fleshling first")

    def test_no_sell_rank_stays_unnamed(self):
        entries = [{"verb": "play", "card": "A", "name": "X",
                    "why": "board is full — sell to make room"}]
        out = value._name_sell_victims(entries, 7, [], {})
        self.assertEqual(out[0]["why"], "board is full — sell to make room")


if __name__ == "__main__":
    unittest.main()
