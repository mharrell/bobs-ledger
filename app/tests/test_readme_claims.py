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


if __name__ == "__main__":
    unittest.main()
