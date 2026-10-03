---
name: hearth-patch-notes
description: Refresh the Hearthstone coach's point-in-time meta DB from official Blizzard patch notes. Use when applying a new patch to the meta JSON files, running the patch-notes pipeline (patch_notes.py / check_patch_notes.py), reviewing a detected patch report, or registering the weekly scheduled check.
---

# Hearthstone Patch Notes → Meta DB

The meta DB is **point-in-time** (see `DESIGN.md` section 6). This is
the "refresh on patches" mechanism: it turns official Blizzard patch-notes prose
into structured before/after changes and matches them against the meta JSON files
in `meta/`.

## The three pieces

| File | Role |
|------|------|
| `patch_notes.py` | Core tool: fetch → isolate Battlegrounds section → LLM → structured changes → match → apply. **Dry-run by default**; `--apply` writes. |
| `check_patch_notes.py` | Scheduled, **review-first** entry point: detects a new patch, writes a report to `patch_reports/`, shows a Windows toast. Never edits the DB. |
| `register_patch_check.ps1` | Registers a weekly Windows Task Scheduler task that runs `check_patch_notes.py`. |

## Pipeline (what `patch_notes.py` does)

1. **Fetch** the patch-notes page (or `discover_latest()` finds the newest
   "Patch Notes" article from the Blizzard news page's `stickyBlogList`).
2. **Isolate** the `## Battlegrounds` section (until the next same-level heading).
3. **LLM extract** — DeepSeek (`deepseek-v4-flash`, temperature 0) turns the prose
   into a JSON array of `{entity_type, name, field, old, new, note}`.
4. **Match** each change against the meta files by normalized name.
5. **Apply** (only with `--apply`) writes matched changes back; otherwise it's a
   dry-run report for human review.

## Entity types → meta files

`ENTITY_FILES` in `patch_notes.py` maps each entity type to its JSON file and a
field-alias table (LLM field names → actual JSON keys):

| entity_type | meta file | notable fields |
|---|---|---|
| `minion` | `minions.json` | attack, health, cost, tier, tribe, text |
| `hero` | `heroes.json` | hero_power, pick_rate |
| `trinket` | `trinkets.json` | description, pick_rate, avg_placement |
| `tavern_spell` | `tavern_spells.json` | cost, tier, text |
| `dark_gift` | `dark_gifts.json` | description |
| `card` | `cards.json` | atk, health, tier, tribe |
| `comp` | `comps.json` | meta_tier, difficulty |

`field: "removed"` marks a card removed from the pool (deletes the entity).

## Workflows

### Manual apply (the normal path)

```powershell
# 1. Dry-run against a specific patch, or auto-discover the latest:
python patch_notes.py <url>            # or: python patch_notes.py
# 2. Review the printed changes (status: applied / unmatched / removed / skip).
# 3. When it looks right, write them:
python patch_notes.py <url> --apply
```

### Scheduled check (set-and-forget, review-first)

```powershell
# Register a weekly task (default: Mondays 09:00):
powershell -ExecutionPolicy Bypass -File register_patch_check.ps1
# Test it now:
Start-ScheduledTask -TaskName 'HearthCoachPatchCheck'
```

The task runs `check_patch_notes.py`, which:
- skips if the patch id matches `meta/.patch_state.json` (each patch reported once),
- writes a reviewable report to `patch_reports/<slug>.md`,
- shows a Windows toast (suppress with `--no-notify`),
- **never edits the meta DB** — you review the report and apply with
  `patch_notes.py <url> --apply`.

## Key behaviors & caveats

- **Names, not IDs.** Patch notes give card/hero *names* but not internal card
  IDs, so **brand-new cards are reported as `unmatched` for manual entry** — never
  auto-inserted. That's by design.
- **Review-first discipline.** The scheduled task only writes a report; applying
  is always a human decision. `--apply` is the only thing that edits `meta/`.
- **API key.** Read from `DEEPSEEK_API_KEY`, falling back to
  `meta/.patch_config.json` `{"api_key": "..."}`. Without a key (or with
  `--no-llm`), the script just prints/captures the Battlegrounds section for
  manual review.
- **Type coercion.** `coerce()` casts the LLM's string value to the type of the
  existing DB value (int/float/str), so `"5"` → `5` where the field is numeric.
- **LLM output tolerance.** `parse_json_array()` tolerates prose around the JSON
  array; extraction is temperature 0 for determinism.

## Verification

After an `--apply`, confirm the meta files changed as expected:

```powershell
git diff --stat meta/
git diff meta/minions.json   # spot-check a known change
```

And re-run the coach to confirm nothing broke:

```powershell
python coach.py <Power.log> 1
```
