# Verifying the two pages against the log — the accuracy audit

**What this is.** Another Round and Settle Up both make claims about a game: this
hero, this gold, this board, this fight, this placement. Every claim has an
evidence line in `Power.log`. This document is the procedure for checking that
the claim and the evidence agree, and the catalogue of ways they have disagreed.

**What it is not.** It is not a review of whether the *advice* was good. That is
`REPLAY_LEARNING.md` §6 and `outcome_audit.py`, and their rules (calibration is
not outcomes; a game coached across a build change is unusable) apply there. This
audit asks a narrower, harder question: **does the page say what the game did?**

## Method (not optional)

**1. Fix the target before looking at anything.** A session and a game index, not
"the last game" — the log moves on while you read.

```
python logquery.py games <Power.log>        # the games, their hero and placement
```

**2. Get the log's answer FIRST.** Run the queries. Write the numbers down.

This ordering is the whole discipline. If you look at the page first, you will
spend the rest of the audit explaining its numbers — including the wrong ones —
and every "maybe it's the log" you entertain will be against a picture you have
already believed. MEASURED 2026-10-16: the review's last turn reported a *win* on
a fight the player lost. The log had said otherwise in four separate lines.

**3. Then read the page's claim**, from the surface and not from memory:

| page | where the claim lives |
| --- | --- |
| Another Round | the rendered panel, or the payload behind it (`coach_ui.render_json` for a live frame, `welcome_payload` for the cards) |
| Settle Up | `saved_replays/<session>-<hero>-<place>.json` → `rep.timeline.turns[]` |

**4. Compare field by field, and quote evidence for every mismatch** — the log
line number or the timestamp. "The gold looks wrong" is not a finding; "the page
says 10 gold at 23:04:41, and `RESOURCES=13` less `RESOURCES_USED=3` is 10, but
`TEMP_RESOURCES=2` at line 1,021,338 is not counted" is.

**5. Classify it before fixing it.** The class decides the fix, and getting it
wrong is how a good bug gets a bad patch:

| class | symptom | fix |
| --- | --- | --- |
| **parser** | page and log disagree, and the payload agrees with the page | `board_state` / `live_coach` / `turn_review` |
| **renderer** | the payload is right and the page is wrong | `coach_ui` |
| **stale artefact** | the replay file was built by an older build | press Rebuild; no code change |
| **log ambiguity** | the log genuinely does not say | say so on screen; never guess |

**6. No change without a case** (`REPLAY_LEARNING.md` §6). Either the fix flips a
named test or it adds one. A silent behaviour change is this repo's recurring
failure mode.

**7. Write the audit up in `analysis/`, opening with `## Method`** — the
convention this document follows.

## What each page claims, and where the evidence is

Another Round is the live panels; Settle Up re-renders the same panels per turn
plus the fight and the plan. Each panel is one function, reading one payload
field, which comes from one parse of one kind of log line:

| panel | renderer | payload field | log evidence |
| --- | --- | --- | --- |
| hero / gold / tier / turn / place | `lvStatus` | `hero`, `gold`, `tier`, `turn`, `place` | the live payload's base dict (`live.py`), filled from the parse; ground truth via `logquery.py games` and `stats` |
| effective HP | `lvFacts` | `eff` | `HEALTH` − `DAMAGE`, plus `ARMOR` |
| took last fight / last 3 | `lvFacts` | the HP series | the same two tags, sampled at buy-phase starts |
| damage cap | `lvFacts` | `damage_cap` | `BACON_COMBAT_DAMAGE_CAP`, on the NAMED GameEntity form |
| lobby tribes | `lvTribes` | `tribes_available`, banned, out-of-play | the tribe tags in the tavern / the pick, plus `out_of_play.json` |
| tavern offers | `lvShop` | `shop_rank`, `shop_mix`, `shop_passed` | `FULL_ENTITY` + the shop `ZONE=PLAY` set, in game order |
| board / hand | `lvBoardHand` | `board` (`board_cards` in the renderer), `hand` | `ZONE=PLAY` / `ZONE=HAND` for `friendly` |
| comps | `lvCompsBody` | `comps` (core ids + owned/in_hand) | the board and hand ids against `meta/comps.json` |
| next opponent | `lvOpponent` | `opp_comp` | the last board staged for the opponent, seat-keyed and aged |
| lobby seats | `lvLobbyBody` | `tribe_pressure` | tribes with **2+ copies on a last-known board**, per SEEN seat — never-sighted seats are omitted, not assumed absent |
| the fight | `settleTurnCard` | `combat_start` / `combat_peak` / `battle_end` / `winner` / `damage_taken` | `BLOCK_START BlockType=ATTACK`, the `ZONE` drains, `PLAYSTATE` |
| the plan | `tavernRail` | `plan` + its grading | `decision_logs/` — what the coach said **at the time** |

## The truth sources, and what each is worth

- **`Power.log` — primary.** Line-numbered, timestamped, and the only thing that
  cannot be wrong about the game.
- **The saved replay file — derived, so it is a CLAIM.** `rep.log`, `rep.session`
  and `rep.game` name the log it came from; `rep.timeline_error` and the per-turn
  `notes` say what the rebuild could not do. Checking a replay means rebuilding
  it from its own log with the current code and diffing the two.
- **`decision_logs/`** — what the coach actually said. `outcome_audit` replays
  *today's* rules, deliberately, so it answers a different question; do not use
  it to check what was on screen last Tuesday.
- **The two streams.** `GameState.DebugPrintPower()` and
  `PowerTaskList.DebugPrintPower()` both describe the same game, and at the end
  of a game the first runs AHEAD of the second. See trap 1.

## Known traps — each of these has bitten this project

**1. The outcome is printed twice, and the GameState copy comes first.**
Measured 2026-10-16: `GS MikeySCE LOST` at file line 1,018,835, then `PTL
MikeySCE LOST` at 1,024,686. The final fight's seven `ATTACK` blocks sit *between*
them (chunk lines 379,257–381,694). Anything that stops on the first outcome
throws the final fight away. `choices.py` keys on the same distinction in the
other direction, keeping only GameState blocks.

**2. The tail after the last phase is the whole lobby, not you.** Once you are
eliminated the other players keep fighting, and their combats are in your log. The
last turn of the 2026-10-16 game held **three separate fight groups** — theirs
drains, *ours* drains, theirs drains again. `fights[-1]` is not "your fight";
`turn_review._decisive_group` picks by the game's own verdict.

**3. Survivors are the winner's last NON-EMPTY staging.** A BG log stages an empty
board once the dead are cleared, so a fight group's final snapshot is routinely
empty for both sides. Reading it as "survivors" reported 0 for a board that
plainly won.

**4. Summoned leftovers stay in `PLAY` into the next shop.** The opening board has
to be cleaned (`_opening_board`), or a 7-minion board reads as 9.

**5. Golden minions carry a `_G` suffix** (`BG36_762_G`). An id that misses the DB
by its suffix is not an unknown card.

**6. End-of-game cleanup re-creates the board** as enchantments for the
leaderboard. `board_state` stops snapshotting at the outcome for exactly this
reason — which is also why lifting that stop (as the offline replay pass must)
needs the cleanup excluded on the other side.

**7. A replay is stamped by the build that wrote it.** A game coached across an
update is unusable, not partly usable; a replay file is only as good as the code
that built it. If the numbers look old, press **Rebuild** before filing a bug.

**8. OPEN — combat may renumber controllers.** During a duel the two sides can be
re-seated, so `player == friendly` in a combat snapshot is not proof the minion is
yours. This is a hypothesis from the 2026-10-16 session, not a finding: the
three-group tail above is explained by traps 1–2 without it. Verify before
relying on either reading.

## Quick reference: which tool answers which question

| question | command |
| --- | --- |
| which games, which hero, what placement | `logquery.py games <log>` |
| what the player actually did in a turn | `logquery.py actions --game N` |
| the board at the end of a turn | `logquery.py board --game N --turn T` |
| HP, armour, effective HP, damage taken per turn | `logquery.py stats --game N` |
| the escalating combat damage cap | `logquery.py cap --game N` |
| card ids in the log that no meta DB knows | `logquery.py unresolved --game N` |
| what left the hand without being played | `logquery.py vanish --game N` |
| did the advice hold up, across every local game | `outcome_audit.py` |
| one game, turn by turn, as the review renders it | `settle_up.py [<log>] [<game>]`, `--latest` (newest session log), `--session` (every game, summarised), `--history N`, `--json`, `--html PATH` |

## What an audit may NOT claim

- **That a match proves correctness.** Agreeing on one turn rules out large
  classes of error and proves nothing about the next turn; every trap above was
  invisible on the turns that looked right.
- **That a disagreement is a bug.** Class 4 exists. The honest outcomes are
  "the page is wrong" and "the log does not say", and the second one belongs on
  the screen, not in a guess.
- **Anything from a replay you did not rebuild.** The file is a claim.
