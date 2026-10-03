"""comp_gap / comp_target: no fake direction on a tribe the coach has no comp for.

Measured failure this fixes (2026-09-23 win): a 6-of-7 Aberration board, no
Aberration comp in comps.json, and `comp_target` returned "Beasts - Tasty
Lobstah" from two single incidental hits in two different Beast comps. The plan
then advised Banana Slamma onto an all-Aberration board in a game that was won.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import value  # noqa: E402

ABERRATION_IDS = ["BG36_318", "BG36_115", "BG36_101", "BG36_102", "BG36_097"]
BEAST_IDS = ["BG36_201", "BG36_202"]
TITUS = "BG25_354"          # untribed, and a core in several comps


def board(ids, tribe=None):
    out = []
    for i in ids:
        t = tribe
        if t is None:
            t = "ABERRATION" if i.startswith("BG36_3") or i in ABERRATION_IDS \
                else ("BEAST" if i in BEAST_IDS else None)
        out.append({"card": i, "name": i, "atk": 10, "health": 10, "tribe": t})
    return out


BEAST_COMPS = {
    "beasts-lobstah": {"name": "Beasts - Tasty Lobstah", "tribe": "Beast",
                       "core": [BEAST_IDS[0]], "addons": []},
    "beasts-summons": {"name": "Beasts - Summons", "tribe": "Beast",
                       "core": [BEAST_IDS[1]], "addons": []},
}
MECH_COMPS = {
    "mechs": {"name": "Mechs - Test", "tribe": "Mech",
              "core": ["BG26_146"], "addons": []},
}


class TestCompGap(unittest.TestCase):
    def test_a_dominant_tribe_with_no_comp_is_reported(self):
        b = board(ABERRATION_IDS) + [{"card": TITUS, "tribe": None}]
        self.assertEqual(value.comp_gap(b, BEAST_COMPS), "Aberration")

    def test_a_dominant_tribe_that_has_comps_is_not_a_gap(self):
        b = board(BEAST_IDS + ["BG36_201", "BG36_202"])
        self.assertIsNone(value.comp_gap(b, BEAST_COMPS))

    def test_a_mixed_board_is_not_a_gap(self):
        """Needs a real majority, not a plurality of a mixed board."""
        b = board(ABERRATION_IDS[:2]) + board(BEAST_IDS)
        self.assertIsNone(value.comp_gap(b, BEAST_COMPS))

    def test_a_tiny_board_is_not_a_gap(self):
        self.assertIsNone(value.comp_gap(board(ABERRATION_IDS[:2]), BEAST_COMPS))


class TestCompTargetStopsMintingDirections(unittest.TestCase):
    def test_all_aberration_board_gets_no_direction(self):
        b = board(ABERRATION_IDS) + [{"card": TITUS, "tribe": None}]
        self.assertIsNone(
            value.comp_target(b, BEAST_COMPS),
            "a board the comp list cannot describe must not be given a comp")

    def test_untribed_glue_no_longer_gives_every_tribe_a_hit(self):
        """Titus is core in several comps, so raw hits summed to a fake tribe."""
        b = board([TITUS]) + board(BEAST_IDS[:1])
        comps = {"beasts-a": {"name": "a", "tribe": "Beast", "core": [TITUS]},
                 "beasts-b": {"name": "b", "tribe": "Beast", "core": [TITUS]}}
        self.assertIsNone(value.comp_target(b, comps))

    def test_the_real_tribe_case_still_commits(self):
        """The 2026-09-04 case this rule was written for: two Beast comps, two
        Beast cards — Tasty Lobster + Banana Slamma."""
        b = board(BEAST_IDS)
        got = value.comp_target(b, BEAST_COMPS)
        self.assertIsNotNone(got, "two same-tribe cores must still give a tribe")
        self.assertEqual(got.get("tribe"), "Beast")

    def test_a_real_two_core_commit_beats_a_dominant_gap_tribe(self):
        """>=2 hits of one comp is strong evidence and still wins."""
        b = board(ABERRATION_IDS) + board([BEAST_IDS[0], BEAST_IDS[0]])
        comps = {"beasts-lobstah": {"name": "Beasts - Tasty Lobstah",
                                    "tribe": "Beast",
                                    "core": [BEAST_IDS[0]], "addons": []}}
        got = value.comp_target(b, comps)
        self.assertIsNotNone(got)
        self.assertEqual(got.get("tribe"), "Beast")


if __name__ == "__main__":
    unittest.main()
