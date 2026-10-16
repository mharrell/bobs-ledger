# Session 2026-10-15 — first macOS run, and the UI pass that followed

This was the project's first session on a Mac. It produced two things: the macOS
groundwork, and a run of UI calls from the maintainer looking at the page for the
first time on a laptop.

State at the end: **2156 tests green, `check_meta` OK (33 comps, 339 minions)**,
working tree clean, `main == origin/main` at `59b40c1`.

## Shipped, in order

| commit | what |
| --- | --- |
| `ceb75e7` | macOS install: platform marker, launcher, **the 10 MB log cap** |
| `914e12e` | exclude `dsh-usage-monitor` from the zip + gitignore |
| `b8d9364` | `Start Bob's Ledger.command` needs its executable bit (git mode 100755) |
| `914e149` | README rewritten for a new user; screenshots deleted |
| `5c56295` | the page's chrome wears the tavern palette |
| `b9b3d5d` | three columns fire at **1650px**, not 1800 |
| `532b98a` | the hand is one line of text, not card tiles |
| `586d867` | a community comp: two golden Tarecgosas |
| `95532b6` | Comps is the first section, and it is open |
| `59b40c1` | correction: what the open-by-default map can actually reach |

## macOS findings worth keeping

- **The 10 MB log cap** was real and is fixed by `client.config`
  (`Log.FileSizeLimit.Int=-1`). Verified empirically: a capped session ended at
  10,252,109 B with the banner; the next reached 10,793,450 B with none, still
  growing. `setup_logging.py --check` now reports cap state.
- **`.command` files need mode 100755 in git**, not just on disk — a fresh clone
  otherwise refuses to run them. `test_launcher_sh` pins the mode now.
- **`python3` on this Mac is 3.15 from python.org**, with no `requests` and, more
  importantly, **no CA trust store** (below). The project-local `.venv` is the
  supported path.
- The macOS session-directory shape was measured and written into
  `config.log_globs()`.

## UI calls made this session (all the maintainer's, dated in the code)

1. The **chrome** (`#freshness`, `#tabs`, `.s-head`) carries `.tavern` itself, so
   the top of the page matches the views under it. Scoped to those elements, NOT
   `#wrap`: the palette also carries `--tcardw`/`--tstepw`, and page-wide it
   handed sizes to containers that were `width:auto` — the layout tests caught it
   (1356px box → 1332).
2. **Three columns at 1650px.** A maximised 16" MacBook Pro measures ~1728px of
   viewport, so the old 1800 **never fired on the machine it was read on**. 1650
   is the floor, not a rounder number: the tavern box reaches `#wrap`'s 1600px cap
   at about 1640px of window, so below it the columns would get less than the
   622|622|300 they were measured at.
3. **The hand is one line.** "People don't need to see what's in the tavern or in
   their hand — they can just look at the screen." The hand was the clearest case:
   the game draws it better and it cannot be stale.
4. **Comps first and open** — it was fourth of five *and* shut in the accordion.
5. **A correction**: `LIVE_OPEN_BY_DEFAULT` is read by the **accordion only**.
   `lvSection` returns at `if (!acc) return p` before consulting `lvCollapsed`, so
   the wide arrangement has no collapse path at all. The commit that added Comps
   claimed otherwise; `59b40c1` fixes the record. **Any layout change must be
   checked in both arrangements — and for collapse/order the wide one is usually a
   no-op by construction, which is worth verifying rather than assuming.**

## Open, with the detail needed to resume

### 1. The macOS TLS gap (do this first — it is small and self-contained)

Every network call is a bare `urllib.request.urlopen(...)` and **nothing in the
codebase knows about `certifi`**. python.org's macOS installer never wires up a
trust store, so every HTTPS call fails:

```
URLError: [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```

It is not just sharing: `share.py`, `update.py`, `fetch_art.py`, `fetch_sessions.py`,
`upload_corpus.py` and `coach_ui`'s art fetches all fail the same way. On Windows
this never surfaced.

`certifi` is already installed (a `requests` dependency), so the fix is one line
at startup:

```python
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
```

That repairs every `urlopen` in the process. Add a test that a context loads, and
a `DESIGN.md` note — this is the third macOS-specific gap after the launcher
permissions and the log cap. The workarounds for a user today are
`/Applications/Python 3.15/Install Certificates.command` or exporting
`SSL_CERT_FILE` to `.venv/lib/python3.15/site-packages/certifi/cacert.pem`.

### 2. The tavern rows (the maintainer's live call, discussed not built)

The proposal: **invert the emphasis** — lead each offer row with the computed
facts (price, pool count, comp role, value), demote or drop the art, and **keep
the game's offer order**, which is the mapping aid that lets you match row three to
the third card. The tavern's identity is redundant; its *numbers* are the product.

**Decided:** `meta_tier: "B"` on the new comp is fine as-is.
**Open:** whether the **board** is in scope, and what "deprioritise" would mean
there (its per-minion values are the core of the product, so it is a different
question from the hand).

**Safe option, verified this session:** the tavern could be shut by default in the
accordion. Because the default map is accordion-only, that shortens the narrow
view and **cannot touch the wide one**.

### 3. Smaller items

- **Karazhan Chessboard** is missing from `trinkets.json` (246 entries, both it and
  `trinket_effects.json`). It is named in the new comp's prose but has no id, so it
  cannot be shown as a trinket. Waiting on an id.
- **`DESIGN.md` is wrong about images**: it says the GUI model does not accept
  them. It does — a screenshot was read directly this session.
- **Screenshots**: `docs/` is deleted and the guard fails if `docs/` or an `<img>`
  returns, with a note to restore the two-way check when the new set lands. The
  **narrow** live-page shot needs re-taking after the Comps move; the wide one is
  unchanged by it.
- **Comps sourcing**: Firestone is a client-side app (nothing to fetch);
  nomi.gg is also client-side but its data is **static assets** (`/assets/cards.js`)
  and it is open source (`RainWritesCode/NomisKitchenHDT`) — and its "Patch
  analysis" is a better fit for **patch-day cross-checking** (`check_patch_db.py`)
  than for comps. Neither was pursued.

### 4. Releasing — blocked, and one thing not to do

`publish_release.py --dry-run` passes the privacy and reproducibility gates; only
the signing gate fails. **The release key is on the other PC** — wait for it.

**Do not run `release_sig.py --keygen` for a publish key.** The public key is
pinned in `release_sig.py` as `PUBKEY_B64`, so a new key signs releases every
existing install refuses. If the key file cannot be found, that is a decision
(rotate the pin and strand current installs, or migrate), not a command.

Cloudflare (`npx wrangler`) and `gh` auth are also needed, or `--no-github`.

## Comps: what was learned about the pipeline

The one comp added this session is `dragons-golden-tarecgosa` — from a posted
screenshot of another player's 1st-place warband. Facts recorded, wording our own,
`source` crediting the origin: the same line the project drew after rewriting
hsreplay's guide text.

Two things worth carrying forward:

- **Hand-curated comps are already protected from `--prune`.** `prune_unlisted`
  keeps anything whose `source` does not name this scraper. No new guard was
  needed; the only work was the pinned expected-list in the one test that prunes
  the real file (two fixture tests above it are red herrings).
- **The DB rots by omission, and omission is measurable.** `logquery.py
  unresolved` lists card ids in a game that no meta DB knows. It reported **0**
  for the only game available, because the game holding the missing trinket was
  not among the two games logged. Both this and `comp_miner.py` (8 games scanned,
  `min_games` 5) need **volume**: turn on **Save every replay automatically** and
  let the corpus accumulate, and the audit starts finding gaps on its own.
