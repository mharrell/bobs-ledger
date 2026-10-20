"""The README's claims about the CODE, checked in both directions.

The project notes' item 3 has carried this as an open item since 2026-10-05: the README's
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
    """Both directions, for the set that replaced the deleted one.

    REINSTATED 2026-10-19. The class was deleted on 2026-10-15 with the pictures
    ("Let's remove the images as well, as they're out of date. I'll get new ones
    eventually") and its tombstone asserted the opposite of what is now true —
    that `docs/` was gone and the README showed no picture. Three days later the
    new set landed under `docs/screenshots/` and the README showed six of them,
    which left that tombstone failing on EVERY platform while the pairing went
    unchecked in both directions. A red test nobody reads is the same as no test,
    so the check comes back rather than being skipped: this is the class CLAUDE.md
    means when it says a picture is a claim nothing else checks.

    Both directions, for the reason the original gave: four pre-pivot shots
    shipped in two releases before anyone noticed, so "the README shows a picture
    that is not there" and "a picture ships that nothing can reach" are both
    failures, not just the first.
    """

    #: What counts as a picture in `docs/`. A new format has to be added here
    #: deliberately, which is the point — the other direction walks the folder.
    PICTURES = (".png", ".jpg", ".jpeg", ".webp", ".gif")

    def _shown(self):
        with open(README, encoding="utf-8") as fh:
            text = fh.read()
        # Markdown links only. An `<img>` tag would be a second way to show a
        # picture that a markdown scan cannot see, so it is refused rather than
        # silently ignored.
        self.assertNotIn("<img", text,
                         "the README shows a picture with an <img> tag; this "
                         "check reads markdown image links")
        return [os.path.normpath(p) for p in
                re.findall(r"!\[[^\]]*\]\(([^)\s]+)", text)]

    def _in_the_tree(self):
        found = []
        for base, _dirs, files in os.walk(os.path.join(ROOT, "docs")):
            for name in files:
                if name.lower().endswith(self.PICTURES):
                    found.append(os.path.normpath(
                        os.path.relpath(os.path.join(base, name), ROOT)))
        return sorted(found)

    def test_every_picture_the_readme_shows_exists(self):
        shown = self._shown()
        self.assertTrue(shown, "the README shows no picture at all")
        for rel in shown:
            self.assertTrue(
                os.path.exists(os.path.join(ROOT, rel)),
                f"the README shows {rel}, which is not in the tree")

    def test_every_picture_in_the_tree_is_shown_by_the_readme(self):
        shown = set(self._shown())
        pictures = self._in_the_tree()
        self.assertTrue(pictures, "docs/ holds no picture at all")
        for rel in pictures:
            self.assertIn(rel, shown,
                          f"{rel} ships but no README line shows it — a picture "
                          "no reader can reach is dead weight in a download")

    def test_every_picture_is_one_of_the_two_pages(self):
        """The set is named, so a stray screenshot cannot ride along unnoticed.

        Deliberately NOT a count: the maintainer adds shots as screens change, and
        a count would fail on the correct edit and pass on a wrong swap. What is
        pinned is that every picture belongs to one of the two pages the product
        has, and that no pre-pivot name (the ones the deleted set used) is back.
        """
        stale = {"save-replay", "turn-shop", "turn-battle", "turn-result",
                 "settle-up"}
        for rel in self._in_the_tree():
            name = os.path.basename(rel)
            self.assertTrue(
                name.startswith(("another-round-", "settle-up-")),
                f"{rel} is neither an Another Round nor a Settle Up shot")
            stem = os.path.splitext(name)[0]
            self.assertNotIn(stem, stale,
                             f"{rel} is a pre-pivot shot that shipped in two "
                             "releases before anyone noticed")


if __name__ == "__main__":
    unittest.main()
