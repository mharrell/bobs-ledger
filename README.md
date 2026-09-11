# Hearthstone Battlegrounds Coach

A real-time coaching overlay for Hearthstone Battlegrounds. It reads the
live game from Hearthstone's own logs, reasons over the actual board —
your gold, your shop, your pairs, your opponent's board — and tells you
the best move *for this exact situation*, with the reason. Stat overlays
tell you what wins at your rating on average; this tells you what to do
with the board you're holding right now.

No account access, no game modification — it only reads log files that
Hearthstone writes on your disk.

## What you need

- Windows (the log paths default to a standard Windows Hearthstone install;
  a custom install can be pointed at with the `HEARTHSTONE_HOME` env var)
- Python 3.9 or newer
- Hearthstone installed and able to run

The coach needs **no API key and no internet for normal play** — the advice
comes from a local value function plus a meta reference bundled in
`meta/`. (Only card art may be fetched from the web.)

## Quick start

1. **Install:**

   ```
   cd hearth-coach
   python -m pip install -r requirements.txt
   ```

2. **Turn on Hearthstone's file logging.** This is the step everyone
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

3. **Run the coach** (in a terminal):

   ```
   python live.py
   ```

   With Hearthstone running and a game started, it prints its advice to
   the terminal and starts the overlay:

   ```
   Coach UI: http://127.0.0.1:8765/
   ```

   Open that URL in any browser and park the window beside the game.
   Useful flags: `python live.py <path-to-Power.log> --poll 0.5` to
   re-analyze a saved log, `--once` for a single analysis, `--no-ui` to
   skip the overlay.

4. **Sanity check it's reading you correctly:** during a match, check the
   state strip in the overlay — your hero, gold, tavern tier and turn
   should match the game. If the strip is right, everything downstream
   is trustworthy; if it's stuck on "Waiting for live.py analysis…",
   see [Troubleshooting](#troubleshooting).

## The overlay, box by box

The overlay is one priority column. Read it top to bottom:

- **State strip** (top line) — hero, gold, tavern tier, turn, plus:
  - **Scout strip** — your board's stats vs. the next opponent's, so
    "will the next fight kill me" is answered on screen.
  - **Combat forecast** — `favored` / `even` / `behind` for the next fight.
  - **Banned tribes** — this game's 5/5 tribe ban (see glossary).
- **Do this now** — the single best next move with the why ("Buy
  Tram Operator — you have a triple pair, gold left over"), including a
  level-vs-roll reference line and the buy price it actually read from
  the game.
- **Your hand** — cards held in hand as tiles (hand minions are sellable
  too and appear in the Sell row).
- **Sell** — board minions grouped *safe to sell | divider | keep*, on
  one line.
- **Looking for (comp / pivot)** — what to shop for on future rolls.
- **Comp direction** — per-comp commit readiness ("pips"): how close you
  are to committing to each candidate comp.
- **Tavern (ranked)** — the current shop offers, ranked for your board,
  with prices and card art.
- **Playable comps** — the comps actually possible this game (after the
  tribe ban filter), in meta-tier order. Readable from turn 1: while the
  lobby's 5/5 tribe bans are still being read from the shop rolls
  (~turn 3-5), every comp stays listed with not-yet-confirmed tribes
  dimmed, then the list narrows to the ban filter.
- **Choose 1** — appears during hero / trinket / Dark Gift / discover
  picks; ranks the options for your situation.

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
   meta DB (dry-run by default; `--apply` writes).
2. Card art for new cards: re-run `python hearth_art_extract.py` to
   re-extract art from the local client (100% coverage), or let the
   overlay fall back to HearthstoneJSON — which lags a patch by days;
   missing art after a patch is known and harmless.

Everything else keeps working on an old meta — advice just may not know
the newest cards.

## Privacy & telemetry

What the coach writes on your machine:

- `img_cache/` — downloaded card art.
- `decision_logs/` — one JSONL line per advisory: what the coach advised,
  when, on which game state. **Contains no personal data** — card ids and
  minion names only; BattleTags never reach the analysis.

Nothing is uploaded automatically, ever. Sharing data with the coach's
maintainer is an explicit manual step:

```
python package_corpus.py <Power.log>   # bundle: sanitized log + decisions
python upload_corpus.py --latest      # upload (requires your GitHub auth)
```

The Power.log in a bundle is sanitized first (`sanitize_log.py` redacts
BattleTags — the only personal data Hearthstone writes into logs).
`upload_corpus.py`'s default repo is the maintainer's private research
repo (`mharrell/hearth-telemetry`) — set `HEARTH_TELEMETRY_REPO` to
point at your own repo instead. To record no decision log at all
(locally or otherwise), run with `HEARTH_TELEMETRY=0`.

## Troubleshooting

- **`No active Power.log found` / nothing happens during a game** —
  file logging isn't enabled (see Quick start step 2), or Hearthstone
  hasn't written a log in the last 10 minutes. The coach auto-finds the
  newest session log modified within 10 minutes (`LIVE_RECENT` env var
  changes this); pass an explicit path to analyze an older one.
- **Overlay says "Waiting for live.py analysis…"** — live.py isn't
  running, or it found no active log. Check the terminal output.
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
(decision analyses). Post-game tools: `replay_review.py` (coach-vs-player
diff per phase), `replay_stats.py` (replay corpus stats). The test suite:
`python -m unittest discover -s tests`.