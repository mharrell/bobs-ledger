"""Trinket meta integrity: log-id addressing + offered-trinket coverage.

The 2026-09-16 Reno game exposed it: BOTH the player's trinkets (Flaming
Portrait BG35_MagicItem_156, Minion Bait BG30_MagicItem_973) were absent
from the DB — the manual paste had hsreplay's old 4-digit id space while
the log speaks 3-digit ids — so the Greater pick was ranked on raw stats
alone and recommended Timeworn Candelabra over the engine-perfect
Flaming Portrait. refresh_trinkets.py rebuilds the DB with log ids;
these tests keep it that way.
"""
import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import meta  # noqa: E402


class TestLogIdAddressing(unittest.TestCase):
    """The DB must be addressed by the ids the LOG actually prints."""

    def test_reno_game_trinkets_present_by_log_id(self):
        """The two trinkets of the 2026-09-16 win, pinned by log id."""
        by_id = {t["id"]: t for t in meta.trinkets()}
        for cid, name in (("BG35_MagicItem_156", "Flaming Portrait"),
                          ("BG30_MagicItem_973", "Minion Bait")):
            self.assertIn(cid, by_id, f"{name} missing from trinkets DB")
            self.assertEqual(by_id[cid]["name"], name)
            self.assertTrue(by_id[cid].get("description"),
                            f"{name} has no description")

    def test_sous_chef_under_log_id(self):
        """The original drift case: log printed BG35_MagicItem_801, the
        paste had ..._8012. The log id is the one that must resolve."""
        ids = {t["id"] for t in meta.trinkets()}
        self.assertIn("BG35_MagicItem_801", ids)
        self.assertNotIn("BG35_MagicItem_8012", ids)

    def test_flaming_portrait_annotated_as_elemental(self):
        """The pick ranker's synergy term must see the Enforcer amp as an
        Elemental trinket — that's what should have won the 09-16 pick."""
        ann = meta.trinket_effects()
        rec = ann.get("BG35_MagicItem_156")
        self.assertIsNotNone(rec, "Flaming Portrait has no curated read")
        self.assertIn("Elemental", rec.get("synergy", {}).get("tribes", []))


@unittest.skipUnless(
    os.environ.get("HEARTH_REAL_SESSION_TESTS") == "1",
    "reads the newest local logs, so it goes red on any machine that has "
    "played since the last trinket refresh — a real gap reported in the wrong "
    "place. The live check now lives in `doctor.py` (check 'trinkets'), where "
    "the remedy is one line away; `refresh_trinkets.unrecorded` is unit-tested "
    "below without logs. Set HEARTH_REAL_SESSION_TESTS=1 to drive this too.")
class TestOfferedCoverage(unittest.TestCase):
    """Every trinket any local session ever OFFERED or GRANTED must be in the
    DB by its log id.

    Determinism: gated on HEARTH_REAL_SESSION_TESTS because the input is the
    newest logs on this machine. See doctor.check_unrecorded_trinkets for the
    always-on version of this check."""

    CHOICE_OPT = re.compile(
        r"DebugPrintEntityChoices.*?cardId=(BG\d+_MagicItem_\w+)")

    def test_all_offered_trinkets_in_db(self):
        import json
        offered = set()
        logs = sorted(glob.glob(os.path.join(
            r"C:\Program Files (x86)\Hearthstone\Logs",
            "Hearthstone_*", "Power.log")), key=os.path.getmtime,
            reverse=True)[:6]
        if not logs:
            self.skipTest("no Hearthstone session log found")
        for path in logs:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = self.CHOICE_OPT.search(line)
                    if m:
                        offered.add(m.group(1))
        if not offered:
            self.skipTest("no trinket offers in recent logs")
        ids = {t["id"] for t in meta.trinkets()}
        missing = sorted(offered - ids)
        self.assertFalse(
            missing, f"trinkets offered in logs but absent from DB: {missing}")

    #: Any trinket id the log prints, not only the ones in a choice list. The
    #: offered-only rule above passed for months while 13 trinkets that were
    #: GRANTED (not offered) went unrecorded — a granted trinket still drives
    #: stats and still shows in the overlay, and choices.py can only rank what
    #: this DB knows.
    SEEN_ANY = re.compile(r"cardId=(BG\d+_MagicItem_\w+)")

    def test_every_trinket_seen_in_a_log_is_in_the_db(self):
        logs = sorted(glob.glob(os.path.join(
            r"C:\Program Files (x86)\Hearthstone\Logs",
            "Hearthstone_*", "Power.log")), key=os.path.getmtime,
            reverse=True)[:6]
        if not logs:
            self.skipTest("no Hearthstone session log found")
        seen = set()
        for path in logs:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    seen.update(self.SEEN_ANY.findall(line))
        if not seen:
            self.skipTest("no trinket ids in recent logs")
        ids = {t["id"] for t in meta.trinkets()}
        # `...e` is the trinket's own enchantment, not a trinket: BG36_MagicItem_403e
        # is the aura Hammer of Twilight applies. `...e2` is the same thing as a
        # second/premium enchantment: BG35_MagicItem_740e2 is the golden
        # Deathrattle Sky Golem Portrait gives your minions. The base must be
        # known, which is what makes the exemption safe rather than a blanket
        # suffix skip. Anything else is a gap UNLESS it is recorded in
        # meta/patch_gaps.json as deliberately not carried (BG30_MagicItem_442t
        # is the Blood Golem TOKEN its sticker summons) — the registry keeps the
        # evidence, so a new token-shaped id still fails here.
        from logquery import _answered_gaps
        recorded = _answered_gaps()

        def own_enchantment(cid):
            m = re.search(r"e\d*$", cid)
            return bool(m) and cid[:m.start()] in ids

        missing = sorted(c for c in seen - ids - recorded
                         if not own_enchantment(c))
        self.assertFalse(
            missing, f"trinkets seen in logs but absent from DB: {missing}")


class TestUnrecordedTrinketLogic(unittest.TestCase):
    """The coverage check's exemption reasoning, without any logs.

    `refresh_trinkets.unrecorded` is what `doctor.py` and the live tests both
    call, so these pin the rules that decide what counts as a gap: an
    enchantment is only exempt when its BASE is recorded, a registered gap is
    exempt, and anything else is reported.
    """

    def _u(self, seen, recorded, gaps=()):
        import refresh_trinkets
        return refresh_trinkets.unrecorded(seen, recorded, gaps)

    def test_a_recorded_id_is_not_a_gap(self):
        self.assertEqual(self._u({"BG32_MagicItem_892"},
                                 {"BG32_MagicItem_892"}), [])

    def test_an_unrecorded_id_is_a_gap(self):
        self.assertEqual(self._u({"BG35_MagicItem_753"}, set()),
                         ["BG35_MagicItem_753"])

    def test_own_enchantment_is_exempt_only_when_its_base_is_recorded(self):
        # BG36_MagicItem_403e is the aura Hammer of Twilight applies.
        self.assertEqual(
            self._u({"BG36_MagicItem_403e"}, {"BG36_MagicItem_403"}), [])
        # ...and the same id IS a gap when the base went missing, which is
        # what makes this an exemption rather than a suffix skip.
        self.assertEqual(
            self._u({"BG36_MagicItem_403e"}, set()),
            ["BG36_MagicItem_403e"])

    def test_second_premium_enchantment_is_exempt_the_same_way(self):
        self.assertEqual(
            self._u({"BG35_MagicItem_740e2"}, {"BG35_MagicItem_740"}), [])

    def test_a_registered_gap_is_exempt(self):
        self.assertEqual(
            self._u({"BG30_MagicItem_442t"}, set(), {"BG30_MagicItem_442t"}),
            [])

    def test_results_are_sorted_and_deduplicated(self):
        self.assertEqual(
            self._u({"BG35_MagicItem_9", "BG35_MagicItem_1"}, set()),
            ["BG35_MagicItem_1", "BG35_MagicItem_9"])

    def test_real_db_has_no_unrecorded_ids_in_its_own_annotations(self):
        """Cheap always-on invariant: every DECLARED trinket is also
        annotated, so the ranker's synergy table and the DB cannot drift."""
        ids = {t["id"] for t in meta.trinkets() if t.get("id")}
        annotated = set(meta.trinket_effects()) - {"_comment"}
        self.assertEqual(ids - annotated, set(), "unannotated trinkets")
        self.assertEqual(annotated - ids, set(), "orphan annotations")


if __name__ == "__main__":
    unittest.main()
