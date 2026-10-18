"""Summoned tokens are named, and never sneak into the draftable pool.

2026-10-17, the maintainer's report: "Sells aren't being counted totally
correctly... you can't sell spells" turned up a second row in the same list — the
raw id `BGS_115t`, because nothing in the program knew that card. It is
Sellemental's Water Droplet, a MINION that is never in the tavern, so the pool
(`meta/minions.json`) excludes it on purpose: a token in the pool would be
offered as a draftable buy.

`meta/tokens.json` is the table that fixes that without the side effect. These
tests hold the two halves together — a token must be NAMEABLE, and it must stay
out of the pool.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import meta            # noqa: E402
import player_actions  # noqa: E402
import value           # noqa: E402


class TestTheTokenTable(unittest.TestCase):

    def test_every_row_can_be_displayed(self):
        rows = meta.tokens()
        self.assertTrue(rows, "the token table is empty")
        for row in rows:
            self.assertTrue(row.get("id"), f"a token row has no id: {row}")
            self.assertTrue(row.get("name"), f"{row.get('id')} has no name, so the "
                                             f"review would print its raw id")

    def test_no_token_is_draftable(self):
        """The invariant, in both directions: a token is in tokens() and NOT in
        minions(). One that drifts into the pool gets offered as a buy."""
        pool = {m.get("id") for m in meta.minions()}
        for row in meta.tokens():
            self.assertNotIn(row["id"], pool,
                             f"{row['id']} is in the draftable pool as well as the "
                             f"token table; the pool is what the model may draft")

    def test_the_reported_token_resolves_by_name(self):
        """`BGS_115t` was a raw id in a SELLS row — the case that started this."""
        self.assertEqual(value._load_bg_names().get("BGS_115t"), "Water Droplet")

    def test_a_token_counts_as_a_minion_not_a_spell(self):
        """The same turn called its token a CAST, because the cast test asks
        "is this a known minion?" and no table listed it."""
        self.assertIn("BGS_115t", player_actions._load_bg_minion_ids())


if __name__ == "__main__":
    unittest.main()
