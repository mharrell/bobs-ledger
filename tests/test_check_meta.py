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
        This is the red/green property that makes the validator a real guard."""
        import json
        import tempfile
        comps_path = os.path.join(HERE, "meta", "comps.json")
        with open(comps_path, encoding="utf-8") as f:
            original = f.read()
        comps = json.loads(original)
        for c in comps.values():
            if c.get("tribe") == "Elemental":
                c["tribe"] = "Elementals"
                bad = json.dumps(comps, indent=2, ensure_ascii=False)
                tmp = None
                try:
                    with open(comps_path, "w", encoding="utf-8") as f:
                        f.write(bad)
                    r = subprocess.run(
                        [sys.executable, "check_meta.py"], cwd=HERE,
                        capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(r.returncode, 1,
                                     "off-vocabulary comp tribe not caught")
                finally:
                    with open(comps_path, "w", encoding="utf-8") as f:
                        f.write(original)
                break
        else:
            self.fail("no Elemental comp found to corrupt — fixture stale")


if __name__ == "__main__":
    unittest.main()