"""check_meta.py must pass on the committed meta/ — the regression guard for
the tribe-vocabulary bug and comps schema gaps."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


if __name__ == "__main__":
    unittest.main()