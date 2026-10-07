"""Selection ranker: the coach ranks the picks it could only count before.

Covers choice-block parsing (kind detection, PTL dedup, option dedup) and
the three ranking paths (heroes by pick_rate, trinkets by meta + synergy,
minion discovers by comp fit) plus the live wiring (pending choice tracked
incrementally, resolved on SendChoices, and SendChoices still counted for
the discover trigger totals).
"""
import os
import sys
import unittest

# app/ is where the code lives; deriving it from this file
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

from choices import choice_kind, parse_choice_blocks, rank_choices
from live_coach import LiveCoach

GS = "D 11:10:55.4853849 GameState.DebugPrintEntityChoices() - "
PTL = "D 11:10:55.4853849 PowerTaskList.DebugPrintEntityChoices() - "
SEND = ("D 11:10:56.0000000 GameState.SendChoices() -   m_chosenEntities[0]="
        "[entityName=Baller Portrait id=3226 zone=SETASIDE zonePos=0 "
        "cardId=BG36_MagicItem_390 player=3]")

_TRINKETS = [("Baller Portrait", "BG36_MagicItem_390"),
             ("Deathly Phylactery", "BG30_MagicItem_700"),
             ("Reflective Pendant", "BG30_MagicItem_706"),
             ("Stuffed Coin Purse", "BG35_MagicItem_814")]


def _trinket_block(ptl=False, dup=False):
    """A Lesser Trinket choice block (with optional duplicated option lines,
    as the hero-selection screen re-prints)."""
    tag = "PowerTaskList." if ptl else "GameState."
    lines = [f"{tag}DebugPrintEntityChoices() - id=8 Player=X TaskList=1253 "
             f"ChoiceType=GENERAL CountMin=1 CountMax=1",
             f"{tag}DebugPrintEntityChoices() -   Source=[entityName=Lesser "
             f"Trinket id=388 zone=PLAY zonePos=0 cardId=BG30_Trinket_1st "
             f"player=3]"]
    for i, (n, c) in enumerate(_TRINKETS):
        line = (f"{tag}DebugPrintEntityChoices() -   Entities[{i}]="
                f"[entityName={n} id=32{i} zone=SETASIDE zonePos=0 "
                f"cardId={c} player=3]")
        lines.append(line)
        if dup:
            lines.append(line)
    return lines


class TestChoiceParsing(unittest.TestCase):
    def test_trinket_block_kind_source_options(self):
        (kind, src, opts), = parse_choice_blocks(_trinket_block())
        self.assertEqual(kind, "trinket")
        self.assertEqual(src, "Lesser Trinket")
        self.assertEqual(len(opts), 4)

    def test_ptl_copies_skipped(self):
        """PowerTaskList re-prints choices — counting them doubles options."""
        lines = _trinket_block(ptl=True) + _trinket_block()
        (kind, _src, opts), = parse_choice_blocks(lines)
        self.assertEqual(kind, "trinket")
        self.assertEqual(len(opts), 4)

    def test_reprinted_options_deduped(self):
        """The hero-selection screen re-prints the same option lines."""
        lines = _trinket_block(dup=True)
        (kind, _src, opts), = parse_choice_blocks(lines)
        self.assertEqual(len(opts), 4)

    def test_kind_detection_fallbacks(self):
        self.assertEqual(choice_kind("GENERAL", "Shift your Hero Power",
                                     [("Reborn Rites", "BG31_XYZ")]), "unknown")
        self.assertEqual(choice_kind("GENERAL", None,
                                     [("A", "BG33_140")]), "discover")  # a real minion id
        self.assertEqual(choice_kind("MULLIGAN", None, []), "hero")

    def test_trinket_effect_discover_is_trinket(self):
        """A trinket's EFFECT discover (Trip Vouchers, 2026-09-08 20:35 log):
        the source names the trinket, not 'trinket', and the options are
        MagicItem ids MINION_ID can't match — the old check classified
        'unknown' and the coach recommended Entities[0] with no reason."""
        opts = [("Upstart Embers", "BG35_MagicItem_862"),
                ("Corrupted Tome", "BG35_MagicItem_812"),
                ("Nomi Sticker", "BG30_MagicItem_544t"),
                ("Portable Factory", "BG32_MagicItem_361t")]
        self.assertEqual(choice_kind("GENERAL", "Trip Vouchers", opts),
                         "trinket")
        lines = [
            "D 20:35:31.9855470 GameState.DebugPrintEntityChoices() - id=7 "
            "Player=X TaskList=2127 ChoiceType=GENERAL CountMin=1 CountMax=1",
            "D 20:35:31.9855470 GameState.DebugPrintEntityChoices() -   "
            "Source=[entityName=Trip Vouchers id=431 zone=PLAY zonePos=0 "
            "cardId=BG30_MagicItem_891 player=2]",
        ]
        for i, (n, c) in enumerate(opts):
            lines.append(f"D 20:35:31.9855470 "
                         f"GameState.DebugPrintEntityChoices() -   "
                         f"Entities[{i}]=[entityName={n} id=64{i} "
                         f"zone=SETASIDE zonePos=0 cardId={c} player=2]")
        (kind, src, parsed), = parse_choice_blocks(lines)
        self.assertEqual(kind, "trinket")
        self.assertEqual(src, "Trip Vouchers")
        self.assertEqual(len(parsed), 4)

    def test_unranked_options_still_score_none(self):
        """Genuinely unknown picks keep their rows but stay unranked — the
        renderers must not bless the first option (score None = no data)."""
        ranked = rank_choices("unknown", [("A", "BG31_XYZ"), ("B", "BG31_ABC")])
        self.assertEqual(len(ranked), 2)
        self.assertIsNone(ranked[0][2])
        self.assertIsNone(ranked[1][2])


class TestRanking(unittest.TestCase):
    def test_heroes_ranked_by_pick_rate_with_power_text(self):
        ranked = rank_choices("hero", [
            ("King Mukla", "TB_BaconShop_HERO_38"),
            ("Reno Jackson", "TB_BaconShop_HERO_41")])
        self.assertEqual(ranked[0][0], "Reno Jackson")   # ~60% pick rate
        self.assertTrue(ranked[0][3])                    # power text surfaced
        self.assertLess(ranked[-1][2], ranked[0][2])     # both scored, ordered

    def test_unknown_hero_still_listed(self):
        ranked = rank_choices("hero", [("Brand New Hero", "TB_BaconShop_HERO_99")])
        self.assertIsNone(ranked[0][2])
        self.assertEqual(ranked[0][0], "Brand New Hero")

    def test_locked_heroes_filtered_out(self):
        """Season-pass-locked heroes (the player's list) never get recommended
        — the log doesn't expose ownership, so the list is maintained in
        meta/locked_heroes.json."""
        ranked = rank_choices("hero", [
            ("Forest Warden Omu", "TB_BaconShop_HERO_23"),
            ("Reno Jackson", "TB_BaconShop_HERO_41")])
        self.assertEqual([r[0] for r in ranked], ["Reno Jackson"])

    def test_trinkets_ranked_by_meta(self):
        ranked = rank_choices("trinket", [
            ("Stuffed Coin Purse", "BG35_MagicItem_814"),
            ("Baller Portrait", "BG36_MagicItem_390")])
        self.assertEqual(ranked[0][0], "Baller Portrait")  # better meta pick
        self.assertIn("pick", ranked[0][3])

    def test_unknown_trinket_still_listed(self):
        ranked = rank_choices("trinket", [("Totally New Trinket", "XX_1")])
        self.assertEqual(ranked[0][2], 0.0)
        self.assertEqual(ranked[0][0], "Totally New Trinket")


class TestCuratedTrinkets(unittest.TestCase):
    """Card-text pass phase 2 (2026-09-08): every trinket has a curated read
    in meta/trinket_effects.json; the pick ranker's synergy term reads it."""

    def test_all_trinkets_annotated(self):
        import meta
        ids = {t["id"] for t in meta.trinkets()}
        got = set(meta.trinket_effects()) - {"_comment"}
        self.assertFalse(ids - got, f"unannotated: {sorted(ids - got)}")
        self.assertFalse(got - ids, f"orphans: {sorted(got - ids)}")

    def test_curated_synergy_fits_the_board(self):
        # Dragon Skull rewards BATTLECRY boards (keyword in the curated
        # synergy), not just a tribe mention in the description.
        ranked = rank_choices("trinket", [
            ("Dragon Skull", "BG36_MagicItem_2033"),
            ("Holy Mallet", "BG30_MagicItem_9021")],
            [{"card": "X", "tribe": None, "keywords": ["BATTLECRY"]}])
        self.assertEqual(ranked[0][0], "Dragon Skull")
        self.assertIn("fits your board", ranked[0][3])

    def test_curated_tribe_synergy(self):
        # Mama Bear Sticker's synergy tribe is Beast.
        ranked = rank_choices("trinket", [
            ("Mama Bear Sticker", "BG35_MagicItem_8710"),
            ("Holy Mallet", "BG30_MagicItem_9021")],
            [{"card": "X", "tribe": "BEAST"}])
        self.assertEqual(ranked[0][0], "Mama Bear Sticker")

    def test_discover_prefers_comp_core(self):
        comps = {"beasts": {"name": "Beasts", "tribe": "Beast",
                            "core": ["BG33_886"], "addons": []}}
        board = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"},
                 {"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        ranked = rank_choices("discover",
                              [("Metallic Hunter", "BG33_449"),
                               ("Tusked Camper", "BG33_886")],
                              board, comps, comp=comps["beasts"])
        self.assertEqual(ranked[0][0], "Tusked Camper")
        # Already on the board, so the fact says what a second copy does; the
        # comp's own core count is off the board, not asserted (2026-10-07).
        self.assertIn("core of Beasts", ranked[0][3])
        self.assertIn("a second copy triples", ranked[0][3])

    def test_discover_labels_key_on_the_displayed_comp(self):
        """The 2026-09-11 report: Lurking Leviathan (core of Beasts -
        Leviathan) headlined the pick panel as "comp fit" while the overlay
        showed Beasts - Tasty Lobstah committed — the ranking re-derived its
        own comp and the label never inspected anything (an Elemental wore
        "comp fit" in a Beast game). The panel now scores against the passed
        target and labels what the score actually keyed on."""
        comps = {
            "beasts-tasty-lobstah": {
                "name": "Beasts - Tasty Lobstah", "tribe": "Beast",
                "core": ["BG36_202", "BG36_204"], "addons": ["BG36_201"]},
            "beasts-leviathan": {
                "name": "Beasts - Leviathan", "tribe": "Beast",
                "core": ["BG35_602"], "addons": []},
        }
        board = [{"card": "BG36_202", "atk": 1, "health": 1, "tribe": "BEAST"}]
        target = comps["beasts-tasty-lobstah"]
        ranked = rank_choices(
            "discover",
            [("Lurking Leviathan", "BG35_602"),
             ("Felfire Conjurer", "BG32_821"),   # Demon/Dragon — off-comp
             ("Headhunter Gryphon", "BG36_204")],
            board, comps, comp=target)
        by_name = {r[0]: r for r in ranked}
        # Leviathan's raw growth (6.0) legitimately leads the ranking — but
        # its fact may no longer CLAIM comp membership: it is the other comp's
        # core, and the tribe it shares is all it has in common.
        self.assertIn("the tribe Beasts - Tasty Lobstah is built on",
                      by_name["Lurking Leviathan"][3])
        # The displayed comp's own core piece says so, and says how much of
        # that comp's core the player already has.
        self.assertIn("core of Beasts - Tasty Lobstah",
                      by_name["Headhunter Gryphon"][3])
        self.assertIn("you have 1 of its 2",
                      by_name["Headhunter Gryphon"][3])
        self.assertEqual(by_name["Felfire Conjurer"][3],
                         "not a piece of the comp you are on")
        # ...and no option names a best or wears the blanket lie.
        for _n, _c, _s, facts, _o in ranked:
            self.assertNotIn("best", facts.lower())
            self.assertNotEqual(facts, "comp fit")

    def test_discover_without_a_direction_makes_no_comp_claim(self):
        """No displayed target -> no comp wording AND no rank word.

        The top option used to read "best available" — the verdict the pivot
        deleted, surviving one layer below the wall because it rode inside a
        fact STRING rather than a verdict KEY (2026-10-07). With nothing
        displayed to compare against, the honest fact set is empty."""
        ranked = rank_choices("discover",
                              [("Lurking Leviathan", "BG35_602"),
                               ("Felfire Conjurer", "BG32_821")],
                              [], {})
        for name, _cid, _s, facts, _o in ranked:
            self.assertEqual(facts, "", f"{name} claims something with no "
                                        f"displayed comp to claim it against")
        self.assertEqual([r[4] for r in ranked], [0, 1],
                         "rows carry the option's place in the game's list")


class TestTheFactsNameNoRank(unittest.TestCase):
    """The wall is key-level, so a VERDICT INSIDE A STRING walked through it.

    `LIVE_VERDICT_KEYS` drops verdict KEYS from the live payload — that is what
    makes the pivot hold — and the pick panel's words were therefore never
    checked. `_rank_discover` labelled row 0 `"best available"` for six days
    after the pivot (2026-10-06 → 2026-10-07) and this test is what was missing:
    it would have failed on the day the pivot landed.

    Every fact string the three rankers produce is a statistic or a description
    of the card — nothing may rank the options, in a payload whose ordering is
    already a model opinion (row 0 is what `value._top_move_text` records as the
    plan's pick).
    """

    #: Words that rank or instruct. Deliberately checked against the DBs first:
    #: a hero power or trinket description containing one of these would make
    #: this control fire on reference text rather than on our own wording
    #: (measured 2026-10-07: zero of 117 hero powers contain any of them).
    WORDS = ("best", "top pick", "recommend", "should", "you need", "go for",
             "pick this")

    def _facts(self, kind, options, **kw):
        return [row[3] for row in rank_choices(kind, options, **kw)]

    def test_no_ranker_ranks_in_words(self):
        comp = {"name": "Beasts", "tribe": "Beast", "core": ["BG33_886"],
                "addons": []}
        cases = {
            "hero": self._facts("hero", [("Reno Jackson", "TB_BaconShop_HERO_01"),
                                         ("Chenvaala", "TB_BaconShop_HERO_02")]),
            "trinket": self._facts("trinket",
                                   [("Baller Portrait", "BG30_MagicItem_301"),
                                    ("Totally New Trinket", "XX_1")]),
            "discover": self._facts("discover",
                                    [("Tusked Camper", "BG33_886"),
                                     ("Metallic Hunter", "BG33_449")],
                                    board=[{"card": "BG33_886", "tribe": "BEAST"}],
                                    comps={}, comp=comp),
        }
        for kind, facts in cases.items():
            for text in facts:
                low = text.lower()
                for word in self.WORDS:
                    self.assertNotIn(word, low,
                                     f"a {kind} fact ranks the options: {text!r}")

    def test_every_row_carries_its_place_in_the_game_order(self):
        """The page renders in the GAME's order, so each row has to say where
        it sat in the offered list — and a locked hero's removal must not
        renumber the rows that are left."""
        ranked = rank_choices("hero", [("Reno Jackson", "TB_BaconShop_HERO_01"),
                                       ("Chenvaala", "TB_BaconShop_HERO_02")])
        self.assertEqual(sorted(r[4] for r in ranked), [0, 1])

    def test_all_kinds_return_the_same_row_shape(self):
        """Four facts + the order slot, whatever the kind — the page destructures
        it positionally, and `_CHOICE.ranked` in the report spec is DeepScalars."""
        for kind in ("hero", "trinket", "discover", "unknown"):
            rows = rank_choices(kind, [("A", "BG33_886"), ("B", "BG31_330")],
                                [], {}, None)
            for row in rows:
                self.assertEqual(len(row), 5, f"{kind} row shape drifted: {row}")


class TestLiveWiring(unittest.TestCase):
    def _coach(self):
        c = LiveCoach()
        c.friendly = 7  # hero parsed (as it is by the first seeded advise)
        return c

    def test_pending_choice_tracked_and_resolved(self):
        c = self._coach()
        for line in _trinket_block():
            c.feed(line)
        self.assertIsNotNone(c.choice)
        self.assertEqual(c.choice["source"], "Lesser Trinket")
        self.assertEqual(len(c.choice["options"]), 4)
        c.feed(SEND)
        self.assertEqual(c.choice["picked"], "Baller Portrait")

    def test_ptl_choice_lines_ignored(self):
        c = self._coach()
        for line in _trinket_block(ptl=True):
            c.feed(line)
        self.assertIsNone(c.choice)

    def test_sendchoices_still_counts_as_discover(self):
        """The choice tracking must not swallow SendChoices from the action
        tracker — the discover trigger totals depend on it."""
        c = self._coach()
        for line in _trinket_block():
            c.feed(line)
        c.actions.friendly = 7
        c.in_buying = True
        c.feed(SEND)
        self.assertEqual(c.actions.discovers, 1)


if __name__ == "__main__":
    unittest.main()