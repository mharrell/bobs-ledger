"""check_meta.py must pass on the committed meta/ — the regression guard for
the tribe-vocabulary bug and comps schema gaps."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


class TestCheckMeta(unittest.TestCase):
    def test_validator_passes_on_committed_meta(self):
        r = subprocess.run([sys.executable, "check_meta.py"], cwd=HERE,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0,
                         f"check_meta.py failed:\n{r.stderr}\n{r.stdout}")

    def test_validator_catches_off_vocabulary_tribes(self):
        """Feed it a comps.json with the legacy plural vocabulary -> exit 1.
        This is the red/green property that makes the validator a real guard.
        The corrupted copy lives in a tempdir — the committed meta/ is never
        rewritten (a crash mid-test used to corrupt the repo's comps.json)."""
        import json
        import shutil
        import tempfile
        comps_path = os.path.join(HERE, "meta", "comps.json")
        with open(comps_path, encoding="utf-8") as f:
            comps = json.load(f)
        for c in comps.values():
            if c.get("tribe") == "Elemental":
                c["tribe"] = "Elementals"
                break
        else:
            self.fail("no Elemental comp found to corrupt — fixture stale")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(os.path.join(HERE, "meta"), os.path.join(tmp, "meta"))
            for fn in ("check_meta.py", "tribes.py"):
                shutil.copy(os.path.join(HERE, fn), os.path.join(tmp, fn))
            with open(os.path.join(tmp, "meta", "comps.json"), "w",
                      encoding="utf-8") as f:
                json.dump(comps, f, indent=2, ensure_ascii=False)
            r = subprocess.run(
                [sys.executable, "check_meta.py"],
                cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1,
                             "off-vocabulary comp tribe not caught")


class TestGuideTierClaim(unittest.TestCase):
    """A guide's provenance line quotes a tier, and the tier list moves.

    The 2026-10-04 refresh left three guides claiming a tier that no longer
    existed (`mechs-apm-magnetic` A->S, `murlocs-keyword` S->A,
    `aberrations-deathrattle-spells` S->B). All three were found by hand; this
    is the check that finds the fourth one.
    """

    def _run_with_mutated_meta(self, mutate):
        """Copy meta/ to a tempdir, mutate comps.json there, run check_meta."""
        import json
        import shutil
        import tempfile
        comps_path = os.path.join(HERE, "meta", "comps.json")
        with open(comps_path, encoding="utf-8") as f:
            comps = json.load(f)
        mutate(comps)
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(os.path.join(HERE, "meta"), os.path.join(tmp, "meta"))
            for fn in ("check_meta.py", "tribes.py"):
                shutil.copy(os.path.join(HERE, fn), os.path.join(tmp, fn))
            with open(os.path.join(tmp, "meta", "comps.json"), "w",
                      encoding="utf-8") as f:
                json.dump(comps, f, indent=2, ensure_ascii=False)
            return subprocess.run(
                [sys.executable, "check_meta.py"],
                cwd=tmp, capture_output=True, text=True, encoding="utf-8")

    def test_a_guide_claiming_a_moved_tier_is_reported(self):
        """Warning, not error: stale provenance is not broken data — but it
        must be SAID, and the message has to name the comp and the guide."""
        def mutate(comps):
            # the guide claims S; make the comp a B behind its back
            comp = comps["mechs-apm-magnetic"]
            self.assertEqual(comp["meta_tier"], "S", "fixture stale")
            comp["meta_tier"] = "B"
        r = self._run_with_mutated_meta(mutate)
        self.assertEqual(r.returncode, 0, f"a stale guide must not gate:\n{r.stderr}")
        self.assertIn("mechs-apm-magnetic", r.stderr)
        self.assertIn("still claims", r.stderr)
        self.assertIn("guides/mechs-apm-magnetic.md", r.stderr)

    def test_a_guide_that_is_not_there_is_reported(self):
        def mutate(comps):
            comps["menagerie"]["guide"] = "guides/does-not-exist.md"
        r = self._run_with_mutated_meta(mutate)
        self.assertEqual(r.returncode, 0)
        self.assertIn("names a guide that is not there", r.stderr)

    def test_the_committed_guides_and_tiers_agree_today(self):
        """The check has to start green, or it is noise nobody reads."""
        import check_meta
        warnings = []
        check_meta._guide_problems(check_meta._load("comps.json"), warnings)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()