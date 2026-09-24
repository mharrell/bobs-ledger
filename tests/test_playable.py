"""Golden tests for the out-of-play registry (playable.py) and the log-mined
pool roster (pool_roster.py).

Both exist because of the 2026-09-22 patch 36.6.1: a new minion type
(Aberrations) joined the pool and Naga was rotated out. The registry is the
patch-notes side, the roster is the observed-log side, and the interesting
behaviour is in how they disagree.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import playable  # noqa: E402
import pool_roster  # noqa: E402
from tribes import ALL_MARKER, ALL_TRIBES, canon, parts  # noqa: E402


def _pool_block(eid, cid, race=None, tier=1, atk=1, hp=1, cardtype="MINION",
                pool=True):
    """One FULL_ENTITY pool-minion definition, as the game prints it."""
    lines = [
        "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY"
        f" - Creating ID={eid} CardID={cid}\n",
        f"D 12:00:00 GameState.DebugPrintPower() -         tag=CARDTYPE value={cardtype}\n",
        f"D 12:00:00 GameState.DebugPrintPower() -         tag=TECH_LEVEL value={tier}\n",
        f"D 12:00:00 GameState.DebugPrintPower() -         tag=ATK value={atk}\n",
        f"D 12:00:00 GameState.DebugPrintPower() -         tag=HEALTH value={hp}\n",
    ]
    if race:
        lines.append("D 12:00:00 GameState.DebugPrintPower() -         "
                     f"tag=CARDRACE value={race}\n")
    if pool:
        lines.append("D 12:00:00 GameState.DebugPrintPower() -         "
                     "tag=IS_BACON_POOL_MINION value=1\n")
    return lines


class TestOutOfPlayRegistry(unittest.TestCase):
    """The shipped registry: Naga rotated out + the 35 removed minions."""

    def setUp(self):
        self.oop = playable.OutOfPlay()

    def test_shipped_patch_and_rotated_tribe(self):
        self.assertEqual(self.oop.doc.get("patch"), "36.6.1")
        self.assertEqual(self.oop.tribes_out(), {"Naga"})

    def test_removed_minion_is_out_and_explains_itself(self):
        why = self.oop.reason("BGS_071", "Deflect-o-Bot")
        self.assertIsNotNone(why)
        self.assertIn("removed from the minion pool", why)
        self.assertIn("36.6.1", why)

    def test_removed_tavern_spell_and_trinket_are_out(self):
        self.assertTrue(self.oop.is_out("BG33_899", "Mounting Avalanche"))
        self.assertTrue(self.oop.is_out("BG35_MagicItem_863", "Avalanche Sticker"))

    def test_live_card_is_not_out(self):
        # Aureate Laureate is a Pirate, in the pool, never removed.
        self.assertIsNone(self.oop.reason("BG32_236", "Aureate Laureate",
                                          "Pirate"))

    def test_unknown_card_and_tribe_fail_open(self):
        self.assertIsNone(self.oop.reason("BG99_999", "Nonexistent Card"))
        self.assertIsNone(self.oop.reason(None, None, None))
        self.assertIsNone(self.oop.reason(tribe="Void"))

    def test_pure_naga_card_is_out(self):
        self.assertTrue(self.oop.is_out(tribe="Naga"))
        self.assertTrue(self.oop.is_out(tribe="NAGA"))

    def test_compound_card_with_a_live_tribe_stays_in_play(self):
        """The log-verified rule: out only when EVERY tribe is out.

        Post-36.6.1 a game with Demon allowed still had BG31_330 Ominous Seer
        (Demon/Naga) in its pool — so treating a compound as out because one
        part is Naga would drop a buyable card.
        """
        self.assertFalse(self.oop.is_out("BG31_330", "Ominous Seer", "Demon/Naga"))
        self.assertFalse(self.oop.is_out(tribe="Dragon/Naga"))
        # ...but a card whose ONLY tribe is out, is out.
        self.assertTrue(self.oop.is_out(tribe="Naga"))

    def test_amalgam_is_never_out(self):
        """An 'All' card counts as every tribe, so it always has a live one."""
        self.assertFalse(self.oop.is_out("BG36_640", "Gatekeeper Amalgam",
                                         ALL_MARKER))

    def test_filter_cards_splits_with_reasons(self):
        rows = [{"id": "BGS_071", "name": "Deflect-o-Bot", "tribe": "Mech"},
                {"id": "BG32_236", "name": "Aureate Laureate", "tribe": "Pirate"}]
        kept, dropped = self.oop.filter_cards(rows)
        self.assertEqual([r["id"] for r in kept], ["BG32_236"])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0][0]["id"], "BGS_071")
        self.assertIn("out of play", dropped[0][1])

    def test_filter_comps_drops_rotated_tribe_and_keeps_others(self):
        comps = {
            "nagas-eot": {"tribe": "Naga", "core": ["BG32_837"]},
            "beasts": {"tribe": "Beast", "core": ["BG36_202"]},
            "no-tribe": {"tribe": None, "core": ["BG36_202"]},
        }
        kept, dropped = self.oop.filter_comps(comps)
        self.assertEqual(set(kept), {"beasts", "no-tribe"})
        self.assertEqual([slug for slug, _ in dropped], ["nagas-eot"])

    def test_filter_comps_fails_open_on_unknown_core(self):
        comps = {"mystery": {"tribe": None, "core": ["BG99_999"]}}
        kept, dropped = self.oop.filter_comps(comps)
        self.assertEqual(set(kept), {"mystery"})
        self.assertEqual(dropped, [])

    def test_filter_comps_drops_comp_whose_whole_core_is_out(self):
        comps = {"dead": {"tribe": None, "core": ["BGS_071", "BGS_104"]}}
        kept, dropped = self.oop.filter_comps(comps)
        self.assertEqual(kept, {})
        self.assertEqual(len(dropped), 1)

    def test_enforcement_kill_switch(self):
        with mock.patch.dict(os.environ, {"HEARTH_OUT_OF_PLAY": "0"}):
            self.assertIsNone(playable.enforcement())
            self.assertIsNone(playable.out_of_play_reason("BGS_071"))
        with mock.patch.dict(os.environ, {"HEARTH_OUT_OF_PLAY": "1"}):
            self.assertIsNotNone(playable.enforcement())


class TestRegistryAgainstRoster(unittest.TestCase):
    """The two data sources must agree; validate() reports it when they don't."""

    def test_shipped_files_are_consistent(self):
        problems = playable.validate()
        self.assertEqual(problems, [], f"registry/roster disagree: {problems}")

    def test_roster_is_the_new_epoch(self):
        roster = playable.load_roster()
        self.assertIsNotNone(roster, "run `python pool_roster.py --apply`")
        self.assertEqual(roster.get("patch"), "36.6.1")
        # Naga has no PURE pool card any more; Aberration has plenty.
        self.assertNotIn("Naga", roster["tribes_present"])
        self.assertIn("Aberration", roster["tribes_present"])

    def test_shipped_roster_records_dark_paradox_off_pool(self):
        """The known pool-tag gap is RECORDED, not silently dropped or mixed in.

        Dark Paradox is buyable and in the pool, but the game materialises its
        per-game variant through a creator, so it never carries
        IS_BACON_POOL_MINION. It must appear in `created` and must NOT appear in
        `cards` — promoting it into the pool would be exactly the mistake that
        once put tier-0 tokens in the roster.
        """
        roster = playable.load_roster()
        created = roster.get("created") or {}
        paradox = [cid for cid, c in created.items()
                   if (c.get("name") or "") == "Dark Paradox"]
        self.assertTrue(paradox, "Dark Paradox should be recorded in `created`")
        for cid in paradox:
            self.assertNotIn(cid, roster["cards"])
        # ...and the tokens the same signal drags in are recorded alongside it,
        # which is why `created` is a lead list and not a second pool.
        names = {(c.get("name") or "") for c in created.values()}
        self.assertIn("Beetle", names)

    def test_validator_flags_an_out_of_play_card_in_the_pool(self):
        doc = {"patch": "test", "tribes": {}, "cards": {
            "BGS_071": {"name": "Deflect-o-Bot", "kind": "minion",
                        "reason": "removed from the minion pool",
                        "patch": "test", "id": "BGS_071"}}}
        roster = {"patch": "test", "cards": {
            "BGS_071": {"name": "Deflect-o-Bot", "tier": 3, "tribe": "Mech"}}}
        problems = playable.validate(doc, roster)
        self.assertEqual(len(problems), 1)
        self.assertIn("Deflect-o-Bot", problems[0])

    def test_validator_flags_a_rotated_tribe_with_pure_pool_cards(self):
        doc = {"patch": "test", "tribes": {"Naga": {"reason": "rotated",
                                                    "patch": "test"}},
               "cards": {}}
        roster = {"patch": "test", "cards": {
            "BG23_000": {"name": "Some Naga", "tribe": "Naga"}}}
        problems = playable.validate(doc, roster)
        self.assertEqual(len(problems), 1)
        self.assertIn("Naga", problems[0])

    def test_validator_flags_a_returning_card_still_marked_out(self):
        doc = {"patch": "test", "tribes": {}, "cards": {
            "BG32_172": {"name": "Auto Assembler", "kind": "minion",
                         "reason": "removed", "patch": "test",
                         "id": "BG32_172"}},
            "history": [{"patch": "test", "returning": ["Auto Assembler"]}]}
        problems = playable.validate(doc, {"patch": "test", "cards": {}})
        self.assertEqual(len(problems), 1)
        self.assertIn("returning", problems[0])


class TestPoolRosterScan(unittest.TestCase):
    """The log walk: pool membership, tier, stats, races, and what it ignores."""

    def _scan(self, lines):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False,
                                         encoding="utf-8") as f:
            f.writelines(lines)
            path = f.name
        try:
            return pool_roster.scan_log(path)
        finally:
            os.unlink(path)

    def test_reads_tier_stats_and_race_from_the_pool_block(self):
        scan = self._scan(
            ["D 12:00:00 GameState.DebugPrintPower() - CREATE_GAME\n"]
            + _pool_block(330, "BGS_004", "DEMON", tier=1, atk=1, hp=3))
        self.assertEqual(scan["games"], 1)
        card = scan["cards"]["BGS_004"]
        self.assertEqual((card["tier"], card["attack"], card["health"]),
                         (1, 1, 3))
        self.assertEqual(card["races"], ["DEMON"])

    def test_non_minion_entities_are_excluded(self):
        """Tokens/enchantments also carry the pool tag and polluted the roster."""
        scan = self._scan(
            _pool_block(1, "BG34_170e", "MECHANICAL", cardtype="ENCHANTMENT")
            + _pool_block(2, "BGS_004", "DEMON"))
        self.assertNotIn("BG34_170e", scan["cards"])
        self.assertIn("BGS_004", scan["cards"])

    def test_entities_without_the_pool_tag_are_excluded(self):
        scan = self._scan(_pool_block(1, "BGS_004", "DEMON", pool=False))
        self.assertEqual(scan["cards"], {})

    def test_first_unbuffed_definition_wins(self):
        """A later buffed board copy must not overwrite base stats."""
        scan = self._scan(
            _pool_block(1, "BGS_004", "DEMON", atk=1, hp=3)
            + _pool_block(2, "BGS_004", "DEMON", atk=99, hp=99))
        self.assertEqual((scan["cards"]["BGS_004"]["attack"],
                          scan["cards"]["BGS_004"]["health"]), (1, 3))

    def test_multiword_names_are_captured_whole(self):
        scan = self._scan([
            "D 12:00:00 GameState.DebugPrintPower() -     TAG_CHANGE Entity="
            "[entityName=Wrath Weaver id=330 zone=PLAY zonePos=1"
            " cardId=BGS_004 player=7] tag=ATK value=5\n"])
        self.assertEqual(scan["names"]["BGS_004"], "Wrath Weaver")

    def test_games_are_counted_once_each(self):
        scan = self._scan(
            ["D 12:00:00 GameState.DebugPrintPower() - CREATE_GAME\n",
             "D 12:00:00 GameState.DebugPrintPower() - CREATE_GAME\n"])
        self.assertEqual(scan["games"], 2)

    def test_pool_tagged_and_created_entities_are_separated(self):
        """The pool and creator-made minions must never be mixed.

        36.6.1's Dark Paradox is a REAL buyable card that never carries
        IS_BACON_POOL_MINION — the game picks one of its variants per game and
        materialises it through an evolution creator, so it only shows the
        triple-upgrade id. Summoned tokens show that tag too (Beetle, Aberrant
        Tentacle), so a triple-only entity goes to `created` — a lead list —
        and `cards` (the pool) stays exactly what the game tagged as the pool.
        """
        created_block = [
            "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY"
            " - Creating ID=7659 CardID=BG36_360t6\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=CARDTYPE value=MINION\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=TECH_LEVEL value=3\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=ATK value=2\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=HEALTH value=2\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=CARDRACE value=ALL\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=AURA value=1\n",
            "D 12:00:00 GameState.DebugPrintPower() -"
            "         tag=BACON_TRIPLE_UPGRADE_MINION_ID value=134711\n",
        ]
        scan = self._scan(_pool_block(330, "BGS_004", "DEMON") + created_block)
        self.assertIn("BGS_004", scan["cards"])
        self.assertNotIn("BG36_360t6", scan["cards"])
        self.assertIn("BG36_360t6", scan["created"])
        self.assertEqual(scan["created"]["BG36_360t6"]["tier"], 3)

    def test_a_minion_without_either_signal_is_ignored(self):
        """A plain summoned token carries neither tag — it is not a card."""
        token = [
            "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY"
            " - Creating ID=99 CardID=BGXX_999t\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=CARDTYPE value=MINION\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=TECH_LEVEL value=1\n",
        ]
        scan = self._scan(token)
        self.assertEqual(scan["cards"], {})
        self.assertEqual(scan["created"], {})


class TestPureTribesAndEpoch(unittest.TestCase):
    def test_pure_tribes_uses_the_resolved_tribe_field(self):
        """A compound must not read as a pure card of either tribe.

        BG31_330 prints NAGA alone in the log but is Demon/Naga; a race-based
        reading reported Naga as a tribe holding a pure pool card — the exact
        thing rotation removes.
        """
        cards = {
            "BG31_330": {"tribe": "Demon/Naga", "races": ["NAGA"]},
            "BG23_000": {"tribe": "Naga", "races": ["NAGA"]},
            "BG32_236": {"tribe": "Pirate", "races": ["PIRATE"]},
            "BG36_640": {"tribe": ALL_MARKER, "races": ["ALL"]},
        }
        self.assertEqual(pool_roster.pure_tribes(cards), {"Naga", "Pirate"})
        del cards["BG23_000"]
        self.assertEqual(pool_roster.pure_tribes(cards), {"Pirate"})

    def test_pure_tribes_falls_back_to_raw_races_for_a_scan_result(self):
        scan_cards = {"BG36_110": {"races": ["ABERRATION"]},
                      "BG31_330": {"races": ["NAGA"]}}
        self.assertEqual(pool_roster.pure_tribes(scan_cards),
                         {"Aberration", "Naga"})

    def test_epoch_takes_the_new_content_generation(self):
        """A new card/tribe in the newest session marks the patch boundary."""
        old = {"name": "old", "mtime": 1, "scan": {"games": 1, "names": {},
                "cards": {"BGS_004": {"races": ["DEMON"]}}}}
        new = {"name": "new", "mtime": 2, "scan": {"games": 1, "names": {},
                "cards": {"BGS_004": {"races": ["DEMON"]},
                          "BG36_110": {"races": ["ABERRATION"]}}}}
        epoch, (sig_cards, sig_tribes) = pool_roster.current_epoch([old, new])
        self.assertEqual(sig_cards, {"BG36_110"})
        self.assertEqual(sig_tribes, {"Aberration"})
        self.assertEqual([s["name"] for s in epoch], ["new"])

    def test_epoch_falls_back_to_newest_only_when_it_adds_nothing(self):
        """Conservative on purpose — and the reason is worth pinning down.

        If the newest session introduces no card or tribe that older sessions
        lack, there is no detectable boundary. Two very different worlds look
        identical from the pool alone: (a) the same generation, where unioning
        older sessions would only widen coverage, and (b) a patch that only
        REMOVED cards, where unioning older sessions would resurrect every
        removed card into the "current" pool. Since (b) is the harmful one, the
        empty signature resolves to the newest session alone and the operator
        widens coverage explicitly with --sessions N (which warns about any
        out-of-play card the union drags back in).
        """
        a = {"name": "a", "mtime": 1, "scan": {"games": 1, "names": {},
             "cards": {"BGS_004": {"races": ["DEMON"]},
                       "BG36_110": {"races": ["ABERRATION"]}}}}
        b = {"name": "b", "mtime": 2, "scan": {"games": 1, "names": {},
             "cards": {"BG36_110": {"races": ["ABERRATION"]}}}}
        epoch, sig = pool_roster.current_epoch([a, b])
        self.assertEqual([s["name"] for s in epoch], ["b"])
        self.assertEqual(sig, (set(), set()))

    def test_epoch_without_a_signature_is_the_newest_session_only(self):
        """A removal-only patch has no new cards — say so instead of guessing."""
        old = {"name": "old", "mtime": 1, "scan": {"games": 1, "names": {},
                "cards": {"BGS_004": {"races": ["DEMON"]},
                          "BGS_071": {"races": ["MECHANICAL"]}}}}
        new = {"name": "new", "mtime": 2, "scan": {"games": 1, "names": {},
                "cards": {"BGS_004": {"races": ["DEMON"]}}}}
        epoch, sig = pool_roster.current_epoch([old, new])
        self.assertEqual([s["name"] for s in epoch], ["new"])
        self.assertEqual(sig, (set(), set()))


class TestRosterEnrichmentAndDiff(unittest.TestCase):
    def test_enrichment_unions_compound_tribes_from_the_meta_db(self):
        """The log can reveal one half of a compound; the meta DB knows both."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump([{"id": "BG31_330", "name": "Ominous Seer",
                        "tribe": "Demon/Naga"}], f)
            meta_path = f.name
        try:
            cards = {"BG31_330": {"tribe": "Naga", "races": ["NAGA"]}}
            widened = pool_roster.enrich_from_meta(cards, meta_path)
        finally:
            os.unlink(meta_path)
        self.assertEqual(widened, 1)
        self.assertEqual(cards["BG31_330"]["tribe"], "Demon/Naga")
        self.assertEqual(cards["BG31_330"]["tribe_src"], "log+meta")

    def test_enrichment_keeps_amalgams_as_the_all_marker(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump([{"id": "BG36_640", "name": "Gatekeeper Amalgam",
                        "tribe": "All"}], f)
            meta_path = f.name
        try:
            cards = {"BG36_640": {"tribe": None, "races": []}}
            pool_roster.enrich_from_meta(cards, meta_path)
        finally:
            os.unlink(meta_path)
        self.assertEqual(cards["BG36_640"]["tribe"], ALL_MARKER)
        self.assertNotIn("/", cards["BG36_640"]["tribe"])

    def test_diff_reports_added_removed_and_changed(self):
        old = {"cards": {"A": {"tier": 1, "name": "A"},
                         "B": {"tier": 2, "name": "B", "attack": 1}}}
        new = {"cards": {"A": {"tier": 1, "name": "A"},
                         "B": {"tier": 2, "name": "B", "attack": 5},
                         "C": {"tier": 3, "name": "C"}}}
        added, removed, changed = pool_roster.diff_rosters(old, new)
        self.assertEqual(added, ["C"])
        self.assertEqual(removed, [])
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0], "B")
        self.assertEqual(changed[0][1], ["attack"])


class TestAberrationTribeVocabulary(unittest.TestCase):
    """36.6.1 added the first new tribe ever; it must be first-class."""

    def test_aberration_is_canonical_and_in_the_roster(self):
        self.assertIn("ABERRATION", ALL_TRIBES)
        self.assertEqual(canon("ABERRATION"), "Aberration")
        self.assertEqual(canon("ABERRATIONS"), "Aberration")
        self.assertEqual(parts("Aberration"), ["Aberration"])

    def test_aberration_is_not_confused_with_a_legacy_plural(self):
        self.assertNotEqual(canon("ABERRATION"), canon("ABERRATIONS") + "s")

    def test_tribe_list_has_eleven_entries(self):
        self.assertEqual(len(ALL_TRIBES), 11)
        self.assertEqual(len(set(ALL_TRIBES)), 11)
