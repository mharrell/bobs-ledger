---
name: hearth-board-extract
description: Extract a player's actual final-board minions from a Hearthstone Power.log, avoiding enchantment, token, trinket, and end-of-game SETASIDE noise. Use when determining what minions/composition a player actually had on their board at the end of a Battlegrounds game.
---

# Extract Final-Board Minions from Power.log (Correctly)

Getting a player's real board composition from a `Power.log` is error-prone.
The log contains huge numbers of non-board entities (enchantments, trinkets,
tokens, and a full SETASIDE dump at game end). Only extract minions **still in
`zone=PLAY` at game end** for the target player.

## Critical gotchas (learned the hard way)

1. **Do NOT use the end-of-game SETASIDE dump.** At game end the log lists every
   card that ever passed through a player's collection (sold minions, used
   spells, enchantments). Searching that gives a bogus "91-minion board."
2. **Do NOT count enchantment/token/trinket/prefab cards.** Many card IDs are
   effects, not board minions.
3. **Only trust minions whose last-known zone is `PLAY`** controlled by the
   target player.
4. **Player number differs per lobby.** The friendly player is not always 3 or 7;
   find it from `DebugPrintGame` (`PlayerName=Player#1234`).

## Correct approach: track last-known zone per entity

Track each entity's `cardId`, `controller`, and last-known `zone` across the
game range, then report minions in `zone=PLAY` at the end.

A working stdlib Python extractor is at:
`extract_board.py`

Run it per game (path + [start_line, end_line]):

```powershell
python extract_board.py <PowerFile> <startLine> <endLine>
```

## What to filter (noise)

- Card IDs starting with: `TB_BaconShop_`, `BG36_MidGameEffect_`,
  `BG36_Button_`, `BG30_Trinket_`, `BG32_MagicItem_`, `BG_ShopBuff`
  (also bare `BG_ShopBuff`), `EBG_Spell_`, `BG20_GEM`
- Card ID tails: `e`, `t`, `d`, `te` and their digit variants (`e2`, `te3`,
  ...) (enchantments/tokens). **`_G` goldens are NOT noise** — a golden on
  board is a real minion (strip trailing digits before the tail check;
  corrected 2026-09-11 — the old list filtered real goldens like
  `BG31_035_G` Golden Groundbreaker off the board).

## Tribe inference from card prefix

Card ID prefixes are set-dependent and drift every season — do not trust a
fixed prefix→tribe table. Resolve tribe from the coach's meta DB
(`meta/minions.json`, e.g. `BG31_920` = Darkcrest Strategist =
Naga in the 2026-09 season) or ask the player.

**Always prefer the player's own read** of what they played over an automated
extract — verify before asserting a composition.

## Verify against the player

The player knows what they played (e.g. "Yogg = Naga", "George = Elemental").
Cross-check the extract against that. If they disagree, re-check the zone
tracking rather than trusting the parse.

## Card IDs → names

To convert card IDs (`BG33_319` → "Rimescale Priestess") install the `hearthstone`
package (`pip install hearthstone`) and look up the card db. It was blocked on
network during initial work; without it, report raw card IDs and rely on the
tribe-prefix table above.
