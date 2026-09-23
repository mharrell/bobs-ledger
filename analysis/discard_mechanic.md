# The discard / Deity mechanic (patch 36.6.1) — model and evidence

**Written:** 2026-09-22, the day the patch landed, from the five Power.log
sessions on this machine.
**Scope:** what the mechanic is, what the game's own logs do and do not say
about it, the model added to `simulate_growth` / `meta/engines.json` /
`value.py`, and every assumption in it.
**One-line summary:** the *effect* side of the mechanic is measurable (the
Deity is a logged entity with a progress counter); the *input* side is not —
**no Power.log records a discard**, so the per-turn discard **rate is modelled,
not measured**, and this document says which numbers came from the game, which
came from card text, and which are assumptions.

Sibling documents: `analysis/patch_3661_changes.md` (the verbatim 36.6.1 change
list, and the DB update that landed from it), `analysis/pool_and_out_of_play.md`
(the Aberration tribe arriving / Naga leaving), `analysis/VALUE_FUNCTION.md` (the
value function the new term feeds).

---

## 1. What the mechanic is

Verbatim from the official 36.6.1 overview (transcribed in
`patch_3661_changes.md` §1, primary source
<https://hearthstone.blizzard.com/en-us/news/24302091>):

> Meet Aberrations, the newest Battlegrounds minion type. Built around discard
> synergies, Aberrations grow stronger as they work toward awakening their
> Deity.

- Each time a friendly Aberration dies, it advances your Deity's progress.
- There are two Deities, **C'Thun** and **Y'Shaarj**, but only one will answer
  your call — chosen **at random at the start of each game**.
- Once **three sacrifices** have been made, your Deity joins the fight with a
  game-changing effect. The patch-notes page words it "joins **for that
  combat**".

The two heads:

| Deity | Tier | Stats | Text (verbatim) |
|---|---|---|---|
| **C'Thun** | 3 | 1/1 | *Deity.* After this awakens, give this minion's stats split amongst your other minions. |
| **Y'Shaarj** | 3 | 1/1 | *Deity.* Deathrattle: Summon your first 2 Aberrations that died this combat with their maximum stats (except Deities). |

**The structural consequence for any model:** the Deity is not a board minion.
It is a per-combat appearance whose stats (for C'Thun) are handed out inside one
fight and are gone at its end, and whose payoff (for Y'Shaarj) is a summon, not
stats at all. Anything that adds "the Deity's stats" to a board's stats is
reporting one-fight power as persistent growth — the exact error the project's
2026-09-11 player rule exists to catch (*stat increases during a battle do not
persist unless the text says so*).

---

## 2. The cards, verbatim

Card ids below are from `meta/minions.json` / `meta/tavern_spells.json` /
`meta/trinkets.json` (all three were re-read on 2026-09-22 for this document).

**Trinket coverage caveat.** Of the discard-relevant trinkets named in the
36.6.1 change list, only **Hammer of Twilight** (`BG36_MagicItem_403t`) is
present in `meta/trinkets.json` today — the other rows in §2.2 with a `—` id
(Corrupted Baton, Sludge Portrait, Shath'Yar Shrine, Writhing Tentacles, Tome of
the Ancients, Makeshift Master, Mask of Ancient Ones, Evil Experiment) are known
only from the patch article's text (§9 of `patch_3661_changes.md`), not from the
DB. The engine gates those steps on the trinket's **name** as the live game
passes it, so the chain is not blocked by the DB gap — but a trinket that is not
in the DB will not appear in the live coach's trinket list either, and that gap
belongs to the next `refresh_trinkets.py` pass, not to this document.

**Duos scope caveat (a mode decision, not an oversight).** This coach coaches
**solo** Battlegrounds, so the two new Duos minions (`Voidpriest Cloner`
`134693`, `C'Thrax Wrecker` `134695`) and the two changed ones (`Man'ari
Messenger` `106320`, `Transport Reactor` `117359`) are deliberately **kept out of
`meta/minions.json`** — a Duos-only card in the solo DB could be recommended in a
solo shop, where it can never appear. Verified 2026-09-22: none of the four
names, nor any of their article-side ids, occurs anywhere in
`meta/minions.json`. They are cited in this document **as Duos-only evidence**
(for the per-turn cap wording and for "Deity" being a plural family), never as
solo-pool cards, and they are not part of the engine chain.

### 2.1 Discard outlets — the cards that SPEND a discard

| Card | Id | Text (verbatim) |
|---|---|---|
| Brain Rotter | `BG36_099` | Activate (0): Discard a card to give your Deity +2/+2. |
| Abyssal Envoy | `BG36_311` | Activate (0): Discard a card to get a random Tavern spell. |
| Mangled Bandit | `BG28_582` | Activate (0): Discard a card to get 3 Blood Gems. |
| Mindbending Recruiter | `BG36_312` | Activate (0): Discard a card to get a random Aberration. |
| N'raqi Frostcaller | `BG36_300` | Activate (0): Discard a card for your Tavern spells to give an extra +1/+1 this game. |

Those five are the **only** cards in the DB with an `Activate (N): Discard a
card ...` shape (checked by scanning every row of `minions.json` and
`tavern_spells.json` — see §3.1). Each Activate power is usable **once per
turn**, which is the fact the modelled rate rests on.

### 2.2 Payoffs — cards that REWARD a discard

| Card | Id | Text (verbatim) |
|---|---|---|
| Mindbender Ghur'sha | `BG36_097` | Whenever you discard a card, give your other minions +3/+3. |
| Cutthroat K'Thir | `BG36_106` | Whenever you discard a card, give this and your Deity +4/+4. |
| Harbinger Aph'lass | `BGFYM_005` | Whenever you discard a card, give your Deity +1/+1 and improve this. |
| Mysterious K'Thir | `BG36_320` | At the end of your turn, discard your 3 left-most Tavern spells. Gain +8/+8 for each discarded. |
| Parasitic Fleshling | `BG36_114` | At the end of your turn, give your left-most minion +2/+2. (Improved by each card you've discarded this game!) |
| Hammer of Twilight (Greater trinket) | `BG36_MagicItem_403t` | Your minions have +2/+1. (Improved by each card you've discarded this game!) |
| Corrupted Baton (Lesser / Greater) | — | After you cast a Tavern spell, give your Deity +4/+4 / +10/+10. |
| Sludge Portrait (Greater trinket) | — | Get a Sludge Corrosion. After you discard a card, get a Sludge Corrosion. |
| Shath'Yar Shrine (Greater trinket) | — | After you discard a spell, get a random Aberration. |
| Writhing Tentacles (Greater trinket) | — | After you discard your first minion each turn, get a copy of it with double stats. (1 left!) |

### 2.3 Deity fuel — everything that gives the Deity stats

| Card / source | Id | Text (verbatim) | Trigger |
|---|---|---|---|
| Joyous | `BG36_110` | Battlecry: Give your Deity +2/+2. | Battlecry |
| Brain Rotter | `BG36_099` | Activate (0): Discard a card to give your Deity +2/+2. | discard |
| Drifting Sacrifice | `BG36_113` | Reborn. Deathrattle: Give your Deity +2/+1. | death |
| Vicious Mindslasher | `BG36_108` | Whenever you cast a Tavern spell, give this and your Deity +1/+3. | spell cast |
| Cutthroat K'Thir | `BG36_106` | Whenever you discard a card, give this and your Deity +4/+4. | discard |
| Faceless Converter | `BG36_318` | Deathrattle: Give your Deity +1/+1. (Improved by each Tavern spell you've cast this game!) | death |
| Harbinger Aph'lass | `BGFYM_005` | Whenever you discard a card, give your Deity +1/+1 and improve this. | discard |
| The Shadow of Doubt | `BG36_109` | Whenever a card is added to your hand, give your Deity +3/+4. | card added |
| Sha of Fear | *(no id in DB)* | Whenever you cast a Tavern spell, give your minions and Deity +4/+3. | spell cast |
| Energizing Chamber | `BG36_371` | Give your Deity +7/+7. If you discard this, cast it twice. | spell (+2 casts when discarded) |
| N'raqi Sapper | `BG36_103` | Battlecry and Deathrattle: Get an Energizing Chamber. | supplier |
| Corrupted Baton | — | After you cast a Tavern spell, give your Deity +4/+4 (Greater +10/+10). | spell cast |
| Makeshift Master (Greater trinket) | — | Spellcraft: Choose a minion. After it gains stats outside combat this turn, your Deity also gains them. | stat gain |
| Mask of Ancient Ones (Greater trinket) | — | Make your Deity Golden this game. | — |
| Evil Experiment (Greater trinket) | — | After your Deity awakens, give it Reborn. | — |
| C'Thrax Wrecker (**Duos-only**) | `134695` | Battlecry, Deathrattle, and Rally: Give your **team's Deities** +4/+4. | — |
| Voidpriest Cloner (**Duos-only**) | `134693` | Whenever you discard a card, Pass a copy of it. **(2 times per turn.)** | discard |

Two facts this last pair carries, beyond its own numbers:

- **"Deity" is a card type/family, not one card.** C'Thrax Wrecker says "your
  **team's Deities**" (plural, in a Duos team of two). That matches the model's
  treatment: the Deity is a game-level entity per player, not a board minion —
  which is exactly why its stats are banked apart from the board (§4.3).
- **Discard triggers are capped per turn, and the game prints the cap.** The
  "(2 times per turn.)" parenthetical is the idiom the game uses for a
  repeat-trigger cap, which is the evidence behind the modelled per-turn bound
  (§4.4).

### 2.4 Discard sources that need something the board cannot show

| Source | Text (verbatim) | What it needs |
|---|---|---|
| Drest'agath (hero) | Incubate [1 Cost]: Discard a card to get a random Aberration. | hero power |
| Kith'ix (hero) | Dark Ritual [2 Cost]: Get 2 random minions. When you play one, discard the other. | hero power |
| Wandering Willbreaker `BG36_100` | When you sell this, get 2 random Tavern spells. When you play one, discard the other. | a held card |
| Faceless Operative `BG36_308` | When you sell this, get 2 random Aberrations. When you play one, discard the other. | a held card |
| Willbreaker Sticker (Lesser trinket) | Get 2 random Tavern spells. When you play one, discard the other. At the start of your turn, repeat this. | trinket |
| Sludge Corrosion `BG36_301t` | Give your minions +1/+1. If you discard this, cast it twice. | a held card |
| Corrupted Coin `BG36_303` | Gain 2 Gold. If you discard this, increase your maximum Gold by 2. | a held card |

---

## 3. What the log does — and does not — contain

Everything in this section was re-measured for this document with a one-pass
scan of the five session logs at
`C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_2026_09_2*`, counting
substring occurrences per file. The scans are throwaway probes; the numbers are
reproducible with ~20 lines of Python (read each `Power.log` line by line,
count the patterns — the files are 44–154 MB, ~30 s each).

### 3.1 A discard is NOT a logged event

| Session | `CANT_DISCARD` | `DISCARDED` | `tag=DISCARD` | `BlockType=ACTIVATE` | `BACON_DEITY_SIGIL` |
|---|---|---|---|---|---|
| 09-21 10:33 (2 games) | 14 | 0 | 0 | 0 | 0 |
| 09-21 12:14 (1) | 6 | 0 | 0 | 0 | 0 |
| 09-21 20:40 (3) | 48 | 0 | 0 | 0 | 0 |
| 09-22 07:40 (4) | 84 | 0 | 0 | 0 | 0 |
| **09-22 20:59 (3, the win session)** | **36** | **0** | **0** | **0** | **310** |

`CANT_DISCARD` is a *static card property* (`TAG_CHANGE ... tag=CANT_DISCARD
value=1` on minions like Brann Bronzebeard that may never be discarded), not an
event — it says a card cannot be discarded, never that one was. `BlockType`
values in these logs are `PLAY`, `TRIGGER`, `POWER`, `DEATHRATTLE`, `ATTACK`,
`MAIN_ACTION`, … — **`ACTIVATE` never appears**, so the Activate power that
spends the discard has no block of its own.

**The only discard-shaped structure in the whole session** is the pair
mechanic's internal enchantment, found by listing every entity name containing
"discard" in the win session:

| Entity name | Card id | Lines | What it is |
|---|---|---|---|
| `Discard Minion` | `BG36_308e` | 80 | the enchantment behind "when you play one, discard the other" (Faceless Operative `BG36_308` / Wandering Willbreaker `BG36_100` / Willbreaker Sticker) |
| `Discard Paired Cards Player Ench [DNT]` | `BG36_307pe` | 4 `BLOCK_START BlockType=TRIGGER` blocks | the trigger that performs the pair discard |

So the pair-generator discard *could* be counted from the log by a dedicated
pass (the discarded card carries `LAST_AFFECTED_BY` pointing at the enchantment
immediately before its `tag=ZONE value=GRAVEYARD`). **Activate-discards produce
no comparable marker**: across three games in which Brain Rotter, Abyssal Envoy
and N'raqi Frostcaller were played heavily, no enchantment, block or tag names
them. Cards that move `hand -> GRAVEYARD` do carry two unmapped numeric tags
(`4741`, `1068`) — if a future pass decodes those, the Activate-discard rate may
become measurable, but today it is not, and the model must not pretend
otherwise.

### 3.2 `hand -> GRAVEYARD` is NOT a discard proxy

In the win session there are **168** `zone=HAND ... tag=ZONE value=GRAVEYARD`
transitions. Excluding hero entities (`*_HERO_*`, which move hand → graveyard at
game start, one per player) leaves **150**, and they are dominated by *spells
the player cast*:

```
34x Sludge Corrosion (BG36_301t)     32x Energizing Chamber (BG36_371)
 9x Big Banana          5x Bananas    5x Tricky Trousers
 4x Eonar's Favor       4x Staff of Enrichment   4x Tavern Dish Banana
 3x Tavern Coin         3x Methodical Madness    3x Blood Gem Barrage ...
```

Note the first two rows: they are the 36.6.1 spells whose text is *"If you
discard this, cast it twice"*. A cast and a discard put the card in exactly the
same place, so the signal is not merely noisy — it is **ambiguous on precisely
the cards this mechanic cares about**. The brief for this workstream recorded
the Faelin win game: exactly three hand cards went to GRAVEYARD, and all three
were spells the player *cast* (Eonar's Favor, Blood Gem Barrage, Energizing
Chamber).

Only **four** minion hand → graveyard transitions exist in the whole session,
and all four sit inside a pair-discard trigger block (`Discard Paired Cards
Player Ench [DNT]`, `Discard Minion` enchantment active, `LAST_AFFECTED_BY` set)
— e.g. an `Underrot Spawn` in hand going to GRAVEYARD three lines after
`BLOCK_START BlockType=TRIGGER Entity=[entityName=Discard Paired Cards Player
Ench [DNT] ... cardId=BG36_307pe]`. That is a real discard, and it is
recognisable — but it is 4 events in 3 games, and it covers only the pair
mechanic.

**Conclusion:** there is no log-derived discard counter. The per-turn discard
count is modelled (§4.3).

### 3.3 The Deity side IS logged — more of it than expected

| Measurement (win session, 154 MB, 3 games) | Value |
|---|---|
| `BACON_DEITY_SIGIL` occurrences | **310** (0 in all four older sessions) |
| Lines naming `Secret Deity [DNT]` | 9123 |
| Entity | `entityName="Secret Deity [DNT]" cardId=BG_OldGod`, owned by one player, **`zone=SECRET`** (not `SETASIDE` — the earlier probe's note said SETASIDE; the entity's own zone tag reads SECRET) |
| Distinct Deity entity ids | 41 = 11 + 12 + 18 for the session's three games — i.e. **one entity per round/combat**, re-created each combat, exactly as the earlier probe found (ids 329, 350, 451, 564, 566, 603, 898, 945, 962, 1376, 1430, 1493, …) |
| `BACON_DEITY_SIGIL` values | `1` on 234 tag lines, `0` on 76 — a 0/1 flag that does flip |
| `QUEST_PROGRESS` | increments `0 -> 1 -> 2` during a combat, resets at combat end |
| `QUEST_PROGRESS_TOTAL` | **`3`** — the three-sacrifice requirement is printed by the game itself |
| `BACON_EVOLUTION_CARD_OVERWRITE_ATK` / `_HEALTH` | 720 tag lines; values `1` and `3`, reset to `0` at combat end |
| Deity entering play | `Y'Shaarj` (`BGFYM_011`) entities appear in `zone=SETASIDE` and then `zone=PLAY` — the awakening is observable |
| `C'Thun` | **never** seen in this session's three games |

What that means for the model:

- The **3-sacrifice requirement is confirmed by the game** (`QUEST_PROGRESS_TOTAL
  value=3`), not just by the article.
- **The awakening is at least partly measurable**, and this is the most
  promising next step: counting `BACON_DEITY_SIGIL` 0→1 flips (or
  `Y'Shaarj`/`C'Thun` `SETASIDE -> PLAY` transitions) per combat would replace
  the `awakenings_per_turn = 1` assumption in §5 with a measured number. It was
  **not** done here: the semantics of the sigil/progress tags are not documented
  anywhere in this repo, and reverse-engineering them properly is a workstream of
  its own. The model therefore states the assumption instead of implying it was
  measured.
- The Deity entity's stat-overwrite tags suggest the pool itself may be
  readable per combat — the same caveat applies.
- All three games in this session rolled **Y'Shaarj** (C'Thun never appeared),
  which is consistent with "one at random" but is far too small a sample to
  check the 50/50 split assumed in §5.

---

## 4. The model

### 4.1 Where it lives

| Piece | File | What it does |
|---|---|---|
| Engine chain | `meta/engines.json` → `aberrations-discard-deity` | 9 steps, trigger `discard`, tribe `ABERRATION`, every magnitude with a `note` saying card text vs assumption |
| Two new step conventions | `simulate_growth.py` (`count_from: "self"` / `"turn"`) | "the source's own uses of the trigger, once per copy per turn, capped by the turn's total" and "once per copy per turn, whatever the primary count is" |
| One new step type | `simulate_growth.py` (`type: "deity_pool"`) | banks stats on the Deity **outside** `gain`, and returns them in the result's `deity` block |
| Outlet recognition | `value._is_discard_outlet` / `_discard_outlets` | reads the card's own printed `Activate (N): Discard a card ...` shape |
| The discard rate | `value._discard_scenario` | `discard` = number of outlets on the board (once per turn each), overridable by an explicit scenario |
| The marginal value | `value._discard_fuel_bonus` | mirror of `_spell_fuel_bonus`: the simulator delta between "discards = outlets" and "discards = outlets + 1" |
| The seam | `value.shop_ranking` | a shop **minion** carrying an outlet gets `W_DISCARD_FUEL * fuel` — the same seam that credits a tavern spell with `W_SPELL_FUEL * _spell_fuel_bonus` |

`meta/comps.json` still has **no Aberration comp** (deliberately — see
`pool_and_out_of_play.md` §6), so a comp-keyed engine would be unreachable. The
engine is therefore reached exactly the way `_spell_fuel_bonus` reaches the
cast-spell engines: by triggering off the *board*, not off a comp.

### 4.2 The chain, step by step

Numbers are **per discard per copy on board** unless the note says otherwise.

| # | Step | Numbers | Kind | Source of the numbers |
|---|---|---|---|---|
| 1 | Mindbender Ghur'sha | +3/+3 to all (scope `all`) | board stats | text `BG36_097`. Caveat: printed "your **other** minions"; the simulator has no self-excluding scope, so the step over-states by one minion per copy (documented, not silently corrected) |
| 2 | Cutthroat K'Thir | +4/+4 to itself (scope `target`) | board stats | text `BG36_106`, the "this" half |
| 3 | Mysterious K'Thir | +8/+8 × 3 per turn, once per copy | board stats | text `BG36_320` ("Gain +8/+8 for each discarded", 3 discarded). `count_from: "turn"` — its own discard is end-of-turn and needs **no** outlet |
| 4 | Hammer of Twilight | +2/+1 to all per discard, gated on the trinket | board stats | printed +2/+1 from the trinket text; **the per-discarded-card improvement is not printed anywhere → charged as one printed application per discard (assumption)** |
| 5 | Brain Rotter | +2/+2 to the Deity, `count_from: "self"` | Deity pool | text `BG36_099` |
| 6 | Cutthroat K'Thir | +4/+4 to the Deity | Deity pool | text `BG36_106`, the "your Deity" half |
| 7 | Harbinger Aph'lass | +1/+1 to the Deity | Deity pool | text `BGFYM_005`; its "and improve this" self-growth is unmodelled |
| 8 | N'raqi Sapper | +14/+14 to the Deity, `count_from: "self"` | Deity pool | `BG36_103` grants an Energizing Chamber; `BG36_371` gives +7/+7 and is cast **twice** when discarded: 7+7 ×2 = 14 |
| 9 | Corrupted Baton | +4/+4 to the Deity, gated on the trinket, `count_from: "self"` | Deity pool | Lesser text (+4/+4); **used once per discard-turn as a floor (assumption)** |

Engine-level `deity` block:

```json
"deity": {"sacrifices": 3, "awakenings_per_turn": 1, "payoff_share": 0.5,
          "requires_tribe": "ABERRATION"}
```

### 4.3 The Deity pool is kept OUT of the board's stats

This is the decision this document exists to record.

- `gain` — the simulator's existing output — means **persistent board stats**.
  No Deity number ever enters it. `test_discard.py` asserts this directly
  (`TestDiscardEngineChain.test_deity_pool_is_never_board_gain`: a board of
  Brain Rotter + Abyssal Envoy + Drifting Sacrifice with two discards produces
  `gain == 0` while the Deity pool is positive).
- `deity` — a new result block — reports `atk`/`hp` (the pool this turn's
  triggers banked), `awakenings`, and `realised` = pool × awakenings ×
  `payoff_share`. That is the *expected per-turn combat swing*.
- `value._sim_points()` is the only place the two are combined, and it weights
  the realised pool at `W_DEITY_COMBAT = 0.25` per stat — deliberately **below**
  `W_DISCARD_FUEL = 0.3`, because a combat-only stat is worth less than a
  permanent one (the same reasoning that puts `W_COMBAT_ENGINE` under
  `W_ENGINE`).
- The pool only *realises* when an Aberration is on the board
  (`_tribe_units(board, "ABERRATION")`): three friendly Aberrations have to die
  for the Deity to join, so a board with no Aberration banks the pool and gets
  nothing from it. The pool still accumulates in the report — that is the honest
  distinction between "banked" and "realised".

### 4.4 The discard rate, and its per-turn bound

```python
_discard_scenario(board)  # {'discard': min(outlets on the board, DISCARD_RATE_CAP), ...}
DISCARD_RATE_CAP = 7
```

- An `Activate` power is usable once per turn, so **discards per turn = the
  number of discard outlets on the board**. Board-derived, not a magic constant.
- `_DEFAULT_SCENARIO["discard"] = 0` means "derive it from the board" — the
  other triggers keep their tunable constants.
- An explicit `scenario["discard"]` wins. That is the documented seam for
  sources the board snapshot cannot show: Drest'agath's hero power (used once
  per turn), Kith'ix's Dark Ritual, a held pair-generator card, a trinket, or
  Mysterious K'Thir's own three discards (which the engine models inside step 3
  but does **not** add to the counter).

**The rate is bounded, and the bound is stated rather than implied.** The
evidence that the game caps discard triggers at all is 36.6.1's **Voidpriest
Cloner** — *"Whenever you discard a card, Pass a copy of it. **(2 times per
turn.)**"* (that card is **Duos-only**, id `134693`, deliberately not in the
solo DB — see §2). The parenthetical is the game's repeat-trigger cap idiom, so
a per-turn discard count is a bounded quantity rather than a quantity that grows
with every outlet added.

What is **not** published is the cap for the *Activate outlets*. The model
therefore uses the ceiling a solo board can actually produce, and says so:
`DISCARD_RATE_CAP = 7` — one discard per board slot per turn, since each outlet
occupies one of the warband's seven slots. Consequences, all tested:

- the derived count is clamped (`min(outlets, 7)`; a board cannot hold more than
  seven outlets anyway, so the clamp is a stated guarantee rather than a
  behaviour change for real boards);
- an explicit `scenario["discard"]` is clamped the same way, so no caller can
  model nine discards in a turn;
- `_discard_fuel_bonus` clamps its `+1` probe too: a turn already at the cap
  cannot discard more, so **one more outlet is credited nothing new**
  (`test_discard.py::TestDiscardScenario::test_rate_is_bounded_per_turn`,
  `::test_fuel_is_zero_at_the_cap`).

### 4.5 Outlet recognition reads card text, not an id list

```python
_DISCARD_OUTLET_RE = re.compile(r"activate \(\d+\):\s*discard")
```

Five cards match (`BG36_099`, `BG36_311`, `BG28_582`, `BG36_312`, `BG36_300`).
The narrowness is the point: **fifteen** cards in the DB mention discard
(twelve minions, three tavern spells) and only five of them are outlets —

- "If you discard this, cast it twice" (`BG36_371`, `BG36_301t`, `BG36_303`):
  the spell *wants* to be discarded — fuel, not an outlet;
- "Whenever you discard a card …" (`BG36_097`, `BG36_106`, `BGFYM_005`):
  payoffs;
- "discard your 3 left-most Tavern spells" (`BG36_320`) and "when you play one,
  discard the other" (`BG36_100`, `BG36_308`), "improved by each card you've
  discarded" (`BG36_114`): sources/payoffs that need a held card or are
  self-contained.

`test_discard.py::TestDiscardOutlets::test_outlet_set_is_reviewed_when_the_pool_changes`
pins the five-card set, so a later patch that adds an Activate-discard card
fails the suite instead of silently changing the modelled rate.

---

## 5. Every assumption, in one list

| # | Assumption | Provenance |
|---|---|---|
| A1 | **discards per turn = outlets on the board** (each Activate once per turn) | model. The "once per turn" part is game rules; the *rate* is not measured (§3.1) |
| A1b | **the rate is capped at 7** (= one discard per board slot per turn) | model. *That* discard triggers are capped per turn is card-text evidence (Voidpriest Cloner's "(2 times per turn.)", Duos-only, §4.4); the cap *number* for Activate outlets is unpublished, so the board-slot ceiling is used and stated |
| A2 | Hammer of Twilight's "improved by each card you've discarded" adds **one printed application (+2/+1) per discarded card** | **assumption** — the increment is not printed anywhere. Largest single term in the engine |
| A3 | Hammer of Twilight / Corrupted Baton are recognised by **name**, so the Lesser variant (+1 Attack / +4/+4) is credited as the Greater (+2/+1 / +10/+10) or vice versa | assumption: the scenario passes trinket *names*, and the two rows share a name (`patch_3661_changes.md` §9.7). Documented in each step's note |
| A4 | Corrupted Baton's per-cast effect uses **one Tavern-spell cast per discard-turn** as a floor, and its trigger is a *cast*, not a discard | assumption, stated in the step note; the only link is that a discarded spell is cast |
| A5 | N'raqi Sapper: **one** Energizing Chamber per Sapper per turn is discarded (the card grants two — battlecry + deathrattle) | assumption |
| A6 | Mysterious K'Thir: the printed maximum of **3** Tavern spells is discarded every turn | assumption (the real cap is holding 3, invisible to a board snapshot) |
| A7 | `awakenings_per_turn = 1` while an Aberration is on the board | **assumption** — a combat happens once per turn, but the awakening *is* partly measurable (§3.3) and was not measured here |
| A8 | `payoff_share = 0.5` — the two Deities are equally likely, and only C'Thun's split uses the pool (Y'Shaarj's deathrattle does not) | 0.5 is an assumption about "at random"; the *mechanism* is card text |
| A9 | The pool behaves as a per-turn **flow** (this turn's contributions realised each combat) | assumption. Steady-state, consuming or not consuming the pool at awakening gives the same per-turn marginal; the text says neither, and the log was not decoded far enough to say |
| A10 | Mindbender Ghur'sha's "other minions" is modelled as "all minions" | known over-count, documented in the step note |
| A11 | Weights `W_DISCARD_FUEL = 0.3`, `W_DEITY_COMBAT = 0.25` | **tunable weights**, not card data (§4.3); they are the discard mirror of `W_SPELL_FUEL` |
| A12 | The Deity's stats are worth something only through C'Thun's split, and the whole pool is credited at `0.25` per stat | model |

Measured-from-the-game facts the model rests on: the 3-sacrifice requirement
(`QUEST_PROGRESS_TOTAL value=3`); the Deity being a per-combat entity (§3.3);
the 1/1 base stats and tiers (log-mined in the DB update); the five outlet
cards' texts (DB); every other number in the chain (card text, quoted per step).

---

## 6. What is NOT modelled (deliberately, and visibly)

1. **Non-discard Deity fuel** — Joyous, Drifting Sacrifice, Faceless Converter,
   The Shadow of Doubt, Sha of Fear, Vicious Mindslasher, Makeshift Master. The
   pool in this model is therefore a **floor**.
2. **Y'Shaarj's payoff** (re-summon your first 2 dead Aberrations with maximum
   stats). It is not stat-shaped; it is credited as the zero half of
   `payoff_share`.
3. **The sacrifice counter itself.** Deaths during combat are not modelled, so a
   board that cannot produce three Aberration deaths is over-credited by A7.
4. **Discard sources the board cannot show** — the two hero powers, the pair
   generators' held cards, the discard trinkets (Writhing Tentacles, Shath'Yar
   Shrine, Sludge Portrait, Tome of the Ancients, Willbreaker Sticker).
5. **Self-improvement clauses** — Harbinger Aph'lass's "and improve this",
   Parasitic Fleshling's improved end-of-turn buff, Tome of the Ancients'
   "after you discard 3 cards, your Tavern spells give an extra +1/+1".
6. **The economy side** — Corrupted Coin's "increase your maximum Gold by 2" and
   Abyssal Envoy/Mangled Bandit's generated resources. `simulate_growth` models
   stats; the value function scores gold elsewhere.
7. **Hand-side consequences** — a card that wants to be discarded
   (`_spell_score`/`hand_plan` were left alone). The discard fuel term is wired
   into `shop_ranking` only, the seam the tavern-spell fuel already uses; a
   *hand* outlet is not credited, because playing it from hand does not discard
   anything this turn.

---

## 7. What would falsify this

| Claim | Cheapest falsifier |
|---|---|
| "Discards per turn = outlets on the board" (A1) | A session where the count of `Discard Minion`/`Discard Paired Cards` blocks plus Activate uses visibly exceeds or trails the outlet count — or a decoded `4741`/`1068` tag that turns out to *be* the discard marker (§3.1). If those tags decode, the rate becomes measurable and the derivation should be replaced |
| "The rate is capped at 7" (A1b) | A published cap for the Activate outlets (a card-text parenthetical, a patch note, or a tooltip) replacing the board-slot ceiling; or a game in which a discard count above 7 is observable at all, which would mean the ceiling is wrong |
| "One awakening per turn" (A7) | Count `BACON_DEITY_SIGIL` 0→1 flips per combat, or `Y'Shaarj`/`C'Thun` `SETASIDE -> PLAY` transitions, in a session where the player actually had an Aberration board; a rate near 0 or well above 1 falsifies it |
| "C'Thun and Y'Shaarj are equally likely" (A8) | A few dozen games' Deity identities (the entity/`PLAY` appearance is logged). This session rolled Y'Shaarj 3/3 — no information at that sample size |
| "Hammer of Twilight adds +2/+1 per discarded card" (A2) | The trinket's live numbers across a game: read the board's stat gain against the discard count (`BACON_EVOLUTION_CARD_OVERWRITE_*` or the minions' `ATK`/`HEALTH` deltas) |
| "The pool is combat power, not board stats" (§4.3) | If the Deity's stats **persist** on your minions after a combat (C'Thun's split surviving into the shop), the term is mis-weighted — measure a minion's stats before and after a combat in which the Deity awakened |
| "The discard engine is small on a real board" | The worked example below: per-turn +16 Deity stats, ~8 realised, ~4 board-stat-equivalent points — if a real game shows a large board-wide gain tied to discards, a step is missing (most likely A2 or Mindbender Ghur'sha) |

---

## 8. Worked example (the Faelin win)

Board (final board of the 2026-09-22 20:59 win, per the workstream brief):
Faceless Converter ×2, Drifting Sacrifice, N'raqi Sapper, Mysterious K'Thir,
Titus Rivendare — plus Brain Rotter as the outlet in the second run.
`python simulate_growth.py` prints exactly this:

```
=== Aberrations — Discard / Deity — Faelin board, no outlet, 0 discard(s)/turn ===
  board  Mysterious K'Thir: +24/+24
  persistent board gain: +24/+24
  Deity pool banked: +0/+0  awakenings 0  -> realised +0/+0 (per combat, NOT board stats)
  TOTAL per turn (board + realised Deity): 48 stats

=== Aberrations — Discard / Deity — Faelin board, 1 outlet (Brain Rotter), 1 discard(s)/turn ===
  board  Mysterious K'Thir: +24/+24
  Deity  Brain Rotter: +2/+2
  Deity  N'raqi Sapper: +14/+14
  persistent board gain: +24/+24
  Deity pool banked: +16/+16  awakenings 1  -> realised +8/+8 (per combat, NOT board stats)
  TOTAL per turn (board + realised Deity): 64 stats
  marginal value of the outlet this turn: 16 stats
```

Read it honestly: on this board the discard **outlet** is worth **16 stats per
turn of combat power** (+2/+2 from the Rotter itself, +14/+14 from the Sapper's
Energizing Chamber), of which only *half* is realised on average (the 50/50 Deity
roll) and none of it is persistent board growth. The board's own +24/+24 comes
from Mysterious K'Thir and needs no outlet at all. That is the opposite of what a
flat "discard engine = big stats" heuristic would have said.

A board built for the engine (Ghur'sha + K'Thir + Aph'lass + Rotter + Sapper,
both discard trinkets, 2 discards) produces, by hand and by simulation:
`gain +58/+48`, Deity pool `+30/+30`, realised `+15/+15`
(`test_discard.py::TestDiscardEngineChain::test_golden_chain_hand_computed`).

---

## 9. Refreshing / extending on the next patch

```
cd hearth-coach
python -m unittest tests.test_discard     # the mechanic's own suite
python check_meta.py && python -m unittest discover -s tests
python simulate_growth.py                 # the Aberration demo above
```

- New Activate-discard card? `test_outlet_set_is_reviewed_when_the_pool_changes`
  fails until the set is extended — which is the point: the modelled discard
  **rate** changes with the outlet set.
- A **published per-turn discard cap** (a card-text parenthetical, a patch note,
  a tooltip) should replace `DISCARD_RATE_CAP`'s board-slot ceiling and be
  recorded in §5 as card text rather than a model bound.
- Numbers arriving for any currently-assumed magnitude (Hammer of Twilight's
  increment, the Deity's awakening rate, the pool's persistence) should replace
  the corresponding `note`'s assumption and be recorded in §5 with its source.
- Anything measured should be added to §3 with its count and the pattern used,
  the way §3.1–§3.3 are written, so the next session can still tell game data
  from model.
