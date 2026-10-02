# Market & Competitor Analysis — HSReplay / Vicious Syndicate / Firestone

How the incumbent stat-overlay products work, how they get their data, and how
an AI coach competes.

---

## 1. How the incumbents get their data

Both major sources are **crowdsourced from opt-in users** — not mined from
Blizzard, not scraped.

### HSReplay (HearthSim) — Hearthstone Deck Tracker / Firestone
- Users install [Hearthstone-Deck-Tracker](https://github.com/HearthSim/Hearthstone-Deck-Tracker/wiki/Overlay)
  or Firestone and **opt in to replay upload**.
- The tracker reads Hearthstone's **own log files** from the game install folder
  and uploads anonymized replays to HSReplay.net.
- HearthSim parses each replay into a structured event stream, aggregates across
  millions of contributed games, and publishes win-rates (tavern tier, minion/
  triple, comp tier lists).
- Sources:
  - https://hearthsim.info/blog/how-we-process-replays/
  - https://github.com/HearthSim/legal (PRIVACY.md)
  - https://deepwiki.com/bd/HSReplay.net/3-upload-and-processing-pipeline

### Vicious Syndicate (the other major source)
- Same model: their app reads the game log and uploads replays.
- They **pay a small group of high-MMR "contributors"** for a ranked, high-skill
  sample. Win-rate reports come from that pool.
- Source: https://www.vicioussyndicate.com/data-collection/

---

## 2. What the installed app stores locally vs. fetches live

Inspected the installed HDT app at
`<HearthstoneDeckTracker dir>`:

| File | What it is | Local or live? |
|------|-----------|----------------|
| `BgsLastGames.xml` | Own recent BG games: hero, rating before/after, placement, **final board only** — no opponent data | Local |
| `Replays/` | `.hdtreplay` files — **constructed** matches only, own games | Local |
| `hsreplay_winrates.cache` | Tiny (~667 B) transient cache of aggregate class win-rates w/ server timestamp | Live (fetched, barely cached) |
| `hsreplay.cache` | Account token / user id | Local (auth) |
| `hsreplay_oauth`, `tier7_trial` | Encrypted/binary auth tokens | Local (auth) |
| `Images/` | Card art cache | Local (assets) |
| `CardDefs/` | Card definitions | Local |

**Key conclusion:** The app is a **thin client**. It parses the local `Power.log`
into your games, and pulls essentially *all* displayed statistics live from their
API. The numbers are a network call to a service they control — which is exactly
why the user experience is "at the mercy of the owner."

**HDT does not persist opponent data locally.** Its cache stores only your own
final board + placement. So the raw `Power.log` is *more detailed* than the
tracker keeps — a useful asymmetry for our own tool.

---

## 3. Can we get their data?

- **Aggregate stats:** HSReplay has a **public API** serving aggregated statistics
  only (win-rates, card/minion stats, tier lists). Docs:
  https://github.com/HearthSim/hsreplaynet-api-docs
  - Caveat: **Battlegrounds-specific coverage in the *public* API is uncertain.**
    Verify whether the BG endpoints (minion/comp win-rates, tavern tier curves)
    are queryable via the public API or only surfaced in-app. Read their terms and
    respect rate limits.
- **Raw replays:** **not available** from HSReplay or Vicious Syndicate. They are
  the proprietary asset. The only way to accumulate raw/outcome data is your own
  opt-in upload loop.

---

## 4. Positioning strategy

- **We can't beat them on raw aggregate volume** (they have years of contributed
  replays; we'd start at zero).
- **We win on reasoning and dynamic adaptation:** their data says "this comp has
  X% win-rate at 4k"; our coach says "you have a triple pair and 8 gold — here's
  the best move for this exact board, and why."
- **Recommended hybrid:** pull HSReplay aggregate stats (if accessible) as a
  supplement, but **lead with reasoning** + curated meta screenshots (which
  removes dependence on their API entirely).

---

## 5. Our own data flywheel (optional, longer term)

If we want a durable moat and current-meta numbers without depending on HSReplay,
build our own opt-in upload loop: our tool reads the same `Power.log` and uploads
anonymized replays to our own service, accumulating outcome data over time. This
is the same model as HearthSim/VS — starting the flywheel from zero is the real
cost of competing on data.
