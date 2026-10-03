"""comp_miner: propose the comps the scraped source does not have, or say nothing.

The scraped comp list (hsreplay) has no Aberration comp despite the tribe being
in the pool since 36.6.1 — re-scraped and confirmed: 26 comps, ten original
tribes only. comp_miner measures our own corpus instead, and the property that
matters is **honesty**: a tribe seen in two games must be reported as
insufficient evidence, never dressed up as a comp. The `--write` path must also
never touch `meta/comps.json`.
"""
import glob
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import comp_miner as cm  # noqa: E402
import meta  # noqa: E402

#: id -> display name, straight from the minion DB the miner reads: asserting
#: against a hardcoded name would just re-type the DB.
MINION_NAMES = {r.get("id"): r.get("name") for r in (meta._raw("minions.json") or [])}

LOG_GLOB = cm.HS_LOG_GLOB
REAL_LOGS = sorted(glob.glob(LOG_GLOB))
PY = sys.executable


def m(card, tribe):
    return {"card": card, "name": card, "atk": 5, "health": 5, "tribe": tribe}


AB = "Aberration"
DEM = "Demon"


class TestDominantTribe(unittest.TestCase):
    def test_a_clean_majority_wins(self):
        board = [m(f"AB{i}", AB) for i in range(4)] + [m(f"D{i}", DEM) for i in range(3)]
        self.assertEqual(cm.dominant_tribe(board), AB)

    def test_a_two_two_split_is_not_dominant(self):
        board = [m("A1", AB), m("A2", AB), m("D1", DEM), m("D2", DEM)]
        self.assertIsNone(cm.dominant_tribe(board))

    def test_a_two_minion_board_is_not_dominant(self):
        self.assertIsNone(cm.dominant_tribe([m("A1", AB), m("A2", AB)]))

    def test_untribed_and_amalgam_minions_neither_vote_nor_dilute(self):
        """Titus is untribed and an Amalgam is *every* tribe: neither is tribe
        evidence. Counting the Amalgam as all eleven tribes would dilute a
        genuine 4-of-7 majority below the threshold and lose the game."""
        board = ([m(f"AB{i}", AB) for i in range(4)]
                 + [m("TITUS", None), m("AMALGAM1", "All"), m("AMALGAM2", "All")])
        self.assertEqual(cm.dominant_tribe(board), AB)

    def test_a_compound_tribe_votes_for_each_part(self):
        """Demon/Quilboar cards vote once per part, so the parts tie and the
        first one seen wins — either is a true statement about the board."""
        board = [m(f"X{i}", "Demon/Quilboar") for i in range(4)]
        self.assertEqual(cm.dominant_tribe(board), DEM)

    def test_no_board_is_not_dominant(self):
        self.assertIsNone(cm.dominant_tribe([]))
        self.assertIsNone(cm.dominant_tribe(None))


class TestMine(unittest.TestCase):
    ROWS = [
        (AB, 1, ["BG36_318", "BG36_318", "BG36_115", "GLUE"]),
        (AB, 5, ["BG36_318", "BG36_115"]),
        (AB, 3, ["BG36_318", "GLUE"]),
        (AB, None, ["BG36_318"]),
        (AB, 2, ["BG36_318", "BG36_115"]),
    ]

    def test_below_the_floor_is_flagged_and_never_promoted(self):
        got = cm.mine(self.ROWS[:2], AB, min_games=5)
        self.assertFalse(got["enough_evidence"])
        self.assertIn("insufficient evidence (n=2, need 5)", got["note"])
        self.assertEqual(got["games"], 2)
        self.assertTrue(got["core"], "the suggestion is still reported")

    def test_at_the_floor_it_is_a_candidate(self):
        got = cm.mine(self.ROWS, AB, min_games=5)
        self.assertTrue(got["enough_evidence"])
        self.assertIsNone(got["note"])
        self.assertEqual(got["games"], 5)
        self.assertEqual(got["top4"], 3,
                         "1/3/2 are top4; place 5 and an unknown placement are not")
        self.assertEqual(got["core"][0]["card"], "BG36_318")
        self.assertEqual(got["core"][0]["name"], MINION_NAMES["BG36_318"],
                         "the report names cards, it does not print ids")
        self.assertEqual(got["core"][0]["games"], 5)
        self.assertEqual(got["core"][0]["share"], 1.0)

    def test_copies_on_one_board_do_not_inflate_a_card(self):
        """Two copies in game 1 is still one game out of five."""
        got = cm.mine(self.ROWS, AB, min_games=5)
        golden = [c for c in got["core"] + got["addons"] if c["card"] == "BG36_318"][0]
        self.assertEqual(golden["games"], 5)

    def test_core_and_addons_do_not_overlap(self):
        got = cm.mine(self.ROWS, AB, min_games=5)
        core = {c["card"] for c in got["core"]}
        addons = {c["card"] for c in got["addons"]}
        self.assertFalse(core & addons)
        self.assertIn("GLUE", addons, "two games of five is not core material")

    def test_a_missing_placement_does_not_crash_the_average(self):
        got = cm.mine(self.ROWS, AB, min_games=5)
        for row in got["core"] + got["addons"]:
            self.assertIsNotNone(row["avg_place"])
        only_unplaced = cm.mine([(AB, None, ["BG36_318"])], AB)
        self.assertIsNone(only_unplaced["core"][0]["avg_place"])

    def test_an_unknown_tribe_mines_nothing(self):
        got = cm.mine(self.ROWS, "Naga", min_games=5)
        self.assertEqual(got["games"], 0)
        self.assertEqual(got["core"], [])
        self.assertFalse(got["enough_evidence"])

    def test_names_come_from_the_minion_db_and_fall_back_to_the_id(self):
        rows = [(AB, 1, ["BG36_318"]), (AB, 2, ["NOT_A_REAL_CARD"]),
                (AB, 3, ["BG36_318"]), (AB, 4, ["BG36_318"]),
                (AB, 6, ["BG36_318"])]
        got = cm.mine(rows, AB, min_games=5)
        names = {c["card"]: c["name"] for c in got["core"] + got["addons"]}
        self.assertNotEqual(names.get("BG36_318"), "BG36_318",
                            "a known minion must resolve to its display name")
        self.assertEqual(names.get("NOT_A_REAL_CARD"), "NOT_A_REAL_CARD",
                         "an unknown id is reported as itself, never guessed")


class TestTribesWithoutComps(unittest.TestCase):
    def test_a_tribe_no_comp_covers_is_listed(self):
        comps = {"mechs": {"name": "Mechs - Test", "tribe": "Mech"}}
        missing = cm.tribes_without_comps(comps)
        self.assertIn(AB, missing)
        self.assertNotIn("Mech", missing)

    def test_a_comp_for_the_tribe_closes_the_gap(self):
        comps = {"a": {"name": "Aberrations - Test", "tribe": "Aberration"}}
        self.assertNotIn(AB, cm.tribes_without_comps(comps))

    def test_a_comp_with_no_tribe_field_does_not_crash(self):
        self.assertIn(AB, cm.tribes_without_comps({"x": {"name": "no tribe"}}))


@unittest.skipUnless(REAL_LOGS, f"no Power.log at {LOG_GLOB}")
class TestAgainstTheRealCorpus(unittest.TestCase):
    """One real log, bounded — the scan itself is proven on the corpus by hand."""

    @classmethod
    def setUpClass(cls):
        # Six logs, not one: a session can be a launcher-only fragment whose
        # single chunk has no parseable game (the 2026-09-23 13:42 log is one),
        # and scanning only the newest would make this test flap on it.
        cls.rows = cm.scan(limit=6)

    def test_the_scan_yields_plausible_rows(self):
        if not self.rows:
            self.skipTest("no log on disk has a game with a dominant tribe")
        display = set(__import__("tribes").DISPLAY_TRIBES)
        for tribe, place, cards in self.rows:
            self.assertIn(tribe, display)
            self.assertTrue(cards, "a dominant board always has cards")
            self.assertTrue(all(isinstance(c, str) for c in cards))
            if place is not None:
                self.assertTrue(1 <= place <= 8, f"placement {place} out of range")

    def test_a_thin_sample_is_never_reported_as_a_candidate(self):
        for tribe in {t for t, _p, _c in self.rows}:
            got = cm.mine(self.rows, tribe, min_games=99)
            self.assertFalse(got["enough_evidence"])
            self.assertIn("insufficient evidence", got["note"])


@unittest.skipUnless(REAL_LOGS, f"no Power.log at {LOG_GLOB}")
class TestWriteNeverTouchesComps(unittest.TestCase):
    """`--write` writes its own proposal file and never comps.json."""

    def test_write_leaves_comps_json_byte_identical(self):
        comps_path = os.path.join(HERE, "meta", "comps.json")
        with open(comps_path, "rb") as f:
            before = f.read()
        proc = subprocess.run(
            [PY, os.path.join(HERE, "comp_miner.py"), "--limit", "6", "--write",
             "--json"],
            cwd=HERE, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(comps_path, "rb") as f:
            self.assertEqual(f.read(), before, "comp_miner must never write comps.json")
        if "no games with a dominant tribe" in (proc.stdout or ""):
            self.skipTest("no log on disk holds a game with a dominant tribe")
        self.assertTrue(os.path.exists(cm.CANDIDATES),
                        "--write should produce the candidate proposal file")

    def test_promote_is_dry_by_default_in_dry_run_mode(self):
        """--promote --dry-run must print a plan and write nothing at all."""
        comps_path = os.path.join(HERE, "meta", "comps.json")
        with open(comps_path, "rb") as f:
            before = f.read()
        proc = subprocess.run(
            [PY, os.path.join(HERE, "comp_miner.py"), "--promote", "--dry-run",
             "--tribe", "Aberration", "--limit", "6"],
            cwd=HERE, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(comps_path, "rb") as f:
            self.assertEqual(f.read(), before,
                             "--dry-run must not write comps.json")


if __name__ == "__main__":
    unittest.main()
