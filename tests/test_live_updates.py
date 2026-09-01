"""Mid-turn advice updates: the monitor re-advises whenever the decision state
changes during a buy phase (buy, roll, play, sell), not once per buy phase.

The old loop advised once per MAIN_ACTION transition and went stale for the
rest of the turn — the overlay kept showing the pre-buy shop and affordability
even after the player spent gold.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_coach import LiveCoach
from tests.test_shop_parsing import opt_block

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
OPT = "D 21:17:14.0000000 GameState.DebugPrintOptions() - "


def _coach_with_offers(*offers):
    c = LiveCoach()
    c.friendly = 7  # hero parsed (as it is by the first seeded advise)
    for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(1, offers):
        c.feed(line)
    return c


class TestStateFingerprint(unittest.TestCase):
    def test_none_before_hero_parsed(self):
        self.assertIsNone(LiveCoach().state_fingerprint())

    def test_gold_change_changes_fingerprint(self):
        """A buy spends gold — the fingerprint must notice (affordability)."""
        c = LiveCoach()
        c.friendly = 7
        c.account = "TestAccount"
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=5")
        before = c.state_fingerprint()
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=3")
        self.assertNotEqual(before, c.state_fingerprint())

    def test_shop_change_changes_fingerprint(self):
        """After a buy/refresh the shop loses an offer — the advice must re-run."""
        c = self._offers_coach()
        before = c.state_fingerprint()
        # A refresh wipes the captured offers until the next options block.
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        self.assertNotEqual(before, c.state_fingerprint())

    def _offers_coach(self):
        from live_coach import LiveCoach
        c = LiveCoach()
        c.friendly = 7
        for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(1, [
                ("River Skipper", "BG33_140", 15),
                ("Tusked Camper", "BG33_886", 15)]):
            c.feed(line)
        return c


if __name__ == "__main__":
    unittest.main()