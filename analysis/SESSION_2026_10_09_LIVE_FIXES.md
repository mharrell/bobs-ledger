# The LIVE fix lists, rounds 1 and 2 (2026-10-09, released as `4738fa1`)

Moved out of the working notes on 2026-10-24 by the budget rule: this file is
the full record, the working notes keep a pointer and the traps that still
matter.

## Where THIS session left off (2026-10-09 late: the LIVE fix lists, rounds 1 and 2 — RELEASED as `4738fa1`)

Both lists the maintainer handed over (18 items, 3 of them repeats) are
implemented, browser-verified and in players' hands. One commit, `4738fa1`
(2026-10-09 22:04), and it was the FIRST publish attempt that worked — no
`10000` this time. Suite: **1992 tests, OK, 11 skipped** (`test_live_browser` 51,
`test_live_tavern` 47 — up from 37 and 34), browser tests RAN, privacy scan
clean on every changed file.

**What the fixes actually changed, and the traps in them:**

* **Live did not fill the window (round 1 item 1).** `#app` is a two-column GRID
  above 1200x900 and a flex COLUMN at or below it (the media query is
  `(max-width:1199.98px), (max-height:899px)` — and the harness's own 1400x900
  window lands in the flex branch). The tavern container's size was a grid rule
  plus `flex:1 1 100%`, and in a column `flex-basis` is a HEIGHT, so it never
  stretched across: measured 815px of a 1384px window. Fix: one grid column in
  tavern mode plus `width:100%`, which holds in both branches. **A layout claim
  has to be measured in both branches** — they are two layout modes of one page.
* **Round 2 item 9's breakpoints** replaced the 900px rail rule: main + 340px
  rail at >=1200px, stacked from 700 to 1200 (the BASE rule, not a media query),
  single-column pick grid under 700.
* **The pick screen shows one name and one decimal** (round 1 item 2 / round 2
  item 1): `tile(..., {noname: true})` suppresses the tile's own clamped name so
  `.lv-optname` carries it once at a fixed height; the card is 130px (`--tcardw`
  on `.lv-opt`); the headline is `toFixed(1) + '%'` labelled **Picked**; and
  `lvStatRows` no longer emits a `pick_rate` row. **The trap: the Order control
  reads the STATS, not the visible rows** — `lvPickControls` builds `orderKeys`
  separately, or "By picked %" would have vanished with the row.
* **The maintainer's calls beat the design where they conflicted**, and each is
  pinned by a test that says so: §6.1's four dashed skeleton cards are GONE
  (`lv-skel` deleted outright, so no rule can revive them) in favour of the
  sentence plus a hero slot reading "Waiting for the next shop to open"; §4.2's
  "Lethal at" row is gone because it printed effective HP a second time; §4.4's
  slot colours now sit under a legend AND under card art.
* **"banned tribe — can't grow" stayed put** — it is `value.sell_reason`'s string,
  the classic Sell box shows it and `test_hand_engine` pins it — so the payload
  gained what the tavern caption needs instead: `sell_rank` rows carry `off_play`
  (compared in one place) and `tribe`, and `_canon_tribe` runs it through
  `value.normalize` (a board minion logged as `BEAST` would otherwise print the
  raw tag). `lvBoard` renders "<Tribe> — out of play" from those two facts.
* **The empty rounded bar (round 2 item 7) was not a tavern bug at all**:
  `#statebar` has a background, a border and a radius, and the WELCOME card
  blanked its text. It is hidden wherever nothing fills it (welcome, both tavern
  renderers) and unhidden by the two paths that do fill it.
* **The tribe row listed Naga twice** (round 1 item 3): `tribe_roster` is every
  tribe the game has and `out_of_pool` names the rotated ones, so iterating both
  printed it in both states. The classic ban picker already filtered that way;
  the tavern row does now too, and chips are `active` (amber outline) or `dim`.
* **Comps (round 1 item 6)**: slots carry the card's own art through the same
  `thumb()` the tiles use (the hover tooltip and full card render come free),
  dimmed when not owned; the legend is built from the slot ELEMENT, so it cannot
  drift; compare is a real checkbox (disabled at three, reason in its title); and
  `.lv-crow` is a grid with fixed columns — `margin-left:auto` could not promise
  an x, which is what "consistent rows" needed.
* **Round 2 item 3**: one art treatment everywhere, the kind said in a corner tag
  (`tag-kind`, fed by the payload's own `shop_rank[].tag === 'spell'`), and names
  wrap to two lines with the whole name on `title` and on hover.
* **The toggle is themed (round 1 item 9 / round 2 item 8)**: `.vseg` described
  only the ACTIVE state and the radii, so the buttons were whatever the browser
  draws — the white pill. Themed for both pages, and in tavern mode it takes the
  tavern palette so the control matches what it toggles.

**Test-authoring traps this round, worth keeping:**
1. `render_json` DERIVES `a["opp_lobby"]` (from `opp_stats` → `lobby_opp` →
   `baseline_opp`), so a fixture that sets `opp_lobby` directly proves nothing —
   the lobby branch needs `lobby_opp`.
2. `root.querySelector('.tavern.live')` matches no DESCENDANT of the root and
   returns null, which read as "the tavern view is 0px wide" — measure the root.
3. `banned` carries CANONICAL display names ("Beast") while a fixture's board
   minion may carry the raw tag ("BEAST"); `sell_reason` normalizes one side, so
   a fixture that mixes them never triggers the banned-tribe reason at all.
4. `.lv-opts` is used by BOTH the pick screen and the comps Compare block: a
   driver read that assumes a pick-only parent throws on the other screen (this
   bit the harness once already, in the `.lv-pickctl` parentNode bug).

**Release `4738fa1`, verified from the player's side:** all three gates passed
first try; `latest.json` served it on read 1; the signature verifies against the
pinned `4d8fc45534ba558d`; the bounded download matches `zip_bytes`/`zip_sha256`
(1,584,021 bytes) through the SHIPPED path; the zip holds 254 entries whose root
is the two launchers, README, licence, `app/`, `docs/` and the two stamps, with no
maintainer-only part; the GitHub asset is byte-identical; and the SHIPPED updater
from a simulated `7d65909` install offered `7d65909 -> 4738fa1` (exit 1), APPLIED
it (254 files) and then reported "up to date".

**Budget rule applied on the way in**: CLAUDE.md was at 65,316 bytes of the
65,536 a session loads, so the 2026-10-08 access-key section (32,760 bytes) moved
to `analysis/SESSION_2026_10_08_ACCESS_KEY.md` with a pointer left behind. The
README's Live section was re-read against the new layout and is still accurate
(nothing there describes the skeleton bars or the Lethal-at row).

Still open, unchanged: §6.3's older-patch marker, §3's classic-page amber rule,
§9's data-licensing decision, and the README's live-page screenshot.

