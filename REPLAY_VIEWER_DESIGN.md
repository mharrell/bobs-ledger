# Bob's Ledger: Replay Viewer Redesign

Design spec for reworking the post-game replay viewer. Written to be handed to a coding session. I (the author of the mocks) have not seen the viewer source, so component and function names below are descriptive; map them onto what exists.

Reference mockups (interactive canvas): https://claude.ai/artifact/Pix2TjzSFHdEDcWgn8VCnn
Note: in the mocks, the 23-action APM log, the turn results for turns other than 6 and 7, and the tray contents are made up to stress-test the layout. The boards for turn 7 are real.

---

## 1. Goals

- Make cards and board images much larger and arranged like in-game.
- Show **one turn at a time**, large, instead of a long scroll of small cards.
- Present player actions cleanly, and keep that readable for APM comps (dozens of buys/sells/rolls in one phase).
- Add an optional **step-through mode** that replays a phase action by action.
- Move to the warm "Tavern" palette so it stops looking like a dev tool.

Non-goals for now: changing what data is recorded, new analysis, new coaching text.

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Layout | One turn at a time, turn strip along the top (mock "A") |
| Default view | **Summary**: grouped, collapsed action rail |
| Secondary view | **Step through**: scrubber over each action, toggled from the header |
| Palette | **Tavern** (section 6) |
| Rejected | Annotated board with per-action markers ("C"): too cluttered on APM turns. Only *net* changes are marked on the board. |

## 3. Page structure (reference size 1100 x 680, fluid in practice)

```
Header:  [Game title · placement · turn count]            [Summary | Step through]
Strip:   [1][2][3] ... [7 selected] ... [12]               (one button per turn)
Body:    [Rail 330px fixed]  [Main: tabs + boards, flexible]
```

- Main always has tabs: **Shop | Battle | Result**. The mode toggle (Summary / Step through) sits in the header and its choice should persist between sessions.
- Rail is the action list for the selected turn (Summary mode only). In Step-through mode the rail is dropped and the boards get the full width and larger cards.

## 4. Components

### 4.1 Turn strip button
- Min 44px wide, 48px tall. Number on line 1; line 2 is a small marker plus HP lost: `▲` win, `▼` loss, `=` tie, e.g. `▼ −10`.
- Bottom border (3px) is colored by result (`--win`, `--loss`, `--tie`). Result must not rely on color alone, hence the marker.
- Selected turn: filled with `--sel`, dark text.
- Purpose: scan the whole game for bad turns at a glance.

### 4.2 Card (minion)
- Summary mode: 88 x 120. Step-through mode: 130 x 172. Real card art fills the card; name and stats overlay the bottom.
- Stats: attack in `--atk` (gold), health in `--hp` (red), buff delta in `--buff` (green), e.g. `+3/+3`.
- Tag (top-left): `NEW` for minions that appear on the ended board but not the opened board (`--buff` background, dark text).
- **Ghost card** (tray, and sold-in-step-through): 76 x 100, 55% opacity, dashed border.
- Hover: enlarge with full card text (compact cards cannot show it).

### 4.3 Rail (Summary mode)
Header: `Turn N · X actions`, then count chips: `+5 bought`, `−5 sold`, `9 rolls`, `1 level-up`, `2 casts`.

Below are groups, each collapsible:

| Group | Default | Contents |
|---|---|---|
| Economy | collapsed | rolls and level-ups, in order |
| Buys | open | minions bought |
| Sells | open | minions sold |
| Plays | collapsed | plays and casts, in order |

Rules:
- **Collapse repeats**: `Wolf Pup ×2`, `Rolled ×9`.
- Each item is a small chip with a colored left edge: kept = `--win`, sold from board = `--loss`, flipped = `--tie`.
- **Flipped** = bought and sold in the same phase. These never appear on the Opened or Ended boards, so they must appear in the rail and in the tray.
- Cap very long groups (e.g. show first 8 plus "show all N").
- Keep the existing "worth a look, not a verdict" flags; show them under the chips in `--sel`-adjacent warning color (amber/orange).

### 4.4 Boards (Shop tab, Summary mode)
Three stacked sections:
1. **Opened with**: board at the start of the phase.
2. **Ended with**: board at the end of the phase, before battle. Mark **net changes only**: `NEW` tag, stat delta vs Opened. No per-action markers.
3. **Passed through**: ghost cards for flipped minions (hide the section if empty).

Sold-from-board minions appear in Opened but not Ended; the rail's Sells group shows them.

### 4.5 Battle tab
- Opponent board on top, `VS` divider, your board below, hero badge plus HP on each side. Arranged as in-game, centered rows.
- Result panel on the right: outcome (win/loss/tie), minions left, HP taken. This replaces the separate Result tab content, which can mirror it.
- Proposed (not mocked): tint your side warm and the opponent's side cool so the boards read apart instantly.

### 4.6 Step-through mode
- Board label: `Your board after step N of M`. Cards use the large size.
- The card affected by the current action is highlighted (e.g. a sold card shows a `SOLD` tag and a dimmed state).
- Caption: the action in plain words, e.g. `Sold Decoy Conjurer`.
- Controls: `Prev`, `Play`, `Next` (44px targets).
- Track: one button per action, 38 x 44, colored and **lettered** by kind (R roll, B buy, S sell, L level up, P play, C cast). Current step has a 2px `--sel` outline. Legend below.
- Requires board state after every action (see section 8).

## 5. Behavior

- Keyboard: Left/Right = previous/next turn (Summary) or step (Step-through); Shift+Left/Right = turn in Step-through; Space = play/pause; Home/End = first/last. All proposed; adjust to avoid clashing with existing shortcuts.
- Persist the Summary / Step-through choice.
- Play should respect `prefers-reduced-motion` (step on a timer without animation).
- Under about 900px width: move the rail above the boards, collapsed by default; let card rows wrap.
- Optional later: deep links to a turn or step; "copy turn as text".

## 6. Styling: Tavern palette

Design tokens (CSS custom properties):

```css
:root {
  --bg:      #17110d;
  --panel:   #231913;
  --panelbg: linear-gradient(#2a1e16, #1f1610);
  --card:    #33261d;
  --cardbg:  linear-gradient(#3b2c21, #2c2018);
  --line:    #5a4332;
  --text:    #f1e6d2;
  --mute:    #b09c84;
  --sel:     #e0a43a;   /* selection accent only */
  --atk:     #f4c95d;
  --hp:      #e8664f;
  --buff:    #8fd06a;
  --win:     #7cc66b;
  --loss:    #e8664f;
  --tie:     #b09c84;
  --shadow:  0 3px 10px #0007;
}
```

Proposed action-kind colors for the step track (not yet mocked in Tavern; verify contrast):

```css
--k-roll:  #3a2d22;  /* text #b09c84 */
--k-buy:   #35592f;  /* text #e4f5da */
--k-sell:  #7a3328;  /* text #ffe1db */
--k-level: #7a6320;  /* text #fff1c4 */
--k-play:  #2c4f7a;  /* text #dce9fb */
--k-cast:  #54397a;  /* text #eadcfb */
```

Rules of use:
- **Gold is not the accent.** `--atk` is attack only; `--sel` is the selection accent (selected turn, selected tab, mode toggle, current step). Do not use one for the other's job.
- Three surface levels: page (`--bg`), panel (`--panelbg`), card (`--cardbg`). Panels get a 1px `--line` border; cards get `--shadow`.
- Text on `--sel` fills is dark (`#14110c`).
- Typography: `"Segoe UI", system-ui, sans-serif`. Section labels are 12px, uppercase, 0.12em tracking, `--mute`. Card names 11px, stats 15px bold; large mode scales stats to 19px.

Component CSS from the mocks (adapt freely):

```css
.card{width:88px;height:120px;border-radius:10px;background:var(--cardbg);
  border:1px solid var(--line);box-shadow:var(--shadow);display:flex;
  flex-direction:column;justify-content:flex-end;align-items:center;gap:3px;
  padding:6px;box-sizing:border-box;font-size:11px;text-align:center}
.atk{color:var(--atk)} .hp{color:var(--hp)} .delta{color:var(--buff);font-size:11px}
.tag-new{margin-bottom:auto;font-size:10px;font-weight:700;padding:2px 5px;
  border-radius:4px;background:var(--buff);color:#10140f}
.ghost{width:76px;height:100px;opacity:.55;border-style:dashed}
.turn{min-width:44px;height:48px;padding:0 10px;border-radius:8px;
  border:1px solid var(--line);border-bottom:3px solid var(--line);
  background:var(--panel);color:var(--text);cursor:pointer;line-height:1.2}
.turn small{display:block;font-size:10px;color:var(--mute)}
.turn.win{border-bottom-color:var(--win)} .turn.loss{border-bottom-color:var(--loss)}
.turn.tie{border-bottom-color:var(--tie)}
.turn.sel{background:var(--sel);color:#14110c;border-color:var(--sel);font-weight:700}
.chip{padding:5px 10px;border-radius:14px;background:var(--card);
  border:1px solid var(--line);font-size:12px}
.item{padding:6px 8px;border-radius:6px;background:var(--card);
  border:1px solid var(--line);border-left:3px solid var(--tie);font-size:12px}
.item.kept{border-left-color:var(--win)} .item.sold{border-left-color:var(--loss)}
```

## 7. Accessibility

- Result and action kind are never color-only: markers on turns, letters on step ticks.
- Keep body and label text at 4.5:1 or better. `--mute` on `--panel` is roughly 6.5:1. **`--hp` on `--card` is borderline (about 4.5:1) at 15px bold; check it with a contrast tool and lighten `--hp` slightly if it fails.**
- Visible focus ring: 2px `--sel` outline with offset on all buttons.
- Click targets 44px minimum; the step ticks are 38px wide and acceptable only because they sit next to Prev/Next and keyboard control.
- Test against real card art. The palette was only checked against flat placeholder cards.

## 8. Data needed

| Need | Status |
|---|---|
| Opened/ended boards per turn; actions (buy, sell, roll, level); gold and spent; board stat total; next-fight HP; coaching and worth-a-look flags | Already shown in the current viewer |
| Turn result (win/loss/tie), minions left, HP taken | Result tab shows this today; needed per turn for the strip |
| Flipped minions (bought and sold in the same phase) | Derivable from the action list |
| Action counts and run-length collapsing | Derivable from the action list |
| **Board state after each action** | Unknown. Required for Step-through. If not reconstructable from the log, Step-through is the expensive feature. |
| Tavern offers at each step | Unknown. Nice to have in Step-through (shows what you rolled past). |
| Tribe and tier per card | Unknown. Would enable tribe pips and tier badges (optional). |
| Hero id | Needed only for optional hero-tinted accents |

## 9. Suggested build order

1. **Tokens and chrome.** Add the palette tokens and apply them to the existing viewer; split attack/health/buff colors.
2. **Single-turn layout.** Turn strip, one turn at a time, header, tabs, large cards.
3. **Summary rail.** Count header, collapsed groups, run-length collapsing, flipped detection, tray, net-change tags on Ended.
4. **Battle tab.** Face-off layout and result panel.
5. **Step-through mode**, if per-action board state is available.
6. **Optional polish.** Tribe/tier pips, board-strength sparkline above the turn strip, hero-tinted accent, keyboard shortcuts, deep links.

## 10. Open questions

- Can the board be reconstructed after each action today?
- Does the log record tavern offers (shop contents) per roll?
- Is "flipped" the right word, or is there existing terminology to reuse?
- How should a turn with 15+ different buys display (cap and "show all", or scroll within the rail)?
- Which keyboard shortcuts are already taken?
