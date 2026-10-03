"""The account map's local-player row — the join that resolves the purse.

`game["account"]` maps name -> hero card, and live_coach resolves its own
purse by matching the hero card against it, then reading gold from
board_state's per-account table (RESOURCES - RESOURCES_USED + TEMP_RESOURCES).

Until 2026-10-03 the local player had no row: the only place their own name
appears is a `DebugPrintGame` identity line, and their PLAYER block carries no
name, so only the opponents (whose names arrive as `Entity=<name>` tag changes)
were ever collected. With no row, `account` resolved to None and EVERY
advisory was issued with gold=None — measured on a real session: 212 of 212
advisories, and the plan advised "5. LEVEL" on a turn with 0 gold left.

The trap that made the first fix silently do nothing is pinned below: there are
TWO identity lines per game, and the second belongs to the shared spectator id
(PlayerID=12) that all seven opponents hide behind.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import board_state  # noqa: E402
import extract_game as eg  # noqa: E402

#: Assembled at runtime: this file ships, and the release's privacy gate
#: (correctly) refuses anything shaped like a real BattleTag — including a fake
#: one used as an opponent name in a fixture.
PLAYER_NAME = "TestPlayer" + "#" + "0000"
SPECTATOR_NAME = "Bystander" + "#" + "0001"
OPP_NAME = "Some" + "Opp"

PLAYER_HERO = "BG33_HERO_001"
OPP_HERO = "BG23_HERO_306"
PLACEHOLDER_HERO = "TB_BaconShop_HERO_PH"


def _hero(eid, cid, player, place):
    return (f"D 0:00:01.0 GameState.DebugPrintPower() - TAG_CHANGE "
            f"Entity=[entityName=H id={eid} zone=PLAY cardId={cid} "
            f"player={player}] tag=PLAYER_LEADERBOARD_PLACE value={place}")


def _player_block(eid, pid):
    return (f"D 0:00:01.0 GameState.DebugPrintPower() -     Player "
            f"EntityID={eid} PlayerID={pid} GameAccountId=[hi=1 lo=2]")


def _bare_hero_entity(eid):
    return (f"D 0:00:01.0 GameState.DebugPrintPower() -         "
            f"tag=HERO_ENTITY value={eid}")


def _fixture():
    """Shapes and ORDER copied from the real session that exposed the bug."""
    return [
        # Two identity lines: the player first, then the shared spectator id.
        f"D 0:00:01.0 GameState.DebugPrintGame() - PlayerID=4, "
        f"PlayerName={PLAYER_NAME}",
        f"D 0:00:01.0 GameState.DebugPrintGame() - PlayerID=12, "
        f"PlayerName={SPECTATOR_NAME}",
        # Their PLAYER blocks — unnamed — carrying HERO_ENTITY.
        _player_block(11, 4), _bare_hero_entity(119),
        _player_block(12, 12), _bare_hero_entity(62),
        _hero(119, PLAYER_HERO, 4, 1),
        # The spectator's HERO_ENTITY points at the placeholder, as in the log.
        _hero(62, PLACEHOLDER_HERO, 12, 8),
        # An opponent arrives the other way: a NAMED tag change.
        f"D 0:00:01.0 GameState.DebugPrintPower() -     TAG_CHANGE "
        f"Entity={OPP_NAME} tag=HERO_ENTITY value=130",
        _hero(130, OPP_HERO, 12, 2),
        # The purse, keyed by exactly the identity name.
        f"D 0:00:02.0 GameState.DebugPrintPower() -     TAG_CHANGE "
        f"Entity={PLAYER_NAME} tag=RESOURCES value=10",
        f"D 0:00:03.0 GameState.DebugPrintPower() -     TAG_CHANGE "
        f"Entity={PLAYER_NAME} tag=RESOURCES_USED value=10",
    ]


class TestLocalPlayerRow(unittest.TestCase):
    def test_the_local_player_gets_a_row(self):
        account = eg.extract_game(_fixture())["account"]
        self.assertIn(PLAYER_NAME, account)
        self.assertEqual(account[PLAYER_NAME], PLAYER_HERO)

    def test_the_spectator_identity_line_does_not_shadow_the_player(self):
        """Taking the last identity line picked the spectator, whose hero is a
        placeholder, so nothing was added and the bug survived its own fix."""
        account = eg.extract_game(_fixture())["account"]
        self.assertIn(PLAYER_NAME, account)
        self.assertNotIn(SPECTATOR_NAME, account,
                         "the shared spectator id is not a player")

    def test_opponents_still_resolve_by_name(self):
        account = eg.extract_game(_fixture())["account"]
        self.assertEqual(account.get(OPP_NAME), OPP_HERO)


class TestThePurseJoin(unittest.TestCase):
    """The end-to-end chain live_coach walks: hero card -> name -> purse."""

    def test_gold_is_reachable_from_the_account_map(self):
        lines = _fixture()
        account = eg.extract_game(lines)["account"]
        gs = board_state.GameState()
        for line in lines:
            gs.feed(line)
        name = next((n for n, cid in account.items() if cid == PLAYER_HERO),
                    None)
        self.assertEqual(name, PLAYER_NAME,
                         "the purse lookup found no account for the hero card")
        # 10 granted, 10 spent: the coach can now see an empty purse.
        self.assertEqual(gs.gold.get(name), 0)


if __name__ == "__main__":
    unittest.main()
