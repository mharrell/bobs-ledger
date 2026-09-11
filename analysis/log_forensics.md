# Log forensics: script first, grep last

Working rule for game/turn forensics on Power.log files, distilled from the
2026-09-10 Patchwerk review (the Felfire Conjurer dig).

## The rule

- **>2-3 tool calls or >50k log lines scanned ⇒ write a script.** A single
  deterministic pass beats a grep chain: one model round trip, no raw log in
  context. Genuine one-shot lookups stay grep.
- Scripts are stdlib-only and **import the existing parsers** (split_game_chunks,
  player_actions, live_coach, board_state) instead of re-deriving regexes —
  the canonical-definition lesson from the 2026-09-04 code audit: four
  divergent copies of one regex drifted, and extract_board.py drifted again
  until rebuilt in 2026-09-11 (16c7c52).
- **Spec the output before writing the script:** if it isn't 10-30 distilled
  lines, the design is wrong.
- **Sanity-check an extractor against an independent source before trusting
  it on a decisive call** (the player's own board read, the overlay capture).
  extract_board listed sold minions on a "final board" for weeks — silent
  misattribution that poisoned a review.

## In Git Bash

Prefer `python - <<'EOF' … EOF` heredocs for one-offs: bash mangles `$_`
inside double quotes, and tmp-dir scripts hit execution-permission friction.
Quoted heredoc = no interpolation, no files.

## The tools (write one when a question recurs)

- `python turn_forensics.py --latest [game_index] [--turns 13|13-15|all]` —
  per turn: tier/income, labeled gold timeline, settled shop rebuilds with
  comp cores flagged (`*`) and affordability (`[core affordable]`), action
  counts, end-of-turn board.
- `python replay_review.py --latest [game_index] --at 23:27:30` (or an
  absolute log line) — the coach's advice at any moment, including mid-roll
  shops the per-phase review never sees.
- `python extract_board.py <log> <start> <end>` — final boards, per entity
  with stats, goldens included.

Accepted against the 2026-09-10 session (game 2): t13 shows Felfire Conjurer
offered 23:27:30 with exactly 3 gold — affordable, board 6/7 — the answer
that took ~6 ad-hoc calls by hand.
