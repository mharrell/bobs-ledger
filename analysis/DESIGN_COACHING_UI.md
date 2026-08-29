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

---

## V1 widget set (the ones that earn a square)

Not all candidates make v1. Pick the ones that **drive a decision** and are
computable from the existing pipeline (`live.py` → board + bans + comps + value):

1. **Sell ranking** — your board, safest-to-sell → most-valuable (already in `coach.py`).
2. **Tavern buy ranking** — the shop's minions ranked by value to your comp.
3. **Buy this** — the single best tavern minion right now (headline of the shop rank).
4. **Selection ranker** — ranked choices when a pick appears (heroes/trinkets/
   discoveries/dark gifts). Appears only when a choice is active.
5. **Your comp + rival comps** — who's playing what (context).
6. **Refresh-vs-level** — "you can afford to level" vs "roll here."

**Deferred to v2:** opponent-threat box (needs opponent boards), pivot alert
(needs more value tuning), triple tracker, confidence gauge, banned-tribes strip,
turn plan.

## Layout

A **single fixed side panel** (or a small grid of boxes) that docks to the side of
the game window, roughly 250–320px wide. Boxes stack vertically; each is a compact
card with a title and 3–6 ranked rows. It should be **draggable and collapsible**
so the player can move it clear of the shop/board.

## Data flow

```
Hearthstone Power.log (live)
   └─ live.py  →  analysis dict { hero, tier, gold, board, banned,
                                   playable_comps, sell_rank, ... }
                      └─ a local web server (FastAPI/Flask or a tiny stdlib
                         server) exposes the latest analysis as JSON
                              └─ Chrome opens a static HTML page that polls the
                                 server and renders each widget from the JSON
```

- `live.py` already produces the analysis every buy phase; the server just
  serves the latest snapshot.
- Each widget reads a slice of the analysis JSON (e.g. Sell box reads
  `sell_rank`, comp box reads `playable_comps` + the board's implied comp, etc.).
- The **selection ranker** needs a new piece: detect an active choice (a
  discover/trinket/pick) and rank its options. That's a v1 addition to
  `live.py`/`coach.py`.

## Tech approach (local, no cloud)

- Local **Python stdlib HTTP server** (`http.server`) — no framework install.
- A single **static HTML + CSS + JS** page opened in Chrome.
- **No vision/OCR** — everything comes from the log parse the coach already does.
- The advice model (when chosen) slots in later as a `advice` field on the JSON.
