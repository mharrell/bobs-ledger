# Bob's Ledger

A real-time coaching overlay for Hearthstone Battlegrounds. It reads the
live game from Hearthstone's own logs, reasons over the actual board —
your gold, your shop, your pairs, your opponent's board — and tells you
the best move *for this exact situation*, with the reason. Stat overlays
tell you what wins at your rating on average; this tells you what to do
with the board you're holding right now.

Be clear on what that advice is: a **rule-based second opinion**, not a
validated oracle. The coach's recommendations have **not** been validated
against outcomes. The project's own audit (`outcome_audit.py`) is explicit
that its followed-vs-ignored HP comparison is observational and not causal
— players follow advice in easy spots and ignore it in scary ones — and
that the leveling lane is the suspect: followed level advice preceded a
mean −4.6 HP loss against −2.0 when ignored. So treat a level line as a
question to price, not a verdict.

No account access, no game modification — it only reads log files that
Hearthstone writes on your disk.

## What you need

- Windows (the log paths default to a standard Windows Hearthstone install;
  a custom install can be pointed at with the `HEARTHSTONE_HOME` env var)
- Python 3.9 or newer
- Hearthstone installed and able to run

**There is no AI model in the loop.** The advice is computed on your
machine by a deterministic value function and growth simulator over a
curated meta database — no model is called during play, nothing about
your game is sent anywhere to produce it, and there is no API key to
configure. (The repo also contains an optional maintainer tool that uses
a model to extract patch notes into the meta DB; it is not part of the
coach and is not in a release.)

The coach needs **no API key**. It does not need the internet to advise:
the advice comes from a local value function plus a meta reference bundled
in `meta/` (including the card→tribe map, so there is no first-run
download). Two things do use the network, both optional to play: card art
is fetched from HearthstoneJSON on demand, and each start checks the
release channel for a new version (disable with `--no-update`).

## Get it

**1. Download the latest release:** <https://github.com/mharrell/bobs-ledger/releases/latest>
→ click the `.zip` under Assets. (No GitHub account needed; the same file is
always at <https://hearth-telemetry-collector.bobs-ledger.workers.dev/release/latest.zip>.)

**2. Unzip it somewhere you can write** — Desktop or Documents are ideal.
There is no installer and nothing to build. (Not `C:\Program Files`: Windows
won't let the coach keep its card-art cache there, so the overlay would run
without art.)

**3. Double-click `Start Bob's Ledger.cmd`** in the folder you unzipped. That
is the whole install:

- it finds Python 3 (and points you at python.org if there isn't one),
- checks the one dependency it needs, **asking before it installs anything**,
- says where Hearthstone's log folder should be,
- offers a **Bob's Ledger shortcut with its icon** for this folder and your
  Desktop,
- starts the coach and opens the overlay in your browser.

Run it with `--check` to see what it found without starting anything.

After that, **the shortcut is the app** — and it keeps itself current: each
start checks the release channel and offers a newer version if there is one
(decline with `--no-update`).

### If you would rather do it by hand

```
cd <the folder you unzipped>
python -m pip install -r requirements.txt
python live.py
```

### Working on the code

```
git clone https://github.com/mharrell/bobs-ledger
```

A clone is never auto-updated — commit shas can't prove which side is newer,
so the update check stands aside; update with `git pull`. `python live.py
--version` prints what you're running either way.

## Quick start

Once the launcher has run, there are two things between you and real advice.

1. **Turn on Hearthstone's file logging.** This is the step everyone
   misses — by default Hearthstone writes no `Power.log` at all, and with
   no log the coach has nothing to read.

   a. Close Hearthstone if it's running.

   b. Press `Win+R`, paste `%LocalAppData%\Blizzard\Hearthstone`, Enter.

   c. Open (or create) a file called `log.config` with a text editor, and
      make sure it contains at least:

      ```
      [Power]
      LogLevel=1
      FilePrinting=true
      ConsolePrinting=false
      Screenshots=false
      ```

   d. If you use Hearthstone Deck Tracker or Firestone, they likely
      created this file already — then you're done before you started.

   e. Start Hearthstone. The coach looks for logs under
      `C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_<timestamp>\Power.log`.

   (The overlay's welcome card shows this same block, and the launcher tells
   you if the log folder is missing — you should never have to come back
   here for it.)

2. **Play a game.** With Hearthstone running, the launcher's window prints
   its advice and the overlay fills in as you play. The overlay starts as a
   welcome card and shows advice the moment your shop opens.

   Sanity check: the strip at the top shows your hero, gold, tavern tier and
   turn — they should match the game. If the strip is right, everything
   downstream is trustworthy. If it stays on "Waiting for live.py analysis…",
   see [Troubleshooting](#troubleshooting).

Useful flags, if you run it from a terminal: `python live.py <path-to-Power.log>
--poll 0.5` re-analyzes a saved log, `--once` does a single analysis,
`--no-ui` skips the overlay.

## The overlay, box by box

When there's nothing to advise yet — a fresh start, a brand-new game, or
after a press of the **Clear** button (top-right) — the overlay shows a
welcome card instead of panels. It never shows the previous game's
advice: a new game wipes the screen automatically (and resets your
manual ban taps, since the tribe ban differs per game).

On a wide window the overlay is **two panes**: **Decide** on the left —
everything the turn's decision needs, never scrolled away — and
**Reference** on the right, which scrolls. On a narrow window they stack
into one column, decision first.

Decide pane:

- **State strip** (top line) — hero, gold, tavern tier, HP, turn, and
  your live placement, as stat tiles, plus:
  - **Scout strip** — your board's stats vs. the next opponent's, so
    "will the next fight kill me" is answered on screen.
  - **Combat forecast** — `✓ favored` / `even` / `✕ behind` for the next
    fight.
  - **Banned tribes** — this game's 5/5 tribe ban (see glossary).
- **Do this now** — the plan as numbered steps, step 1 bigger than
  everything else with a gold bar: the one move the turn is for. Each
  step carries a kind chip (BUY / LEVEL / SELL / ROLL / …), the action,
  and one reason; the rest of the rationale hides behind the "…". A
  danger band (▲ FRAGILE / ■ DYING) sits above the plan when the next
  hit matters more than the plan. Includes a level-vs-roll reference
  line and the buy price actually read from the game.
- **Choose 1** — appears during hero / trinket / discover
  picks; ranks the options for your situation. Options with no data say
  so instead of pretending to rank. (Dark Gift picks are not ranked —
  there is no dark-gift ranking path, and the overlay drops the line.)
- **Your hand** — held cards with their verdict (cast / play / hold /
  discard); the plan's chosen discard fodder is named on its tile.
- **Hand engine** — when a hand-charge kit is in play: deployer on
  board? slot free? how many charging.

Reference pane:

- **Next opponent** — the announced opponent's comp, as of the round
  shown.
- **Sell** — board minions grouped *safe to sell | divider | do not
  sell*, each row with the why ("comp core" is a keep; "stats only" is
  a safe sell).
- **Looking for (comp / pivot)** — what to shop for on future rolls.
- **Comp direction** — a meter per candidate comp: how close you are to
  the 2-core-hit commit point, with the state in words beside it.
- **Lobby pressure** — which tribes the seats you've seen are committing.
- **Tavern (ranked)** — the current shop offers, ranked for your board,
  with prices and card art; the plan's buy glows gold.
- **Playable comps** — the comps actually possible this game (after the
  tribe ban filter), in meta-tier order, click to expand a comp's
  shopping list. Readable from turn 1: while the lobby's 5/5 tribe bans
  are still being read from the shop rolls (~turn 3-5), every comp stays
  listed with not-yet-confirmed tribes dimmed, and the ban-picker chips
  let you set the banned tribes by hand from the reveal screen.

## Coach vocabulary

- **Hold** — you have a pair (2 copies of a minion); keep it — a 3rd copy
  triples it and turns it golden.
- **Off-build** — a buy outside your committed comp's tribe/build; the
  coach damps these once a comp is committed.
- **Pivot** — switching comps mid-game; "Looking for (pivot)" means the
  coach believes your current comp is no longer winnable and names the
  next-best.
- **Comp pips / commit readiness** — how many of a comp's core minions
  you already own (core hits / 2). More pips = stronger case to commit.
- **Level vs board** — the rule behind the level/roll reference line:
  level the tavern when your board is strong enough to survive on
  tempo; roll when it isn't.
- **5/5 tribe ban** — Battlegrounds bans 5 of the minion tribes each
  game (shown in the state strip); comps whose core is mostly banned
  are filtered out, degraded comps are kept and marked.

## After a Hearthstone patch

The meta reference (`meta/*.json`) is a point-in-time snapshot. After a
game patch:

1. New minions/spells change: run the patch-notes pipeline —
   `python patch_notes.py` applies official Blizzard patch notes to the
   meta DB (dry-run by default; `--apply` writes). `python doctor.py`
   is the one-command verdict afterwards (patch, coverage, art, newest
   log); it flags anything the refresh missed.
2. Card art for new cards: re-run `python hearth_art_extract.py` to
   re-extract art from the local client (needs the optional
   `python -m pip install UnityPy`), or let the overlay fall back to
   HearthstoneJSON — which lags a patch by days; missing art after a
   patch is known and harmless (the overlay shows a text tile).

Everything else keeps working on an old meta — advice just may not know
the newest cards.

## Privacy & telemetry

What the coach writes on your machine:

- `img_cache/` — downloaded card art.
- `decision_logs/` — one JSONL line per advisory: what the coach advised,
  when, on which game state. **Contains no personal data** — card ids and
  minion names only. (Verified, not assumed: a scan of 31,607 records for
  BattleTag-shaped text finds none, because player names never reach the
  analysis.)

Nothing is uploaded automatically, ever. The only network traffic the coach
generates on its own is card art and the start-of-run release check above.
Sharing data with the maintainer is an explicit manual step:

```
python package_corpus.py <Power.log>   # bundle: sanitized log + decisions
python package_corpus.py --inspect corpus_out/<bundle>   # what's inside
python upload_corpus.py --latest       # upload
```

`--inspect` decodes a bundle and re-scans its contents with
`privacy_scan.py` — deliberately separate code from the sanitizer, so a
redactor that misses a category cannot certify its own work. A bundle is
one gzipped JSON file: the sanitized log, the decision log, and a
manifest. Nothing else.

Three ways to send it — **no GitHub account needed for the first two:**

1. **Collector URL** (what beta testers use): set
   `HEARTH_TELEMETRY_URL` (and optionally `HEARTH_TELEMETRY_KEY`, the
   shared secret the maintainer hands out with the URL) and run
   `python upload_corpus.py --latest`. A plain HTTPS POST; the reference
   collector lives in `../telemetry/`.
2. **The file itself**: the bundle from `package_corpus.py` is a single
   self-contained file — email it, attach it, drop it wherever you
   already talk to the maintainer.
3. **Your own GitHub repo**: `gh` logged in, or `GH_TELEMETRY_TOKEN`
   (a fine-grained PAT with Contents write on that repo only); default
   repo `mharrell/hearth-telemetry`, override with
   `HEARTH_TELEMETRY_REPO`.

The Power.log in a bundle is sanitized first. `sanitize_log.py` redacts
**every player identity** the log carries, which is three categories, not
one: BattleTags (`handle#1234`), the bare opponent handles Battlegrounds
writes for most opponents (no discriminator at all), and `GameAccountId`
pairs — the `lo` half is stable for an account across sessions, so leaving
it in would let uploads be linked together. Each becomes a stable
placeholder (`P1`, `P2`, …), so the sanitized log still analyses exactly
like the original. `--inspect` proves it on the file you are about to send.

To record no decision log at all (locally or otherwise), run with
`HEARTH_TELEMETRY=0`. That switch governs the local advisory log only; it
does not stop the release check (`--no-update` does that).

## Uninstalling

Delete the install folder — the one you unzipped. Nothing is written
outside it: no registry entries, no services, no data under `AppData`.
Everything the coach stores lives inside the install:

- `img_cache/` — downloaded and extracted card art.
- `decision_logs/` — the local advisory log (one JSONL line
  per advisory).
- `.card_races.json` — the card→tribe cache.
- `.update_state.json` — the install's last-updated stamp, at the install
  root.
- `Bob's Ledger.lnk` — the shortcut the launcher offers: one here in the
  install folder (it travels with the folder) and optionally one on your
  Desktop. Windows cannot put an icon on a `.cmd`, so a shortcut is the only
  clickable thing that shows the icon. Delete either like any other
  shortcut.

The one thing the coach asks you to change outside its folder is
Hearthstone's own `log.config` (Quick start step 2). It belongs to
Hearthstone, not the coach, and other trackers may rely on it — leave it
alone unless you want the logging off.

## License & attribution

The coach's code is MIT-licensed — see `LICENSE` in the repo root. Two
things the license doesn't cover, credited where they came from:

- The meta reference (`meta/*.json`) credits its sources: each comp in
  `comps.json` names where the build came from (hsreplay.net's public
  comp pages, via `scrape_comps.py`; one comp is mined from our own
  replay corpus, curated with the maintainer), and card data comes from
  HearthstoneJSON. The strategy *builds* are facts; the guide text is
  written in the coach's own words — nothing is republished.
- Hearthstone — card names, text, and art — is © Blizzard
  Entertainment. This is an unofficial fan tool: it reads log files
  only and is not affiliated with or endorsed by Blizzard.

## Something wrong? Ask

The coach reads a log file, so most problems are some version of "it isn't
seeing my game". Two things make that quick to sort out:

1. Run **`Start Bob's Ledger.cmd --check`** and read the top few lines — it
   reports the Python it found, whether the dependency is installed, and
   where it looked for Hearthstone's log folder. That output answers most
   questions on its own.
2. Then open an issue: <https://github.com/mharrell/bobs-ledger/issues>.
   Paste the `--check` output and what you expected to happen; a screenshot
   of the overlay helps more than a description of it.

## Troubleshooting

- **`Start Bob's Ledger.cmd` says Python 3 was not found** — install it from
  python.org and tick *"Add python.exe to PATH"* in the installer, then run
  the launcher again. It offers to open the download page for you.
- **The launcher window flashes and closes** — run it from a Command Prompt
  (or run `Start Bob's Ledger.cmd --check`) so you can read the message;
  the window normally stays open for the whole session.
- **`No active Power.log found` / nothing happens during a game** —
  file logging isn't enabled (see Quick start step 2), or Hearthstone
  hasn't written a log in the last 10 minutes. The coach auto-finds the
  newest session log modified within 10 minutes (`LIVE_RECENT` env var
  changes this); pass an explicit path to analyze an older one. The overlay's
  welcome card also shows the `log.config` block.
- **Overlay says "Waiting for live.py analysis…"** — live.py isn't
  running, or it found no active log. Check the terminal output.
- **The overlay's advice says it is N seconds old** — that line only appears
  when the advice has stopped updating: live.py has wedged or exited. The
  overlay is deliberately showing you its last frame and telling you so
  rather than pretending it is live.
- **Overlay frozen / shows a stale board** — refresh the browser tab.
  Between rounds the shop can legitimately be empty (shop is dealt at
  round start); that gap is normal.
- **Advice ignores a new patch's cards / comps look wrong after a
  patch** — stale meta; see [After a Hearthstone patch](#after-a-hearthstone-patch).
- **Card art missing** — HearthstoneJSON lags a patch (harmless), or
  `img_cache/` was cleared; re-run `hearth_art_extract.py` for full
  coverage from the local client.
- **`Coach UI skipped (...)` at startup** — the default port is taken;
  the overlay is skipped for that run. Retry or free the port.
- **Advice mid-spectate / replay looks odd** — hero parsing can fail on
  spectated or oddly-formatted games; live coaching is built for your
  own games.

## Going further

Internal docs (design history, not needed to use the coach):
`DESIGN.md` (architecture), `ROADMAP.md` (phase status), `analysis/*.md`
(decision analyses). `analysis/` is maintainer-only and is **not** in a
release zip (its replay reviews name real opponents), so a zip install has
no `analysis/` directory — that is expected, not a broken install.
Post-game tools: `replay_review.py` (coach-vs-player
diff per phase), `replay_stats.py` (replay corpus stats). The test suite:
`python -m unittest discover -s tests`.