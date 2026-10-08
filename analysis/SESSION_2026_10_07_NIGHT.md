# Session 2026-10-07 night: Settle Up becomes a tab (c885b2e, 409a47e)

Moved from the working notes on 2026-10-08 by the budget rule (a session
section moves to `analysis/` when the next one lands). One session-directory
name scrubbed to the tracked-file standard; what is still live from this session
is digested in the working notes.

## Where the 2026-10-07 night session left off (Settle Up becomes a tab — released as c885b2e, then 409a47e)

The pivot's Phase 2 shipped a review **page** (2026-10-06). This session turned it
into something a player can keep and browse, and re-pinned the wall it crosses.
12 commits, 10-06 23:53 → 10-07 10:23; a review pass the next hour added 3 more
(the two repairs in item 4/5, the golden consolidation in item 6, and this
record). Suite **1732 green (11 skipped)** — the 1694 sentence below/above was
stale: the count was taken before the session's last test-adding commits
(corrected 2026-10-07).

**1. Saved reviews outlive the process.** `app/replay_store.py`: one JSON per
game under `app/saved_replays/` — readable ids
(`2026-10-06_185502-Chenvaala-2`, collision-suffixed), atomic writes,
corruption-tolerant listing, path-safe load. The stored rep keeps card IDS;
display names are joined at SERVE time (`coach_ui._name_timeline_boards`), so the
file stays canonical and a renamed card fixes old saves. Per-user data, the
`decision_logs` class: gitignored by BASENAME (the `sync.py --new` reason) and in
`publish_release.EXCLUDE_DIRS`. The source log rides as a POINTER (`log` +
`game`), never a copy.

**2. The tab.** A two-tab toggle at the top of the overlay page — **Another
Round** (the live view, byte-for-byte underneath) and **Settle Up** (a browser
over saved games, fetched ONLY from `/review/*`). Endpoints: `POST
/review/save` (the end-of-game card's only button now — the "Settle up" link and
the page's Clear button are gone, 2026-10-07), `GET /review/list`, `GET
/review/game?id=`, `POST /review/open-folder`. The id charset is the store's
filename charset.

**3. The turn cards, and the two rules that were paid for with a wrong answer.**
Each turn is three views — **Shop** (the default since 2026-10-07: it is where
the player's own decisions and the phase rows are read), **Battle**, **Result**.
The battle
board is the strongest burst **before the first death**: the staging burst reads
low (31 stats staged vs 51 a burst later, measured 10-06) and plain max-combined
landed on the duel's aftermath (4730 vs 448). A turn's decisive fight is the
**last** staging group (`_fights`), because the 10-07 final staged the round's
fight and the game's final duel in the SAME turn — first-burst selection showed
the wrong game. A RESULT comes from the fight itself: combat ends when one board
dies, so the side that drained first lost, and the winner is reported with their
last staged board rather than from the next shop's mid-teardown snapshots (those
once produced an aftermath with both sides "surviving").

**4. One control was DEAD for six commits, which matters more than the bug it
should have caught (found and fixed 2026-10-07).** `19fbcb5` — whose message is
literally "docs + the wall re-pinned" — replaced `class TestTheWall(_StoreRoot):`
with `class TestNamedBoards(_StoreRoot):` and left the old body indented under a
fresh `if __name__ == "__main__": unittest.main()`. Python accepts that, unittest
registers nothing, and `Ran 1691 tests … OK` said all was well while PIVOT.md §6.4
and `analysis/SETTLE_UP_BOARDS.md` both cited those two tests as the wall's
enforcement. Restored — and they PASS, so the invariant held while its control was
dead. Two lessons: a green suite is evidence only about the tests that EXIST (a
class statement lost in an edit is invisible to discovery), and a doc citing a
control is not a control.

**5. The same pass fixed a NameError that made the tab unable to open a game.**
`_name_timeline_boards` called `value.display_name` while coach_ui did `from
value import (…)` and never imported the module — `GET /review/game` answered 500
for every saved game, which is the tab's only way in. Three tests errored.

**6. Golden naming is ONE function now.** `value.display_name(names, cid)` is the
single place a golden is spelled out, lowercase `"(golden)"` — that is the string
the live plan text has always carried and `split_step` parses it back
(`test_value` anchors "Buy River Skipper (golden)"), so a second capitalization
would be a second convention. The uncommitted 10-07 draft added a second helper
spelling it "(Golden)"; `_shop_name` is gone and its eight call sites use the one
function. **And a timeline board never carries a `_G` id at all**:
`board_state._minion` strips the suffix and keeps the flag beside the base id —
measured on a real 15-turn rep, 0 board ids end in `_G` while 91 minions carry
`golden` — so the serve-time join NAMES and touches nothing else.

**OPEN, in the order worth doing them:**

1. **A fight straddling the turn boundary can leave the Result unreadable.**
   Measured on the newest game (`the 2026-10-07 morning session`, Tavish
   Stormpike, 1st): `winner` is None on T6 and T9, both of which held a real
   fight — the LAST staging group in the bucket never drains inside the turn, and
   their board keeps draining (7→6→6→5→4→4→4) into the NEXT turn's buy snapshots.
   The Result view then prints "(fight result not readable)" and, in the same
   panel, "They survived with — none": the `w === null` branch falls through to
   the `— none` text. `_fights`' separator (their board coming BACK) is the
   suspect, and this is the same family as the wrong-fight selection `ac0b031`
   fixed. T2 and T11 are a different case and are fine: no coach analysis, so
   `gold` is None and the card header reads "—g".
2. **A review costs TWO replays per game** (~10 s for 15 turns):
   `outcome_audit.audit_game` for the phase rows and `turn_review.timeline` for
   the boards. An injected coach would make it one.
3. **`player_actions` may double-count a single sell** — unchanged from 10-06:
   turn 7 of that game reports three entries for two cards, and the count feeds
   `fight_table` and the audits, so it needs its own look, not a dedupe in the
   consumer.
4. **A swap-led plan is still ungraded** — grading one needs the sell AND the
   play that replaced it as a pair, which the row does not carry.
5. **`docs/` has its pictures back (DONE 2026-10-07).** Five shots against the
   current layout — `save-replay`, `settle-up`, `turn-shop`, `turn-battle`,
   `turn-result` — all shown by the README, all pinned by
   `test_readme_claims.TestTheScreenshotsMatchTheReadme`. Still missing: a shot of
   the LIVE page (**Another Round**), which no release has carried since the
   pivot, and `docs/` is the one shipped directory the privacy gate cannot read
   at all — see Layout. The turn shots were taken with Battle as the default, so
   the Shop one was reached by a click; re-shoot if the button order ever
   changes.
6. **PUBLISHED TWICE, BOTH VERIFIED FROM THE PLAYER'S SIDE (2026-10-07).**
   `c885b2e` shipped the tab, the replay store and the turn cards; `409a47e`
   followed within the hour with the turn cards defaulting to **Shop** and the
   screenshots back in `docs/` (plus the README sentences that had gone stale).
   For both: all three gates passed, the live manifest verifies against the
   pinned `PUBKEY_B64` (`4d8fc45534ba558d`) with `zip_bytes`/`zip_sha256`
   matching the downloaded zip, the pin INSIDE the zip matches this checkout, the
   two stamps sit at the root with no maintainer or local paths, the SHIPPED
   updater run from inside the zip offers the update from the previous release
   and exits 1 (only reachable through a successful verification), and that same
   shipped code REFUSES a manifest whose `note` was rewritten, printing the key
   fingerprint and downloading nothing. Neither publish hit either documented
   gotcha: no `Authentication error [code: 10000]`, and `latest.json` served the
   new manifest on the first read both times. `409a47e` is 245 entries / 1.4 MB
   and **carries `docs/*.png`** — the first release since the pivot with pictures
   in it, which means the one shipped directory `privacy_scan` cannot read is
   back in a download (see Layout). The KV + GitHub copies carry both
   (`releases/latest` is `409a47e`).

