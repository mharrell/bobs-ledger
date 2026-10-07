"""The README's claims about the CODE, checked in both directions.

CLAUDE.md item 3 has carried this as an open item since 2026-10-05: the README's
"Is this allowed?" section tells a player what the coach does and does not do to
their machine, and two of its sentences are load-bearing —

    it "does not touch the game's process or its memory"
    it "does not automate input"

Both were verified by hand with a grep before they were written, and a grep run
once is not a control. The failure it guards against is the `Clear` failure mode
in the one place a player goes to decide whether to trust the thing: a future
branch adds a memory or input path, and the README goes on asserting the
opposite of the truth. The example is not hypothetical for THIS repository —
Warden-style detection is exactly what a reader is worried about, and the answer
"we read a text file the game writes to your own disk" is the whole argument.

So both halves are asserted, and breaking either side fails:

  * the README still makes the claims (a rewrite cannot quietly drop them);
  * the named APIs stay absent from `app/` (a new call cannot quietly break them).

The scan is over every text file under `app/` rather than only `*.py`, because
the README's claim is about the program, and a capability could arrive in a
.cmd, a .command or a JS file just as easily.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
ROOT = os.path.dirname(HERE)

README = os.path.join(ROOT, "README.md")

#: The sentences that must survive any README rewrite. Matched on the paragraph
#: with whitespace collapsed, because the README wraps its lines.
CLAIMS = (
    "does not touch the game's process or its memory",
    "does not automate input",
    "reads the log file Hearthstone writes to your own disk",
)

#: Capabilities that would make those claims false. Named as the APIs a Windows
#: implementation would actually call, not as concepts: "memory" appears in this
#: codebase legitimately (Hearthstone's own "reads game memory" is not a thing we
#: do), so the list is deliberately concrete.
FORBIDDEN = (
    "SendInput", "SetCursorPos", "mouse_event", "keybd_event", "pyautogui",
    "OpenProcess", "ReadProcessMemory", "WriteProcessMemory",
    "CreateRemoteThread",
)

#: Skipped when scanning: compiled output and the vendored parser's own test
#: fixtures. `python-hslog/` is third-party code we ship but do not write; if it
#: ever grew one of these calls that would be worth learning about, but it is not
#: THIS repository's claim to have to make good on, and a vendored-tree failure
#: would be unactionable.
_SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", "python-hslog"}
_TEXT_EXT = {".py", ".js", ".cmd", ".command", ".md", ".json", ".html", ".sh"}


def _readme_text():
    with open(README, encoding="utf-8") as fh:
        return re.sub(r"\s+", " ", fh.read())


def _app_sources():
    """(relpath, text) for every text file under app/, this test excluded.

    This file is excluded because the assertMISSING list above is itself written
    in it: the control has to name what it forbids, so it cannot also be the
    thing it scans for.
    """
    me = os.path.abspath(__file__)
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == me:
                continue
            if os.path.splitext(name)[1].lower() not in _TEXT_EXT:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    # Forward slashes on every platform: the report below is read
                    # by a person, and a Windows-only separator made the
                    # live-path assertion in this file fail on the machine it
                    # was written on.
                    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                    yield rel, fh.read()
            except OSError:
                continue


class TestTheReadmeStillMakesItsClaims(unittest.TestCase):
    def test_every_claim_is_present(self):
        text = _readme_text()
        for claim in CLAIMS:
            self.assertIn(claim, text,
                          f"the README no longer claims: {claim!r}")


class TestTheCodeCannotMakeThemFalse(unittest.TestCase):
    def test_no_process_memory_or_input_api_in_app(self):
        hits = []
        for rel, text in _app_sources():
            for name in FORBIDDEN:
                if name in text:
                    line = next((i + 1 for i, ln in enumerate(text.splitlines())
                                 if name in ln), 0)
                    hits.append(f"{rel}:{line} {name}")
        self.assertEqual(hits, [],
                         "the README says this does not touch the game's process, "
                         "its memory, or synthetic input — these do:\n  "
                         + "\n  ".join(hits))

    def test_the_scan_actually_looks_at_the_live_path(self):
        """A control that cannot fail is not a control: package_corpus.inspect()
        scanned mojibake for weeks. This asserts the walk reaches the files the
        claim is about."""
        seen = {rel for rel, _text in _app_sources()}
        for required in ("app/live.py", "app/live_coach.py", "app/coach_ui.py",
                         "app/value.py"):
            self.assertIn(required, seen)


class TestTheScreenshotsMatchTheReadme(unittest.TestCase):
    """The README's pictures, in both directions.

    The four shots that used to live in `docs/` showed the pre-pivot overlay —
    `decide.png` was captioned "DO THIS NOW gives one buy with its reason", the
    panel the 2026-10-06 pivot deleted — and they SHIPPED in the `94a07de` and
    `2ef006c` releases before anyone noticed. A picture is a claim about the
    layout, and nothing checked it: not a test, not a gate (`privacy_scan` reads
    TEXT_SUFFIXES, which no image has). So both halves are asserted now, the same
    shape as the claims above:

      * every `docs/...` image the README shows is really there (a rename or a
        deletion cannot leave a broken picture in the one document a player reads);
      * every file in `docs/` is shown BY the README (a shipped zip should carry
        no orphan: a picture no reader can reach is dead weight, and the old set
        rotted precisely because nothing tied the files to the text).

    What this CANNOT check is what a picture shows — a screenshot of a layout
    that no longer exists passes both. That is what CLAUDE.md's rule about
    re-shooting is for, and why the images are re-taken in the same change as the
    layout that moved.
    """

    DOCS = os.path.join(ROOT, "docs")

    def _referenced(self):
        with open(README, encoding="utf-8") as fh:
            return sorted(set(re.findall(r'<img src="(docs/[^"]+)"', fh.read())))

    def test_every_picture_the_readme_shows_exists(self):
        shown = self._referenced()
        self.assertTrue(shown, "the README no longer shows any picture — if that "
                               "is deliberate, delete docs/ and this test with it")
        missing = [p for p in shown
                   if not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
        self.assertEqual(missing, [], f"the README points at missing images: {missing}")

    def test_no_screenshot_ships_that_the_readme_never_shows(self):
        if not os.path.isdir(self.DOCS):
            self.skipTest("no docs/ directory")
        on_disk = {"docs/" + n for n in os.listdir(self.DOCS)
                   if n.lower().endswith(".png")}
        orphans = sorted(on_disk - set(self._referenced()))
        self.assertEqual(orphans, [],
                         "these ship in the zip but appear in no README section: "
                         + ", ".join(orphans))


if __name__ == "__main__":
    unittest.main()
