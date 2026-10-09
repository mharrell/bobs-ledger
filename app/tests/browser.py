"""The headless-browser harness the layout tests share.

`node` runs the page's JS but lays nothing out, so any question of the form
"does the page actually render" needs a browser. These helpers load a document
in headless Chromium and read back what the page printed into `#out` through
`--dump-dom` — a headless run gives no other channel, and parsing a screenshot
would need the pixels read, which nothing here can do.

It lives in ONE place because two suites need it: the turn card's height
(`test_overlay_layout`, 2026-10-07) and the Tavern viewer's render
(`test_settle_browser`, 2026-10-08). Only the document differs; the launch, the
skip and the diagnosis are the same problem twice.

**A browser that cannot START is a SKIP, not a failure** (2026-10-08). A
restricted session can have `chrome.exe` on disk and still be refused the
process and pipe access Chromium needs — measured here: Chromium's crashpad
client reporting `Access is denied` on a process handle, followed by a mojo
`platform_channel` FATAL, on every launch variant tried including
`--single-process` and `--headless=old`. Reporting that as a broken page is a
red herring: the artifact is fine and the environment is not, and a red herring
is how a real regression gets ignored. So `run()` distinguishes the two from the
OUTPUT rather than from a wish:

* no DOM at all came back — the browser never started → `BrowserUnavailable`,
  which the tests turn into a skip that quotes what the browser said;
* a DOM came back but the page misbehaved (no `#out`, a JS error the document
  captured, a renderer that threw) → the test FAILS, as it should.

A skip is only honest if the tests can still fail where they run, which is why
every suite here carries a rehearsal: `test_overlay_layout` measures the OLD
structure and requires it to come out unequal, and `test_settle_browser` feeds
the renderer a rep it must report an error on.
"""
import os
import re
import shutil
import subprocess
import tempfile

#: Where a Chromium browser lives on this platform. Checked in order.
BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

#: The launcher's flags. `--no-sandbox` because a test has no business asking
#: for one, and a fixed user-data-dir so two runs cannot share a profile.
#:
#: `run()` decodes the DOM as UTF-8 EXPLICITLY. `text=True` alone uses the
#: locale encoding, which on a Windows console is cp1252 — and `--dump-dom`
#: emits the page's own typography (em dashes, arrows, the card-art placeholders
#: and their glyphs). Measured 2026-10-08: the reader thread died with
#: `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d` on a 106 KB DOM,
#: which surfaced as "no output and no error" — a browser that had in fact run
#: perfectly. A one-line bug that only appears once the page contains a
#: character cp1252 lacks.
_FLAGS = ("--headless=new", "--disable-gpu", "--no-sandbox")


class BrowserUnavailable(RuntimeError):
    """Chromium is installed but this session cannot start it.

    Callers turn this into a skip: it says nothing about the artifact.
    """


def browser():
    """The Chromium binary to use, or None when the machine has none."""
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def require_browser(case):
    """Skip `case` when there is no browser at all, and return the path."""
    exe = browser()
    if exe is None:
        case.skipTest("no Chromium browser on this machine, so the page cannot "
                      "be laid out")
    return exe


def run(doc, timeout=120):
    """Load `doc` in headless Chromium; return the DOM it ended up with.

    Raises `BrowserUnavailable` when the browser never produced a document —
    the only honest reading of "it was installed and did not run".
    """
    exe = browser()
    if exe is None:
        raise BrowserUnavailable("no Chromium browser on this machine")
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(doc)
        proc = subprocess.run(
            [exe, *_FLAGS,
             f"--user-data-dir={os.path.join(tmp, 'profile')}",
             "--dump-dom", "file:///" + page.replace(os.sep, "/")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
    out = proc.stdout or ""
    if "<html" not in out.lower():
        lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
        raise BrowserUnavailable(
            "the browser is installed but could not start here: "
            + (lines[-1][:200] if lines else
               f"no document came back (exit {proc.returncode}, "
               f"{len(out)} bytes of stdout)"))
    return out


def numbers(doc, timeout=120):
    """The ints the page printed into `#out`, as a dict.

    ints, not the strings the page printed: a string comparison would make
    `assertGreater` raise and every equality check pass on the text.
    """
    m = re.search(r'id="out">([^<]*)<', run(doc, timeout))
    if not m:
        raise AssertionError("the page ran but printed no #out — the harness "
                             "document has to carry one")
    return {part.split("=")[0]: int(part.split("=")[1])
            for part in m.group(1).split()}


def fields(doc, timeout=120):
    """The `key=value` pairs the page printed into `#out`, values as text.

    A value the page marked with a leading `#` (that is what `fields` uses for
    a count) comes back as an int, so a test can say `assertEqual(n, 2)` rather
    than comparing against `'2'`. Everything else — words, sizes like `130x172`
    — stays text.
    """
    m = re.search(r'id="out">([^<]*)<', run(doc, timeout))
    if not m:
        raise AssertionError("the page ran but printed no #out — the harness "
                             "document has to carry one")
    out = {}
    for part in m.group(1).split(" ;; "):
        if not part.strip():
            continue
        key, _, value = part.partition("=")
        value = value.strip()
        if value.startswith("#"):
            out[key.strip()] = int(value[1:])
        else:
            out[key.strip()] = value
    return out
