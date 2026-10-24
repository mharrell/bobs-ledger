"""The maintainer inbox: verification, the index, and the three tables.

Nothing here touches the network. The transport is `fetch_sessions`/`wrangler`,
so both are replaced at the seam the module actually calls, and the fixtures are
built in memory — the same rule the rest of the suite follows for anything that
reads other people's data.
"""
import contextlib
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import report_corpus  # noqa: E402

#: Assembled at runtime, like test_privacy_gates: this file ships, and a
#: handle-shaped literal in it is exactly what the scanner would flag.
_HANDLE = "Stranger" + "#" + "9821"


def _report(manifest_over=None, advisories=None):
    manifest = {"created": "2026-10-24T10:00:00", "report_id": "abc123",
                "coach_version": "151b259", "coach_versions": ["151b259"],
                "advisories": 2, "games": 1, "opponent_names_dropped": 0,
                "placement": 3}
    manifest.update(manifest_over or {})
    return {"schema": 1, "manifest": manifest,
            "advisories": advisories or []}


def _adv(turn, ts, change, band="steady", kind="buy"):
    return {"schema": 1, "ts": ts, "game": 1, "turn": turn, "gold": 5,
            "tier": 3, "health": 20, "hp_change": change,
            "analysis": {"fragility": {"band": band},
                         "comp_progress": [],
                         "top_move_steps": [{"kind": kind, "card": "BG31_820"}]}}


def _write(out, rel, data):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(json.dumps(data).encode("utf-8"))
    return path


class _Inbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = self.tmp.name


class TestTheIndex(_Inbox):
    def test_a_report_with_an_unknown_field_is_refused_not_indexed(self):
        """The SPEC is the privacy control, so a field it does not name is a
        finding — the inbox must say so rather than file the report as data."""
        bad = _report()
        bad["manifest"]["surprise"] = "something nobody decided to send"
        _write(self.out, "2026-10-24/good.json.gz", _report())
        _write(self.out, "2026-10-24/bad.json.gz", bad)
        index, problems = report_corpus.build_index(self.out)
        self.assertEqual(len(index["reports"]), 1)
        self.assertEqual(index["refused"][0]["file"],
                         os.path.join("2026-10-24", "bad.json.gz"))
        self.assertIn("surprise", index["refused"][0]["why"])
        self.assertEqual(len(problems), 1)

    def test_the_index_names_what_the_tables_read(self):
        _write(self.out, "2026-10-24/one.json.gz",
               _report({"report_id": "r1", "placement": 2}))
        index, _ = report_corpus.build_index(self.out)
        row = index["reports"][0]
        self.assertEqual(row["report_id"], "r1")
        self.assertEqual(row["placement"], 2)
        self.assertEqual(row["coach_version"], "151b259")
        self.assertEqual(row["advisories"], 2)

    def test_a_file_that_is_not_a_gz_report_is_refused(self):
        path = os.path.join(self.out, "2026-10-24", "broken.json.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"not gzip at all")
        index, problems = report_corpus.build_index(self.out)
        self.assertEqual(index["reports"], [])
        self.assertIn("not a gz json", problems[0][1])


class TestTheTables(_Inbox):
    def test_the_fight_cost_is_read_at_the_last_advisory_of_a_turn(self):
        """Intra-turn re-reads are not fights: only the turn's LAST row is
        followed by one, so reading any row would count shopping as damage."""
        advs = [_adv(5, "t1", 0), _adv(5, "t2", 0), _adv(5, "t3", -7),
                _adv(6, "t4", -3)]
        _write(self.out, "2026-10-24/one.json.gz", _report(advisories=advs))
        t = report_corpus.tables(self.out)
        self.assertEqual(t["turns_seen"], 2)
        self.assertEqual(t["turns_with_cost"], 2)
        self.assertEqual(t["band"]["steady"]["n"], 2)
        self.assertEqual(t["band"]["steady"]["median"], -3.0)
        self.assertEqual(t["band"]["steady"]["mean_loss"], -5.0)

    def test_a_missing_outcome_is_counted_not_guessed(self):
        advs = [_adv(5, "t1", None), _adv(6, "t2", None)]
        _write(self.out, "2026-10-24/one.json.gz", _report(advisories=advs))
        t = report_corpus.tables(self.out)
        self.assertEqual(t["turns_with_cost"], 0)
        self.assertEqual(t["hp_change_none"], 2)
        self.assertEqual(t["band"], {})

    def test_the_commitment_cut_groups_by_placement_and_by_version(self):
        for i, (place, hits) in enumerate(((1, 5), (5, 2), (7, 1))):
            adv = _adv(9, "t", 0)
            adv["analysis"]["comp_progress"] = [
                {"name": "Comps", "tribe": "Beast", "hits": hits}]
            _write(self.out, f"2026-10-24/r{i}.json.gz",
                   _report({"report_id": f"r{i}", "placement": place,
                            "coach_version": "v1"}, advisories=[adv]))
        t = report_corpus.tables(self.out)
        self.assertEqual(t["by_place"]["1"]["median_hits"], 5)
        self.assertEqual(t["by_version"]["v1"], {
            "games": 3, "median_place": 5, "median_hits": 2})

    def test_plan_kinds_come_from_the_last_read_of_each_turn(self):
        advs = [_adv(5, "t1", 0, kind="level"), _adv(5, "t2", -2, kind="buy")]
        _write(self.out, "2026-10-24/one.json.gz", _report(advisories=advs))
        t = report_corpus.tables(self.out)
        self.assertEqual(t["kinds"], {"buy": 1})


class TestTheCorpusGate(_Inbox):
    def _bundle(self, log):
        return gzip.compress(json.dumps(
            {"log": log, "decisions": [], "manifest": {"created": "2026-10-24"}}
        ).encode("utf-8"))

    def test_a_surviving_handle_refuses_the_bundle(self):
        bundle, problems = report_corpus.check_bundle(
            self._bundle(f"a line naming {_HANDLE} in the log"))
        self.assertTrue(problems, "a bundle carrying a handle was accepted")
        self.assertIn("survived", problems[0])

    def test_a_clean_bundle_passes(self):
        bundle, problems = report_corpus.check_bundle(
            self._bundle("D 11:41:01 GameState.DebugPrintPower() - TAG_CHANGE"))
        self.assertEqual(problems, [])
        self.assertEqual(bundle["manifest"]["created"], "2026-10-24")

    def test_a_bundle_with_no_log_or_manifest_is_refused(self):
        _b, problems = report_corpus.check_bundle(
            gzip.compress(json.dumps({"decisions": []}).encode("utf-8")))
        self.assertIn("no log text", problems[0])
        self.assertIn("no manifest", problems[-1])

    def test_the_bundle_is_unpacked_where_the_review_can_reach_the_log(self):
        """`--corpus` is the "process any replay we receive" half: a verified
        bundle lands as JSON for the manifest and a .log for replay_review."""
        keys = ["corpus/corpus_20261024T101010.json.gz"]
        with mock.patch.object(report_corpus, "wrangler_keys", lambda prefix="corpus/": keys), \
                mock.patch.object(report_corpus, "wrangler_get",
                                  lambda key: self._bundle(
                                      "D 11:41:01 GameState.DebugPrintPower() - x")):
            stored, refused, skipped = report_corpus.collect_corpus(self.out)
        self.assertEqual((stored, refused, skipped), (1, [], 0))
        root = os.path.join(self.out, "corpus")
        names = sorted(os.listdir(root))
        self.assertEqual(names, ["corpus_20261024T101010.json",
                                 "corpus_20261024T101010.log"])
        index, _ = report_corpus.build_index(self.out)
        self.assertEqual(len(index["corpus"]), 1)
        self.assertEqual(index["corpus"][0]["created"], "2026-10-24")

        # A second run is idempotent: the bundle is already here.
        with mock.patch.object(report_corpus, "wrangler_keys", lambda prefix="corpus/": keys):
            stored, refused, skipped = report_corpus.collect_corpus(self.out)
        self.assertEqual((stored, skipped), (0, 1))


class TestTheCommands(_Inbox):
    def test_the_inbox_has_to_be_outside_the_checkout(self):
        """Other people's data in the working tree is how it ends up in a
        release: `publish_release` walks that tree."""
        repo = os.path.dirname(os.path.abspath(report_corpus._HERE))
        with self.assertRaises(SystemExit) as raised:
            report_corpus.main(["--out", os.path.join(repo, "sessions_in"),
                                "--tables"])
        self.assertIn("outside the checkout", str(raised.exception))

    def test_collect_without_a_key_says_what_to_set(self):
        with mock.patch.dict(os.environ, {"HEARTH_TELEMETRY_KEY": ""}):
            with self.assertRaises(SystemExit) as raised:
                report_corpus.collect_reports(self.out)
        self.assertIn("HEARTH_TELEMETRY_KEY", str(raised.exception))

    def test_tables_print_without_a_network(self):
        _write(self.out, "2026-10-24/one.json.gz",
               _report(advisories=[_adv(5, "t1", -4)]))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = report_corpus.main(["--out", self.out, "--tables"])
        self.assertEqual(code, 0)
        self.assertIn("FIGHT COST", buf.getvalue())
        self.assertIn("reports 1", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
