"""Friendly-player detection (extract_game._friendly_player).

The live coach locks `friendly` in once, the first moment a hero parses â€”
so the detection must be right at that moment, not merely right once the
game is complete. The 2026-09-16 session misfired for a whole game: the
first placement-tagged hero was a lone OPPONENT (Vanndar, bracket 16) and
the old "fewest heroes" min() happily returned 16 â€” the coach then spent
the game reading a dead opponent's health/board/tier while advising.

Fixtures use the real line shapes (Hearthstone_2026_01_01).
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from config import HS_LOG_GLOB as LOG_GLOB  # noqa: E402

import live_coach  # noqa: E402

from extract_game import (  # noqa: E402
    CHOICE_PLAYER, _friendly_player, extract_game,
)

CHOICE_OPTION = (
    "D 06:28:05.0722531 GameState.DebugPrintEntityChoices() -   "
    "Entities[2]=[entityName=Xyrella id=100 zone=HAND zonePos=4 "
    "cardId=BG20_HERO_101 player=8]\n")
CHOICE_HEADER = (
    "D 06:28:05.0722531 GameState.DebugPrintEntityChoices() - id=1 "
    "Player=Tester#1234 TaskList=7 ChoiceType=MULLIGAN CountMin=1 "
    "CountMax=1\n")


def _place_line(name, eid, cid, player, place):
    return ("D 06:28:22.6049640 PowerTaskList.DebugPrintPower() -     "
            f"TAG_CHANGE Entity=[entityName={name} id={eid} zone=PLAY "
            f"zonePos=0 cardId={cid} player={player}] "
            f"tag=PLAYER_LEADERBOARD_PLACE value={place} \n")


def _meta(lines):
    """The exact early-parse call _ensure_meta makes on the line buffer."""
    game = extract_game(lines)
    return _friendly_player(game["heroes"], game.get("choice_players"))


class TestChoiceSignal(unittest.TestCase):
    def test_choice_option_line_captures_player(self):
        m = CHOICE_PLAYER.search(CHOICE_OPTION)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 8)

    def test_choice_header_not_matched(self):
        # The header names the account ("Player=Tester#1234"), not a
        # bracket number â€” it must not feed a garbage player into the set.
        self.assertIsNone(CHOICE_PLAYER.search(CHOICE_HEADER))

    def test_extract_game_returns_choice_players(self):
        game = extract_game([CHOICE_HEADER, CHOICE_OPTION])
        self.assertEqual(game["choice_players"], {8})

    def test_choice_wins_while_heroes_are_lone_opponent(self):
        """The live misfire, in miniature: the hero pick printed (player 8)
        but the only placement-tagged hero so far is opponent Vanndar (16).
        The choice signal must carry the detection."""
        lines = [CHOICE_HEADER, CHOICE_OPTION,
                 _place_line("Vanndar Stormpike", 180, "BG22_HERO_003", 16, 8)]
        self.assertEqual(_meta(lines), 8)

    def test_choice_beats_a_wrongly_split_counter(self):
        """Even a materialized split defers to the choice signal: opponents
        share one bracket id, so {16:2, 8:1} would 'work' â€” but the choice
        says the same thing and is authoritative from t=0."""
        lines = [CHOICE_HEADER, CHOICE_OPTION,
                 _place_line("Vanndar Stormpike", 180, "BG22_HERO_003", 16, 8),
                 _place_line("Lord Barov", 181, "TB_BaconShop_HERO_72", 16, 3),
                 _place_line("Xyrella", 100, "BG20_HERO_101", 8, 6)]
        self.assertEqual(_meta(lines), 8)


class TestHeuristicFallback(unittest.TestCase):
    def test_no_choices_unsplit_returns_none(self):
        """THE regression: old code returned the lone player (16) and the
        live coach locked onto an opponent for the whole game. With no
        choice signal yet, an unsplit counter must return None instead â€”
        the caller retries."""
        lines = [_place_line("Vanndar Stormpike", 180,
                             "BG22_HERO_003", 16, 8)]
        self.assertIsNone(_meta(lines))

    def test_no_choices_tied_split_returns_none(self):
        """Two bracket ids at one hero each: the 1-vs-7 shape hasn't
        materialized â€” min() would just pick insertion order."""
        lines = [_place_line("Vanndar Stormpike", 180,
                             "BG22_HERO_003", 16, 8),
                 _place_line("Xyrella", 100, "BG20_HERO_101", 8, 6)]
        self.assertIsNone(_meta(lines))

    def test_no_choices_full_split_names_friendly(self):
        """The original 1-vs-7 contract on a complete parse: 7 opponents
        under the spectator bracket, the friendly hero alone."""
        lines = [_place_line("Xyrella", 100, "BG20_HERO_101", 8, 6)]
        for i, (name, eid, cid, place) in enumerate([
                ("Vanndar Stormpike", 180, "BG22_HERO_003", 8),
                ("Lord Barov", 181, "TB_BaconShop_HERO_72", 3),
                ("Exarch Othaar", 182, "BG31_HERO_006", 2),
                ("Guff Runetotem", 183, "BG20_HERO_242", 4),
                ("Zerek, Master Cloner", 184, "BG31_HERO_005", 5),
                ("Malygos", 185, "TB_BaconShop_HERO_58_SKIN_E", 7),
                ("Enhance-o Mechano", 186, "BG24_HERO_204_SKIN_E", 1)]):
            lines.append(_place_line(name, eid, cid, 16, place))
        self.assertEqual(_meta(lines), 8)

    def test_no_heroes_no_choices_returns_none(self):
        self.assertIsNone(_meta([CHOICE_HEADER]))  # header names no bracket

    def test_ambiguous_choices_fall_through_to_heuristic(self):
        """Two distinct bracket numbers on choice lines can't happen in a
        real log; if parsing ever yields it, defer to the hero-count
        heuristic rather than guessing between them."""
        game = extract_game([
            CHOICE_OPTION,
            "D 06:28:05.0722531 GameState.DebugPrintEntityChoices() -   "
            "Entities[0]=[entityName=Guff id=101 zone=SETASIDE zonePos=0 "
            "cardId=BG20_HERO_242 player=9]\n",
            _place_line("Vanndar Stormpike", 180, "BG22_HERO_003", 16, 8),
            _place_line("Xyrella", 100, "BG20_HERO_101", 8, 6),
            _place_line("Lord Barov", 181, "TB_BaconShop_HERO_72", 16, 3)])
        # choices {8, 9} don't decide; the split {16:2, 8:1} does.
        self.assertEqual(
            _friendly_player(game["heroes"], game["choice_players"]), 8)


class TestLiveLockContract(unittest.TestCase):
    """The live_coach._ensure_meta contract on top of _friendly_player.

    The choice signal fires at the mulligan, before hero entities carry
    placements. Locking the player number there captured a hero-less meta
    that never re-parsed (2026-09-16 07:48 session: hero/tier/gold/health
    None all game; the coach advised spell buys with no LEVEL machinery â€”
    reported as "prioritizing spells over leveling"). The lock must wait
    for the friendly player's hero record.
    """

    def _coach_with(self, *lines):
        lc = live_coach.LiveCoach()
        for line in lines:
            lc.feed(line)
        lc.ensure_meta()
        return lc

    def test_choices_alone_do_not_lock(self):
        lc = self._coach_with(CHOICE_HEADER, CHOICE_OPTION)
        self.assertIsNone(lc.friendly)
        self.assertIsNone(lc.hero_card)
        self.assertIsNone(lc.meta)

    def test_hero_placement_completes_the_lock(self):
        lc = self._coach_with(
            CHOICE_HEADER, CHOICE_OPTION,
            _place_line("Xyrella", 100, "BG20_HERO_101", 8, 6))
        self.assertEqual(lc.friendly, 8)
        self.assertEqual(lc.hero_card, "BG20_HERO_101")
        self.assertEqual(lc.hero_name, "Xyrella")

    def test_wrong_player_hero_still_waits(self):
        """An opponent hero spawning first (the morning misfire's shape)
        must not satisfy the gate either â€” the friendly's OWN hero is the
        requirement."""
        lc = self._coach_with(
            CHOICE_HEADER, CHOICE_OPTION,
            _place_line("Vanndar Stormpike", 180, "BG22_HERO_003", 16, 8))
        self.assertIsNone(lc.friendly)
        self.assertIsNone(lc.hero_card)

    def test_late_lock_drains_pending_hero_stats(self):
        """Armor/health writes that arrived before the lock are buffered in
        _stat_pending and drained at lock time â€” a later lock must not lose
        the opening health."""
        lc = live_coach.LiveCoach()
        for line in (CHOICE_HEADER, CHOICE_OPTION):
            lc.feed(line)
        # A friendly-hero ARMOR write, pre-lock.
        lc.feed("D 06:28:06.0000000 PowerTaskList.DebugPrintPower() -     "
                "TAG_CHANGE Entity=[entityName=Xyrella id=100 zone=HAND "
                "zonePos=4 cardId=BG20_HERO_101 player=8] tag=ARMOR "
                "value=10 \n")
        self.assertTrue(lc._stat_pending)
        lc.feed(_place_line("Xyrella", 100, "BG20_HERO_101", 8, 6))
        lc.ensure_meta()
        self.assertEqual(lc.friendly, 8)
        self.assertEqual(lc._stat_pending, [])


class TestRealLog(unittest.TestCase):
    def test_incremental_lock_matches_full_parse(self):
        """On every game of the newest real session, the friendly player the
        live coach WOULD lock in at its first parseable moment must equal the
        one the full parse agrees on. Skipped when no session log exists â€”
        the committed suite stays deterministic (the 2026-09-16 session is
        the pinned misfire)."""
        logs = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime, reverse=True)
        if not logs:
            self.skipTest("no Hearthstone session log found")
        with open(logs[0], encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        starts = [i for i, l in enumerate(lines)
                  if "CREATE_GAME" in l and "GameState" in l]
        if not starts:
            self.skipTest(f"{logs[0]} contains no Battlegrounds game")
        ends = starts[1:] + [len(lines)]
        for s, e in zip(starts, ends):
            buf = lines[s:e]
            full = _friendly_player(extract_game(buf)["heroes"],
                                    extract_game(buf)["choice_players"])
            if full is None:
                continue
            # Walk forward until the lock LANDS (non-None) â€” the contract is
            # that whenever it lands, it equals the full parse. An opponent-
            # only hero sighting must be waited out, not locked on.
            locked = None
            for n in range(1, len(buf) + 1):
                g = extract_game(buf[:n])
                locked = _friendly_player(g["heroes"], g["choice_players"])
                if locked is not None:
                    break
            self.assertEqual(
                locked, full,
                f"early lock {locked} != full-parse friendly {full}")


if __name__ == "__main__":
    unittest.main()
