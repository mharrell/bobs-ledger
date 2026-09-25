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
   Coach UI: http://127.0.0.1:8747/
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
- **Choose 1** — appears during hero / trinket / Dark Gift / discover
  picks; ranks the options for your situation. Options with no data say
  so instead of pretending to rank.
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

## License & attribution

The coach's code is MIT-licensed — see `LICENSE` in the repo root. Two
things the license doesn't cover, credited where they came from:

- The meta reference (`meta/*.json`) credits its sources: each comp in
  `comps.json` names where the build came from (hsreplay.net's public
  comp pages, via `scrape_comps.py`; one comp is mined from our own
  replay corpus and marked `provisional`), and card data comes from
  HearthstoneJSON. The strategy *builds* are facts; the guide text is
  written in the coach's own words — nothing is republished.
- Hearthstone — card names, text, and art — is © Blizzard
  Entertainment. This is an unofficial fan tool: it reads log files
  only and is not affiliated with or endorsed by Blizzard.

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