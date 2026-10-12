#!/usr/bin/env python3
"""Dev live-replay: put a FINISHED game on the real Another Round page.

WHY THIS EXISTS

The live overlay is only reachable while a game is being played: its states are
whatever the last `coach_ui.update_analysis()` put in the server's memory, and
the interesting ones (the hero pick, a mid-game Choose-1, the end-of-game card
and its Save button) each need a specific moment in a specific log. So the live
page was the one surface nobody could look at on purpose — the layout suite
fakes payloads, and everything else waits for a real game.

This tool drives that page from a game that is already over: it reads the log,
replays it through the SAME producer the live loop uses, and pushes the frame
you ask for. `n` walks the buy phases, `k` jumps to the next pick panel, `e`
ends the game onto the real end-of-game card.

MAINTAINER TOOL. It is excluded from the release zip
(`publish_release.EXCLUDE_FILES`) and must never reach the README: a player's
download is the launcher, the README, the licence and `app/`, and a "replay
mode" in it would read as a product feature. Its docstring is the only
documentation, deliberately.

WHAT IT PUSHES, AND WHY THAT IS THE WHOLE POINT

Every frame goes through `live._advise` / `live._advise_pick` /
`coach_ui.show_game_over` — the functions the shipped loop calls — so the payload
on screen is not a lookalike of a live one, it IS one. The pivot's wall holds by
construction: `coach_ui.render_json` is what turns an analysis into the page's
payload and the plan is dropped there (`LIVE_VERDICT_KEYS`), so a replayed frame
cannot show a verdict the live page would not.

ONE FRESH COACH PER STEP, measured rather than assumed (2026-10-12). Keeping one
coach and resuming each phase where the last one settled looks equivalent and is
not: `analyze()` is not a pure read of the parse state, so the extra call per
step costs the LATER frames their content. Measured here on the 16-phase
2026-10-12 game — incremental vs the review's fresh-coach cadence:

    phase 1   identical but for `generated`
    phase 8   15 keys differ, `board` / `gold` / `board_stats` among them
    phase 16  the same, and worse

Those are the numbers on screen, so the incremental version was thrown away.
Each step now re-feeds from line 0 through `replay_review.feed_to_settle` — the
review's own cadence, one implementation for both — which is also what makes
`test_the_frame_equals_the_review` an equality rather than an approximation. The
price is time, printed on every step: ~0.1s for an early phase, ~4.5s for the
last phase of a 330k-line game.

WHAT IT MUST NEVER DO (each one pinned by a test)

  * write a decision-log record (`record=False` — the live.py seam). A replay is
    not a played game, and the corpus joins on (log, byte offset, game).
  * share anything: `share.share_session` / `_share_game` are not on this path.
  * write a saved replay by itself. `live._settle_up_in_background` is NOT
    reused — it ends with `auto_save_current_review()`, which writes one with no
    click. The end-of-game card's own Save button does write, which is the
    feature being tested and the dev's own click.
  * run `replay_store.backfill()`: it DELETES duplicate files from the store.
    live.py runs it at startup; a dev tool must not prune the store.
  * check for updates, or restart the install.
  * show a plan for a game that has not ended. `e` asks the log's own
    `_game_ended` — the condition live.py's tick uses — and builds the review
    only after that answers yes.

TWO THINGS IT CANNOT DO, so nobody asks it to

  * It is not a measurement. An eyeball at an unknown window width is not a
    layout claim: `test_live_browser` / `test_live_tavern` own those, and
    `browser.py` records why ("the default viewport silently exercised the
    NARROW layout").
  * A screenshot from a session here is not usable for the docs. The band is in
    the frame, and the overlay's "Next opponent" line renders
    `analysis.opp_comp.name`, where a real opponent's handle rides.

Usage:
  python live_replay.py --list                      the saved games, and which
                                                    still have their log
  python live_replay.py --rid <id> [--phase N] [--open]
  python live_replay.py --latest [--game N]
  python live_replay.py --log <Power.log> [--game N]
  python live_replay.py --log <Power.log> --no-ui   console only (a pipe works)
"""
import argparse
import glob
import json
import os
import sys
import time
import webbrowser

# Import order matters, and it is not style. `coach_ui` pulls in settle_up →
# outcome_audit → live_coach, and live_coach does `from coach_ui import
# latest_manual_bans` — so live_coach has to be fully loaded BEFORE coach_ui
# starts loading, or that import runs against a half-built module. live.py
# primes it the same way (its `from live_coach import LiveCoach` sits above
# `import coach_ui`), and the suite's "running one module by hand" note records
# the hour it costs to meet this while debugging something else.
from live_coach import LiveCoach          # noqa: F401  (the circular-import primer)
import coach_ui
import live
import replay_review
import replay_store
import settle_up
from config import HS_LOG_GLOBS
from extract_game import split_game_chunks


class SpecError(Exception):
    """Something that cannot be answered — SAID, not raised as a traceback:
    this runs before the overlay exists, so a traceback here is the whole run."""


# ------------------------------------------------------------------ the band

#: The band this process injects into the served page. STATIC, and never
#: formatted from a path, a replay id, a hero or an opponent handle:
#: `coach_ui._page_html()` rewrites `_HTML` per request and hands the result to
#: the browser, so anything interpolated here would be interpolated into served
#: HTML. That is the one injection-shaped risk this tool could have, and not
#: doing the thing is the whole defence.
#:
#: It is load-bearing rather than decoration: a replayed frame is otherwise
#: indistinguishable from live advice, the failure this project has already paid
#: for twice (live.log_age_note's "console said live while the window showed
#: welcome"). The second sentence names the controls that WRITE, because on a
#: replayed welcome card the sharing question is the real one.
BAND = (
    '<div id="replay-band" style="margin:0 0 8px;padding:6px 10px;'
    'border:1px solid var(--warn,#d9a441);border-radius:var(--radius,6px);'
    'background:var(--panel,#1b1d22);color:var(--warn,#d9a441);'
    "font:600 12px 'Segoe UI',system-ui,sans-serif;letter-spacing:.03em\">"
    "REPLAY — a saved game on the live page, not live advice. Controls that "
    "write (sharing, Save replay, the auto-save checkbox) are REAL here."
    "</div>")

#: Where the band goes: the nav row's close tag. The band lands OUTSIDE every
#: container the page's renderers clear (`#app`, `#col-decide`, `#col-ref`,
#: `#settle`) and outside the `.tavern.live` subtree the verdict scan reads, so
#: no frame, viewer toggle or tab switch can wipe it, and no scan can trip on it.
BAND_ANCHOR = "</nav>"

#: The two anchors are CHECKED even when only one is used, because the check is
#: about the page's structure this tool depends on.
FRESHNESS_ANCHOR = "</head>"

#: Hides the page's freshness strip, whose line in a replay is untrue: with the
#: server answering, after 8s it reads "Read from 23s ago — it updates when your
#: next shop opens", and in here nothing is coming (you drive it). Opt-in,
#: because the strip is itself a live-page feature worth looking at.
FRESHNESS_CSS = "<style>#freshness{display:none !important}</style>"


def install_band(html, hide_freshness=False):
    """`_HTML` with the dev band after the nav. Raises when an anchor is gone.

    A silent miss would leave a REPLAY frame on screen looking exactly like live
    advice, so this fails loudly instead. Pinned by the suite too: the page's
    structure is the one thing the band depends on.
    """
    for anchor, what in ((BAND_ANCHOR, "the nav row"),
                         (FRESHNESS_ANCHOR, "the head")):
        if html.count(anchor) != 1:
            raise SpecError(
                f"coach_ui._HTML no longer carries exactly one {anchor!r} "
                f"({what}) — the dev band has nowhere safe to go, and a silent "
                f"miss would put a replay on screen looking like live advice")
    if hide_freshness:
        html = html.replace(FRESHNESS_ANCHOR,
                            FRESHNESS_CSS + FRESHNESS_ANCHOR, 1)
    return html.replace(BAND_ANCHOR, BAND_ANCHOR + "\n" + BAND, 1)


# --------------------------------------------------------------- the pointer

def _log_index():
    """{(session-dir name, log basename)} for every session log on disk."""
    out = set()
    for pattern in HS_LOG_GLOBS:
        for p in glob.glob(pattern):
            out.add((os.path.basename(os.path.dirname(p)),
                     os.path.basename(p)))
    return out


def list_rows():
    """The store's rows, each marked with whether its log is still on disk.

    That mark is why this is not just `replay_store.list()`: Hearthstone rotates
    session dirs, and a row whose log is gone cannot be replayed at all — the
    stored rep is a summary, carrying no shop, no comps and no pick panel, so it
    cannot fill the live page.
    """
    rows = replay_store.list()
    index = _log_index()
    for row in rows:
        row["log_on_disk"] = (row.get("session"), row.get("log")) in index
    return rows


def resolve(args):
    """(log_path, game, label). `game` None means "the last game in the log",
    resolved by the driver so the log is read once."""
    if args.rid:
        if args.game is not None:
            raise SpecError("--rid names its own game; drop --game (a saved "
                            "replay stores its pointer)")
        rid = args.rid.strip()
        if rid.endswith(".json"):
            rid = rid[:-len(".json")]
            _say(f"note: --rid takes the replay id, not the filename — "
                 f"using {rid!r}")
        stored = replay_store.load(rid)
        if stored is None:
            raise SpecError(f"no saved replay {rid!r} in "
                            f"{replay_store.store_dir()} — --list shows the ids")
        rep = stored.get("rep") or {}
        path = settle_up.log_path_for(rep.get("session"), rep.get("log"))
        if not path:
            raise SpecError("the session log for this replay is gone — "
                            "Hearthstone rotates its logs, so older games may "
                            "not be replayable")
        return (path, rep.get("game") or 1,
                f"{rep.get('hero') or 'unknown hero'}, saved as {rid}")
    if args.log:
        if not os.path.exists(args.log):
            raise SpecError(f"no such log: {args.log}")
        return args.log, args.game or 1, os.path.basename(args.log)
    if args.latest:
        path = settle_up.latest_log()
        if not path:
            raise SpecError("no Power.log found — is Hearthstone's file logging "
                            "on, and has a game been played?")
        return path, args.game, os.path.basename(path)
    raise SpecError("say which game: --rid <id>, --latest, or --log <Power.log> "
                    "(--list shows the saved ones)")


# --------------------------------------------------------------- the driver

def read_log(log_path):
    """(bounds, lines) for the whole log; the driver slices one game out.

    A module function rather than a method body, and named plainly, because it
    is the ONE thing here that needs the client's own install: the suite patches
    it to hand the driver a fixture chunk, so the cadence, the frames and the
    absence contract are all testable with no Hearthstone log on the machine.
    """
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    return list(split_game_chunks(lines)), lines


class LiveReplay:
    """One game, replayed onto the overlay a step at a time.

    It holds the game's chunk and nothing that can go stale: every step builds a
    fresh coach and feeds it from line 0 (the module docstring has the
    measurement that forced this). `pos` is the chunk line index of the frame on
    screen, which is what "the next pick" means, and `phase_of` derives the
    phase number from it rather than keeping a second copy that could disagree.
    """

    def __init__(self, log_path, game=None, label="", quiet=False):
        self.log_path = log_path
        self.label = label
        self.quiet = quiet
        self._coach = None
        bounds, lines = read_log(log_path)
        self._games = len(bounds)
        if not bounds:
            raise SpecError(f"{os.path.basename(log_path)} holds no game at all "
                            f"— no CREATE_GAME to replay")
        game = self._games if game is None else game
        if not 1 <= game <= self._games:
            raise SpecError(f"{os.path.basename(log_path)} has {self._games} "
                            f"game(s); game {game} does not exist")
        lo, hi = bounds[game - 1]
        self.game = game
        # `split_game_chunks` yields (start, end) LINE INDEX PAIRS, not chunks —
        # every caller slices, and settle_up.build says so out loud for the one
        # that got it wrong. `line_offset` is kept because an absolute line
        # number (--at, and `m`'s spec) means the FILE's numbering, which is what
        # a dev reading the log or logquery.py output has in hand.
        self.line_offset = lo
        self.chunk = lines[lo:hi]
        self.phases = replay_review._phases(self.chunk)
        self.pos = 0
        self.phase = 0
        self.mode = "welcome"
        self.built_review = None

    @property
    def phase_count(self):
        return len(self.phases)

    @property
    def round(self):
        """The round the game is in, from the coach's own action count.

        Deliberately NOT the phase index: `_phases` counts buy phases, and a
        skipped turn makes the two numbers disagree (test_skip_turns.py), so the
        console prints both and never conflates them.
        """
        actions = getattr(self._coach, "actions", None)
        return getattr(actions, "turn", None)

    def _containing_phase(self, pos):
        """The phase number whose window holds `pos` (0 before the first)."""
        best = 0
        for i, (lo, _hi) in enumerate(self.phases, 1):
            if lo <= pos:
                best = i
        return best

    def phase_of(self):
        """The phase whose frame is on screen.

        STORED, not derived from `pos`, because `pos` cannot answer it alone:
        `feed_to_settle` returns `len(chunk)` as its "never settled" sentinel,
        so a phase with no parsable shop would look like it ended the game —
        measured, and it made `n` report the last phase from phase 2 on.
        """
        return self.phase

    def status(self):
        return {"mode": self.mode, "pos": self.pos, "game": self.game,
                "games": self._games, "phases": self.phase_count,
                "log": self.log_path, "label": self.label}

    # ---------------------------------------------------------------- steps

    def _fresh(self, lo, hi):
        """(coach, stop, saw_offers) — a FRESH coach fed in the live cadence."""
        coach = LiveCoach()
        stop, saw = replay_review.feed_to_settle(coach, self.chunk, lo, hi)
        self._coach = coach
        return coach, stop, saw

    def _run(self, fn, *a, **kw):
        """Call a live push function, swallowing its console block if quiet."""
        if not self.quiet:
            return fn(*a, **kw)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return fn(*a, **kw)

    def _push(self, coach):
        """Push through the LIVE push function, writing no record.

        `live._last_state` is cleared first because that module global is the
        MONITOR's dedup key: without the reset a re-visited pick panel would be
        silently skipped instead of re-pushed. There is no monitor in this
        process — this tool is the only thing pushing — so the key starts empty
        on every frame.
        """
        live._last_state = None
        return self._run(live._advise, coach, force=True, record=False)

    def welcome(self):
        """The welcome / first-run card, exactly as Clear serves it."""
        coach_ui.clear_analysis()
        self.mode, self.pos, self.phase = "welcome", 0, 0
        return {"mode": "welcome"}

    def goto_phase(self, n):
        """Put buy phase `n` (1-based) on the overlay."""
        if not self.phases:
            raise SpecError("this game has no buy phase in the log yet — there "
                            "is nothing to advise on")
        if not 1 <= n <= len(self.phases):
            raise SpecError(f"phase {n} does not exist — this game has "
                            f"{len(self.phases)} buy phase(s)")
        lo, hi = self.phases[n - 1]
        coach, stop, saw = self._fresh(lo, hi)
        pushed = self._push(coach)
        # `stop` is where the settle was found, and it falls back to len(chunk)
        # when the phase never settled — which is real, not an error: a phase
        # whose shop never parses runs to its own MAIN_END. The lines actually
        # fed are therefore bounded by the phase's end.
        fed = min(stop, hi if hi is not None else len(self.chunk))
        self.pos, self.phase, self.mode = fed, n, "phase"
        return {"phase": n, "of": len(self.phases), "saw_offers": saw,
                "fed": fed, "round": self.round, "pushed": bool(pushed)}

    def goto_pick(self):
        """The next pending Choose-1 panel at or after the frame on screen.

        The dispatch is live.py's own (`if in_action and coach.tavern_offers()`
        in its tick): inside a shop the FULL analysis is the frame, outside one
        the minimal pick panel is. Branching differently here would show a
        screen the live loop never shows — the class of bug this file exists to
        make visible rather than create.
        """
        start = self.pos
        coach = LiveCoach()
        in_action = False
        found = None
        for j, line in enumerate(self.chunk):
            if "tag=STEP value=MAIN_ACTION" in line:
                in_action = True
                # The phase-boundary seed, as live.py and feed_to_settle do:
                # analyze() is what identifies the friendly player, and the
                # pairing guard is gated on it.
                coach.analyze()
            elif "tag=STEP value=MAIN_END" in line:
                in_action = False
            coach.feed(line)
            if j < start:
                continue
            c = coach.choice
            if c is not None and c.get("picked") is None and c.get("options"):
                found = j
                break
        if found is None:
            return None
        live._last_state = None
        if in_action and coach.tavern_offers():
            self._run(live._advise, coach, force=True, record=False)
        else:
            self._run(live._advise_pick, coach, record=False)
        self._coach = coach
        self.pos, self.mode = found, "pick"
        self.phase = self._containing_phase(found)
        return {"at": found, "in_shop": in_action, "round": self.round}

    def goto_moment(self, spec):
        """A mid-phase moment: `HH:MM:SS`, or an absolute log line number.

        The one step that pushes without `live._advise`, because
        `replay_review._advise_at` returns an ANALYSIS rather than a coach: it
        owns its own feed and its own long settle, which is what finds a shop
        the player ROLLED into (the phase-start settle deliberately does not
        report those). The producer is unchanged — `coach_ui.render_json` is
        what turns an analysis into the page's payload — so the wall is
        untouched and nothing is recorded.
        """
        if not spec:
            raise SpecError("a moment is needed: HH:MM:SS, or an absolute log "
                            "line number")
        target = replay_review._resolve_at(self.chunk, spec, self.line_offset)
        if target is None:
            raise SpecError(f"no moment {spec!r} in this game — HH:MM:SS, or a "
                            f"line number between {self.line_offset + 1} and "
                            f"{self.line_offset + len(self.chunk)}")
        a = replay_review._advise_at(self.chunk, target)
        if a is None:
            raise SpecError("the coach is not ready at that moment")
        coach_ui.update_analysis(a)
        self.mode, self.pos = "moment", target
        self.phase = self._containing_phase(target)
        return {"at": target, "spec": spec,
                "round": (a.get("scenario") or {}).get("turns")}

    def to_end(self, build_review=True):
        """The end of the game: the real end-of-game card, and its review.

        Returns (info, refusal). A refusal is not an error — pressing `e` on a
        game that has not ended is normal (`--latest` against a log being
        written right now IS the in-progress chunk), and the honest answer is to
        say so rather than invent a card. The gate is the game's own
        `_game_ended`, the same condition live.py's tick uses.
        """
        coach = LiveCoach()
        for line in self.chunk:
            coach.feed(line)
        try:
            # The one settle live.py makes after a pure catch-up: the shop table
            # commits only when tavern_offers() flushes the pending options
            # block, and the round count is read off that flush.
            coach.tavern_offers()
        except Exception:                    # noqa: BLE001 - a read, not a step
            pass
        state = live._game_state(coach)
        if not (state and state[1]):
            return None, ("this game has not ended in the log — no card, and no "
                          "review: the plan is never shown for a game that is "
                          "still being played")
        try:
            if coach.hero_card is None or coach.friendly is None:
                coach.ensure_meta()
        except Exception:                    # noqa: BLE001 - the card must show
            pass
        self._coach = coach
        placement = coach.final_placement()
        turn = self.round
        coach_ui.show_game_over(coach_ui.latest_analysis(),
                                placement=placement, turn=turn)
        self.mode, self.pos = "end", len(self.chunk)
        self.phase = self.phase_count
        info = {"placement": placement, "round": turn, "review": None}
        if build_review:
            info["review"] = self.build_review()
        return info, None

    def build_review(self):
        """Build the game's review, so the card's own Save button works.

        Exactly what `live._settle_up_in_background` does MINUS the one line
        this tool must not run: it ends with `auto_save_current_review()`, which
        writes a saved replay with no click. A dev stepping through a game is
        not a player deciding to keep it.

        INLINE rather than off-thread — a deliberate departure from the plan:
        this file touches the coach, the page's state and the console from ONE
        thread by design, and a review build is a read that cannot usefully
        interleave with a step anyway. It costs seconds, so the console says what
        it is doing first.
        """
        rep = settle_up.build(self.log_path, self.game)
        label = (f"Settle up — {rep.get('hero') or 'your game'}"
                 + (f", finished {rep['placement']}"
                    if rep.get("placement") else ""))
        coach_ui.set_review(settle_up.render_html(rep), label, rep=rep)
        self.built_review = rep
        return {"hero": rep.get("hero"), "placement": rep.get("placement"),
                "phases": len(rep.get("phases") or []),
                "timeline_error": rep.get("timeline_error")}


# ---------------------------------------------------------------- the console

HELP = """commands:
  n / p    next / previous buy phase        g N    go to phase N (1-based)
  k        the next Choose-1 panel (hero pick, dark gift, trinket, triple)
  m SPEC   a mid-phase moment: HH:MM:SS, or an absolute log line number
  e        the end of the game (the end-of-game card, and its review)
  w        the welcome / first-run card      r      re-push the frame on screen
  a        auto-advance one phase every 4s   s      status
  h        this list                         q      quit
"""


def _say(msg=""):
    print(msg, flush=True)


def _read_key(timeout=0.25):
    """One keypress if one is waiting, else None after ~`timeout`.

    Non-blocking, and called from the ONE thread that touches the coach: waiting
    for input cannot live in a thread of its own, or a re-push on a ban change
    would analyze while a step was feeding. Windows reads the console directly
    (so a keypress needs no Enter); a POSIX terminal is polled with `select`;
    anything else — a pipe, a test — takes a line per command, and a closed
    stdin quits rather than spinning.
    """
    if os.name == "nt" and sys.stdin.isatty():
        try:
            import msvcrt
        except ImportError:                            # pragma: no cover
            msvcrt = None
        if msvcrt is not None:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    # An arrow/function key arrives as a two-character sequence
                    # starting \x00 or \xe0; swallowing the second half keeps a
                    # stray arrow from being read as a command.
                    if ch in ("\x00", "\xe0"):
                        msvcrt.getwch()
                        continue
                    return ch
                time.sleep(0.03)
            return None
    if sys.stdin.isatty():
        try:
            import select
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            return sys.stdin.read(1) if ready else None
        except Exception:                              # noqa: BLE001
            return None
    line = sys.stdin.readline()
    return "q" if line == "" else line.strip()         # EOF ends a piped run


def _split_command(raw):
    """("g", "7") from "g 7"; ("n", None) from "n".

    The single-key reader hands back one character and the piped reader hands
    back a whole line, so the argument has to be split off HERE — the loop that
    did not do this turned `g 7` into the unknown command "g 7".
    """
    parts = str(raw or "").strip().split(None, 1)
    if not parts:
        return "\n", None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def _describe_step(key, result):
    """One line per step, so the console is the record of what was pushed."""
    if key in ("n", "p", "g"):
        return (f"phase {result['phase']}/{result['of']}"
                f" (round {result.get('round')}) — fed {result['fed']:,} lines "
                f"— pushed to the overlay"
                + ("" if result.get("saw_offers")
                   else "  [no shop parsed at this phase's settle]"))
    if key == "k":
        return (f"Choose-1 at line {result['at']:,}"
                + (" (inside a shop: the full analysis is the frame)"
                   if result["in_shop"] else " (the pick panel)")
                + f" — round {result.get('round')} — pushed")
    if key == "m":
        return (f"moment {result['spec']} (line {result['at']:,}) — round "
                f"{result.get('round')} — pushed")
    if key == "w":
        return "welcome card — pushed (the manual ban set went with it)"
    return "pushed"


def step(driver, key, arg=None, opts=None):
    """Run one command: (message, done). `done` means "quit".

    Separate from the loop so the whole command surface is testable without a
    terminal — the loop reads keys and prints, this decides.
    """
    opts = opts or {}
    if key in ("q", "\x03", "\x04"):
        return "bye", True
    if key in ("h", "?", "\n", ""):
        return HELP, False
    if key == "s":
        st = driver.status()
        note = f" [{'log on disk' if os.path.exists(st['log']) else 'log GONE'}]"
        return (f"{st['log']}{note} game {st['game']}/{st['games']}, "
                f"{st['phases']} buy phase(s) — on screen: {st['mode']} "
                f"(line {st['pos']:,})", False)
    if key == "w":
        return _describe_step(key, driver.welcome()), False
    if key == "e":
        if opts.get("no_review"):
            _say("--no-review: building nothing, so the card's Save button "
                 "will answer 409 (rerun without it to test that path)")
        else:
            _say("replaying the game for the review — seconds…")
        info, refusal = driver.to_end(build_review=not opts.get("no_review"))
        if refusal:
            return refusal, False
        _say(f"end-of-game card pushed — finished {info['placement']}, round "
             f"{info['round']}")
        rev = info.get("review")
        if rev is not None:
            _say(f"review ready: {rev['phases']} phase(s)"
                 + (f", timeline error: {rev['timeline_error']}"
                    if rev.get("timeline_error") else "")
                 + " — the card's Save replay button now works")
        return _describe_step(key, info), False
    if key == "r":
        if driver.mode == "phase":
            n = driver.phase_of()
            return _describe_step("g", driver.goto_phase(n or 1)), False
        if driver.mode == "pick":
            r = driver.goto_pick()
            if r is None:
                return "no Choose-1 panel on screen to re-push", False
            return _describe_step("k", r), False
        if driver.mode == "end":
            return ("the end-of-game card is on screen — n re-pushes the last "
                    "phase, or e rebuilds the card", False)
        return _describe_step("w", driver.welcome()), False
    if key == "n":
        cur = driver.phase_of()
        nxt = cur + 1 if driver.mode in ("phase", "moment") else max(1, cur)
        if nxt > driver.phase_count:
            return (f"phase {driver.phase_count} is the last one this game has — "
                    f"press e for the end-of-game card", False)
        return _describe_step(key, driver.goto_phase(nxt)), False
    if key == "p":
        if driver.mode != "phase":
            return "not on a phase — n starts at the first one", False
        prev = driver.phase_of() - 1
        if prev < 1:
            return "that is the first buy phase of the game", False
        return _describe_step(key, driver.goto_phase(prev)), False
    if key == "g":
        try:
            n = int(arg)
        except (TypeError, ValueError):
            return ("g needs a phase number — `g 7`, or just `g` and type it "
                    "when asked", False)
        try:
            return _describe_step(key, driver.goto_phase(n)), False
        except SpecError as exc:
            # The phase's own sentence, not the generic one: "phase 99 does not
            # exist — this game has 16 buy phase(s)" is what tells a dev what to
            # type next, and swallowing it under "needs a phase number" made an
            # out-of-range number look like a typo.
            return str(exc), False
    if key == "k":
        r = driver.goto_pick()
        if r is None:
            return ("no further Choose-1 panel in this game — w for the welcome "
                    "card, or n for the buy phases", False)
        return _describe_step(key, r), False
    if key == "m":
        try:
            return _describe_step(key, driver.goto_moment(arg)), False
        except SpecError as exc:
            return f"m: {exc} — `m 12:34:56`, or `m <log line>`", False
    return (f"unknown command {key!r} — h lists them", False)


# ------------------------------------------------------------------ the run

def _parse_argv(argv):
    """argparse, not the hand-rolled splitter live.py carries: that splitter is
    where `--poll 0.5` silently became a log path (test_live_args.py is the
    record), and a tool whose flags take values has no business repeating it."""
    ap = argparse.ArgumentParser(
        prog="live_replay.py",
        description="Replay a finished game onto the live overlay, so Another "
                    "Round can be looked at without playing. MAINTAINER TOOL — "
                    "excluded from the release zip.")
    ap.add_argument("--list", action="store_true",
                    help="the saved games, and which still have their log")
    ap.add_argument("--json", action="store_true",
                    help="with --list: print the rows as JSON")
    ap.add_argument("--rid", help="a saved replay's id (see --list)")
    ap.add_argument("--log", help="a Power.log to read the game out of")
    ap.add_argument("--latest", action="store_true",
                    help="the newest session log (default game: its last one)")
    ap.add_argument("--game", type=int, default=None,
                    help="which game in the log, 1-based (default 1, or the "
                         "last game with --latest)")
    ap.add_argument("--phase", type=int, default=None,
                    help="start on this buy phase instead of the welcome card")
    ap.add_argument("--open", action="store_true",
                    help="open the overlay in a browser")
    ap.add_argument("--no-ui", action="store_true",
                    help="console only: push the frames, serve no page")
    ap.add_argument("--no-review", action="store_true",
                    help="skip the review build at the end of the game (the "
                         "card's Save button then answers 409)")
    ap.add_argument("--hide-freshness", action="store_true",
                    help="hide the page's freshness strip, whose 'it updates "
                         "when your next shop opens' is untrue here")
    ap.add_argument("--quiet", action="store_true",
                    help="one line per step, without the analysis block")
    ap.add_argument("--port", type=int, default=None,
                    help="the overlay port (default: coach_ui's)")
    return ap.parse_args(argv)


def main(argv=None):
    # The analysis text carries '⚠' and '·'; a piped or redirected run dies with
    # UnicodeEncodeError on a cp1252 console instead of printing what it just
    # computed. Same guard, same reason, as every other entry point here.
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:                                  # noqa: BLE001
        pass
    args = _parse_argv(sys.argv[1:] if argv is None else argv)

    if args.list:
        rows = list_rows()
        if args.json:
            _say(json.dumps(rows, indent=2, ensure_ascii=False))
            return 0
        if not rows:
            _say(f"no saved replays yet in {replay_store.store_dir()} — the "
                 f"end-of-game card's Save replay button writes them")
            return 0
        _say(f"{len(rows)} saved replay(s) in {replay_store.store_dir()}:")
        for row in rows:
            _say(f"  {row['id']}"
                 f"  [{'log on disk' if row.get('log_on_disk') else 'log GONE'}]"
                 f"  {row.get('hero') or '?'}"
                 + (f", {row['placement']}" if row.get("placement") else "")
                 + f", {row.get('turns') or '?'} turns, {row.get('created')}")
        _say("\na row whose log is GONE cannot be replayed: the stored review is "
             "a summary, with no shop and no pick panel in it.")
        return 0

    try:
        log_path, game, label = resolve(args)
    except SpecError as exc:
        _say(f"live_replay: {exc}")
        return 2
    try:
        driver = LiveReplay(log_path, game, label, quiet=args.quiet)
    except SpecError as exc:
        _say(f"live_replay: {exc}")
        return 2

    _say(f"Bob's Ledger — REPLAY (dev)  {log_path}")
    _say(f"  game {driver.game}/{driver._games}, {driver.phase_count} buy "
         f"phase(s), {len(driver.chunk):,} lines"
         + (f" — {label}" if label else ""))
    _say("  Advice on the overlay is REPLAYED, not live. Every frame comes from "
         "the live push path; nothing is recorded and nothing is shared.")

    if not args.no_ui:
        coach_ui._HTML = install_band(coach_ui._HTML,
                                      hide_freshness=args.hide_freshness)
        try:
            server = coach_ui.start_server(args.port or coach_ui.DEFAULT_PORT)
        except OSError as exc:
            _say(f"live_replay: the overlay server could not start ({exc}) — "
                 f"--no-ui drives the frames without a page")
            return 1
        _say(f"  overlay: {coach_ui.overlay_url(server)}")
        if args.open:
            import threading
            threading.Thread(target=webbrowser.open,
                             args=(coach_ui.overlay_url(server),),
                             daemon=True).start()

    opts = {"no_review": args.no_review, "auto": 0.0}
    if args.phase is not None:
        try:
            _say(_describe_step("g", driver.goto_phase(args.phase)))
        except SpecError as exc:
            _say(f"live_replay: --phase {args.phase}: {exc}")
            return 2

    _say(HELP)
    _say("(every step re-reads the game from the start, so a late phase takes "
         "seconds)")
    last_bans = tuple(coach_ui.latest_manual_bans() or ())
    due = 0.0
    try:
        while True:
            raw = _read_key(0.25)
            if raw is None:
                # The live monitor re-advises the instant a ban chip lands. This
                # tool cannot re-run a phase for free, so it says what to press
                # rather than doing seconds of work behind the dev's back.
                bans = tuple(coach_ui.latest_manual_bans() or ())
                if bans != last_bans:
                    last_bans = bans
                    _say(f"manual bans changed ({len(bans)} set) — r re-pushes "
                         f"this frame with them; every later frame picks them up")
                if opts["auto"] and time.time() >= due:
                    due = time.time() + opts["auto"]
                    nxt = (driver.phase_of() + 1
                           if driver.mode == "phase" else 1)
                    if nxt > driver.phase_count:
                        opts["auto"] = 0.0
                        _say("auto-advance: the last buy phase is on screen")
                        continue
                    try:
                        _say(_describe_step("n", driver.goto_phase(nxt)))
                    except SpecError as exc:
                        opts["auto"] = 0.0
                        _say(f"auto-advance stopped: {exc}")
                continue
            key, arg = _split_command(raw)
            if key == "a":
                if opts["auto"]:
                    opts["auto"] = 0.0
                    _say("auto-advance: off")
                else:
                    opts["auto"] = 4.0
                    due = time.time()
                    _say("auto-advance: on, one phase every 4s (a stops it)")
                continue
            if key in ("g", "m") and arg is None and sys.stdin.isatty():
                # The single-key reader cannot hand over an argument, so the two
                # value-taking commands ask for it. A piped run passes it on the
                # line instead (`g 7`), which is how the tests drive this.
                try:
                    arg = input(f"{'phase' if key == 'g' else 'moment'}: ")
                except (EOFError, KeyboardInterrupt):
                    arg = None
            msg, done = step(driver, key, arg=arg, opts=opts)
            _say(msg)
            if done:
                break
    except KeyboardInterrupt:
        _say("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
