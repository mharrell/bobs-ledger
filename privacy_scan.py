#!/usr/bin/env python3
"""Independent personal-data detector for logs, bundles and releases.

This module is deliberately NOT the redactor. `sanitize_log` decides what
to remove; `privacy_scan` decides whether anything was missed — so that
"it's clean" is a measurement taken by different code than the one doing
the cleaning.

Why that matters (2026-10-02): the old check called `sanitize_text` on its
own output, so it certified bundles clean using exactly the regex that had
just failed to redact anything. It reported "0 unredacted BattleTags" on a
bundle shipping fifteen opponent handles.

The categories below are the WHOLE class, not the shape the redactor
happens to know:

  battletag     any `handle#discriminator` token
  player_name   a `PlayerName=` value that isn't a placeholder or sentinel
  player_entity a bare `Entity=` value that isn't a placeholder, sentinel
                or number — Battlegrounds writes every opponent's display
                handle this way, with no discriminator at all
  account_id    a raw `GameAccountId=[hi=... lo=...]` pair (stable per
                account across sessions, so it links a player's uploads)
  user_path     a local `C:\\Users\\<name>` path (docs, not logs)
  session_dir   a `Hearthstone_YYYY_MM_DD_HH_MM_SS` session directory name
                (docs and meta data, not logs)

Placeholders are the ONLY values exempted inside the name categories:
whatever the redactor emits must match PLACEHOLDER, so a missed name shows
up as a non-placeholder bare value and is reported.
"""
import io
import re

#: What the redactor is allowed to emit. Anything else in a name slot is a
#: finding.
PLACEHOLDER = re.compile(r"^(?:P|H|A)\d+$")

#: Not people: engine sentinels the log writes into player-shaped slots.
SENTINELS = {
    "GameEntity",
    "UNKNOWN",
    "UNKNOWN HUMAN PLAYER",
    "None",
    "",
}

#: Obvious fakes, allowed to appear as `handle#discriminator` in shipped
#: text (docstring examples and test fixtures) so the release gate can stay
#: strict without forbidding documentation of the pattern itself. Anything
#: not on this list is treated as a real handle — which is how the
#: maintainer's own tag and five upstream fixtures got caught.
#:
#: The non-ASCII entries exist so the non-ASCII case can be TESTED: the
#: handles literally mean "test" in three scripts, and building that test
#: from a handle observed in a real log would put a real person's name in
#: the release to prove the code removes names.
PLACEHOLDER_HANDLES = {
    "Name", "Player", "Tester", "SomeBody", "OtherGuy", "FakePlayer",
    "handle",
    "Test\u00fc", "Fake\u00e5", "\u0422\u0435\u0441\u0442",
    "\u6d4b\u8bd5",
}

#: Characters a handle or display name can plausibly be made of. Narrow on
#: purpose. This module is a DETECTOR: it must not fire on source code, and
#: a naive `[^\s]+#\d+` flags regex fragments (`Entity=(.+?)`) and CSS
#: colours (`--dim:#898781`). The REDACTOR in sanitize_log keeps broad
#: patterns, so an unusual handle is still removed even when this detector
#: would not have named it. Detector precise, redactor broad — that way a
#: false positive can't block a release, and a false negative can't leak.
_NAMEISH = r"A-Za-z0-9_.\-\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff"

#: `handle#discriminator`, both halves name-shaped, discriminator in the
#: 3-6 digit range real BattleTags use.
BATTLETAG = re.compile(rf"[{_NAMEISH}]+#\d{{3,6}}\b")
PLAYER_NAME_FIELD = re.compile(r"PlayerName=([^\r\n]+)")
BARE_ENTITY = re.compile(rf"\bEntity=([{_NAMEISH}#]+)")
ACCOUNT_ID = re.compile(r"GameAccountId=\[hi=(\d+) lo=(\d+)\]")

#: A value is only treated as a person if it looks like a name (letters,
#: digits, `_ . -`, and spaces for display names), so `PlayerName=([^\r\n]+)`
#: in our own source is not a finding.
_NAME_VALUE = re.compile(rf"^[{_NAMEISH} ]{{1,40}}$")

#: Tags that only ever land on a PLAYER entity. A bare `Entity=<value>` on a
#: line carrying one of these is a person; the identical shape under
#: `tag=CARDRACE` / `tag=ZONE` is a minion or a hero card (`Entity=Ooze`,
#: `Entity=Kel'Thuzad`), which is why "any bare name" would flag card names
#: and why the detector wants evidence of playerhood instead.
#:
#: The redactor does not use this list — it removes every bare name, card
#: names included, because consistent over-redaction costs a corpus nothing
#: and under-redaction costs a person their privacy.
PLAYER_TAGS = (
    "CURRENT_PLAYER", "PLAYSTATE", "NUM_TURNS_IN_PLAY", "PLAYER_ID",
    "PLAYER_LEADERBOARD_PLACE", "TEAM_ID", "HERO_ENTITY",
    "BACON_CURRENT_COMBAT_PLAYER_ID", "NEXT_OPPONENT_PLAYER_ID",
    "NUM_FRIENDLY_MINIONS_THAT_DIED_THIS_TURN", "RESOURCES",
    "RESOURCES_USED", "MULLIGAN_STATE",
)

#: Invented fixtures. These exist only in our own tests, and they are what
#: keeps the release gate usable: without them the gate would have to treat
#: every plausible handle in a fixture as a real person and could never
#: pass. Adding a name here is a claim that no real player has it — keep the
#: list short, and never add a name that came out of a log.
SYNTHETIC_NAMES = {"TestAccount", "Space2000", "TestPlayer", "Friendly",
                   "OpponentA", "OpponentB"}

#: A name needs at least one letter. Without this, `Entity=.` (our own
#: regexes) reads as a name.
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: The one session name our fixtures use. It is a placeholder with an
#: impossible timestamp, and it is named here rather than left as a loose
#: regex exemption so that "which session names are allowed" has exactly one
#: answer.
SYNTHETIC_SESSIONS = {"Hearthstone_2026_01_01"}


def _is_fake_account(hi, lo):
    """An all-same-digit pair (1111…, 2222…) is a fixture, not an account.
    Lets the account-id redaction be tested without writing a plausible id
    into a shipped test file."""
    return all(len(set(d)) == 1 for d in (hi, lo))

#: Artifact-level (docs, meta JSON, test fixtures) rather than log-level.
USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"'`]+")
SESSION_DIR = re.compile(r"Hearthstone_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}")

#: Text extensions worth scanning in a release.
TEXT_SUFFIXES = (".md", ".py", ".json", ".toml", ".txt", ".ps1", ".cfg",
                 ".sh", ".js", ".yaml", ".yml", ".ini", ".csv")


def _person(value):
    """Is this name-slot value a person we should report?"""
    v = value.strip()
    if not v or v.isdigit():
        return False
    if v in SENTINELS or v in SYNTHETIC_NAMES or PLACEHOLDER.match(v):
        return False
    if _is_placeholder_tag(v):
        return False
    if not _NAME_VALUE.match(v) or not _HAS_LETTER.search(v):
        return False
    return True


def _is_placeholder_tag(token):
    """`Player#1234` is documentation; a real account handle is a person."""
    handle = token.rsplit("#", 1)[0]
    return handle in PLACEHOLDER_HANDLES


def find(text):
    """{category: sorted unique findings} for one piece of text.

    Findings are the matched strings themselves (truncated for display by
    the caller), so a report can name what it saw rather than count it.
    """
    out = {}

    def _add(cat, values):
        # Materialise first: a generator is always truthy, so testing it
        # directly recorded every category as present-but-empty and made
        # is_clean() permanently False.
        found = sorted(set(values))
        if found:
            out[cat] = found

    _add("battletag", (m.group(0) for m in BATTLETAG.finditer(text)
                       if not _is_placeholder_tag(m.group(0))))
    _add("account_id", (m.group(0) for m in ACCOUNT_ID.finditer(text)
                        if not _is_fake_account(m.group(1), m.group(2))))
    _add("user_path", (m.group(0) for m in USER_PATH.finditer(text)))
    _add("session_dir", (m.group(0) for m in SESSION_DIR.finditer(text)
                         if m.group(0) not in SYNTHETIC_SESSIONS))

    # Players, by evidence of playerhood rather than by "looks like a name":
    # a PlayerName field, or a bare Entity on a line carrying a player-only
    # tag. Card names (`Entity=Ooze` under tag=CARDRACE) stay out of it.
    names, player_entities = set(), set()
    for line in io.StringIO(text):
        if "PlayerName=" in line:
            for m in PLAYER_NAME_FIELD.finditer(line):
                names.add(m.group(1))
        if any(t in line for t in PLAYER_TAGS):
            for m in BARE_ENTITY.finditer(line):
                player_entities.add(m.group(1))
    _add("player_name", (n for n in names if _person(n)))
    _add("player_entity", (e for e in player_entities if _person(e)))
    return out


def is_clean(text):
    """True when nothing in any category is left in `text`."""
    return not find(text)


def describe(label, findings, limit=6):
    """A few bounded reporting lines for one finding set."""
    lines = []
    for cat in sorted(findings):
        vals = findings[cat]
        shown = ", ".join(v[:60] for v in vals[:limit])
        more = f" (+{len(vals) - limit} more)" if len(vals) > limit else ""
        lines.append(f"  {label}: {cat} x{len(vals)}: {shown}{more}")
    return lines
