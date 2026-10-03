---
name: hearth-powerlog-games
description: Split a Hearthstone Power.log into individual Battlegrounds games and extract per-player data (heroes, picks, placements) for the AI coach. Use when reconstructing the players, heroes, hero choices, and final placements of a Battlegrounds match from a Power.log file.
---

# Split a Power.log into Games and Extract Player Data

Battlegrounds `Power.log` files are one continuous stream spanning many matches.
Each game begins with `CREATE_GAME` and ends when the lobby resolves
(`TAG_PLAYSTATE value=WON/LOST`). Use this to reconstruct individual games.

## 1. Locate game boundaries

Find every `CREATE_GAME` line number (note the duplicate `PowerTaskList`
entries — only use `GameState.DebugPrintPower()` ones for boundaries):

```powershell
Select-String -Path <PowerFile> -Pattern 'CREATE_GAME' |
  Where-Object { $_.Line -match 'GameState\.DebugPrintPower' } |
  ForEach-Object { $_.LineNumber }
```

Game ranges:
- Game 1 = line 1 → (second GameState CREATE_GAME − 1)
- Game N = (Nth GameState CREATE_GAME) → EOF

## Game seed

Each game has a `GAME_SEED` (e.g. `tag=GAME_SEED value=1336465919`). Use it as a
stable game id.

## Extract each player's hero choice (your pick)

Look at the hero mulligan choice near game start:

```
DebugPrintEntityChoices() - id=1 Player=<YourName> ChoiceType=MULLIGAN ...
DebugPrintEntityChoices() - Entities[N]=[... cardId=TB_BaconShop_HERO_XX player=<N>]
```

- `TB_BaconShop_HERO_XX` are the offered heroes.
- The chosen hero is the one that ends in `zone=PLAY` with `HERO_ENTITY` matching
  the player's hero entity.

```powershell
# Which hero ended in PLAY for the friendly player
Select-String -Path <PowerFile> -Pattern 'zone=PLAY.*cardId=TB_BaconShop_HERO_.*player=<YOUR#>'
```

## Identify your player

Your name (e.g. `Player#1234`) appears in `DebugPrintGame`:
`PlayerID=7, PlayerName=Player#1234`. `PlayerID` is the player number for that
game (may differ per lobby).

## Extract final placements

Final result markers:

```powershell
Select-String -Path <PowerFile> -Pattern 'PLAYSTATE value=(WON|LOST)'
Select-String -Path <PowerFile> -Pattern 'PLAYER_LEADERBOARD_PLACE value='
```

- `PLAYSTATE value=WON` → won the lobby (1st); `LOST` → eliminated.
- `PLAYER_LEADERBOARD_PLACE value=N` on the player's hero entity = final rank.

## Notes

- 8 players per Battlegrounds lobby (Duos: 4 teams of 2).
- Only the friendly player's hand/cards are fully revealed; opponent hands and
  shop offers are not visible, but opponent heroes, boards, and placements ARE
  reconstructable from the log.
