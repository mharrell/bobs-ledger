# Leveling model — design spec

Sources: Jeef "Leveling Explained By a PRO" (A0EqnsBkClo), Shadybunny
"7 Things I Wish I Knew" (GeuRrFYtsZo), "How to get 8000 MMR" (yhult8FLYM4),
"Ultimate Beginner's Guide" (0plivGW2PPo) — transcripts in
`meta/transcripts/` (fetched 2026-09-04) — plus the 2026-09-04 Guff replay
review and player feedback ("a must-buy in the shop; or hero power /
trinket makes me feel OP right now").

## The two questions (Jeef, for tiers 5-6 — generalizes)

**Q1: What am I leveling FOR?** You must be able to name cards.
Valid: "I need this specific tier+1 card", "my comp's core lives there",
"I have pairs to triple", "nothing on my tier improves my board".
Invalid: "because the curve says so", "to deal one extra damage".

**Q2: Will I die if I level?** Below ~15 effective health with a weak
board, stabilize first. From turn 8+, prefer ~31 effective health (two
turns of stabilization room). The damage cap scales with opponent tier,
so late-game losses cost far more than early ones (early losses cap at 5).

**Q0 (Shady): Am I TOO strong right now?** If you are already winning
fights comfortably, buying more tempo is a waste — "that strength is
there to allow you to level". Aim to *barely* clear the fight, invest
the rest into leveling and economy. The inverse holds: losing combats
(armor flow) means tempo, not levels.

## Per-tier structure

- **Tier 2 (standard: turn 2).** Shop-driven: never waste gold. Level
  turn 3 (Jeef curve) only when the turn stays "clean" (every gold has a
  use: hero power, 1-cost spell, economy unit); level turn 4 (Raam curve)
  only for 1-gold hero powers (or Tavern Tipper-like effects).
- **Tier 3 (standard: turn 5).** Still shop-driven. "Three on three"
  (turn 3) is often correct — a bad shop's trash buys are worse than the
  risk. Strong pairs and synergistic combos are not trash; weak pairs are.
  Curve-fixing spells (Tad, Scout) are reasons to stay down.
- **Tier 4 (standard: turn 7).** The decision moves from the shop to the
  BOARD: is the board full (staying = inefficient upgrades)? Are we
  stable (5 strong units can be enough to level)? Would leveling take 15
  damage (board too weak → buy stabilizers: pairs, combos, buffs)?
  Past turn 7 to tier 4 is underleveling.
- **Tier 5/6: not about the turn number at all** (turn 7 to turn 12).
  Q1 and Q2 only. Key odds rule: **leveling to 5 lowers your odds of
  finding 4-drops** — don't level if what we need is mostly on our
  current tier; don't level to 6 if the needs are 5-drops. Tribe-
  specific: some comps level out on 4 (Quilboar, Demons), some high-roll
  on 5/6 (Elementals, Pirates). Comp-specific cap: e.g. Quillboar waits
  for the Prickly Piper setup — "I don't care what turn it is".

## The five gates (implementation)

Ordered; each flip must produce a stated REASON (advice with a visible
why is coachable; opaque advice teaches nothing):

1. **Curve prior** — the standard cadence (tier 2 ~t2/3, 3 ~t5, 4 ~t7)
   is the default plan, stated as such.
2. **Tempo-surplus flip (Q0)** — winning combats (armor flow flat) with
   a board already above the turn baseline → level even off-curve; if
   losing (armor dropped) → buy tempo instead. Player's "must-buy"/
   "feel OP" triggers live here (shop core → buy-first, exists; hero/
   trinket power spikes → confidence to level).
3. **Trash-shop flip** — nothing buyable in the shop (top cards under
   the "would improve the board" bar) → LEVEL ("don't buy trash").
   Amazing shop (double economy / shop-buff combos) → stay and buy.
4. **Payoff gate (Q1)** — the target comp's shopping list filtered to
   tier+1 must contain ≥1 unowned piece, OR we hold pairs near a triple,
   OR our current tier's shopping list is exhausted. If what we need is
   mostly at the CURRENT tier (or 4-drops while at 4), stay: leveling
   lowers the odds of finding it.
5. **Survival gate (Q2)** — effective health below the stabilization
   buffer (~15 urgent / ~31 comfortable from turn 8+) with a weak board
   → stabilize first; with a strong board or a known winnable next fight
   (ghosting / scouted weaker opponent) → level anyway.

## Signals we have vs need

Have: turn, gold, live level cost (button price, −1/turn waited), tier,
board (minions/stats/engines/comp), shop rank + prices, HP + armor,
target comp + shopping list, hero + trinket, armor delta (loss streak —
needs tracking per phase).

Need (build order):
1. **Armor-flow tracking** (per-phase armor delta) — DONE 2026-09-04
   (gates 1+2): `damage_last` + `loss_streak`; two straight losses or
   one ≥10 hit at tier ≥3 defer the level with a stated reason.
2. **Shopping-list tier filter** — DONE 2026-09-04 (gates 1+2):
   `_comp_needs_by_tier` splits the comp's unowned pieces by tier;
   pieces only on the current tier → stay and buy, stated.
3. **Turn baseline** — DONE 2026-09-04 (gate 3): `build_baseline.py`
   mines the local corpus into `meta/turn_baseline.json` (median
   friendly + fought-opponent board stats per turn); the coach falls
   back down the turn ladder when a turn has no samples.
4. **Opponent estimate** — DONE 2026-09-04 (gate 4): the log carries
   `NEXT_OPPONENT_PLAYER_ID` (announced each buy phase on the friendly
   hero/account), and every combat WE fight logs the opponent-side
   board (fixed player id 11 — real ids are not recoverable). The
   pairing maps each combat board to its announced opponent, so the
   announced next opponent's LAST-KNOWN board is exactly the buy-phase
   preview the player sees; never-fought opponents fall back to the
   lobby median, then the corpus baseline. Live: analysis exposes
   `board_stats`, `opp_stats` (exact, last-known), `lobby_opp`,
   `baseline_opp`; the state strip shows "you X stats · ~Y theirs",
   and the level gates' reasons carry the comparison ("your 7 vs
   their ~16"). Shadybunny's Q0 uses it: already ≥1.5x their board and
   not losing → "you're strong — convert it into a tier".
5. **Next: combat forecast** — a real "will I win the next fight"
   estimate (positioning, keywords, deathrattles) would ground gate 5
   properly; the stat-total comparison is the v1 proxy.