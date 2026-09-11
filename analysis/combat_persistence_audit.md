# Combat-phase buff persistence — full card-text audit (2026-09-11)

Player rule: **stat increases gained DURING a battle evaporate at combat end
unless the card text says otherwise.** Buff-givers whose gains die with the
fight are combat power (`W_COMBAT_SCALE`), not growth engines. Every minion in
`meta/minions.json` (263 cards, current patch) was reviewed against its
stored text; this doc records the verdicts and the machinery in `value.py`.

## The rule family (player-confirmed, 2026-09-11)

1. **Combat gains evaporate** — start-of-combat / in-combat / Rally /
   on-attack / Avenge / Reborn-proc / takes-damage / deathrattle STAT buffs
   revert when the fight ends. Combat-granted KEYWORDS too (Venomous, Reborn,
   Divine Shield granted mid-fight).
2. **Self-improving combat engines are their own class** — Tasty Lobster's
   grants evaporate, but each grant makes future grants fire once more
   (grant COUNT compounds); Lurking Leviathan's grant SIZE improves
   permanently ("improve this permanently" = the card's grant, not the
   target's stats). Credited at `W_COMBAT_ENGINE` (8.0), labeled "scaling
   combat engine". No stats persist, so never a growth engine.
3. **Hand-targeted gains persist** even when granted mid-combat — the hand
   card didn't fight, so nothing reverts (Winterfinner, Tide Oracle Morgl).
   The RECEIVING side decides: gains FROM the hand ONTO a board minion
   (Choral Mrrrglr, Costume Enthusiast) still evaporate.
4. **Shop-phase manipulation** (rare, intentional): a combat-triggered buff
   becomes permanent when the trigger is forced in the tavern — Lurking
   Lionfish makes your left-most Beast attack a Fishbait in the shop (Rally /
   on-attack buffs stick), golden Headhunter Gryphon + Rally chains trigger
   deathrattles in the shop (the Beasts — Tasty Lobstah comp finisher).
   Card-level classification keeps the in-combat default; the manipulation
   tech lives in the comp guides, not the value function.
5. **Text can override**: "permanently" (Motley Phalanx, The Last One
   Standing, Razorfen Vineweaver's "3 permanent Blood Gems", Devout
   Hellcaller, Jelly Belly), "this game" (Beetles family, Plaguerunner,
   Tavern-buff clan), "wherever they are" persist; "until next turn",
   "this combat only", "rest of this combat" explicitly expire.

## Machinery (value.py)

- `_combat_only_gain()` — the classifier: explicit-expiry markers →
  persist markers (incl. hand-target markers) → stat-gain shape (incl.
  `+N/+N` regex and "plays a blood gem") + combat trigger. Markers match on
  wrap-collapsed text (`_flat_text`) — DB text wraps mid-phrase.
- `COMBAT_ONLY_GAIN_OVERRIDES` — curated by name for prose that defeats the
  markers: Fire-forged Evoker, Showy Cyclist, Lurking Leviathan (→
  combat-only), Snazzy Phantom (→ NOT combat-only; its transfer lands "in
  combat and in the shop" per the player-corrected undead engine entry).
- `SELF_IMPROVING_COMBAT_ENGINES` — Lobster, Leviathan.

## Verdicts (buff-granting minions only)

**Persistent granters (real growth):** all Battlecry buffers (Fallen Sun
Cleric, Mama/Papa Mrrglton, Lovesick Balladist, Electric Synthesizer's
battlecry half, Forest Rover, Nerubian Deathswarmer, …), shop-time triggers
(Fleeing Fugitive, Wrath Weaver, Meteorite Crasher, Timecap'n Hooktail,
Charging Czarina, Devilish Distractor, Shamanic Tidecaller, Twilight
Tidehunter, Bream Counter, sell-triggers: Fire/Snow/Air Ballers, …),
"this game" family (Beetles: Ravaging Scorpid, Turquoise Skitterer, Forest
Rover; Plaguerunner; Friendly Geist; Glowing Cinder; Dancing Barnstormer;
Champion of Sargeras; Waveling; Sanguine Champion/Refiner; Dustbone
Devastator; Moat Custodian; Forsaken Weaver; Azsharan Cutlassier; Blue Whelp;
Intrepid Botanist; Felfire Conjurer; Tranquil Meditative; Void Pup Trainer),
"permanently" family (Motley Phalanx, Devout Hellcaller, Jelly Belly,
Razorfen Vineweaver, The Last One Standing), keep-buff Dragons (Tarecgosa,
Persistent Poet), hand-target gainers (Very Hungry Winterfinner, Tide Oracle
Morgl, Bream Counter, Twilight Tidehunter, Futurefin), eat-stats demons
(Flaming Enforcer, Felboar, Insatiable Ur'zul, Soulkeeping Jailer, Mind
Muck, Unbound Tempest).

**Combat-only granters (one-fight power, `W_COMBAT_SCALE`; self-improving
ones `W_COMBAT_ENGINE`):** Flighty Scout, Glim Guardian, Mini-Myrmidon,
Tusked Camper, Wailing Banshee, Electric Synthesizer (SoC half), Expert
Aviator, Fishbait, Humming Bird, Prodigious Tusker, Roaring Recruiter,
Thaumaturgist, Wolf Pup, Scarlet Skull, Deep-Sea Angler, Amber Guardian,
Deflect-o-Bot, Bonker, Cage Gnawer, Diremuck Forager, Mummifier, Steadfast
Spirit, Tasty Lobster*, Waverider, Banana Slamma, Barrier Banshee, Bile
Spitter, Costume Enthusiast, Glowscale, Goldrinn, Showy Cyclist, Stalwart
Kodo, Choral Mrrrglr, Deathly Striker, Fire-forged Evoker, Lurking
Leviathan*, Tide Oracle Morgl was hand-target → persistent. (* = self-
improving.)

**Deliberately kept as engines despite combat-shaped text:** Snazzy Phantom
(dual-phase per curated engine entry), the hero-damage demon loop (Soul
Rewinder, Tichondrius, Ashen Corruptor — "After your hero takes damage"
fires in the tavern too via self-damage; Ashen's buff is even text-limited
to "this turn").

**Summons / generated cards persist** (not stat gains): Buzzing Vermin,
Cord Puller, Harmless Bonehead, Sewer Rat, Sly Raptor, Cadaver Caretaker,
Handless Forsaken, Auto Assembler, Kangor's Apprentice, Sewer Lord, Eternal
Summoner, Ravaging/Turquoise beetle summons, Stitched Salvager, Jailbird
Juggernaut; "Get a X" card generators.

## Known gaps / assumptions

- **Rally** is treated as a combat-start trigger (corroborated by
  Deathstrider's "After a friendly Rally minion attacks"). If Rally ever
  fires in the tavern by default, Glim Guardian / Wolf Pup reclassify.
- **Token-mediated grants** are invisible: Seafloor Recruiter's "Rally: Cast
  Chef's Choice on the minion to the right" grants stats mid-combat through
  a spell we don't resolve. Same for Runic Arcanist's Shiny Ring cast at
  start of combat (those expire; we just don't flag the granter).
- Ashen Corruptor's "+2/+2 this turn" is the only explicit shop-turn-limited
  buff in the pool; it's kept as an engine (the demon loop value lives in
  the trigger frequency, and "this turn" shop buffs still compound the
  Tavern-eat plan).
- Spells/trinkets are out of scope here (spells are cast in the tavern, so
  their buffs persist by default — see `hearth-tavern-buff-waste` memory for
  the one-shot exception).
