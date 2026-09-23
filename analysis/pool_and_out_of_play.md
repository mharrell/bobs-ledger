# The current card pool and the out-of-play registry

Design + evidence for the two databases added for patch **36.6.1**
(2026-09-22): a log-mined **current card pool**, and an **out-of-play
registry** the coach enforces. Written the day the patch landed, from the
games played on it.

The problem this solves is not "the meta DB is stale". It is that the DB had
**no concept of a card leaving**. `meta/minions.json` is a hand-refreshed
snapshot of what was in play when someone last pasted a page; nothing recorded
what had been removed, so a removed card stayed recommendable forever, and a
rotated-out tribe stayed buildable forever. 36.6.1 made both concrete: a new
minion type arrived (Aberrations — the first tribe ever *added*) and Naga was
rotated **out** of the pool.

## 1. What the game tells us for free

Every Battlegrounds game begins by dumping its minion pool. Each in-pool minion
is created as a `FULL_ENTITY` block:

```
FULL_ENTITY - Creating ID=331 CardID=BG36_110
    tag=CARDTYPE value=MINION
    tag=TECH_LEVEL value=1          <- the tavern tier
    tag=ATK value=2 / tag=HEALTH value=3
    tag=CARDRACE value=ABERRATION   <- one per tribe; compounds print several
    tag=IS_BACON_POOL_MINION value=1
    tag=BACON_SUBSET_ABERRATION value=1
```

So the authoritative pool — card ids, names, tiers, stats, tribes, and pool
membership — is already on disk, offline, with no paste, no Cloudflare and no
hearthstonejson lag. `pool_roster.py` reads it (mirroring the proven run-walk in
`bans.bans_from_log`) and writes `meta/pool_roster.json`.

Three details earned by getting it wrong first:

- **`CARDTYPE value=MINION` is required.** `IS_BACON_POOL_MINION` also rides on
  tokens and enchantments the pool machinery creates (`BG34_170e Volumized`,
  `BG31_890t Way of the Mage`). Without the filter the roster grew 19 "tier 0"
  minions that do not exist.
- **`tag=TECH_LEVEL` is the tavern tier** (`BGS_004` Wrath Weaver = 1), and the
  first *unbuffed* definition must win — a later board copy with combat buffs
  otherwise overwrote base stats.
- **`entityName=` carries spaces** (`Wrath Weaver`), so a naive `\S+` capture
  silently truncates most names. Names arrive on later `TAG_CHANGE` lines, not
  in the creation block.

## 2. Patch boundaries are content, not build number

`BuildNumber=251952` appears in the logs **before and after** 36.6.1 — the
client didn't change; the patch was server-side content enablement. So the
patch boundary has to be read from content. `pool_roster.current_epoch()`
defines the newest session's *signature* (cards and pure pool tribes it has that
no older session has; for 36.6.1 that was 44 cards + the `Aberration` tribe) and
sweeps in every session holding a signature element.

Measured across the five sessions on disk:

| Session | Games | Pool cards | `ABERRATION` CARDRACE lines |
|---|---|---|---|
| 09-21 10:33 | 2 | 201 | 0 |
| 09-21 12:14 | 1 | 101 | 0 |
| 09-21 20:40 | 3 | 172 | 0 |
| 09-22 07:40 | 4 | 191 | 0 |
| **09-22 20:59** | **3** | **181** | **2298** |

The evening session is the epoch: **181 pool minions, including all 20
Aberration cards**, with Naga holding no pure pool card at all.

### The empty-signature case is deliberately conservative

If the newest session introduces nothing new, no boundary is detectable, and
two very different worlds look identical from the pool alone: (a) the same
generation, where unioning older sessions only widens coverage, or (b) a
**removal-only** patch, where unioning older sessions would resurrect every
removed card as "current". Only (b) is harmful, so the empty signature resolves
to the newest session alone. Widening is explicit: `--sessions N`, which
**refuses to write** when the union pulls an out-of-play card back in. On the
real data a 3-session union drags back 22 removed cards and is correctly
refused.

### Coverage caveat

Each game puts only **5 of the ~10 tribes** in the pool, so one session observes
only the tribes its lobbies rolled. A tribe missing from the roster is
*untested*, not *absent* — absence must come from the patch notes. The current
roster shows Murloc and Naga as unobserved for exactly this reason (Naga's
absence is independently confirmed by the official rotation).

## 3. The out-of-play registry

`meta/out_of_play.json`: 36.6.1 rotated Naga out of the pool, removed **35
minions**, 2 tavern spells and 6 trinkets. Each entry carries a `reason`, the
`patch` and `date`, and the document keeps a `history` block (including the 25
returning minions) so a card that rotates back can be re-enabled with its reason
on record.

**It is validated against the log, not trusted.** Cross-checking the official
removal list against the mined pools:

- all **35/35** removed minions are **absent** from the post-patch pool;
- **33/35** were present in a pre-patch pool (the other two simply never rolled
  into a lobby's 5 tribes — the coverage caveat again, not a contradiction).

`playable.py` owns enforcement. `validate()` re-runs that cross-check and
reports disagreements instead of hiding them, because a disagreement is
information: the official list may be wrong, the roster may be under-covered, or
a card name may have been reused.

### The load-bearing rule: out only when EVERY tribe is out

A card is out of play by tribe only when **all** of its tribes are out. This is
log-verified, not inferred: post-rotation, a game whose allowed tribes included
Demon still had **`BG31_330 Ominous Seer`** — a Demon/Naga compound — sitting in
its pool. Naga-only cards are gone; Naga-*touched* cards are not.

Getting this wrong cuts both ways, and both were live bugs during this work:
treating a compound as out because one part is Naga would drop a buyable card,
and reading "Naga" from a log's partial reveal would claim a pure Naga card sat
in a pool Naga had left. The second is real: a compound's creation block can
print **one** of its races (Ominous Seer prints `NAGA` alone), which is why
`pool_roster.enrich_from_meta()` unions the log's races with the curated meta
DB's tribe — exactly the union semantics `parse_minions.refresh_tribes` already
used, for the same reason.

Amalgams are the third trap: a card that counts as every tribe must stay the
`All` marker and never be expanded into a compound list, or it silently stops
matching every tribe-fit term in `value.py`.

## 4. Enforcement, and its kill switch

`bans.filter_comps_by_available_tribes` now also drops out-of-play comps — it is
the single funnel both `coach.py` and `live_coach.py` use, so both are covered
by one change. The two Naga comps are gone (24 → 22 playable). The per-game ban
answer ("unplayable in *this* game") and the patch answer ("doesn't exist any
more") are deliberately different layers with different weights:
`value.W_OUT_OF_PLAY = 8.0` against the banned-tribe `-2.0`.

`HEARTH_OUT_OF_PLAY=0` disables enforcement. That is not a debugging nicety:
`replay_review.py` replays an **old** log through the **current** meta, and a
pre-rotation game legitimately contains Naga shops and Naga comps. Judging that
game against today's list would report phantom "coach bugs".

## 5. The other bug this uncovered

The patch-refresh mechanism had been **dead since 2026-09-05** and nobody could
have noticed from the DB alone: commit `6264486` replaced `import requests` with
`import coach_llm` while the fetch functions kept calling `requests.get`, so
every fetch raised `NameError` — including the weekly scheduled
`check_patch_notes.py` task. A second, silent bug sat behind it:
`html_to_text()` rendered both `<h2>` and `<h3>` as `"## "`, and
`extract_bg_section()` stopped at the next `"## "`, so any Battlegrounds section
with sub-headings collapsed to its intro paragraph. The real 36.6 notes page
extracted to **92 characters**; it is **1169** now. Even a working fetch could
never have seen a card list. Both are fixed and regression-tested.

## 6. What is still missing (deliberately)

> Updated 2026-09-22 (same day), after the follow-up work. Two of the gaps below
> are now closed and are kept here with the resolution so the record shows what
> changed and why; the rest stand.

- **No Aberration comps.** `meta/comps.json` has none, and inventing them from
  a one-day-old patch would be exactly the "checklist comp from turn 1" habit
  Shadybunny warns about. The coach can now *see* Aberration cards (tribe,
  tier, stats) but has no comp to build toward; comps should come from observed
  play over the next days, not from this document. **Still open.**
- **The Deity mechanic — implemented, NOT yet in main.** Branch
  `worktree-discard-engine` adds an `aberrations-discard-deity` engine to
  `meta/engines.json` (trigger `discard`) and a comp-independent detector in
  `value.py` alongside `_spell_fuel_bonus`, with `analysis/discard_mechanic.md`
  and tests. Named here as a branch, not a commit, because **if it is not in
  main it is not done** — flip this line when it lands. The discarded rate is
  modeled, not measured, and the Deity half is grounded in the only log state
  that exists for it (`BACON_DEITY_SIGIL` on the `BG_OldGod` "Secret Deity
  [DNT]" entity, re-created per combat). Note the mechanic has **no discard event
  in the log at all**: the only tag is `CANT_DISCARD`, and `hand -> GRAVEYARD`
  cannot separate a discard from casting a spell (in the Faelin win, all three
  hand-to-graveyard cards were spells the player *cast*).
- **Two cards a `no carddef` boundary, not an oversight:** `BGFYM_005` and
  `BGFYM_011` (the Y'Shaarj family) have **no card definition in the installed
  client**, so no art can be extracted for them; `BG30_MagicItem_4262`
  (Colorful Compass) has no portrait under its base id because its 10 tribe
  variants share one id, so the overlay cannot resolve art for it and falls back
  to the placeholder. Both were confirmed by asking the running overlay for the
  image, not by inspecting paths.
- **Four patch-named minions exist with no card id anywhere on this machine** —
  C'Thun, Sha of Fear, Greedy Conniver, Sewer Escapee. Recorded with evidence in
  `meta/patch_gaps.json` so `check_patch_db.py` reports them as *accepted* gaps
  while still failing on a new one. An id-less row is not an option:
  `value._buy_prices` indexes by id and `None + "_G"` raises.
- **`Dark Paradox`'s minion type is never stated** in the article (its image
  code is `NEUTRAL_BG36_360`, and it mentions neither a Deity nor discarding),
  and it did not appear in the three mined games. The log settles it as an
  **All-type (Amalgam-class)** minion, so this is now resolved by observation
  rather than left to the prose.
- **`Oozeling Gladiator` is listed twice by the article** — "now an Aberration"
  *and* "Removed". The log settles it: `BG27_002` is absent from the post-patch
  pool, so the registry treats it as removed. If a distinct Aberration version
  exists under another id, it will appear in a future roster and the
  `validate()` cross-check will surface it.
- **Duos is out of scope on purpose.** The patch also changed 2 Duos-only
  minions and added 2 more. The coach coaches *solo* Battlegrounds, and a
  Duos-only row in the solo DB could be recommended in a solo shop where it can
  never appear. Recorded in `meta/patch_gaps.json` under `out_of_scope` rather
  than dropped silently.
- **Naga-specific heroes are not enumerated** anywhere official, so
  `out_of_play.heroes` is empty on purpose. The hero/tribe restrictions that
  *were* published (7 heroes banned from Aberrations, 4 of them Y'Shaarj-only)
  are recorded under `hero_constraints` for the pick ranker.


## 7. How to refresh on the next patch

```
cd hearth-coach
python check_patch_notes.py --no-notify          # detect + report (never edits)
python patch_notes.py <url>                      # dry-run the balance changes
python patch_notes.py <url> --apply              # apply them
python pool_roster.py                            # mine the new epoch (dry run)
python pool_roster.py --apply --patch <version>  # write meta/pool_roster.json
# hand-edit meta/out_of_play.json from the official notes (tribes + card lists)
python playable.py                               # registry vs roster: must be 0
python check_patch_db.py                         # change list vs DB: must be 0 gaps
python refresh_trinkets.py                       # regenerate, then curate its list
python hearth_art_extract.py                     # new card art from the client
python check_meta.py && python -m unittest discover -s tests
```

Three of those are gates, not just reports, and each one caught something real
the first time it ran on 36.6.1:

- **`playable.py`** — the official removal list vs the observed pool. A non-empty
  conflict list means they disagree and a human decides which is wrong.
- **`check_patch_db.py`** — the change list vs the meta DB. Every name the patch
  labels must be reflected (present, or in the registry) or be recorded in
  `meta/patch_gaps.json` with a reason AND the evidence that closed it. This is
  the one that proved the non-Aberration lists were covered while finding the
  one returning spell that was missing, and it now self-checks by comparing each
  section's parsed count against the count the heading claims — because its first
  version silently audited 34 of 35 removed minions.
- **`refresh_trinkets.py`** — the trinket ids offered in local logs must all be
  in the DB, and the trinket `<->` effects join must stay bidirectional. It had
  simply not been run since 2026-09-13, which is what the "missing trinkets"
  failure actually was both times it appeared.

After `hearth_art_extract.py`, check coverage rather than assuming it: on 36.6.1
it went from 0/25 Aberration minions to 24/25 and 83/191 trinkets to 181/191, and
the stragglers were `no carddef` in the client rather than extraction failures.
The cheapest way to confirm the overlay actually serves an id is to ask it —
start `coach_ui.start_server(port)` and GET `/img/<id>.png`.

