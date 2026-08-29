# Coaching UI — Design (local Chrome overlay)

**Status: design / brainstorm — NOT implementation.**

The goal is a local web overlay (opened in Chrome) that sits over/next to
Hearthstone while playing Battlegrounds, showing a set of small "boxes"
(widgets) that give advice or track info, driven by the live coach pipeline
(`live.py` → board + bans + comps + value).

## Guiding principle

Each box should ideally drive a **decision** (buy / sell / level / pivot /
pick) rather than just report status. Pure-status boxes exist, but decision
boxes matter most.

## Candidate widgets

### Board & state
- **Health / placement / opponents-left** meter — "am I winning" strip.
- **Triple tracker** — which minions you're one copy from tripling (great shop
  signal: a triple is a big tempo/engine play).
- **Hero power status** — ready this turn, and whether it's worth using now.
- **Banned-tribes strip** — always-visible reminder of what's not coming (the
  5/5 family ban).

### Shop / buy decision
- **"Buy this"** — the single best tavern minion to buy right now (value
  function applied to the shop).
- **Tavern minion ranking** — the shop's minions ranked by value to the current
  comp.
- **Refresh-vs-level call** — "you can afford to level", or "roll here" (EV of
  refresh vs buying what's there).

### Comps & opponents
- **Your comp + rival comps** — who's playing what.
- **Opponent threat box** — which rival's board actually beats yours, and why
  (counter-value).
- **Pivot alert** — if your comp is fading vs the lobby, a nudge toward a
  higher-tier comp.
- **Selection ranker** — **ranks the choices when the player must make a
  selection**: heroes, trinkets, discoveries, dark-gift minions, etc.

### Planning & coaching
- **Suggested turn plan** — a mini-sequence: "buy X, sell Y, level, roll".
- **Top-3 high-tier comp targets** — if you pivot, these are the comps to build
  toward (comp-level, with their key minions).
- **Confidence gauge** — how strongly the coach rates the current board.

## Open design questions (for the design pass)
- Which subset of these actually earns a square — not all belong.
- Layout: how they arrange on screen without covering the game.
- Data flow: `live.py` already produces the board + comps + value; how the
  widgets are fed (the analysis the advice model also consumes).
- Whether a widget is advisory (coach's opinion) vs tracking (raw game state).
