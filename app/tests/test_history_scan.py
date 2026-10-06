"""The history scan: what was committed once and is still in the repository.

The release gate scans the ZIP, so a value that was committed and later replaced
with a placeholder passes every gate AND stays in a public repository forever.
These tests pin the tool that answers the second question, and they pin it
against real git repositories in a temp directory rather than mocked output --
the whole point is what git actually keeps.

The handle is built at RUNTIME (`"No" + "body"`) rather than written down: this
file ships, and a handle-shaped literal in a shipped file is exactly what
privacy_scan is for. `SomeBody#1234` is written down because it is one of the
documented placeholders -- and the test that it is NOT reported is what keeps
the detector honest about the difference.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
for path in (APP, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import history_scan  # noqa: E402
import privacy_scan  # noqa: E402

#: A tag-shaped value that is NOT a documented placeholder, assembled so the
#: text of this file does not contain one.
HANDLE = "No" + "body"
TAG = HANDLE + "#" + "12" + "34"
PLACEHOLDER_TAG = "SomeBody#1234"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True).stdout


class _Repo(unittest.TestCase):
    """A throwaway git repository with a commit helper."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = self._td.name
        self.addCleanup(self._td.cleanup)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "commit.gpgsign", "false")

    def commit(self, name, text, message="wip"):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)


class TestHistoryVsWorkingTree(_Repo):

    def test_a_value_removed_later_is_still_reported(self):
        """The failure this tool exists for: the gate passed, the file is clean
        today, and the tag is still readable by anyone who clones."""
        self.commit("notes.md", f"played vs {TAG} today\n", "leak it")
        self.commit("notes.md", "played vs SomeBody#1234 today\n", "sanitize it")
        findings = history_scan.scan(self.repo)
        self.assertEqual([f["category"] for f in findings], ["battletag"])
        self.assertEqual(findings[0]["value"], TAG)
        self.assertFalse(findings[0]["in_head"],
                         "the current file is clean, which is the whole point")
        self.assertTrue(findings[0]["added_by"],
                        "it should say which commit let it in")

    def test_a_value_still_in_the_tree_is_marked_live(self):
        self.commit("notes.md", f"played vs {TAG} today\n")
        findings = history_scan.scan(self.repo)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["in_head"])

    def test_a_documented_placeholder_is_not_reported(self):
        """Without this, a scanner that flagged every tag-shaped string would
        pass the tests above while being useless."""
        self.commit("notes.md", f"played vs {PLACEHOLDER_TAG} today\n")
        self.assertEqual(history_scan.scan(self.repo), [])

    def test_identical_files_are_one_blob_but_both_paths_are_named(self):
        """git stores identical content once, so two fixtures with the same text
        are a single object with a single path attached. A report built from
        `rev-list --objects` alone names one of them and drops the other, which
        is how this tool's own test found that bug."""
        self.commit("a.md", f"vs {TAG}\n")
        self.commit("b.md", f"vs {TAG}\n")
        findings = history_scan.scan(self.repo)
        self.assertEqual(sorted(f["path"] for f in findings), ["a.md", "b.md"])
        self.assertEqual({f["blobs"] for f in findings}, {1},
                         "both rows are the same single blob")

    def test_an_unchanged_line_across_many_edits_is_one_place(self):
        """A file edited repeatedly re-stores its blob each time; reporting one
        row per blob would turn one line into a wall of findings."""
        self.commit("notes.md", f"vs {TAG}\n", "one")
        for i in range(4):
            self.commit("notes.md", f"vs {TAG}\nand a change {i}\n", f"edit {i}")
        findings = history_scan.scan(self.repo)
        self.assertEqual(len(findings), 1, "one value, one file, one row")
        self.assertEqual(findings[0]["blobs"], 5, "five blobs carried it")

    def test_different_files_with_different_text_are_two_findings(self):
        self.commit("a.md", f"vs {TAG} in the morning\n")
        self.commit("b.md", f"vs {TAG} at night\n")
        findings = history_scan.scan(self.repo)
        self.assertEqual(len(findings), 2)
        self.assertEqual(sorted(f["path"] for f in findings), ["a.md", "b.md"])

    def test_binary_blobs_are_left_alone(self):
        """Card art in this repo is committed and its compressed bytes can
        contain a tag-shaped token by chance — four real PNGs do (2026-10-07,
        which is also how the first version of this docstring tripped the
        release gate: writing the shape out literally reads as a real handle
        in a shipped file)."""
        path = os.path.join(self.repo, "art.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + TAG.encode() + b"\x00" * 32)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "art")
        self.assertEqual(history_scan.scan(self.repo), [])


class TestTheReportMasksByDefault(unittest.TestCase):

    def test_mask_keeps_the_shape_and_hides_the_name(self):
        masked = history_scan.mask(TAG)
        self.assertNotIn(HANDLE, masked)
        self.assertEqual(len(masked), len(TAG))
        self.assertTrue(masked.startswith("No"))

    def test_a_short_value_is_masked_entirely(self):
        self.assertEqual(history_scan.mask("ab"), "**")

    def test_the_default_report_hides_the_value_full_does_not(self):
        findings = [{"category": "battletag", "value": TAG, "path": "x.md",
                     "paths": ["x.md"], "blobs": 1, "in_head": True,
                     "added_by": ["abc wip"]}]
        import contextlib
        import io as _io
        plain, full = _io.StringIO(), _io.StringIO()
        with contextlib.redirect_stdout(plain):
            history_scan.report(findings)
        with contextlib.redirect_stdout(full):
            history_scan.report(findings, full=True)
        self.assertNotIn(HANDLE, plain.getvalue())
        self.assertIn(TAG, full.getvalue())


class TestItUsesTheProjectsOwnVerifier(unittest.TestCase):
    """A second set of patterns would be a second thing to keep in step, and
    the gate's verifier is deliberately independent of the redactor."""

    def test_it_calls_privacy_scan_rather_than_its_own_patterns(self):
        import inspect
        source = inspect.getsource(history_scan)
        self.assertIn("privacy_scan.find(", source)
        self.assertNotIn("re.compile(", source,
                         "history_scan must not carry patterns of its own")

    def test_the_two_agree_on_a_sample(self):
        sample = f"line vs {TAG} and a PlayerName={HANDLE}\n"
        self.assertEqual(sorted(privacy_scan.find(sample)),
                         ["battletag", "player_name"])


if __name__ == "__main__":
    unittest.main()
