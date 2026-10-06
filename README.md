# Bob's Ledger

<img src="docs/decide.png" alt="The overlay mid-game: DO THIS NOW gives one buy with its reason, and the level step underneath" width="560">

A real-time coach for **Hearthstone Battlegrounds**. It watches the game you are
already playing, reads the board you actually have, and tells you the best move
this turn — with the reason why.

**Windows only.** It reads the log file Hearthstone writes on your own PC and
asks for no account. It does not modify the game — the one file it can change is
Hearthstone's own logging setting, and only if you say yes to it (see
[turning on logging](#turn-on-hearthstones-logging)).

**[Install it](#install-it)** · **[Turn on logging](#turn-on-hearthstones-logging)** ·
**[Is this allowed?](#is-this-allowed)** · **[The question it asks you](#the-one-question-it-asks-you)** ·
**[Something's wrong](#if-somethings-wrong)**

## What you need

- A Windows PC with Hearthstone installed.
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
you where Hearthstone's log folder should be, offers a **shortcut with its own
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

- **Left — the decision.** The one move for this turn, in large text, with the
  reason underneath and the numbers behind it.
- **Right — the reference.** Your shop ranked for the board you have, the comps
  worth committing to and how close you are to each, and what your next opponent
  is likely bringing.

It ranks the awkward picks too: heroes, trinkets, discovers.

## The one question it asks you

<img src="docs/first-run.png" alt="The first-run card: the log.config block to copy, a line saying nothing has been sent yet, and the question with Yes and No buttons" width="560">

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

Why I ask: the advice has not been measured against results yet, and those
summaries are how it gets measured.

## One honest thing about the advice

Bob's Ledger is a second opinion, not an oracle. Its recommendations have not yet
been checked against outcomes, and its own audits say some of them — the ones
about when to level up especially — may be wrong. Treat a surprising call as a
question worth pricing, not a verdict.

## Is this allowed?

Worth answering straight, because it is the first thing a lot of people ask.

**This is real-time assistance, and that is not a technicality.** It reads the
board you actually have and tells you what to buy, every buy phase. It is not a
spreadsheet of statistics you interpret yourself, and it does not pretend to be.
If you think anything past raw data is cheating, this is past raw data, and you
should not use it.

Some facts, kept apart from that judgement:

- **Blizzard has not prohibited this.** It does not touch the game's process or
  its memory, does not automate input, and reads the log file Hearthstone writes
  to your own disk. Tools in this category — Deck Tracker, Firestone, stat
  overlays — have been used openly for years. The one file it will change is
  Hearthstone's own logging setting, and only if you say yes.
- **"Not prohibited" is not the same as "appropriate everywhere".** Turn it off
  for tournaments and any organised event. Their rules usually bar outside help
  outright, whatever Blizzard's position is.
- **Keep it off stream if that worries you.** In practice this kind of thing gets
  noticed because it was on screen in a screenshot or a clip, not because
  anything detected it.
- **You are allowed to disagree with the paragraph above.** Some people draw this
  line where raw data ends and reasonable people land on both sides of it. It is
  a fair position, and the answer is to not run the coach — not to find a
  cleverer reason it is fine.

## Two more things worth knowing

- **Patch days.** After a Hearthstone patch the coach's reference data lags a few
  days, so advice can be less sharp until it catches up. It looks for a new
  version every time you start.
- **Where it comes from.** The advice is worked out on your own PC, from
  Hearthstone's log plus a reference file that ships with the app — nothing is
  sent anywhere to produce it, and it works with your internet off. Only the card
  pictures need a connection.

## If something's wrong

- **A black window flashes and vanishes.** You ran the file from inside the .zip.
  Unzip it first (step 2), then run it from the folder you get.
- **It says Python was not found.** Install Python from python.org, tick **Add
  python.exe to PATH**, and run the file again.
- **The overlay keeps waiting for advice.** Hearthstone's logging is probably
  still off. The overlay shows that same setting on screen.
- **The advice stops changing.** The overlay says how long ago it was written, so
  you can tell stale advice from live advice.
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
model in the loop early on and decided against it, so nothing on the advising
path calls one: `live.py`, `live_coach.py`, `value.py` and `coach_ui.py` do not
import it, and every recommendation comes from the local value function and the
meta database. The experiment is still here — `coach_llm.py` is the client,
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
README, `LICENSE`, `docs/`, the launcher — plus what never ships: `analysis/`
(research notes, some of which name real opponents), `telemetry/` (the release
channel itself), `CLAUDE.md`, `DESIGN.md`, `ROADMAP.md`.

### Tests

```
python -m unittest discover -s app/tests
```

About a thousand tests, ~45 seconds. Some skip by design: the ones that need a
real `Power.log` or maintainer-only files report as skipped rather than passing
quietly.

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
