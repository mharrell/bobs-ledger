# Bob's Ledger

A tracker for **Hearthstone Battlegrounds** that reads the game's own log file
and shows you the board you actually have: what each of your minions is worth,
which pieces of a comp you hold and which you are missing, how hard the lobby is
pressing, what each tavern offer costs, and how close this hero is to dying.

**It shows you the state, not the instruction.** It does not tell you what to
buy, and that is a deliberate limit rather than a missing feature — see
[Is this allowed?](#is-this-allowed) for the reasoning. While you play, the
model's opinion appears as a number you read, never as a move it names. Its plan
for each turn is still worked out and written to your own disk, and you see it
**after the game**, in [Settle Up](#settle-up-the-review) — where the decision it
describes can no longer be acted on.

**Windows only.** It reads the log file Hearthstone writes on your own PC and
asks for no account. It does not modify the game — the one file it can change is
Hearthstone's own logging setting, and only if you say yes to it (see
[turning on logging](#turn-on-hearthstones-logging)).

**[Install it](#install-it)** · **[Turn on logging](#turn-on-hearthstones-logging)** ·
**[Is this allowed?](#is-this-allowed)** · **[The question it asks you](#the-one-question-it-asks-you)** ·
**[Something's wrong](#if-somethings-wrong)**

## What you need

- A Windows PC with Hearthstone installed — on any drive.
- Python 3 — free. If it is missing, the app tells you and links you to it.
- Five minutes, most of it the download.

## Install it

**1. Download it.** [Click here](https://hearth-telemetry-collector.bobs-ledger.workers.dev/release/latest.zip)
— it saves as `Bob's Ledger.zip`. No account needed.

**2. Unzip it.** Right-click the file → **Extract All**, somewhere you can write
to: Desktop or Documents are ideal. (Not `C:\Program Files` — Windows will not
let the coach keep its card pictures there.) You get a folder called
`Bob's Ledger`.

**3. Double-click `Start Bob's Ledger.cmd`** in that folder. That is the whole
install. It finds Python, asks before adding the one small extra it needs, tells
you where it will read Hearthstone's log from, offers a **shortcut with its own
icon** for the folder and your Desktop, then opens the overlay in your browser.

Windows may ask once whether to run a file from an "unknown publisher" — the
normal prompt for anything you downloaded. Click **Run**.

Already unzipped it? Skip to [logging](#turn-on-hearthstones-logging).

## Turn on Hearthstone's logging

**The app offers to do this for you.** If logging is off when you start it, it
asks — say yes and the step is done: it adds the two lines the coach needs to the
settings file Hearthstone already has, leaves the rest of that file exactly as it
was, and keeps a copy of the original first. (It will not do it while Hearthstone
is running, because the game only reads that file when it starts.)

To do it by hand instead: by default Hearthstone does not write the file the
coach reads.

1. Close Hearthstone.
2. Hold **Win**, press **R**, paste `%LocalAppData%\Blizzard\Hearthstone`, press
   Enter.
3. Open `log.config` with Notepad — or create it there — and make sure it
   contains at least this:

   ```
   [Power]
   LogLevel=1
   FilePrinting=true
   ConsolePrinting=false
   Screenshots=false
   ```

4. Start Hearthstone.

If you use Hearthstone Deck Tracker or Firestone, this file exists already and
you are done.

## What you'll see

The overlay opens as a page in your browser and updates as you play — not a
second game window, so put it on another monitor or leave it behind the game.

- **Left — where the game stands.** How strong your board is against the next
  opponent and against the lobby, how close this hero is to dying and to what,
  what is in your hand, and how charged a hand-engine is.
- **Right — the reference.** Your board with each minion's value and its role,
  the comp this board reads as closest to and which of its pieces you hold, how
  close each candidate comp is to its commit threshold, who in the lobby is
  contesting which tribe, and the tavern's offers with their prices and pool
  counts — in the order the game shows them, not ranked.

Every card carries the same facts: its tier, its text on hover, and what it is
worth. Nothing on the page names a move.

## Settle Up (the review)

When a game ends, the card on screen offers **Settle up** — and a **Save
replay** button beside it. Saving keeps that game in the overlay's **Settle
Up** tab (the second tab at the top of the page, next to **Another Round**):
pick any saved game from the dropdown and the same turn-by-turn view opens
with real card tiles. Saving is per game and yours alone — nothing saved
leaves your machine, and it never ships in a release. The review page the
**Settle up** link opens is unchanged: a standalone file you can keep, and
`settle_up.py --session / --history` still work for games still in the log.

**The part the game never shows you: the board, three times a turn.** For every
turn the review prints what you went in with, what your opponent brought, and
what you kept — plus what the turn cost.

    t5  7g  board 15 stats (+12)  spent 7g
       you went in with: Locked-up Mutineer 6/3, Crackling Cyclone 2/1 x2,
                         Wolf Pup 3/6, Fire Baller 4/3
       they brought    : Dune Dweller 3/3, Fetid Corroder 3/3
       you kept        : Wolf Pup 3/6, Locked-up Mutineer 6/3, Fire Baller 4/3,
                         Crackling Cyclone 2/1 x2

The numbers on that line are the turn's own: gold at the end of the buy phase,
your board's total attack + health and how much it changed, and what you spent
on cards, rolls and levelling. A turn marked **?** is one worth a second look —
you sold a key card while a filler stayed on the board. It is a question, not a
verdict, and a turn where you sold most of your board is labelled a rebuild
instead, because that is what it is. Keep an eye out for `*` after a minion's
stats: that one is golden.

**Then the phase-by-phase view**, which is where the plan is:

- **Model** — the plan it would have played, e.g. "1. LEVEL to tier 4 · 2. Buy
  Bronze Warden".
- **You** — what the log says you did: bought, rolled, levelled up, sold.
- **The fight after it** — effective HP gained or lost across the next combat.
  Negative means it hurt.

It also says how much of itself it *could not* judge. A plan that opens with a
minion swap, or with a spell whose card it could not resolve, is reported as
**not graded** rather than counted either way, and the count is printed on the
summary — it will not pretend to have assessed a decision it cannot see.

The summary prints how the phases you followed went against the phases you
didn't — and says plainly that this is **observational, not causal**, because
following a plan is easier in games you were already winning. It also warns you
when the count leans on turns that opened with a spell, because a turn that
casts several spells can satisfy "cast the one it named" by accident. Read any
of it as a reason to look at a turn, never as a score.

The review opens in its own browser tab from the end-of-game card. To keep one,
or to review any game still in the log, run this in the window you started the
coach from:

    python app\settle_up.py --latest --html my-review.html

**A whole session, or your last few.** `--session` reviews every game in the
newest log and puts them in one table — placements, boards, spend, and how often
you took the plan. `--history 3` does the same across your three newest logs.
Both re-read every game in full, so they take a few seconds per game; the
single-game review is instant by comparison.

    python app\settle_up.py --latest --session
    python app\settle_up.py --history 3

## The one question it asks you

The first time it starts, the coach asks whether it may send a short summary of
each finished game back to me. **Nothing is sent unless you say yes**, and saying
no changes nothing else about the coach.

Saying yes covers the games you play **from that point on**. Anything you played
before you answered — while the answer was no, or before there was one — was
played under "nothing leaves your machine", and it is never sent, not even after
you say yes.

If you say yes, a summary is your decisions and how the game went: turn, gold,
tavern tier, health, what was advised, and what happened next. Not your name, not
the chat, not your file paths, and not your log file. A copy of everything sent
is kept in `session_reports/` in the app folder, so you can read it yourself. To
change your mind, press **Clear** at the top-right of the overlay: the card comes
back, with a switch you can turn either way. (Once you have answered, it shows
that switch rather than the question — the question is only asked when you have
not answered yet.)

Why I ask: the model's plan has not been measured against results yet, and those
summaries are how it gets measured.

## One honest thing about the model

Bob's Ledger's value function is a second opinion, not an oracle. Its judgements
have not been checked against outcomes, and its own audits say some of them — the
ones about when to level up especially — may be wrong. On the live page you read
them as numbers and decide for yourself; in the review they will be shown
alongside what actually happened, which is the only honest way to present them.

## Is this allowed?

Worth answering straight, because it is the first thing a lot of people ask.

**The live overlay shows state, not instructions, and that is a deliberate
limit.** It reads the board you actually have and tells you what is true about
it: your stats against theirs, what your minions are worth, which comp pieces you
hold, what each offer costs. It does not name a move. That line was drawn
deliberately, and what it does and does not buy is worth being precise about.

Some facts, kept apart from that judgement:

- **Blizzard's rules do cover this, so read the next line rather than a
  comfortable one.** The EULA does not name "real-time assistance" anywhere, but
  it does prohibit software that "facilitates the gameplay" and grants "an
  advantage over other players not using such methods". **A statistics overlay
  grants that advantage too** — the clause does not mention verdicts, so
  "showing you numbers" is not a safe harbour, and I am not going to pretend it
  is. What the wording plainly does not describe is a bot or a hack: this does
  not touch the game's process or its memory, does not automate input, and reads
  the log file Hearthstone writes to your own disk. The one file it will change
  is Hearthstone's own logging setting, and only if you say yes. The wording
  above is quoted from
  [Section 1.C of Blizzard's EULA](https://www.blizzard.com/en-us/legal/fba4d00f-c7e4-4883-b8b9-1b4500a402ea/blizzard-end-user-license-agreement)
  — read it yourself rather than taking my summary of it.
- **So what the limit actually buys is a smaller, easier-to-defend surface — not
  permission.** Nothing in Blizzard's rules "expressly authorizes" a log-reading
  overlay; Deck Tracker, Firestone and stat overlays have instead been used
  openly for years without enforcement, which is a real reason to think this is
  fine and not a promise that it is. Blizzard reserves the right to read its own
  words differently whenever it likes. I am not a lawyer and this is not legal
  advice.
- **Two things are true at once, and the review is the honest half.** Not naming
  a move while you play is the limit this tool accepted. But the model's plan
  was never the problem by itself — an unmeasured plan asserted at you mid-turn
  was. Settle Up shows it after the game, beside what actually happened and how
  much of it the review could judge, which is the version of this that can be
  checked rather than believed.
- **None of that makes it appropriate everywhere.** Turn it off for tournaments
  and any organised event. Their rules bar outside help outright, and in that
  setting the question is not even close.
- **Keep it off stream if that worries you.** In practice this kind of thing gets
  noticed because it was on screen in a screenshot or a clip, not because
  anything detected it.
- **You are allowed to disagree with the paragraph above.** Some people draw this
  line where raw data ends and reasonable people land on both sides of it. It is
  a fair position, and the answer is to not run the coach — not to find a
  cleverer reason it is fine.

## Two more things worth knowing

- **Patch days.** After a Hearthstone patch the coach's reference data lags a few
  days, so its numbers can be less sharp until it catches up. It looks for a new
  version every time you start.
- **Where it comes from.** Every number on the page is worked out on your own PC,
  from Hearthstone's log plus a reference file that ships with the app — nothing
  is sent anywhere to produce it, and it works with your internet off. Only the
  card pictures need a connection.

## If something's wrong

- **A black window flashes and vanishes.** You ran the file from inside the .zip.
  Unzip it first (step 2), then run it from the folder you get.
- **It says Python was not found.** Install Python from python.org, tick **Add
  python.exe to PATH**, and run the file again.
- **The overlay keeps waiting.** Two things cause that, and the overlay says which
  one you have. Either Hearthstone's file logging is still off — the overlay shows
  that same setting on screen — or the coach is looking in the wrong place,
  because your game is installed somewhere other than the usual folder. The
  window you started it from prints the one-line command that fixes the second
  one for good.
- **The page stops changing.** The overlay says how long ago the last read was
  written, so you can tell a stale read from a live one.
- **It says the folder cannot be written to.** Move the `Bob's Ledger` folder to
  Documents or the Desktop and start it again.

Still stuck? [Open an issue](https://github.com/mharrell/bobs-ledger/issues) with
what the window said, or a screenshot of it.

## Uninstalling

Delete the `Bob's Ledger` folder, and the shortcut if you made one. Nothing else
was installed — no registry entries, no services, nothing left behind.

## Licence & credits

MIT licensed — see `LICENSE`. Card names, card text and card art are © Blizzard
Entertainment, and this is an unofficial fan tool: not affiliated with, or
endorsed by, Blizzard. Card data comes from
[HearthstoneJSON](https://hearthstonejson.com), and the sources behind the comp
reference are credited inside `meta/comps.json`.

## Working on the code

**A note on the model tooling you will find in this tree.** I tried a language
model in the loop early on and decided against it, so nothing on the live path
calls one: `live.py`, `live_coach.py`, `value.py` and `coach_ui.py` do not
import it, and every number on the page comes from the local value function and
the meta database. The experiment is still here — `coach_llm.py` is the client,
`compare_models.py` races models against each other, and `patch_notes.py` and
`check_patch_notes.py` use one to turn official patch notes into the meta DB. It
stays because it is useful for maintainer work, and none of it ships in a
release.

### Clone and run it

```
git clone https://github.com/mharrell/bobs-ledger
cd bobs-ledger
python -m pip install -r app\requirements.txt
python app\live.py
```

That is the same program the launcher starts. `app\live.py` also takes a log path,
and `--poll 0.5` re-analyses a saved log, `--once` does a single pass, `--no-ui`
skips the overlay, `--version` prints what you are running. `python app\doctor.py`
is the one-shot pre-flight verdict: patch, coverage, art, newest log.

A clone never auto-updates: commit shas cannot prove which side is newer, so the
release check stands aside and you update with `git pull`.

### The layout

The program lives in `app/`. The root keeps what a player should see — this
README, `LICENSE`, the launcher — plus what never ships: `analysis/`
(research notes, some of which name real opponents), `telemetry/` (the release
channel itself), `CLAUDE.md`, `DESIGN.md`, `ROADMAP.md`.

There are no screenshots in the tree at the moment. The old ones showed the
pre-pivot overlay and went out in the 2026-10-06 releases; the replacements will
land with a layout that still exists.

### Tests

```
python -m unittest discover -s app/tests
```

About 1,500 tests, ~60 seconds. Some skip by design: the ones that need a
real `Power.log` or maintainer-only files report as skipped rather than passing
quietly.

Two of them are posture controls rather than behaviour tests, and they are the
reason the paragraph at the top of this file can be trusted: one asserts this
README's claims about what the coach does to your machine *and* that the
corresponding capability (process or memory access, synthetic input) is absent
from `app/`; the other asserts that the live payload carries no verdict — no
plan, no named buy, no pick — while the analysis keeps every one of them for the
decision log and the review.

### What not to break

- **The privacy gates, and the sharing whitelist.** `session_report.py`'s `SPEC`
  names every field a shared summary may contain; a field it does not name cannot
  appear, so adding one means adding it there deliberately.
- **The launcher.** `Start Bob's Ledger.cmd` has to stay CRLF and pure ASCII: a
  bare LF makes cmd.exe mis-parse it, and a stray UTF-8 byte renders as garbage in
  a console.
- **The macOS launcher's mirror of those rules.** `Start Bob's Ledger.command`
  has to be LF-only (one CR and bash dies on `$'\r'`), pure ASCII, and free of
  bash-4 syntax: `/bin/bash` is still 3.2 on macOS. **It has never been run** —
  no Mac has executed it and no shell here has even parsed it, so its first real
  run is the test.
- **The platform layer.** The client root, the `log.config` location and the
  "is Hearthstone running?" probe all branch on the platform in `config.py` and
  `setup_logging.py`, and the log lookup asks for both known `Power.log` shapes
  because which one macOS writes is still unverified.
- **The update join.** `VERSION` and `.update_state.json` are stamped into every
  release and are what let an installed copy learn that a newer one exists.
- **The install promise.** Outside Hearthstone's own `log.config` — which the
  launcher edits only when asked, keeping a backup — everything the coach writes
  stays inside its own folder. Uninstalling is deleting one folder, and that has
  to stay true.

### Releasing

```
python app\publish_release.py --note "what changed" --dry-run   # gates only
python app\publish_release.py --note "what changed"             # publish
```

It walks the working tree, runs two gates, stamps the version, uploads to the
collector's KV store and cuts a GitHub release. The gates are the review that
matters most:

- **PRIVACY** — no BattleTags, opponent handles, account ids, local paths or
  session names in any shipped text file.
- **REPRODUCIBILITY** — the zip matches HEAD, with no stray entries.

The version is the commit sha, and `VERSION` is half of the update join: without
it, an installed copy could never be offered a newer release.

### Where the detail lives

- `DESIGN.md` — architecture, and the reasoning behind it.
- `CLAUDE.md` — working rules, and the game's log quirks that keep biting.
- `ROADMAP.md` — phase status.
- `analysis/` — the research the design came out of (not shipped).
- `telemetry/README.md` — the collector: its routes, retention and deploy notes.
