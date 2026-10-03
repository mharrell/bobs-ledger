---
name: hearth-powerlog-locate
description: Locate and identify Hearthstone session logs (Power.log) on Windows so their game data can be parsed for the Battlegrounds AI coach. Use when finding where Hearthstone logs live, identifying the most recent games, or determining which Power.log to parse for a given session.
---

# Locate Hearthstone Session Logs (Power.log)

Hearthstone writes per-session logs under its install directory on Windows.
Use this to find the raw game data for the Battlegrounds AI coach.

## Where the logs live

```
C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_<timestamp>\
```

Each `Hearthstone_<timestamp>` folder is one launch session. The raw game data
is in **`Power.log`** (or `Power_old.log` after rotation at the next session).

Typical sizes: 30–250 MB per session. Recent sessions may have several.

## Key files

| File | Contents |
|------|----------|
| `Power.log` / `Power_old.log` | The full per-game action stream (gold mine) |
| `Achievements.log`, `Hearthstone.log` | Not needed for parsing |
| `All.log` | Concatenated log (if present) |

## Identify the newest session

List sessions and their Power logs by modification time:

```powershell
$root = "C:\Program Files (x86)\Hearthstone\Logs"
Get-ChildItem $root -Directory | Sort-Object Name | Select-Object Name
Get-ChildItem $root -Recurse -Include "Power.log","Power_old.log" |
  ForEach-Object { "{0}  {1:N1} MB  {2}" -f $_.Directory.Name, ($_.Length/1MB), $_.LastWriteTime }
```

## Confirm a session contains games

Count `CREATE_GAME` markers in a Power file:

```powershell
(Select-String -Path <PowerFile> -Pattern 'CREATE_GAME' | Measure-Object).Count
```

Each `CREATE_GAME` is one match. Battlegrounds games also contain `BACON_*`
tags and a `GAME_SEED` value.

## Distinguish your account

Your player name (e.g. `Player#1234`) appears in `PLAYSTATE` tag changes and
`DebugPrintGame` lines (`PlayerName=Player#1234`). Use it to identify which
of the 8 players is you.
