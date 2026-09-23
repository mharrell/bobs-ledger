# Patch 36.6.1 — Battlegrounds change list (card DB input)

**Patch:** 36.6.1 — live **2026-09-22**
**Primary source (full card list):** <https://hearthstone.blizzard.com/en-us/news/24302091>
— *"Aberrations Join Battlegrounds at BlizzCon!"* (published 2026-09-12, article id 24302091)
**Patch-notes page (links here):** <https://hearthstone.blizzard.com/en-us/news/24294373/366-patch-notes>
— *"36.6 Patch Notes"* (article id 24294373)

This is a **literal transcription** of the two official articles for the meta-DB update.
Nothing here has been applied to `hearth-coach/meta/` — this document is the input, not the change.
Tier/stat/cost values are exactly as printed by Blizzard; card names preserve Blizzard's
capitalisation and apostrophes.

**Provenance / how to reproduce.**
Both pages were fetched with `requests` (after the `patch_notes.py` import fix in this worktree) and
converted with `patch_notes.html_to_text()`. The card names and every list below were then
re-derived a second time straight from the raw HTML (`<h2>`/`<h3>`/`<h4>`, `<p>`, `<ul><li>`) and the
two derivations were diffed by hand — they agree exactly. A third, independent check compared every
list against `meta/minions.json` / `heroes.json` / `trinkets.json` / `tavern_spells.json`; results are
in **Appendix C**.
The "internal card id" column is **not** in the article prose: it comes from the article's own card
image `alt` attributes (e.g. `alt="PRIEST_BG36_099_enUS_BrainRotter-131696_NORMAL.png"`), so it is
Blizzard data, but treat it as derived rather than quoted.

---

## 1. New minion type: Aberrations

> Meet Aberrations, the newest Battlegrounds minion type. Built around discard synergies,
> Aberrations grow stronger as they work toward awakening their Deity. Different Aberration cards
> support this strategy in different ways, giving you multiple paths to unlock the power of the Old
> Gods.

**How summoning a Deity works:** (verbatim)

- Each time a friendly Aberration dies, it advances your Deity's progress.
- There are two Deities, **C'Thun** and **Y'Shaarj**, but only one will answer your call.
- Which Deity answers is chosen at random at the start of each game.
- Once **three sacrifices** have been made, your Deity joins the fight with a game-changing effect.

> The patch-notes page (24294373) words the last two bullets slightly differently — it says the
> Deity "joins **for that combat**" and the requirement is "once three sacrifices have been made".
> Either way the trigger is **3 friendly Aberration deaths**, and the Deity is a **per-combat**
> appearance, not a permanent board add.

**Guaranteed availability (important for the pool model):**

> Aberrations will appear in every lobby during the first two weeks following their debut, starting
> September 22.

i.e. **2026-09-22 → 2026-10-06** (two weeks) Aberrations cannot be absent from a lobby's allowed
tribes, exactly like the new-hero guarantee below.

---

## 2. Rotations

> With Aberrations joining Battlegrounds as the newest minion type, Naga will be rotated out of the
> minion pool. Naga-specific heroes and cards will be unavailable while Naga are out of the pool.

- **Naga** is rotated **out** of the minion pool as of 36.6.1. The patch-notes page says
  "**temporarily** rotated out"; the overview does not use the word "temporarily". So: out now,
  date of return unknown.
- Naga-specific **heroes** and **cards** are unavailable while Naga is out.
- The article does **not** enumerate which heroes or cards are "Naga-specific", and it does not say
  what happens to **compound (multi-tribe) cards that are only partly Naga** — e.g. `Ominous Seer`
  (`Demon/Naga`), `Sea Witch Zar'jira`, `Faerlina`-style dual-tribe entries. See
  **Appendix A.4** — the sibling pool workstream read this as "a card is out of play only when *all*
  of its tribes are out", which is the reading I'd keep, but it is an **inference, not article text**.
- `meta/minions.json` currently holds **22 Naga-tagged minions** (20 `Naga` + `Demon/Naga`,
  `Dragon/Naga`) — see Appendix C.

---

## 3. Heroes

### 3.1 New heroes (2)

> New Heroes are guaranteed in every game for two weeks, starting September 22.

Same two-week window as the Aberrations (**2026-09-22 → 2026-10-06**): both new heroes are guaranteed
to be offered.

| Hero | Hero power | Cost | Power text | Power card id |
|---|---|---|---|---|
| **Drest'agath** | **Incubate** | 1 | Discard a card to get a random Aberration. | 134503 |
| **Kith'ix** | **Dark Ritual** | 2 | Get 2 random minions. When you play one, discard the other. | 134505 |

(Printed in the article as `Drest'agath – Incubate` and `Kith'ix - Dark Ritual`; the mixed dash/hyphen
is Blizzard's. Card ids from the hero-power images on the page, same `alt`-attribute provenance as
above.)

### 3.2 Changed heroes (1)

**Rat King - A Tale of Kings**

- Now includes Aberrations.

> DB note: `meta/heroes.json` keys this hero as **"The Rat King"**, the article says **"Rat King"**.

### 3.3 Heroes banned from Aberrations (7)

Verbatim lead-in from the article: *"The following Heroes have been banned from Aberrations:"*

Completely banned when the lobby's Aberration tribe is in play:

- Morchie
- Murozond, Unbounded
- Sylvanas Windrunner

Banned **only when the game's chosen Deity is Y'Shaarj** ("Y'Shaarj only"):

- The Curator
- The Lich King
- Teron Gorefiend
- N'Zoth

> The article states this as a flat list under the heading "The following Heroes have been banned
> from Aberrations:". The `(Y'Shaarj only)` qualifier is Blizzard's own parenthetical.

---

## 4. New minions (38 names)

The article has a single **New Minions** heading with no separator inside it, but the block splits
cleanly into two groups — an **Aberration** group and an **other-tribes** group. The split point is
positional in the article (after *Sha of Fear*), and it is corroborated independently:
`meta/pool_roster.json` (log-mined from a 2026-09-22 session) tags every `PRIEST_BG36_*` card as
`ABERRATION`, and tags the first card of the second group (*Victorious Geomant*, `BG36_370`) as
`QUILBOAR` with *Holy Vanguard* (`BG36_372`) untribed. **The article itself never labels the split** —
if you want the tribe for each new card, that comes from the card data, not this prose.

### 4.1 New Aberration minions (28 names, incl. the 2 Deities and Dark Paradox)

| # | Name | Tier | Stats | Text (verbatim) | Card id |
|---|---|---|---|---|---|
| 1 | **C'Thun** | 3 | 1/1 | Deity. After this awakens, give this minion's stats split amongst your other minions. | 130610 |
| 2 | **Y'Shaarj** | 3 | 1/1 | Deity. Deathrattle: Summon your first 2 Aberrations that died this combat with their maximum stats (except Deities). | 132532 |
| 3 | **Dark Paradox** | ? | ?/? | *see 4.2 — six variants* | 134401 (base) |
| 4 | **Joyous** | 1 | 2/3 | Battlecry: Give your Deity +2/+2. | 131718 |
| 5 | **Zoatroid** | 1 | 3/2 | When you sell this, get a 0/2 Tentacle with Taunt. | 131694 |
| 6 | **Brain Rotter** | 2 | 3/4 | Activate (0): Discard a card to give your Deity +2/+2. | 131696 |
| 7 | **Underrot Spawn** | 2 | 2/2 | Deathrattle: Summon a 0/2 Tentacle with Taunt. Give your minions +1 Attack. | 133104 |
| 8 | **Unwilling Slacker** | 2 | 1/1 | Deathrattle: Get a random 1-Cost Tavern spell. | 131700 |
| 9 | **Abyssal Envoy** | 3 | 3/4 | Activate (0): Discard a card to get a random Tavern spell. | 132213 |
| 10 | **Drifting Sacrifice** | 3 | 2/1 | Reborn. Deathrattle: Give your Deity +2/+1. | 133098 |
| 11 | **Fetid Corroder** | 3 | 3/3 | Battlecry: Get a Sludge Corrosion. | 133096 |
| 12 | **Vicious Mindslasher** | 3 | 3/1 | Whenever you cast a Tavern spell, give this and your Deity +1/+3. | 131714 |
| 13 | **Wandering Willbreaker** | 3 | 1/3 | When you sell this, get 2 random Tavern spells. When you play one, discard the other. | 131698 |
| 14 | **Cutthroat K'Thir** | 4 | 4/4 | Whenever you discard a card, give this and your Deity +4/+4. | 131710 |
| 15 | **Faceless Operative** | 4 | 4/2 | When you sell this, get 2 random Aberrations. When you play one, discard the other. | 132182 |
| 16 | **Mindbending Recruiter** | 4 | 6/2 | Activate (0): Discard a card to get a random Aberration. | 132215 |
| 17 | **Nightmare Corroder** | 4 | 7/4 | Deathrattle: Get a Sludge Corrosion. | 133102 |
| 18 | **Parasitic Fleshling** | 4 | 4/6 | At the end of your turn, give your left-most minion +2/+2. (Improved by each card you've discarded this game!) | 133100 |
| 19 | **De-volition-ist** | 5 | 4/8 | After this attacks, deal damage equal to this minion's Attack to the highest-Health enemy minion. | 131702 |
| 20 | **Faceless Converter** | 5 | 5/5 | Deathrattle: Give your Deity +1/+1. (Improved by each Tavern spell you've cast this game!) | 132331 |
| 21 | **Mindbender Ghur'sha** | 5 | 3/9 | Whenever you discard a card, give your other minions +3/+3. | 131692 |
| 22 | **Mysterious K'Thir** | 5 | 8/8 | At the end of your turn, discard your 3 left-most Tavern spells. Gain +8/+8 for each discarded. | 134497 |
| 23 | **N'raqi Frostcaller** | 5 | 6/3 | Activate (0): Discard a card for your Tavern spells to give an extra +1/+1 this game. | 132136 |
| 24 | **N'raqi Sapper** | 5 | 6/3 | Battlecry and Deathrattle: Get an Energizing Chamber. | 131704 |
| 25 | **Harbinger Aph'lass** | 6 | 3/6 | Whenever you discard a card, give your Deity +1/+1 and improve this. | 130620 |
| 26 | **Dark Puppeteer** | 6 | 8/4 | Deathrattle: Your Tavern spells give an extra +4 Health this game. | 131706 |
| 27 | **The Shadow of Doubt** | 6 | 6/8 | Whenever a card is added to your hand, give your Deity +3/+4. | 131716 |
| 28 | **Sha of Fear** | 7 | 9/12 | Whenever you cast a Tavern spell, give your minions and Deity +4/+3. | 131720 |

Token created by Zoatroid / Underrot Spawn: **Tentacle**, 0/2 with **Taunt** (no tier/stats row of its
own in the article — named only inside those two card texts).

### 4.2 Dark Paradox — six printed rows, five playable versions

> **Dev Comment:** Dark Paradox comes in five different versions, each associated with a unique Dark
> Gift. One version is selected at random at the start of every game.

Printed placeholder row:

- **`[Tier ?] ?/?.`** This has a different Dark Gift, stats, and Tier each game! — base card id 134401

The five versions, in the order the article prints them:

| # | Tier | Stats | Text | Card id (see caveat) |
|---|---|---|---|---|
| 1 | 2 | 2/4 | Whenever you play a card, gain +2 Attack. | 134704 |
| 2 | 3 | 2/2 | Has +2/+2 for each Battlecry you've triggered this game (wherever this is). | 134710 |
| 3 | 4 | 2/6 | Rally: Get a random minion of your most common type. | 134708 |
| 4 | 5 | 8/4 | Divine Shield. This minion's Divine Shield takes 3 hits to break. | 134706 |
| 5 | 6 | 10/2 | Deathrattle: Summon a Golem with this minion's stats. | 134716 |

**Dev Comment attached to the Tier 5 / 8/4 version** (it sits directly under that version's text in the
HTML, above that version's image):

> **Dev Comment:** Cannot appear in lobbies with Undead.

**Caveat on the card ids:** the images are printed in the order
`360 (base) → 360t3 → 360t6 → 360t5 → 360t4 → 360t9`, while the *text* is in tier order 2/3/4/5/6.
The `tN` suffix is therefore **not** the tier — the mapping above pairs each id to the text line it
follows in the HTML, which is correct by position, but the suffix ordering means I cannot
independently confirm that id↔tier pairing from the article. **Treat the tier/stats/text columns as
authoritative and the ids as positional.** Also see Appendix A.1 (Dark Paradox's tribe is not stated).

### 4.3 New non-Aberration minions (10 names, same "New Minions" heading)

| # | Name | Tier | Stats | Text (verbatim) | Card id |
|---|---|---|---|---|---|
| 29 | **Greedy Conniver** | 3 | 7/7 | If this is Golden when you sell it, Discover a Tier 7 minion. | 134421 |
| 30 | **Sacrificial Wrathguard** | 4 | 5/3 | Deathrattle: Give minions in the Tavern +2/+2 this game. Activate (1): Improve this. | 134405 |
| 31 | **Holy Vanguard** | 4 | 5/5 | Divine Shield. Has +15/+15 while you have 15 or less Health. | 134409 |
| 32 | **Sewer Escapee** | 4 | 4/5 | Activate (1): Give another Murloc +7/+7 and a random Bonus Keyword. | 132881 |
| 33 | **Hopebringer** | 5 | 3/3 | Start of Combat: Give your minions +3/+3. (Permanently improves after a friendly minion loses Divine Shield!) | 134411 |
| 34 | **Lichling Hoarder** | 5 | 5/10 | Avenge (4): Get a plain copy of a different minion that started in your warband this combat. | 134492 |
| 35 | **Resourceful Robot** | 5 | 4/8 | At the end of your turn, Magnetize a random Volumizer to this. Get a copy of it. | 134415 |
| 36 | **Auto Reveille** | 6 | 6/6 | After you buy 3 cards, get a random Magnetic Volumizer. (3 left!) | 134417 |
| 37 | **Heroic Broodmother** | 6 | 7/7 | Rally: Gain Divine Shield. Start of Combat: Attack immediately. | 134494 |
| 38 | **Victorious Geomant** | 6 | 10/10 | Activate (2): Get 6 Blood Gems. Cast any that can't fit on your left-most minion. | 134423 |

---

## 5. Changed minions

### 5.1 Minions that are now Aberrations (4)

Verbatim lead-in from the article: *"The following minions are now Aberrations:"*

The article's literal list:

- Oozeling Gladiator
- Faceless Manipulator
- Faceless Taverngoer
- Orgozoa, the Tender

> **This list conflicts with §7.** *Oozeling Gladiator* also appears in **Removed Minions**. The
> article gives no old/new stats for any of the four — only the tribe change is stated. See
> Appendix A.2 for both readings and for the log-mined evidence.

### 5.2 Changed minions with old → new values (7)

| Name | Change | Old (verbatim) | New (verbatim) | Card id |
|---|---|---|---|---|
| **Iron Groundskeeper** | **Redesign** | *(none given — article prints only the new card)* | `[Tier 3] 2/2. Battlecry: Get 2 copies of Fortify.` | 103666 |
| **Ghastcoiler** | Tier | `[Tier 6]` | `[Tier 5]` | 59687 |
| **Bronze Warden** | Tier | `[Tier 3]` | `[Tier 2]` | 60558 |
| **Dune Dweller** | Stats | `3/2.` | `3/3.` | 116734 |
| **Drone Duplicator** | Text | `Divine Shield Activate (1): The next Magnetization to this minion this turn is doubled.` | `Divine Shield. Activate (1): The next Magnzetization to this minion this turn happens an extra time.` | 132312 |
| **Hackerfin** | Text | `Battlecry: Give your other minions +1/+2. (Improved by each different Bonus Keyword in your warband!)` | `Battlecry: Give your other minions +3/+2. (Improved by each different Bonus Keyword in your warband!)` | 115848 |
| **Mangled Bandit** | **Redesign** | *(none given)* | `Activate (0): Discard a card to get 3 Blood Gems.` | 104764 |

Notes:

- "**Redesign**" rows (Iron Groundskeeper, Mangled Bandit) carry only the new text — the article does
  not print the old version, so `old` must come from the DB, not from this document.
- **Drone Duplicator's new text contains a typo in the article**: `Magnzetization`. It is almost
  certainly `Magnetization`. Transcribed above **as printed**. The rest of the sentence also changed
  ("is doubled" → "happens an extra time"), so it is a rules change, not only a fix.
- All seven changed minions **also appear in the Returning Minions list** (§6) except
  *Drone Duplicator*. Same card, two rows in the article — a DB update must not double-apply.

---

## 6. Removed minions (35 — complete, alphabetical)

Transcribed **in full**, in the article's original order:

| # | Name | # | Name |
|---|---|---|---|
| 1 | Ancestral Automaton | 19 | Moat Custodian |
| 2 | Auto Assembler | 20 | Molten Rock |
| 3 | Breakout Mastermind | 21 | Motley Phalanx |
| 4 | Captain Cookie | 22 | Nomi, Kitchen Nightmare |
| 5 | Clunker Junker | 23 | Oozeling Gladiator |
| 6 | Cousin Errgl | 24 | Papa Mrrglton |
| 7 | Dancing Barnstormer | 25 | Primitive Painter |
| 8 | Deepwater Chieftain | 26 | Private Investigator |
| 9 | Deflect-o-Bot | 27 | River Skipper |
| 10 | Dual-Wield Corsair | 28 | Sand Swirler |
| 11 | Dustbone Devastator | 29 | Scrap Scraper |
| 12 | Fire-forged Evoker | 30 | Sly Raptor |
| 13 | Glowing Cinder | 31 | Thousandth Paper Drake |
| 14 | Ignition Specialist | 32 | Unleashed Mana Surge |
| 15 | Kangor's Apprentice | 33 | Vigilant Bristlemane |
| 16 | Mama Mrrglton | 34 | Void Pup Trainer |
| 17 | Metallic Hunter | 35 | Warpwing |
| 18 | Meteorite Crasher | | |

Plain list, for copy/paste:

```
Ancestral Automaton, Auto Assembler, Breakout Mastermind, Captain Cookie, Clunker Junker,
Cousin Errgl, Dancing Barnstormer, Deepwater Chieftain, Deflect-o-Bot, Dual-Wield Corsair,
Dustbone Devastator, Fire-forged Evoker, Glowing Cinder, Ignition Specialist,
Kangor's Apprentice, Mama Mrrglton, Metallic Hunter, Meteorite Crasher, Moat Custodian,
Molten Rock, Motley Phalanx, Nomi, Kitchen Nightmare, Oozeling Gladiator, Papa Mrrglton,
Primitive Painter, Private Investigator, River Skipper, Sand Swirler, Scrap Scraper,
Sly Raptor, Thousandth Paper Drake, Unleashed Mana Surge, Vigilant Bristlemane,
Void Pup Trainer, Warpwing
```

**All 35 names match `meta/minions.json` exactly** (Appendix C) — spelling in this document is
confirmed against the DB, not just the article.

---

## 7. Returning minions (25 — complete, alphabetical)

The article has this heading (it is not one of the sections the task asked for, but the DB needs it —
these cards must be (re-)added):

- Auto Accelerator
- Blue Volumizer
- Bronze Warden
- Bubble Gunner
- Conveyor Construct
- Dune Dweller
- Elite Navigator
- Firelands Fugitive
- Geomagus Roogug
- Ghastcoiler
- Gormling Gourmet
- Green Volumizer
- Hackerfin
- Hot-Air Surveyor
- Ichoron the Protector
- Iron Groundskeeper
- Leyline Surfacer
- Living Azerite
- Mangled Bandit
- Nadina the Red
- Red Volumizer
- Relentless Deflector
- Shoalfin Mystic
- Ultraviolet Ascendant
- Young Murk-Eye

Six of these are also in §5.2 (Bronze Warden, Dune Dweller, Ghastcoiler, Hackerfin,
Iron Groundskeeper, Mangled Bandit) — i.e. the card returns **and** its data changed. *Drone
Duplicator* is the only changed minion that is **not** in this list.

**None of the 25 are currently in `meta/minions.json`** (Appendix C) — they were rotated out in an
earlier patch and the DB never carried them, so a DB update has to source their base stats from
somewhere other than the DB.

---

## 8. Tavern spells

The article has **New / Removed / Returning** tavern-spell sections only — there is **no "Changed
Tavern Spells" section**, so nothing in this patch changed an existing tavern spell's numbers.

### 8.1 New tavern spells (3)

| Name | Cost | Text (verbatim) | Card id |
|---|---|---|---|
| **Sludge Corrosion** | 1 | Give your minions +1/+1. If you discard this, cast it twice. | 132140 |
| **Corrupted Coin** | 2 | Gain 2 Gold. If you discard this, increase your maximum Gold by 2. | 132153 |
| **Energizing Chamber** | 1 | Give your Deity +7/+7. If you discard this, cast it twice. | 134496 |

### 8.2 Removed tavern spells (2)

- Mounting Avalanche
- Deepwater Clan

(Both are present in `meta/tavern_spells.json`.)

### 8.3 Returning tavern spells (1)

- Seafood Stew

(Not currently in `meta/tavern_spells.json`.)

---

## 9. Trinkets

The article's trinket sections carry **no card images**, so unlike the minions there are **no internal
card ids** available for any trinket below.

### 9.1 New Lesser Trinkets (15)

| Name | Cost | Text (verbatim) |
|---|---|---|
| **Corrupted Coin Portrait** | 0 | Get 2 Corrupted Coins. |
| **Mindslasher Portrait** | 5 | Get a Vicious Mindslasher. Your Vicious Mindslashers also give stats to adjacent minions. |
| **Hammer of Twilight** | 1 | Your minions have +1 Attack. (Improved by each card you've discarded this game!) |
| **Corrupted Baton** | 1 | After you cast a Tavern spell, give your Deity +4/+4. |
| **Willbreaker Sticker** | 1 | Get 2 random Tavern spells. When you play one, discard the other. At the start of your turn, repeat this. |
| **Dragonhead Staff** | 0 | After 13 friendly minions attack, replace this with a random Greater Dragon Trinket. (13 left!) |
| **Quartermaster's Hook** | 0 | After you spend 50 Gold, replace this with a random Greater Pirate Trinket. (50 Gold left!) |
| **Rascal Sticker** | 0 | Gain 1 Gold for each friendly Golden minion. At the start of your turn, repeat this. |
| **Ruby Tusk** | 0 | After you play 10 Blood Gems from hand, replace this with a random Greater Quilboar Trinket. (10 left!) |
| **Soul Battery** | 0 | After you summon 25 minions, replace this with a random Greater Undead Trinket. (25 left!) |
| **Volumizer Portrait** | 3 | Get a random Magnetic Volumizer. At the start of each turn, get another. |
| **Reinvigorating Light** | 0 | Discover a second Hero Power. Gain 3 Gold. |
| **Kiri's Double Eclipse** | 4 | Choose a Lesser Trinket that costs (4) or less to buy. Transform this and your Hero Power into a copy of it. |
| **Trickster's Sleeve** | 1 | After you buy a minion, gain 1 Gold. (Then swap to Tavern spell!) |
| **Weighted Gauntlet** | 3 | At the end of your turn, give your minions +1/+1. (Doubles at the start of each turn!) |

### 9.2 Removed Lesser Trinkets (4)

- Amplifying Essence
- Avalanche Sticker
- Assembler Portrait
- Kaleidoscope

### 9.3 Returning Lesser Trinkets (1)

- Vibrant Bubble

### 9.4 New Greater Trinkets (15)

| Name | Cost | Text (verbatim) |
|---|---|---|
| **Sludge Portrait** | 2 | Get a Sludge Corrosion. After you discard a card, get a Sludge Corrosion. |
| **Shath'Yar Shrine** | 4 | After you discard a spell, get a random Aberration. |
| **Converter Portrait** | 4 | Get a Faceless Converter. Start of Combat: Give your Faceless Converters Reborn. |
| **Mask of Ancient Ones** | 3 | Make your Deity Golden this game. |
| **Corrupted Baton** | 1 | After you cast a Tavern spell, give your Deity +10/+10. |
| **Hammer of Twilight** | 1 | Your minions have +2/+1. (Improved by each card you've discarded this game!) |
| **Writhing Tentacles** | 1 | After you discard your first minion each turn, get a copy of it with double stats. (1 left!) |
| **Evil Experiment** | 0 | After your Deity awakens, give it Reborn. |
| **Makeshift Master** | 0 | Spellcraft: Choose a minion. After it gains stats outside combat this turn, your Deity also gains them. |
| **Tome of the Ancients** | 0 | After you discard 3 cards, your Tavern spells give an extra +1/+1 this game. (3 left!) |
| **Snarky Portrait** | 2 | Get 2 Snarky Sharks. Whenever a Fishbait dies, give your Beasts +4/+4 and improve this. |
| **Volumizer Portrait** | 3 | Get 2 random Magnetic Volumizers. At the start of each turn, repeat this. |
| **Kiri's Double Eclipse** | 4 | Choose a Greater Trinket that costs (4) or less to buy. Transform this and your Hero Power into a copy of it. |
| **Sinister Invitation** | 4 | Discover a Golden minion of your most common type with a Dark Gift. It doesn't give a Triple Reward. |
| **Tableware Portrait** | 4 | Get a Menagerie Tableware. At the start of each turn, get another. |

### 9.5 Removed Greater Trinkets (3)

- Automaton Portrait
- Kaleidoscope
- Errgl Sticker

### 9.6 Returning Greater Trinkets (3)

- Surveyor Portrait
- Azerite Portrait
- Hackerfin Portrait

### 9.7 Duplicate trinket names — read this before applying

Four names appear **twice** in this patch, once as a Lesser and once as a Greater, with **different
costs and different text**:

| Name | Lesser (cost / text) | Greater (cost / text) |
|---|---|---|
| **Corrupted Baton** | 1 / "give your Deity +4/+4" | 1 / "give your Deity +10/+10" |
| **Hammer of Twilight** | 1 / "Your minions have +1 Attack." | 1 / "Your minions have +2/+1." |
| **Volumizer Portrait** | 3 / "Get **a** random Magnetic Volumizer." | 3 / "Get **2** random Magnetic Volumizers." |
| **Kiri's Double Eclipse** | 4 / "Choose a **Lesser** Trinket …" | 4 / "Choose a **Greater** Trinket …" |

Plus **Kaleidoscope** is listed in *both* Removed Lesser and Removed Greater.

This is the same homonym hazard `patch_notes.apply_changes()` already reports as `ambiguous` for the
dark gifts: a name-keyed update will silently edit whichever trinket is last unless the Lesser/Greater
tier is used to disambiguate. (`meta/trinkets.json` has 145 entries — check whether it keys these
four the way the dark gifts are keyed, one entry per tier, before writing.)

---

## 10. Appendix: other 36.6.1 Battlegrounds changes on the patch-notes page

The patch-notes page (24294373) carries a **Bug Fixes → Battlegrounds** list. These are not card-data
changes, but they are 36.6.1 BG changes and they are quoted verbatim:

- Fixed a bug where Neutral minions that became All-type minions did not correctly receive Elemental
  scaling bonuses.
- Fixed a bug where Rot Hide Gnoll could gain Attack from a teammate's minions dying.
- Fixed a bug where Power of the Storm interacted incorrectly with Cosmic Duality.
- Fixed a bug where Timewarped Sea Glass only doubled Attack instead of applying its full effect.
- Fixed a bug where Unforeseen Portal could activate multiple times in a single game.
- Fixed a bug where Sire Denathrius' Kidnap Sack rewarded two Spellcraft spells instead of one.
- Fixed a bug where Valithria Dreamwalker failed to receive buffs when Dragons were summoned during
  combat.
- Fixed a bug where Pyramad's Hero Power could be used when no Tavern minions remained.
- Fixed a bug where purchasing a Spell incorrectly counted as a Discover while using Magicfin
  Sticker.
- Fixed a bug where Arch-Villain Rafaam's Hero Power could trigger during the Shop Phase.
- Fixed a bug where Reclaimed Souls could be used after Aureate Laureate died in combat without
  granting the expected copy.

The rest of the 36.6 patch-notes page is constructed/Standard content (pre-purchase, Arena, shop,
cosmetics) and is not Battlegrounds data.

---

## 11. Duos updates (bonus — not in the required section list)

The overview has a **Duos Updates** section. Duos is a separate mode/DB surface; included for
completeness.

**New Duos minions (2)**

| Name | Tier | Stats | Text (verbatim) | Card id |
|---|---|---|---|---|
| **Voidpriest Cloner** | 3 | 4/5 | Whenever you discard a card, Pass a copy of it. (2 times per turn.) | 134693 |
| **C'Thrax Wrecker** | 5 | 8/8 | Battlecry, Deathrattle, and Rally: Give your team's Deities +4/+4. | 134695 |

**Changed Duos minions (2)**

| Name | Old | New | Card id |
|---|---|---|---|
| **Man'ari Messenger** | Battlecry: Minions in your team's Taverns have +1/+1 this game. | Battlecry: Minions in your team's Taverns have +3/+2 this game. | 106320 |
| **Transport Reactor** | 1/1. Magnetic Has +1/+1 for each time your team has Passed this game (wherever this is). | 3/3. Magnetic Has +3/+3 for each time your team has Passed this game (wherever this is). | 117359 |

---

## Appendix A — things I could NOT determine cleanly

**A.1 — Dark Paradox's minion type is never stated.** It is printed inside the Aberration group of
"New Minions", but its card image is coded `NEUTRAL_BG36_360`, and it is the only card in that group
whose text mentions neither a Deity nor discarding (it is a Dark Gift carrier). The article nowhere
says "Aberration" for it. Its 3-game log roster snapshot does not contain it either, so the log cannot
settle it. **Unresolved:** assume Aberration because of placement, but the DB entry should be verified
against card data.

**A.2 — Oozeling Gladiator appears in two mutually exclusive lists.** §5.1 says it "is now
[Aberration]"; §6 says it is "Removed". Two readings:

1. *Removed wins* — the "now Aberrations" list is stale for this one card. Supporting evidence:
   the sibling workstream's `meta/out_of_play.json` lists it as removed on the strength of a
   log-mined post-patch pool roster, and my own read of that file found it absent from the
   2026-09-22 `pool_roster.json` card set.
2. *Re-typed wins* — the card stays, re-tagged Aberration, and its appearance in "Removed Minions" is
   an article error.

I did **not** find a tiebreaker in the article. Reading 1 has independent log evidence; reading 2 does
not. **Flagged, not resolved** — the sibling workstream currently has it as removed.

**A.3 — "Redesign" rows carry no old values.** Iron Groundskeeper and Mangled Bandit print only the
new text. Any `old` column for them has to come from the DB or from the game client, not from this
patch's prose.

**A.4 — Which heroes/cards are "Naga-specific" is not enumerated.** The rotation section states the
rule ("Naga-specific heroes and cards will be unavailable") but never lists them, and it does not say
whether multi-tribe cards that are *partly* Naga (e.g. `Ominous Seer`, `Demon/Naga`) rotate out too.
The sibling `out_of_play.json` resolves this as "out of play only when **all** of a card's tribes are
out" — a sensible reading with log support, but it is an inference.

**A.5 — Drone Duplicator's new text has an apparent typo.** `Magnzetization` (printed) vs
`Magnetization`. Transcribed as printed; do not silently "fix" it in the DB without deciding.

**A.6 — Dark Paradox id ↔ tier pairing.** See §4.2. The `tN` image suffixes are not in tier order, so
only the article's text order ties an id to a tier.

**A.7 — No tier is given for the Dark Paradox placeholder row** (`[Tier ?] ?/?.`), and no
cost/tier is given for the four "now Aberrations" minions.

**A.8 — Returning minions carry no stats.** For the 25 returning minions the article gives names only
(no tier/stats/text), and 25 of them are absent from `meta/minions.json`. Their data must come from
another source. Same for the 4 returning trinkets and the 1 returning tavern spell.

**A.9 — `meta/` is being edited concurrently right now.** While producing this document I observed
another workstream's **uncommitted** files in this same worktree (`meta/out_of_play.json`,
`meta/pool_roster.json`, `playable.py`, `pool_roster.py`, plus a modified `tribes.py`), and
`pool_roster.json` changed *between two of my reads*. The cross-checks in Appendix C are therefore a
**snapshot**, and this document was deliberately not used to write anything under `meta/`.

---

## Appendix B — counts (for a quick sanity check when applying)

| Group | Count |
|---|---|
| New minions (Aberration group) | 28 names (incl. 2 Deities + Dark Paradox ×6 printed rows) |
| New minions (non-Aberration group) | 10 |
| **New minions total** | **38** |
| Changed minions — now Aberrations | 4 |
| Changed minions — old → new values | 7 |
| **Changed minions total** | **11** (Oozeling Gladiator counted in both lists once) |
| **Removed minions** | **35** |
| Returning minions | 25 |
| New heroes | 2 |
| Changed heroes | 1 |
| Heroes banned from Aberrations | 7 (3 flat + 4 Y'Shaarj-only) |
| New tavern spells | 3 |
| Changed tavern spells | 0 (no such section) |
| Removed tavern spells | 2 |
| Returning tavern spells | 1 |
| New Lesser trinkets | 15 |
| Removed Lesser trinkets | 4 |
| Returning Lesser trinkets | 1 |
| New Greater trinkets | 15 |
| Removed Greater trinkets | 3 |
| Returning Greater trinkets | 3 |
| Duos — new minions | 2 |
| Duos — changed minions | 2 |

---

## Appendix C — name cross-check against the current `meta/`

Read-only comparison, run from this worktree at the time of writing
(`meta/minions.json` 263 minions, `heroes.json` 115, `trinkets.json` 145,
`tavern_spells.json` 71). Name matching normalises to `[a-z0-9]` only.

| Article group | Names | Found in DB | Not in DB |
|---|---|---|---|
| New minions | 38 | 0 | 38 (all genuinely new) |
| Changed minions | 11 | 2 — *Oozeling Gladiator*, *Drone Duplicator* | 9 — the other two "now Aberrations" (Faceless Manipulator, Faceless Taverngoer, Orgozoa, the Tender) and all six returning-and-changed ones |
| Removed minions | 35 | **35** | 0 |
| Returning minions | 25 | 0 | 25 |
| New heroes | 2 | 0 | 2 |
| Banned/changed heroes | 8 | 7 | 1 — article "**Rat King**" vs DB "**The Rat King**" |
| New tavern spells | 3 | 0 | 3 |
| Removed tavern spells | 2 | 2 | 0 |
| Returning tavern spells | 1 | 0 | 1 |
| New Lesser trinkets | 15 | 0 | 15 |
| Removed Lesser trinkets | 4 | 2 — *Avalanche Sticker*, *Kaleidoscope* | 2 — *Amplifying Essence*, *Assembler Portrait* |
| Returning Lesser trinkets | 1 | 0 | 1 |
| New Greater trinkets | 15 | 0 | 15 |
| Removed Greater trinkets | 3 | 2 — *Automaton Portrait*, *Kaleidoscope* | 1 — *Errgl Sticker* |
| Returning Greater trinkets | 3 | 0 | 3 |

Two things this check proves, independent of the article:

1. **All 35 removed minions match `meta/minions.json` name-for-name.** The removal list is
   transcribed correctly and completely (it is the one list where a silent typo would strand a card
   in the pool).
2. **Every "new" and every "returning" entity is genuinely absent from the DB**, so an update cannot
   be a pure in-place edit — new rows have to be created.

It also surfaces two DB-side name issues to resolve during the update: **Rat King / The Rat King**,
and that `meta/trinkets.json` has no entry at all for *Amplifying Essence*, *Assembler Portrait* or
*Errgl Sticker* (so "removed" for those is a no-op unless they exist under another spelling).

Finally, `meta/minions.json` still contains **22 Naga-tagged minions** (20 `Naga` + `Demon/Naga` +
`Dragon/Naga`) — `Abyssal Bruiser`, `Cagey Conjurer`, `Darkcrest Strategist`, `Deep-Sea Angler`,
`Fauna Whisperer`, `Firescale Hoarder`, `Fleeing Fugitive`, `Glowscale`, `Groundbreaker`,
`Lava Lurker`, `Mini-Myrmidon`, `Ominous Seer`, `Rimescale Priestess`, `Sea Witch Zar'jira`,
`Seafloor Recruiter`, `Shell Collector`, `Showy Cyclist`, `Thaumaturgist`, `Torrential Ruiner`,
`Tranquil Meditative`, `Waverider`, `Zesty Shaker` — and **no minion tagged `Aberration`**. The Naga
rotation and the Aberration tribe are both still to be reflected there.
