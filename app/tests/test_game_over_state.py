"""The card a finished game leaves behind.

Field report, 2026-10-04: "I just played a game and the coaching stopped before
the end. But it appears the app was still running." Both halves were true and
neither was a fault — the coach had advised through the whole final buy phase
(turn 15), shared the complete game (268 advisories, 268 in the cloud) and
stopped exactly when combat began, because there is no shop to advise on — and
the app was still tailing for the next game.

What was wrong is what the player was looking at. The end of a game fell back to
the FIRST-RUN card, the same one a fresh install shows ("Waiting for your next
buy phase…"), so "the game ended" and "the coach died" were the same screen. The
only thing that told them apart was the console.

So these tests pin the two states apart: the first-run card keeps its log.config
steps, the end-of-game card names what happened and says the coach is still
there. A pure function builds the sentence, because the alternative is a test
that reads copy by eye.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import coach_ui  # noqa: E402


def _payload(**kw):
    return json.loads(coach_ui.welcome_payload(**kw))


class TestTheTwoStates(unittest.TestCase):
    def test_a_first_run_card_is_not_a_game_over_card(self):
        card = _payload()
        self.assertTrue(card["welcome"])
        self.assertNotIn("game_over", card)
        self.assertNotIn("title", card)
        # the first-run card is where the log.config block lives
        self.assertIn("steps", card)
        self.assertIn("hint", card)

    def _after_game_over(self, analysis=None, placement=None):
        """Run the real entry point and read the card it published.

        `show_game_over` writes global state (it IS the live transition), so the
        previous payload goes back afterwards — a test that left the coach in a
        game-over state would be felt by every test that runs after it.
        """
        before = (coach_ui._state.payload, coach_ui._state.etag,
                  coach_ui._state.analysis)
        self.addCleanup(self._restore, before)
        coach_ui.show_game_over(analysis, placement=placement)
        return json.loads(coach_ui._state.payload)

    @staticmethod
    def _restore(before):
        payload, etag, analysis = before
        coach_ui._state.payload, coach_ui._state.etag = payload, etag
        coach_ui._state.analysis = analysis

    def test_the_games_own_placement_beats_the_last_advisorys_standing(self):
        """`show_game_over` is handed the placement the coach resolved from the
        log's own tag, and it must win over the analysis's `current_place`.

        Measured 2026-10-07: the analysis is the LAST ADVISORY, taken before the
        final fight resolves, so on the 2026-10-06 13:00 game it carried 4 while
        the game reports 3. The card read "4th" for a 3rd-place finish, and the
        shared report would have carried the same wrong number.
        """
        card = self._after_game_over({"current_place": 4, "turn": 14},
                                     placement=3)
        self.assertEqual(card["game_over"]["placement"], 3)
        self.assertIn("3rd", card["tagline"])
        self.assertNotIn("4th", card["tagline"])

    def test_without_a_log_placement_the_standing_is_still_used(self):
        """The exit backstop has no coach to ask, so the fallback has to work."""
        card = self._after_game_over({"current_place": 4, "turn": 14})
        self.assertEqual(card["game_over"]["placement"], 4)

    def test_a_game_over_card_names_the_game_and_stays_a_card(self):
        card = _payload(game_over={"placement": 3, "turn": 15})
        self.assertTrue(card["welcome"], "the page draws cards from this flag")
        self.assertEqual(card["title"], "Game over")
        self.assertEqual(card["game_over"]["placement"], 3)
        self.assertIn("3rd", card["tagline"])
        self.assertIn("Round 15", card["tagline"])

    def test_a_game_over_card_drops_the_first_run_instructions(self):
        """log.config steps after a game are noise at best, and they were half
        the reason the card read like a fresh install."""
        card = _payload(game_over={"placement": 3})
        self.assertNotIn("steps", card)
        self.assertNotIn("hint", card)

    def test_a_game_over_card_says_the_coach_is_still_running(self):
        card = _payload(game_over={"placement": 3})
        self.assertIn("still running", card["status"])
        self.assertIn("next shop", card["status"])

    def test_consent_is_still_reachable_from_the_end_of_a_game(self):
        """The card is the only place the sharing answer can be changed."""
        card = _payload(game_over={"placement": 3})
        self.assertIn("share", card)
        self.assertIn("privacy", card)

    def test_only_the_fields_we_have_are_carried(self):
        card = _payload(game_over={"placement": None, "turn": None,
                                   "health": None, "tier": None})
        self.assertEqual(card["game_over"], {},
                         "absent is better than a null the page must special-case")


class TestTheSentence(unittest.TestCase):
    def test_each_placement_reads_as_english(self):
        """A Battlegrounds lobby seats eight, so 1st-8th is the whole reachable
        range — the four line above it are not hypothetical here."""
        cases = {1: "First place", 2: "You placed 2nd", 3: "You placed 3rd",
                 4: "You placed 4th", 5: "You placed 5th",
                 6: "You placed 6th", 7: "You placed 7th",
                 8: "You placed 8th"}
        for place, expected in cases.items():
            with self.subTest(place=place):
                self.assertIn(expected, coach_ui._game_over_line(
                    {"placement": place}))

    def test_the_ordinal_helper_is_right_beyond_a_lobby_too(self):
        """Only 1st-8th can reach a card, but the helper is general, and a
        "11st" is the kind of wrong that reads as mockery. (The first version of
        this test asserted 11th/21st reach the CARD, which cannot happen: the
        card falls back for anything outside the eight seats.)"""
        self.assertEqual(coach_ui._ordinal(11), "11th")
        self.assertEqual(coach_ui._ordinal(21), "21st")
        self.assertEqual(coach_ui._ordinal(1), "1st")
        self.assertEqual(coach_ui._ordinal(8), "8th")

    def test_a_missing_placement_still_says_something_true(self):
        for missing in ({}, {"placement": None}, {"placement": "3"},
                        {"placement": 11}, {"placement": 99}):
            with self.subTest(missing=missing):
                line = coach_ui._game_over_line(missing)
                self.assertIn("finished", line)
                self.assertNotIn("None", line)

    def test_the_round_is_added_only_when_known(self):
        self.assertNotIn("Round", coach_ui._game_over_line({"placement": 2}))
        self.assertIn("Round 9", coach_ui._game_over_line({"placement": 2,
                                                           "turn": 9}))


class TestWhatThePageActuallyGets(unittest.TestCase):
    """Through the response the overlay polls, not the function it calls."""

    def tearDown(self):
        coach_ui.clear_analysis()

    def test_the_end_of_a_game_serves_the_game_over_card(self):
        coach_ui.update_analysis({"board": [], "current_place": 3, "turn": 15,
                                  "health": 10, "tier": 6, "gold": 0,
                                  "scenario": {"turns": 15}, "sell_rank": [],
                                  "cards": {}})
        self.assertIsNotNone(coach_ui.latest_analysis())

        coach_ui.show_game_over(coach_ui.latest_analysis())

        served = json.loads(coach_ui._analysis_response()[2])
        self.assertEqual(served["title"], "Game over")
        self.assertEqual(served["game_over"]["placement"], 3)
        self.assertIsNone(coach_ui.latest_analysis(),
                          "the finished game's plan is still in memory")

    def test_it_survives_never_having_advised(self):
        """A coach attached to a finished session knows none of it."""
        coach_ui.show_game_over(None)
        served = json.loads(coach_ui._analysis_response()[2])
        self.assertEqual(served["title"], "Game over")
        self.assertEqual(served["game_over"], {})
        self.assertIn("finished", served["tagline"])

    def test_the_page_draws_the_title_when_there_is_one(self):
        """Pinned by reading the served script: the h1 has to prefer `title`,
        or the end-of-game card is headed "Bob's Ledger" and the two states are
        the same screen again."""
        self.assertIn("a.title ||", coach_ui._HTML)


if __name__ == "__main__":
    unittest.main()
