# Session 2026-10-07 evening: the local-only scrub, trinkets closed, the auto-save checkbox (main 33456e1)

Moved out of the working notes on 2026-10-08 by the budget rule (a session
section moves to `analysis/` when the next one lands). Local-only wording is
scrubbed to the tracked-file standard, as the 2026-10-06 move was; what was
still live from this session is digested in the working notes.

## Where the 2026-10-07 evening session left off

Suite 1747 green (11 skipped) at 02ababf. Four commits pushed (b2a8c88, bc6fed3,
02ababf, 33456e1). **A decision recorded this session — the public repository
stops showing how this project is built — shapes items 1 and 5 below; the rule
lives in the warning at the top of the working notes.**

1. **The working notes and the folders that carry session-local setup are
   UNTRACKED local state now**, kept out by `.git/info/exclude` (shared
   across worktrees). The untrack commit necessarily names the paths once;
   nothing forward does. Tracked files say "the working notes" / "the
   project rules" instead of naming them, and four FUNCTIONAL strings keep
   their names (`publish_release.EXCLUDE_DIRS/.EXCLUDE_FILES`,
   `update.PROTECTED` ×2) — `git grep -inE "claude|anthropic"` shows those
   four plus the notes-file mentions the 2026-10-06 move's own file carries
   (its known, accepted exception). History still carries everything;
   rewriting it would rewrite the release version strings (the BattleTag
   decision, applied again).
2. **The trinket drift is CLOSED**: doctor read 21 missing, then a moving
   newest-6-log window (the machine was in live use the whole session) kept
   surfacing new ids; the final state is **ok, 112/112 recorded, 237 rows**.
   The real bug found: `refresh_trinkets` built its name→id universe from
   offered+guided ids, so a TOKEN trinket (…208t) re-keyed its annotation
   away to the pickable parent on every refresh and the curation gate
   re-flagged it forever — seen ids are in the universe now and tokens
   inherit their parent's curated read. 11 entries curated from card text,
   ALL carrying the `review` key — **they are first passes; the maintainer
   still owes them a read** (the convention says delete the key once agreed).
   Re-run `refresh_trinkets.py` after play sessions; the window moves.
3. **The end-of-game card has a "Save every replay automatically" checkbox.**
   `POST /review/auto-save` persists the answer in `.save_all_replays.json`
   (the share-consent shape; guarded in .gitignore + EXCLUDE_FILES +
   PROTECTED); while the answer is yes the card yields its button to "Saved
   automatically" and `live._settle_up_in_background` writes the replay in
   the SAME build via `coach_ui.auto_save_current_review()`. 15 tests in
   `app/tests/test_auto_save.py`, one per half of the contract. The
   `docs/save-replay.png` shot predates the checkbox and still shows a
   layout that exists; re-shoot whenever the card is re-shot anyway.
4. PUBLISHED AND VERIFIED FROM THE PLAYER'S SIDE (2026-10-07): release
   `33456e1` — the auto-save checkbox, the trinket DB refresh, and the
   local-only scrub. Both gates' runs passed; the FIRST attempt died on the
   zip PUT with `Authentication error [code: 10000]` (the documented
   intermittent; the channel kept serving `b547905`, re-run published
   cleanly), and `latest.json` served the new manifest on the FIRST read (the
   eventual-consistency gotcha did not appear). Verified with the SHIPPED
   code paths: the manifest verifies against the pinned key, the zip is
   1,451,433 bytes with sha256 matching through `update.download_zip`, the
   pin inside the zip matches this checkout, the root holds exactly the two
   launchers, README, licence, `docs/`, `app/` and the two stamps (247
   entries), a tampered manifest is refused naming fingerprint
   `4d8fc45534ba558d`, and the SHIPPED updater from a simulated `b547905`
   install offers `b547905 -> 33456e1` and exits 1.
5. The overlay's bottom-right corner stamps `release: <sha>` (main dd11c3f):
   every payload carries `update.local_version()`, the page renders it in
   the share toggle's quiet gray, pointer-events:none — information, not a
   control. README sentence + 7 tests (test_release_tag.py, one runs the
   wording under node). It first SHIPS in the `32aeecb` release (2026-10-08).

6. NOT done, flagged: the local env script still names itself in
   EXCLUDE_FILES (renaming the local file would scrub it — the maintainer's
   call, it may be sourced by name somewhere); `requests>=2.28` still
   unpinned; the working notes were near their instruction budget — the
   NEXT session section must move one to `analysis/` per the rule.
