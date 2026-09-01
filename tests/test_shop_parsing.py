"""Shop parsing must track the CURRENT options block and separate the tavern's
offers from the friendly player's own minions (sell options) and buttons.

Live symptom (2026-08-31 Patchwerk game): the advise fired on the first minion
option — the player's OWN board minion listed as a sell option — so the buy
recommendation was None every turn and the overlay showed only "level".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_coach import LiveCoach

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
OPT = "D 21:17:14.0000000 GameState.DebugPrintOptions() - "


def opt_block(n, offers):
    """An options block: header + one POWER option per mainEntity."""
    lines = [f"{OPT}  id={n}", ]
    for i, (name, cid, player) in enumerate(offers):
        lines.append(
            f"{OPT}  option {i} type=POWER mainEntity=[entityName={name} "
            f"id={100 + i} zone=PLAY zonePos=0 cardId={cid} player={player}] "
            f"error=NONE errorParam=")
    lines.append(f"{OPT}  option {2 + len(offers)} type=END_TURN mainEntity= "
                 f"error=NONE errorParam=")
    return lines


class TestShopParsing(unittest.TestCase):
    def _coach(self):
        c = LiveCoach()
        c.friendly = 7  # hero parsed (as it is by the first seeded advise)
        return c

    def test_tavern_offers_exclude_own_minions_and_buttons(self):
        c = self._coach()
        for line in ["x STEP MAIN_ACTION"] + opt_block(1, [
                ("River Skipper", "BG33_140", 15),
                ("Tusked Camper", "BG33_886", 15),
                ("Patchwerk", "BG33_444", 7),          # own board: sell option
                ("Refresh", "TB_BaconShop_8p_Reroll_Button", 7),
        ]):
            c.feed(line)
        self.assertEqual(c.tavern_offers(), ["BG33_140", "BG33_886"])

    def test_latest_block_wins(self):
        """Options re-print after every event; the shop is the most recent
        block, not the union of every generation this turn."""
        c = self._coach()
        lines = (["x tag=STEP value=MAIN_ACTION"]
                 + opt_block(1, [("Old Offer", "BG21_034", 15)])
                 + ["x tag=STEP value=MAIN_END"])
        for line in lines:
            c.feed(line)
        # next phase: a fresh block with different offers
        for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(2, [
                ("New Offer", "BG22_010", 15)]):
            c.feed(line)
        self.assertEqual(c.tavern_offers(), ["BG22_010"])

    def test_fired_advice_uses_current_shop(self):
        """The live.py fire condition (pending + tavern_offers) must not fire
        on the friendly player's sell options alone — that was the empty-'Buy
        this' bug."""
        c = self._coach()
        for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(3, [
                ("My Board Minion", "BG33_444", 7)]):
            c.feed(line)
        self.assertFalse(c.tavern_offers())  # only own minions -> no fire yet


if __name__ == "__main__":
    unittest.main()