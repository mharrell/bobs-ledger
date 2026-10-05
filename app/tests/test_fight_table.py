"""The fight table: the join that turns logged fights into labelled examples.

Two things here are easy to get silently wrong and were both wrong in the first
draft, so they are pinned:

  * WHICH fight a row describes. The advice at buy phase k is about the fight
    that has NOT happened yet, but the snapshots that exist at that moment
    describe the PREVIOUS one. Joining during the pass attached the wrong
    fight to every row; the join now happens after the game is fed, against
    bucket k+1.
  * WHICH snapshot of a turn is the opponent's board. Combat reveals their
    board progressively and deaths empty it, so the fullest view is the honest
    estimate — `_resolve_boards`' own rule.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fight_table


def m(player, card, atk, hp, golden=False, kw=()):
    """A snapshot minion: the 6-tuple the widened projection now stores."""
    return (player, card, atk, hp, golden, tuple(kw))


class FakeCoach:
    def __init__(self, snaps):
        self._snap_by_turn = snaps


class TestTheirBoard(unittest.TestCase):
    def test_picks_the_fullest_combat_snapshot(self):
        # combat reveals progressively and deaths empty it: the most opponent
        # presence is the honest estimate, not the first or the last
        coach = FakeCoach({3: [
            {"phase": "combat", "minions": [m(9, "A", 1, 1)]},
            {"phase": "combat", "minions": [m(9, "A", 5, 5),
                                            m(9, "B", 5, 5),
                                            m(1, "MINE", 9, 9)]},
            {"phase": "combat", "minions": [m(9, "A", 2, 2)]},
        ]})
        got = fight_table._their_board(coach, 3, friendly=1)
        self.assertEqual(len(got), 2)
        self.assertEqual({g["card"] for g in got}, {"A", "B"})
        self.assertEqual(sum(g["atk"] + g["health"] for g in got), 20)

    def test_our_own_minions_are_never_theirs(self):
        coach = FakeCoach({2: [
            {"phase": "combat", "minions": [m(1, "MINE", 50, 50),
                                            m(9, "THEIRS", 1, 1)]},
        ]})
        got = fight_table._their_board(coach, 2, friendly=1)
        self.assertEqual([g["card"] for g in got], ["THEIRS"])

    def test_keywords_ride_along(self):
        # the whole point of the widening: a scalar total cannot see these
        coach = FakeCoach({4: [
            {"phase": "combat", "minions": [
                m(9, "A", 1, 1, kw=("DIVINE_SHIELD", "REBORN"))]},
        ]})
        got = fight_table._their_board(coach, 4, friendly=1)
        self.assertEqual(got[0]["keywords"], ["DIVINE_SHIELD", "REBORN"])

    def test_buy_phase_snapshots_are_the_fallback(self):
        # a turn that staged nothing in combat still has buy-phase snapshots
        # (shop plays) — better than reporting no board at all
        coach = FakeCoach({5: [
            {"phase": "buy", "minions": [m(9, "A", 3, 3)]},
        ]})
        got = fight_table._their_board(coach, 5, friendly=1)
        self.assertEqual([g["card"] for g in got], ["A"])

    def test_no_snapshots_is_empty_not_an_error(self):
        self.assertEqual(fight_table._their_board(FakeCoach({}), 9, 1), [])


class TestFightOutcomes(unittest.TestCase):
    """The outcome label, read from the LOG rather than from the coach.

    Every number in Check A rests on this, and the first version of the tool
    got it wrong by joining the coach's own `_predamage_turns` bucket. That
    bucket is stamped when the stat log drains, so it SLIDES for turns that
    arrive before the hero parses (`_stat_pending`) — producing a table where
    11 of 24 "losses" showed no damage, i.e. the label and the damage described
    different fights.
    """

    HERO = 106
    GS = "D 12:00:00.0000000 GameState.DebugPrintPower() - "

    def _log(self, armor_before=None, armor_after=None, damage_after=None,
             predamage=False):
        """Two buy phases with one combat window between them."""
        gs = self.GS
        lines = []
        if armor_before is not None:
            lines.append(f"{gs}TAG_CHANGE Entity={self.HERO} "
                         f"tag=ARMOR value={armor_before}")
        lines.append(f"{gs}Entity=GameEntity tag=STEP value=MAIN_ACTION")  # t1
        lines.append(f"{gs}Entity=GameEntity tag=STEP value=MAIN_END")
        if predamage:
            lines.append(f"{gs}TAG_CHANGE Entity={self.HERO} "
                         f"tag=PREDAMAGE value=10")
            lines.append(f"{gs}TAG_CHANGE Entity={self.HERO} "
                         f"tag=PREDAMAGE value=0")
        if armor_after is not None:
            lines.append(f"{gs}TAG_CHANGE Entity={self.HERO} "
                         f"tag=ARMOR value={armor_after}")
        if damage_after is not None:
            lines.append(f"{gs}TAG_CHANGE Entity={self.HERO} "
                         f"tag=DAMAGE value={damage_after}")
        lines.append(f"{gs}Entity=GameEntity tag=STEP value=MAIN_ACTION")  # t2
        return [ln + "\n" for ln in lines] + ["D 12:00:01.0 X - filler\n"]

    def test_damage_taken_is_a_loss(self):
        o = fight_table.fight_outcomes(
            self._log(damage_after=9, predamage=True), self.HERO)
        self.assertTrue(o[1]["lost"])
        self.assertEqual(o[1]["damage"], 9)
        self.assertFalse(o[1]["tie"])

    def test_predamage_with_no_damage_is_a_tie_not_a_loss(self):
        # the winner takes 0 and so does a tie, so predamage alone cannot tell
        # them apart — which is why `lost` reads the health writes instead
        o = fight_table.fight_outcomes(self._log(predamage=True), self.HERO)
        self.assertFalse(o[1]["lost"])
        self.assertEqual(o[1]["damage"], 0)
        self.assertTrue(o[1]["tie"])

    def test_clean_win_is_neither_lost_nor_tie(self):
        o = fight_table.fight_outcomes(self._log(), self.HERO)
        self.assertFalse(o[1]["lost"])
        self.assertFalse(o[1]["tie"])

    def test_armor_absorbing_the_hit_still_counts(self):
        # Armor goes before HP, so a lost fight can strip ARMOR and leave true
        # HP untouched. Ignoring armor read 15 of 24 losses as "no damage";
        # the code's own rule is "a won combat never drops health+armor".
        o = fight_table.fight_outcomes(
            self._log(armor_before=10, armor_after=6), self.HERO)
        self.assertTrue(o[1]["lost"])
        self.assertEqual(o[1]["damage"], 4)      # 10 armor -> 6 armor


class TestVerdict(unittest.TestCase):
    def test_reads_the_shipped_strings(self):
        self.assertEqual(fight_table.verdict_of(
            "favored — 121 vs ~40 (yours: 2 divine shields)"), "favored")
        self.assertEqual(fight_table.verdict_of(
            "close fight — 136 vs ~125, seen 1 round ago"), "close fight")
        self.assertEqual(fight_table.verdict_of(
            "behind — 60 vs ~200; don't take this fight"), "behind")
        self.assertEqual(fight_table.verdict_of(
            "ahead on paper — 300 vs ~40"), "ahead on paper")

    def test_none_when_absent(self):
        self.assertIsNone(fight_table.verdict_of(None))
        self.assertIsNone(fight_table.verdict_of(""))


class TestBaselineReport(unittest.TestCase):
    """The Check A numbers, on a hand-computed fixture.

    The point of the report is the LOSS RATE per verdict, so a class whose
    ordering is inverted must show up as inverted.
    """

    def _rows(self):
        rows = []
        # favored: 3 advisories, 1 lost
        for lost in (False, False, True):
            rows.append({"session": "s", "game": 1, "lost": lost,
                         "fresh": False,
                         "forecast": "favored — 300 vs ~100"})
        # behind: 2 advisories, 2 lost (should be the WORST, not the best)
        for lost in (True, True):
            rows.append({"session": "s", "game": 1, "lost": lost,
                         "fresh": False,
                         "forecast": "behind — 50 vs ~300"})
        return rows

    def test_counts_and_rates(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fight_table.baseline_report(self._rows())
        out = buf.getvalue()
        self.assertIn("favored", out)
        self.assertIn("33%", out)      # 1 of 3
        self.assertIn("100%", out)     # 2 of 2
        # the constant baseline is reported beside the accuracy, so a rule
        # that beats nothing cannot look good
        self.assertIn("guessing 'not lost'", out)

    def test_ignores_rows_without_a_label(self):
        import io
        import contextlib
        rows = self._rows() + [{"session": "s", "game": 1, "lost": None,
                                "fresh": False, "forecast": "favored"}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fight_table.baseline_report(rows)
        self.assertIn("5 advisories with an outcome label", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
