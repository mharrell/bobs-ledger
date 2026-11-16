"""The trinket-history API join: id-keyed, missing-only by default.

No network here: `plan` is pure, and the file round-trip uses the shipped
document so a formatting regression (the file is indent=1/CRLF/no trailing
newline) is caught without hitting hsreplay.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import trinket_history as th  # noqa: E402


def _rec(cid, pick=None, avg=None):
    return {"id": cid, "name": "T" + cid, "pick_rate": pick,
            "avg_placement": avg}


def _row(dbf, pick, avg, dist=None):
    return {"trinket_dbf_id": dbf, "pick_rate": pick,
            "avg_final_placement": avg,
            "final_placement_distribution": dist or [10, 11, 12, 13, 14, 15,
                                                     16, 9]}


class TestDistribution(unittest.TestCase):
    def test_maps_eight_places(self):
        self.assertEqual(
            th.distribution([1, 2, 3, 4, 5, 6, 7, 8]),
            {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0,
             "5": 5.0, "6": 6.0, "7": 7.0, "8": 8.0})

    def test_rejects_a_short_list(self):
        self.assertIsNone(th.distribution([1, 2, 3]))

    def test_rejects_non_numeric(self):
        self.assertIsNone(th.distribution(["x"] * 8))


class TestPlan(unittest.TestCase):
    def test_missing_only_is_the_default(self):
        recs = [_rec("A"), _rec("B", 20.0, 4.0)]
        rows = [_row(1, 21.0, 4.1), _row(2, 22.0, 4.2)]
        out = th.plan(recs, rows, {"A": 1, "B": 2})
        self.assertEqual([r["id"] for r, _ in out["updates"]], ["A"])
        self.assertEqual(out["updates"][0][1]["pick_rate"], 21.0)

    def test_all_refreshes_a_row_that_already_has_history(self):
        recs = [_rec("B", 20.0, 4.0)]
        rows = [_row(2, 22.0, 4.2)]
        out = th.plan(recs, rows, {"B": 2}, refresh_all=True)
        self.assertEqual(len(out["updates"]), 1)
        self.assertEqual(out["updates"][0][1]["avg_placement"], 4.2)

    def test_the_join_is_by_dbf_id_not_name(self):
        recs = [_rec("A"), _rec("B")]
        rows = [_row(11, 1.0, 1.0), _row(22, 2.0, 2.0)]
        out = th.plan(recs, rows, {"A": 22, "B": 11})
        got = {r["id"]: ch["pick_rate"] for r, ch in out["updates"]}
        self.assertEqual(got, {"A": 2.0, "B": 1.0})

    def test_a_record_with_no_api_row_is_left_alone(self):
        out = th.plan([_rec("A")], [], {"A": 1})
        self.assertEqual(out["updates"], [])
        self.assertEqual(out["no_row"], ["A"])

    def test_a_malformed_distribution_is_not_written(self):
        recs = [_rec("A")]
        rows = [_row(1, 21.0, 4.0, dist=[1, 2, 3])]
        out = th.plan(recs, rows, {"A": 1})
        changed = out["updates"][0][1]
        self.assertNotIn("placement_distribution", changed)
        self.assertEqual(changed["pick_rate"], 21.0)

    def test_apply_updates_in_place(self):
        recs = [_rec("A")]
        rows = [_row(1, 21.0, 4.1)]
        out = th.plan(recs, rows, {"A": 1})
        th.apply_updates(out["updates"])
        self.assertEqual(recs[0]["pick_rate"], 21.0)
        self.assertEqual(recs[0]["avg_placement"], 4.1)
        self.assertEqual(recs[0]["placement_distribution"]["8"], 9.0)


class TestFileFormatting(unittest.TestCase):
    def test_a_round_trip_does_not_reformat_the_shipped_file(self):
        doc, fmt = th.load_trinkets()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "trinkets.json")
            th.save_trinkets(doc, fmt, path=out)
            with open(out, "rb") as f:
                got = f.read()
            with open(th.TRINKETS_PATH, "rb") as f:
                want = f.read()
        self.assertEqual(got, want, "indent/EOL/trailing newline drifted")
