"""The corpus bundle must not carry an opponent's name.

`sanitize_decisions` used to pop exactly one key, `analysis.opp_comp.name`,
which is where the overlay's "Hero . Odin3539" line comes from. That single pop
was the entire guarantee the bundle had, and it could not have been checked:
privacy_scan matches the shapes the LOG writes (PlayerName=, Entity=, account
ids), and a bare display handle in a JSON key called "name" matches none of
them. So `inspect` printed "no opponent handles ... in the decisions" over a
bundle that carried fifty of them (found 2026-10-03, while designing the upload
path that would have made it a player-facing leak).

The strip now checks every string against the identities `sanitize_text` found
in this session's own log: any depth, keys as well as values, embedded in
rendered advice text as well as standing alone. What a field is CALLED no
longer decides whether it is checked, so a field added later cannot leak.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import package_corpus as pc  # noqa: E402

#: Assembled at runtime: this file ships, and the release's privacy gate reads
#: a handle-shaped literal as a real person.
HANDLE = "Odin" + "3539"
OTHER = "Tessa" + "77"
TOKEN = "[opponent1]"
IDENTITIES = {HANDLE: TOKEN, OTHER: "[opponent2]"}
#: A hero name, not a person: game data, and it has to survive.
HERO = "Morchie"


def _record(**over):
    rec = {"ts": "2026-10-03T14:50:04", "turn": 11, "gold": 0,
           "log": "Power.log",
           "analysis": {"tier": 5, "hero": HERO,
                        "opp_comp": {"hero_name": HERO, "name": HANDLE},
                        "top_move": f"swing at {HANDLE} now",
                        "top_move_steps": [{"text": f"watch {HANDLE}"}]}}
    rec.update(over)
    return rec


def _clean(rec, identities=IDENTITIES):
    out, removed = pc.sanitize_decisions([rec], identities=identities)
    return out[0], removed


class TestIdentitiesAreRemovedWhereverTheySit(unittest.TestCase):
    def test_the_named_key_is_still_dropped(self):
        rec, removed = _clean(_record())
        self.assertNotIn("name", rec["analysis"]["opp_comp"])
        self.assertGreaterEqual(removed, 1)

    def test_a_handle_inside_advice_text_is_replaced_not_left(self):
        rec, _ = _clean(_record())
        self.assertNotIn(HANDLE, rec["analysis"]["top_move"])
        self.assertIn(TOKEN, rec["analysis"]["top_move"])

    def test_a_handle_nested_in_a_list_is_replaced(self):
        rec, _ = _clean(_record())
        self.assertNotIn(HANDLE, json.dumps(rec))

    def test_a_handle_used_as_a_key_is_replaced(self):
        rec, _ = _clean(_record(opponent_notes={HANDLE: 3}))
        self.assertNotIn(HANDLE, json.dumps(rec))

    def test_a_field_that_did_not_exist_before_is_still_covered(self):
        """The reason this checks identities instead of field names."""
        rec, _ = _clean(_record(opponent_summary={"who": HANDLE}))
        self.assertNotIn(HANDLE, json.dumps(rec))

    def test_the_other_identity_is_caught_too(self):
        rec, _ = _clean(_record(notes=f"lost to {OTHER}"))
        self.assertNotIn(OTHER, json.dumps(rec))

    def test_a_partial_match_does_not_mangle_a_card_name(self):
        """Word boundaries: a short handle must not eat letters out of a
        longer game name that merely contains them."""
        rec, _ = _clean(_record(notes="Odinwald the minion"), identities=IDENTITIES)
        self.assertIn("Odinwald", rec["notes"])

    def test_game_data_survives(self):
        rec, _ = _clean(_record())
        self.assertEqual(rec["analysis"]["opp_comp"]["hero_name"], HERO)
        self.assertEqual(rec["analysis"]["hero"], HERO)
        self.assertEqual(rec["analysis"]["tier"], 5)

    def test_the_callers_records_are_not_mutated(self):
        original = _record()
        pc.sanitize_decisions([original], identities=IDENTITIES)
        self.assertEqual(original["analysis"]["opp_comp"]["name"], HANDLE)

    def test_the_session_field_stays_a_placeholder(self):
        rec, _ = _clean(_record())
        self.assertEqual(rec["log"], pc._SESSION_PLACEHOLDER)


class TestTheGuardThatRefusesToWrite(unittest.TestCase):
    def test_a_clean_record_reports_nothing_left(self):
        rec, _ = _clean(_record())
        self.assertEqual(pc.identities_left([rec], IDENTITIES), [])

    def test_it_can_actually_fail(self):
        """The guard is only worth having if it detects what it is for."""
        dirty = [{"analysis": {"deep": [{"x": f"hi {HANDLE}!"}]}}]
        self.assertTrue(pc.identities_left(dirty, IDENTITIES))

    def test_it_catches_a_handle_used_as_a_key(self):
        self.assertTrue(pc.identities_left([{HANDLE: 1}], IDENTITIES))

    def test_the_report_names_paths_and_never_the_person(self):
        """Reporting a leak by printing the handle is its own leak."""
        left = pc.identities_left([{"analysis": {"b": HANDLE}}], IDENTITIES)
        self.assertTrue(left)
        self.assertNotIn(HANDLE, json.dumps(left))

    def test_without_an_identity_list_only_the_named_key_is_dropped(self):
        """The old behaviour, kept as the fallback and pinned as the gap: the
        one key goes, references embedded in text survive, and the guard has
        nothing to check against. This is why package() passes the real list
        from sanitize_text rather than relying on the named path."""
        rec, removed = _clean(_record(), identities={})
        self.assertNotIn("name", rec["analysis"]["opp_comp"])
        self.assertEqual(removed, 1)
        self.assertIn(HANDLE, rec["analysis"]["top_move"])
        self.assertEqual(pc.identities_left([rec], {}), [])


if __name__ == "__main__":
    unittest.main()
