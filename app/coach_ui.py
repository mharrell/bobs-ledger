#!/usr/bin/env python3
"""V1 coaching UI: a local overlay served over HTTP.

Runs a tiny stdlib HTTP server (no dependencies). `live.py` pushes the latest
situation analysis here each buy phase; the server exposes it as JSON at
`/analysis` (ETag/304 — the page polls at 300ms and unchanged pushes cost a
header) and serves a static HTML/CSS/JS page at `/`.
Layout (2026-09-24 rework): two panes on a wide window — DECIDE (the state
strip, the Situation panel — the model's read of the game, the danger band, a
pending pick's options — Your hand, Hand engine) sticky and never scrolled
away; REFERENCE (Next opponent, Your board, Comp pieces, Comp direction
meters, Lobby pressure, Tavern, Playable comps) scrolls. Below ~1200px the
original single priority column returns, decide first. Colors come from the
token block at the top of the stylesheet (a test fails on hex drift); severity
uses the status palette with a mark and a word, never color alone.
**This page shows STATE, never a verdict** (2026-10-06, PIVOT.md): the panel
that used to say "Do this now" and the tavern row that used to be ranked
best-first are the two visible ends of it, and render_json's
LIVE_VERDICT_KEYS is the mechanism. The model's plan is still computed and
still recorded — it is shown after the game, in the review, where the decision
it describes cannot be acted on.
Design: analysis/DESIGN_COACHING_UI.md. Tile names carry a '*N' tavern-tier
badge (2026-09-09); hovering a tile shows the full card render — framed
layout WITH text (img_cache/card/, fetched on demand) — or, when upstream
has no render, the card text from the meta DBs. The "Playable comps" panel
groups the playable comps by meta tier; clicking a comp expands its required
cards (owned faded, banned struck out), clicking again collapses it
(expansion state survives the rebuilds).

Usage:
    python coach_ui.py [--port=N]     # run the server standalone (empty state)
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.request
from functools import lru_cache
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from value import (_load_bg_names, _load_card_db, _load_spell_db,
                   DYING_HEALTH, SELL_FILLER_SCORE,
                   HAND_DEPLOY_KITS, hand_engine, sell_reason)
# The module itself, for the serve-time name join in _name_timeline_boards —
# the `from ... import` above brings the names it uses live, not the module.
import value
import pool
import meta
import choices
import config
import replay_store
import settle_up

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 8747

#: Fields the LIVE overlay never receives (2026-10-06, PIVOT.md).
#:
#: The live path ships STATE; the verdict ships after the fact, in the review
#: built from `decision_logs/` — where the decision it describes can no longer
#: be acted on. render_json() is the ONE place the page's view is built, so
#: this is the one place the split has to hold: `value.top_move` keeps
#: computing all of it, `decision_log.record()` keeps receiving ALL of it (the
#: review and the corpus need it, and the analysis never leaves the machine),
#: and the page gets what is left after these are dropped.
#:
#: Why drop rather than stop computing: the numbering, the ordering and the
#: "Buy X" verb are the part that reads as an instruction, and they are exactly
#: what a review needs in order to compare the player's line against the
#: model's. Deleting the producers would delete the product's one real asset —
#: PIVOT.md §3. Dropped rather than never-computed so nothing downstream can
#: quietly reintroduce a key: `test_live_view.py` asserts each name here is
#: ABSENT from the rendered payload and PRESENT in the analysis it came from.
LIVE_VERDICT_KEYS = frozenset({
    "top_move",            # the numbered plan, as text
    "top_move_steps",      # ... and its structured steps (kind/action/reason)
    "buy_this",            # the headline card the plan picked
    "buy_step_card",       # the same pick, rewritten by the slot arbiter
    "buy_step_roll",       # "roll instead" — the plan's other outcome
    "buy_step_swap_veto",  # "not worth a board slot" — a verdict about a card
    "buy_roll_text",       # the Buy box's copy of the roll step
    "discard_target",      # which card the plan wants fed to a discard outlet
    "hand_plan",           # the hand's ordered plan (the `hand` rows carry it)
    "hunt_targets",        # "go find these" — a shopping list, not a state
    "target_state",        # "pivot" / "committing" — a directive about direction
})

# On-demand card art: TWO kinds of image, so TWO sources (probed 2026-10-04,
# per id class — see PORTRAIT_URLS/CARD_URLS below).
#
# The single /v1/render/... URL this used to fetch from 404s EVERY
# current-patch Battlegrounds card: minions, tavern spells, trinkets and
# tokens. A fresh install therefore drew placeholders for most of the board
# while the maintainer's checkout looked fine, because its art had arrived
# through a different door — hearth_art_extract.py pulling portraits out of
# the local game client, which no player has. Nothing here may assume that
# door: the tiles and the tooltip must be reachable from the CDN alone.
#
#   portrait  the square raw art the 56x56 tile shows and its 4.5x hover zoom
#             enlarges. /v1/orig/ answers for EVERY id class that has art at
#             all (minions, spells, trinkets, tokens, heroes, golden `_G`),
#             so one URL suffices.
#   render    the framed card WITH name/text for the hover tooltip, 256x388.
#             /v1/bgs/... is the Battlegrounds render — it covers the current
#             patch but 404s heroes and `_G` — while /v1/render/... covers
#             exactly the other way round (returning ids, heroes, golden).
#             Two sources that each 404 half the catalogue is why this is a
#             CHAIN rather than a URL.
PORTRAIT_URLS = ("https://art.hearthstonejson.com/v1/orig/{}.png",)
CARD_URLS = (
    "https://art.hearthstonejson.com/v1/bgs/latest/enUS/256x/{}.png",
    "https://art.hearthstonejson.com/v1/render/latest/enUS/256x/{}.png",
)
#: The generic (non-Battlegrounds) render, kept named so the chain's second
#: source is greppable from the tools that reason about it.
RENDER_URL = CARD_URLS[1]
MISS_TTL = 3600.0       # upstream HAS no art for this id — stop asking
SOFT_MISS_TTL = 120.0   # we could not REACH upstream — ask again soon
#: 256x512 raw art is 150-360KB; 5s was tight enough that a slow first paint
#: counted as a miss for an hour (see SOFT_MISS_TTL for why that no longer
#: costs an hour either).
ART_TIMEOUT = 10
# A bare "Mozilla/5.0" now gets 403 from the art CDN (2026-09-09 probe) —
# the on-demand fetches need a plausible full browser User-Agent.
RENDER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Full-card renders (framed layout WITH name/text, unlike img_cache root's
# raw portraits) for the hover tooltip, kept in their own subdir so the two art
# kinds don't get confused. The kinds no longer share a source, so they no
# longer share a miss list either: a card missing from one says nothing about
# the other (see _art_miss_card). Both it and ART_CACHE are resolved below,
# once, by resolve_art_cache() — it is the install's cache unless the install
# folder cannot be written to.
_art_lock = threading.Lock()
_art_miss_path = os.path.join(_HERE, ".art_miss.json")


def ensure_dir(path):
    """True if path is a directory afterwards, False if it cannot be made.

    A read-only install folder — unzipped into the system programs
    directory, or a managed / one-way-synced folder — refuses the create
    outright, and
    Windows offers no elevation prompt for it. An unguarded makedirs here
    therefore killed the coach at import with a bare PermissionError
    traceback (WinError 5, reproduced 2026-10-02) before a single piece of
    advice could be shown. Card art is optional; that crash was not.
    """
    try:
        os.makedirs(path, exist_ok=True)
        return os.path.isdir(path)
    except OSError:
        return False


def user_cache_root(env=None, home=None, platform=None):
    """The per-user cache directory to fall back to when the install is
    read-only: %LOCALAPPDATA%\\bobs-ledger on Windows, ~/Library/Caches on
    macOS, $XDG_CACHE_HOME or ~/.cache elsewhere.

    Written as a function of `env`/`home`/`platform` rather than reading the
    globals, so the choice is testable on any machine instead of only the one
    whose layout happens to be under test.
    """
    env = os.environ if env is None else env
    home = home if home is not None else os.path.expanduser("~")
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        base = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    else:
        base = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "bobs-ledger")


def resolve_art_cache(install_dir, fallback=None):
    """Where this install keeps card art: (root, card_dir, ok, source).

    `img_cache/` in the install folder is what the maintainer, the extractor
    and doctor's art check all mean by "the cache", so it stays the first
    choice. A player who unzipped into the system programs directory, or into
    a managed / one-way-synced folder, cannot write there — Windows offers no
    elevation prompt, so every write is simply refused.

    Until now that meant giving up on art entirely and silently: `/img`
    answered 404 for every card and the page drew placeholders that look
    exactly like a card upstream does not have (reproduced 2026-10-04 — the
    same face as the CDN bug, so nobody could tell them apart). Falling back
    to a per-user directory means such an install still gets art; only a
    machine with no writable location at all runs art-free, and then the note
    says so.

    `fallback` is the exact directory to use as the cache root when the
    install's own is unusable (tests pass one; production leaves it None and
    gets `<user cache>/img_cache`).
    """
    install_root = os.path.join(install_dir, "img_cache")
    if ensure_dir(install_root) and ensure_dir(os.path.join(install_root, "card")):
        return install_root, os.path.join(install_root, "card"), True, "install"
    root = fallback if fallback is not None else os.path.join(
        user_cache_root(), "img_cache")
    if ensure_dir(root) and ensure_dir(os.path.join(root, "card")):
        return root, os.path.join(root, "card"), True, "user"
    return install_root, os.path.join(install_root, "card"), False, "none"


ART_CACHE, CARD_DIR, ART_CACHE_OK, ART_CACHE_SOURCE = resolve_art_cache(_HERE)
if not ART_CACHE_OK:
    print(f"Note: cannot write the card art cache at {ART_CACHE}, nor a "
          f"per-user one.\n"
          f"      The coach runs without card art; everything else works.\n"
          f"      Unzip it somewhere writable (Desktop or Documents) for\n"
          f"      the full overlay.")
elif ART_CACHE_SOURCE == "user":
    print(f"Note: {_HERE} is not writable, so card art is kept in\n"
          f"      {ART_CACHE}\n"
          f"      instead. Everything else works normally.")
# The miss list rides with the cache when the cache had to move: in a
# read-only install the write was refused silently, so the same 404s were
# re-attempted after every restart.
if ART_CACHE_SOURCE == "user" and ART_CACHE_OK:
    _art_miss_path = os.path.join(ART_CACHE, ".art_miss.json")
try:
    with open(_art_miss_path, encoding="utf-8") as _f:
        _art_miss = json.load(_f)
except (OSError, ValueError):
    _art_miss = {}


_miss_last_write = [0.0]  # last on-disk flush of the miss list (rate-limit)

#: Transport failures (timeout, DNS, refused), kept OUT of `_art_miss`: a card
#: upstream really does not have and a card we merely failed to reach are
#: different answers, and conflating them meant one slow first paint drew a
#: placeholder for an hour for a card whose art was sitting right there.
_art_soft = {}

#: Tooltip-render misses, kept apart from portrait misses because the two
#: endpoints read different sources (`CARD_URLS` vs `PORTRAIT_URLS`).
_art_miss_card = {}

#: Ids with a download in flight. The page polls every 300ms and rebuilds its
#: DOM, so a 150-360KB portrait that takes a second would otherwise be asked
#: for — and downloaded — several times over (worst on a fresh install's first
#: board, where every tile is a miss at once). ThreadingHTTPServer gives each
#: request its own thread, so this guard is what keeps it to one download.
_art_inflight = set()


def _remember_miss(cid, hard=True, card=False):
    """Note that cid has no art (hard) or could not be reached (soft).

    Only a hard miss for the PORTRAIT is persisted to `.art_miss.json`: that
    file is the client's placeholder list (GET /artmiss), and a soft miss must
    not land on it or the page would placeholder a card that may well load on
    the next poll. The card-render list is deliberately in-memory — it feeds
    one hover endpoint, so crash recovery buys nothing.
    """
    with _art_lock:
        now = time.time()
        if not hard:
            _art_soft[cid] = now
            return
        misses = _art_miss_card if card else _art_miss
        misses[cid] = now
        # Prune entries already dead to _can_retry — the file used to grow
        # without bound (502 ids and counting). The in-memory dict is the
        # gate; the disk write is only crash recovery, so it is rate-limited
        # (it used to rewrite the whole file on every miss).
        for c in [c for c, t in misses.items() if now - t > MISS_TTL]:
            del misses[c]
        if card:
            return
        if now - _miss_last_write[0] >= 30.0:
            _miss_last_write[0] = now
            try:
                with open(_art_miss_path, "w", encoding="utf-8") as f:
                    json.dump(_art_miss, f)
            except OSError:
                pass


def _active_misses():
    """Card ids that would 404 RIGHT NOW — fresh on the miss list AND with
    no art file on disk. Served once at GET /artmiss so the page renders
    placeholder tiles with no 404 round-trip per tile per rebuild.

    The file-exists check is not optional: the miss list goes stale when art
    arrives by another door (patch-day hearth_art_extract rewrites img_cache
    without touching this file — 434 of its 504 entries had files on disk on
    2026-09-24). The /img endpoint itself is immune (it stats the file
    first); only this list can lie, and the client trusts it."""
    with _art_lock:
        now = time.time()
        return sorted(
            c for c, t in _art_miss.items()
            if now - t <= MISS_TTL
            and not os.path.exists(
                os.path.join(ART_CACHE, f"{c}.png")))


def _can_retry(cid, card=False):
    """True when cid is worth another upstream request.

    Two clocks: a hard miss waits MISS_TTL, a transport failure only
    SOFT_MISS_TTL. The soft clock is shared by both endpoints — if upstream is
    unreachable, it is unreachable for the tooltip too.
    """
    now = time.time()
    if now - _art_soft.get(cid, 0) <= SOFT_MISS_TTL:
        return False
    misses = _art_miss_card if card else _art_miss
    return now - misses.get(cid, 0) > MISS_TTL


def _fetch_render(cid, dest_dir=None, urls=None, card=False):
    """Download cid's art into dest_dir (img_cache root by default).

    Walks `urls` in order, because one source does not cover the catalogue:
    a Battlegrounds card 404s on the generic render and a hero 404s on the
    Battlegrounds one, so the card chain tries both. True on success.

    A 404 from EVERY url means upstream has no art: that is a hard miss.
    Anything else (timeout, DNS, connection reset) is a soft one, so a flaky
    link costs a two-minute retry instead of an hour of placeholders. The
    browser re-requests images on every DOM rebuild, so both are remembered —
    repeated polls must not re-hammer upstream.
    """
    if dest_dir is None:
        if not ART_CACHE_OK:
            return False  # nowhere to put it — do not hammer upstream
        dest_dir = ART_CACHE
    if urls is None:
        urls = CARD_URLS if card else PORTRAIT_URLS
    with _art_lock:
        if cid in _art_inflight:
            return False  # another thread is already downloading it
        _art_inflight.add(cid)
    try:
        return _download(cid, dest_dir, urls, card)
    finally:
        with _art_lock:
            _art_inflight.discard(cid)


def _download(cid, dest_dir, urls, card):
    """The fetch itself — see _fetch_render for the contract and the guard."""
    saw_404 = False
    for url in urls:
        try:
            req = urllib.request.Request(url.format(cid),
                                         headers={"User-Agent": RENDER_UA})
            with urllib.request.urlopen(req, timeout=ART_TIMEOUT) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                saw_404 = True
                continue  # not at this source; the next one may have it
            _remember_miss(cid, hard=False)
            return False
        except Exception:
            _remember_miss(cid, hard=False)
            return False
        try:
            with open(os.path.join(dest_dir, f"{cid}.png"), "wb") as f:
                f.write(data)
        except OSError:
            return False  # nowhere to put it
        with _art_lock:
            if card:
                _art_miss_card.pop(cid, None)
            else:
                _art_miss.pop(cid, None)
            _art_soft.pop(cid, None)
        return True
    if saw_404:
        _remember_miss(cid, card=card)
    else:
        _remember_miss(cid, hard=False)  # empty chain — treat as unreachable
    return False

_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bob's Ledger</title>
<style>
  /* Design tokens — the ONLY place a raw hex may appear (a test parses this
     block and fails on hex drift anywhere else). Values from the validated
     dark-mode reference palette; status colors are for STATE, never
     decoration, and always ride a word or mark, never color alone. */
  :root {
    /* surfaces + ink */
    --bg:#0d0d0d;        /* page plane */
    --panel:#1a1a19;     /* box surface */
    --panel2:#242422;    /* raised surface: chips, placeholder thumbs, hover */
    --text:#ffffff;      /* primary ink: values, names, actions */
    --text-2:#c3c2b7;    /* secondary ink: why-lines, subs, body */
    --dim:#898781;       /* muted: labels, headers, de-emphasis */
    --border:rgba(255,255,255,.10);  --gridline:#2c2c2a;
    /* status */
    --good:#0ca30c;      /* favored / safe */
    --warn:#fab219;      /* fragile / out-of-play */
    --bad:#ec835a;       /* serious: behind, do-not-sell, banned */
    --critical:#d03b3b;  /* DYING only — 3.6:1, large marks never small text */
    /* coach identity: currency / commit */
    --gold:#ffd97a;
    /* Spell tag accent. The other three (--k-level, --k-cast, --k-sell) only
       ever colored plan-step chips and went with them (2026-10-06). */
    --k-spell:#7ab8f0;
    /* severity band tints; --crit-ink carries the dying band's body text */
    --warn-bg:rgba(250,178,25,.13);  --warn-border:rgba(250,178,25,.38);
    --crit-bg:rgba(208,59,59,.16);   --crit-border:rgba(208,59,59,.45);
    --crit-ink:#ffd7d7;
    --shadow:0 8px 24px rgba(0,0,0,.65);
    --radius:6px;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.45 "Segoe UI", system-ui, sans-serif; padding:8px; }
  #wrap { max-width:1600px; margin:0 auto; }
  /* State strip: stat tiles (muted label over a semibold value), then the
     chip row (triggers, bans, out-of-play, forecast). */
  #statebar { display:flex; align-items:center; gap:16px; flex-wrap:wrap;
              background:var(--panel); border:1px solid var(--border);
              border-radius:var(--radius); padding:6px 12px; margin-bottom:8px;
              font-size:14px; }
  #statebar .tile { display:inline-flex; flex-direction:column;
                    align-items:flex-start; line-height:1.25; }
  #statebar .lbl { color:var(--dim); font-weight:400; font-size:11px; }
  #statebar .val { font-weight:600; font-size:15px;
                   font-variant-numeric:tabular-nums; }
  #statebar .val.gold { color:var(--gold); }
  #statebar .val.warn { color:var(--warn); }
  /* DYING HP: --crit-ink, not --critical — critical is 3.6:1 on this
     surface, below large-text size at 15px. */
  #statebar .val.bad { color:var(--crit-ink); font-weight:700; }
  #statebar .good { color:var(--good); font-weight:600; font-size:12px; }
  #statebar .bad { color:var(--bad); font-weight:600; font-size:12px; }
  #statebar .banned { color:var(--text-2); font-weight:400; font-size:12px; }
  /* Out-of-play tribes (rotated by a patch: Naga since 36.6.1) are a THIRD
     state, not a ban — struck through and warn-colored so "Naga — out of
     play" never reads as "Naga was banned this game". */
  #statebar .oop { color:var(--warn); font-weight:400; font-size:12px;
                   text-decoration:line-through; }
  /* Ban picker (2026-09-19): tap the 5 banned tribes from the reveal
     screen — the log never carries the ban list, the inference takes
     minutes, a manual set is exact from turn 1. */
  .banchips { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
  .banchips .chip { border:1px solid var(--border); border-radius:12px;
                    padding:2px 10px; font-size:12px; cursor:pointer;
                    color:var(--dim); user-select:none; }
  .banchips .chip.picked { border-color:var(--bad); color:var(--bad);
                           text-decoration:line-through; }
  /* Two panes on a wide window: DECIDE (the turn's decision — never
     needs scrolling, sticky) and REFERENCE (scout intel + shopping
     lists, scrolls). Under 1200px — or a very short window, where a
     sticky column taller than the viewport would trap its bottom —
     they stack into the original single priority column, decide first.
     NEVER set overflow on a pane: it clips the 4.5x hover zoom. */
  #app { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr);
         gap:8px; align-items:start; }
  #app > section { display:flex; flex-direction:column; gap:8px;
                   min-width:0; }
  #col-decide { position:sticky; top:8px; }
  @media (max-width:1199.98px), (max-height:899px) {
    #app { display:flex; flex-direction:column; }
    #col-decide { position:static; }
  }
  .box { background:var(--panel); border:1px solid var(--border); border-radius:var(--radius);
         padding:7px 9px; }
  .box h3 { margin:0 0 4px; font-size:11px; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); }
  /* The situation panel leads the page: gold border. It used to be "Do this
     now" with big numbered steps; the steps are gone (2026-10-06, PIVOT.md) —
     what it carries now is state, danger and a pending pick's options. */
  .instructions { border:2px solid var(--gold); padding:10px 12px; }
  .instructions h3 { color:var(--gold); font-size:12px; }
  .instructions .footline { margin-top:6px; padding-top:5px;
                            border-top:1px solid var(--border);
                            color:var(--dim); font-size:13px; }
  /* The situation read: direction, strength, danger in one line. */
  .instructions .situation { font-size:14px; font-weight:600;
                             color:var(--warn); padding:2px 0 3px; }
  /* DANGER: the fragility band as its own line. The 2026-09-18 loss was a
     misread of a legal-looking plan at 14 HP, so this must not be buried in
     the row above it. */
  .instructions .danger { font-size:15px; font-weight:700; padding:4px 6px;
                          margin:2px 0 4px; border-radius:3px; }
  /* Status never rides color alone: the mark (▲/■) + the word FRAGILE/DYING
     carry the state; the tint band just makes it un-missable. Body text is
     ink (--crit-ink for dying), never the status color itself — critical is
     3.6:1 on this surface, too low for small text. */
  .instructions .danger.fragile { color:var(--text); background:var(--warn-bg);
                                  border:1px solid var(--warn-border); }
  .instructions .danger.fragile .dmark { color:var(--warn); }
  .instructions .danger.dying { color:var(--crit-ink); background:var(--crit-bg);
                                border:1px solid var(--crit-border); }
  .instructions .danger.dying .dmark { color:var(--critical); }
  #statebar .warn { color:var(--warn); font-weight:700; }
  /* (The plan-step rules lived here: the kind chip, the action, the tag, the
     reason, the hover clone, and "step 1 is the view's ONE hero". All of it
     styled the numbered plan, which the live page no longer renders — the step
     vocabulary went with it on 2026-10-06, PIVOT.md. The `.hero` rule's whole
     premise was that one line was the answer.) */
  /* Horizontal game-like card tiles: thumb on top, name below. */
  .tiles { display:flex; flex-wrap:wrap; gap:10px 12px; align-items:flex-start; }
  .tile { display:flex; flex-direction:column; align-items:center; gap:2px;
          width:104px; min-width:0; text-align:center; }
  .tile .thumb { width:56px; height:56px; }
  .tile .tname { font-size:12px; line-height:1.25; width:104px; overflow:hidden;
                 text-overflow:ellipsis; white-space:nowrap; }
  .tile .tsub { font-size:11px; color:var(--text-2); }
  .tile .xcount { color:var(--dim); font-size:11px; }
  /* (`.tile.buynow` — the plan's pick glowing gold in the shop row — went with
     the ranking itself: one lit tile is the recommendation the live page no
     longer makes, 2026-10-06.) */
  /* (The sell groups lived here: "Safe to sell | Do not sell" as two labelled
     columns with a divider and good/bad name colors. Both labels are verdicts;
     the box is "Your board" now, one row of numbers and roles.) */
  /* Hand-charge engine row: deployer on board? slot free? charging? */
  .engrow { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .engbit { font-size:12px; color:var(--text-2); }
  .engbit.ok { color:var(--good); }
  .engbit.bad { color:var(--bad); font-weight:700; }
  /* Target-comp tiles: missing pieces fully opaque, owned faded. */
  .tile.comprow { opacity:.4; }
  .tile.comprow.missing { opacity:1; }
  /* A banned-tribe piece of a hybrid comp: struck out, dim. */
  .tile.comprow.bannedrow .tname { text-decoration:line-through; }
  .tile.comprow.bannedrow .tsub { color:var(--bad); }
  .gold { color:var(--gold); }
  .thumb { width:56px; height:56px; border-radius:5px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* No art cached for this card: a same-size placeholder keeps every row
     aligned (missing art used to collapse the row and shift names). */
  .thumb.ph { display:inline-flex; align-items:center; justify-content:center;
              color:var(--dim); background:var(--panel2);
              border:1px solid var(--border); font-size:18px; cursor:default; }
  /* Hover zoom (the fallback when no tooltip appears): art is 256x256, so
     scale(4.5) on a 56px tile thumb shows it near full size; origin center
     bottom grows the popup up and outward from the tile, z-index floats it
     above the other boxes. Scoped to real images with no tooltip content —
     canzoom is dropped the moment a render/text tooltip shows. */
  img.thumb.canzoom:hover { transform:scale(4.5); transform-origin:center bottom;
                    position:relative; z-index:5; }
  .thumb.golden { box-shadow:0 0 0 2px var(--gold); }
  /* (The tavern's "this is the buy" glow went with the plan's pick —
     2026-10-06.) */
  /* Hover card: the full framed render (with text) near the tile, or — when
     upstream has no render for the card — a text box fed from the meta DB. */
  #tip { position:fixed; z-index:50; max-width:300px; }
  .tiprender { display:block; width:256px; border-radius:8px;
               box-shadow:0 8px 24px var(--shadow); }
  .tipbox { background:var(--panel2); border:1px solid var(--border);
            border-radius:var(--radius); padding:6px 9px; max-width:280px;
            box-shadow:0 8px 24px var(--shadow); }
  .tipname { font-weight:700; font-size:13px; }
  .tiptext { font-size:12px; color:var(--text-2); margin-top:2px; }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:1px 8px;
          font-size:13px; }
  /* Comps panel (bottom): tier headers + click-to-expand comp rows. The
     expanded shopping list reuses the target-comp tile language (owned
     faded, banned struck out, missing opaque). */
  .cptier { font-size:11px; font-weight:700; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); margin:6px 0 2px; }
  .cptier:first-child { margin-top:0; }
  .crowhead { display:flex; align-items:baseline; gap:7px; padding:2px 6px;
              cursor:pointer; border-radius:4px; }
  .crowhead:hover { background:var(--panel2); }
  /* Detection-window rows: tribe not yet confirmed in this lobby — still
     listed (it's the game-level view) but visibly uncertain. */
  .crow.unconf { opacity:.5; }
  .carrow { color:var(--dim); font-size:11px; flex:none; width:10px; }
  .cname { font-weight:600; }
  .cstat { color:var(--text-2); font-size:12px; flex:none; }
  .cbody { padding:0 0 4px 17px; }
  /* Comp guidance (2026-10-02): the curated per-comp advice that ships in
     meta/comps.json and the mined guide fetched on expand. Before this the
     expanded row showed card chips only, so none of it reached a player. */
  .cguidance { margin:0 0 5px; }
  .cline { font-size:12px; line-height:1.45; padding:1px 0; }
  .cline.dim { color:var(--text-2); }
  .cguideslot:empty { display:none; }
  .cguidefull { margin-top:5px; padding-top:5px;
                border-top:1px solid var(--gridline); }
  .cguidemd { font-size:12px; line-height:1.5; color:var(--text-2);
              white-space:pre-wrap; margin:3px 0 0; font-family:inherit;
              max-height:320px; overflow-y:auto; }
  /* (The plan's per-step line and its gold step number lived here. The plan is
     not rendered on the live page any more — 2026-10-06, PIVOT.md.) */
  .target { font-size:14px; font-weight:600; color:var(--gold); }
  .tag-core { color:var(--gold); }
  .tag-spell { color:var(--k-spell); }
  .tag-addon { color:var(--warn); }
  /* Comp direction meter: track (light step of the same ramp) + severity
     fill + candidate name + the text state that carries the meaning. */
  .mrow { display:flex; align-items:center; gap:8px; padding:2px 0;
          font-size:14px; min-width:0; }
  .mrow .meter { width:44px; height:8px; border-radius:4px; flex:none;
                 background:rgba(255,217,122,.16); overflow:hidden;
                 position:relative; }
  .mrow .meter.near { background:rgba(250,178,25,.14); }
  .mrow .meter:not(.met):not(.near) { background:var(--gridline); }
  .mrow .meter .fill { position:absolute; inset:0 auto 0 0; display:block;
                       height:100%; border-radius:4px; min-width:4px;
                       background:var(--dim); }
  .mrow .meter.near .fill { background:var(--warn); }
  .mrow .meter.met .fill { background:var(--gold); }
  .mrow .mname { font-weight:600; overflow:hidden; text-overflow:ellipsis;
                 white-space:nowrap; }
  .mrow .mstat { color:var(--text-2); font-size:12px; flex:none; }
  .mrow.locked .mname { color:var(--gold); font-weight:700; }
  /* Pane headers: the two-pane grouping (Decide | Reference). */
  .pane-h { margin:0; font-size:11px; font-weight:700; letter-spacing:.14em;
            text-transform:uppercase; color:var(--dim); }
  .none { color:var(--dim); font-style:italic; }
  .score { color:var(--dim); flex:none; }
  .xcount { color:var(--dim); font-weight:400; }
  /* Welcome (the deliberate empty state): teaches instead of faking.
     Shown on fresh boot, a new game's first tick, and after Clear. */
  .welcome { margin-top:8vh; padding:30px 34px; border:1px solid var(--dim);
             border-radius:12px; max-width:560px; }
  .welcome .w-title { margin:0 0 4px; font-size:26px; color:var(--gold); }
  .welcome .w-tag { font-size:14px; margin-bottom:16px; }
  .welcome .w-share { margin-top:14px; display:flex; gap:10px;
    align-items:center; flex-wrap:wrap; }
  .welcome .w-share-q { color:var(--text-2); font-size:13px; }
  .welcome .w-share-btn { background:var(--panel2); color:inherit;
    border:1px solid var(--dim); border-radius:6px; padding:6px 12px;
    font-size:12px; cursor:pointer; }
  .welcome .w-share-btn:hover { border-color:var(--gold); color:var(--gold); }
  .welcome .w-status { color:var(--text-2); font-size:13px; margin-bottom:10px; }
  .welcome .w-hint, .welcome .w-priv { color:var(--dim); font-size:12px;
                                       margin-top:6px; }
  /* The first-run fix, on screen. live.py's console message has always told
     the player "the welcome card shows the same steps" — it did not, it sent
     them to the README on disk, which is exactly the wrong place when the
     reason they opened the overlay is that nothing was happening. */
  .welcome .w-steps { color:var(--text-2); background:var(--panel2);
                      border:1px solid var(--gridline); border-radius:6px;
                      padding:8px 10px; margin:8px 0 2px; font-size:12px;
                      line-height:1.45; white-space:pre-wrap;
                      font-family:ui-monospace,Consolas,monospace; }
  /* Stale-advice marker. The overlay only re-renders when the server pushes,
     so a wedged live.py (or a dead one) left the last advice on screen
     looking exactly like live advice — the worst failure for a coach, since
     the player acts on it. This shows the age once it stops being fresh. */
  #freshness { display:none; font-size:12px; font-weight:700;
               color:var(--warn); padding:2px 0 4px; }
  #freshness.on { display:block; }
  /* Old advice is NORMAL between buy phases (a median 81 s gap against the 8 s
     this first alarmed on), so it is stated plainly rather than warningly: the
     alarm colour is reserved for the coach having stopped answering at all. */
  #freshness.info { display:block; color:var(--dim); font-weight:400; }
  /* Tabs (2026-10-06): Another Round is the live overlay this page has
     always been; Settle Up is the saved-game browser. A tab is a plain
     toggle — the live poll keeps running either way, and switching never
     clears live state. */
  #tabs { display:flex; gap:4px; margin:2px 0 8px; }
  #tabs .tab { background:var(--panel); color:var(--dim);
               border:1px solid var(--border); border-radius:var(--radius);
               padding:5px 14px; font:600 13px "Segoe UI", system-ui;
               cursor:pointer; }
  #tabs .tab:hover { color:var(--text-2); }
  #tabs .tab.on { color:var(--text); background:var(--panel2);
                  border-color:rgba(255,255,255,.22); }
  /* The sharing control (2026-10-07): a quiet line at the right end of the tab
     row, not a button on a card. It has to be reachable for as long as sharing
     is ON — that is what keeps the answer reviewable and reversible — and the
     card it used to live on is only on screen at a game's start or end, so it
     was invisible for the whole game it was describing. Muted deliberately
     (--dim, no border until hover): a control that decides whether data leaves
     the machine should be easy to find and hard to hit by accident. */
  #tabs #share-toggle { margin-left:8px; background:none;
                        border:1px solid transparent; color:var(--dim);
                        font:400 12px "Segoe UI", system-ui;
                        padding:4px 8px; cursor:pointer; opacity:.55; }
  #tabs #share-toggle:hover { opacity:1; color:var(--text-2);
                              border-color:var(--border); }
  #tabs #share-toggle[hidden] { display:none; }
  /* The Live viewer flag (2026-10-09): Classic is the shipped renderer, Tavern
     is the LIVE_VIEW_DESIGN.md build. Same shape as the Settle Up flag — a
     styling toggle, not a rewrite switch, and the classic path below is
     untouched. It used to live in the top nav; it heads the LIVE page now
     (one toggle per page — see the markup note). */
  #live-viewer-row { grid-column:1 / -1; display:flex;
                     justify-content:flex-end; margin:0 0 8px; }
  #live-viewer-row[hidden] { display:none; }
  /* The Tavern Live view's own container, and the two classic panes it hides
     (2026-10-09). Hiding rather than replacing is what keeps the way back to
     Classic working.
     **It FILLS the window now (2026-10-09, fix list round 1).** `#app` is a
     two-column grid above 1200x900 and a flex COLUMN at or below it, and the
     tavern container was a grid rule with `flex:1 1 100%` as its size in the
     flex case — where `flex-basis` is a height, so it did not stretch across.
     Measured before the fix: 815px of a 1384px window. One column when the grid
     applies, and `width:100%` in both. */
  #app.tavern-on { grid-template-columns:minmax(0,1fr); align-items:stretch; }
  #app.tavern-on #live-tavern { grid-column:1 / -1; width:100%;
                                min-width:0; }
  #app.tavern-on > #col-decide, #app.tavern-on > #col-ref { display:none; }
  /* An EMPTY state strip is a rounded bar with nothing in it, and the welcome
     and game-over cards leave it empty by design (2026-10-09, fix list round 2
     item 7). It is hidden rather than blanked. */
  #statebar[hidden] { display:none; }
  /* The release stamp (2026-10-07): which release this overlay was served
     by, bottom-right and nearly invisible. A screenshot or a field report
     can then name the release without anyone digging for it — the question
     every bug report starts with. Quieter than the share toggle on
     purpose: it is information, not a control, so it takes no clicks. */
  #release-tag { position:fixed; right:10px; bottom:6px; color:var(--dim);
                 font:400 11px "Segoe UI", system-ui; opacity:.45;
                 pointer-events:none; z-index:100; }
  #release-tag[hidden] { display:none; }
  #app.off { display:none; }
  #settle { display:none; }
  #settle.on { display:block; }
  .s-head { display:flex; align-items:center; gap:10px; margin:0 0 10px;
            position:sticky; top:0; background:var(--bg); z-index:10;
            padding:6px 0; }
  .s-head select { background:var(--panel2); color:var(--text);
                   border:1px solid var(--border); border-radius:var(--radius);
                   padding:6px 8px; font:14px "Segoe UI", system-ui;
                   min-width:360px; }
  .s-head button { background:var(--panel); color:var(--dim);
                   border:1px solid var(--border); border-radius:var(--radius);
                   padding:6px 12px; font:600 12px "Segoe UI", system-ui;
                   cursor:pointer; }
  .s-head button:hover { color:var(--text-2); }
  /* The two Settle Up segment controls (2026-10-08 viewer flag; 2026-10-09
     mode): Classic | Tavern picks the renderer, Summary | Step through picks
     the Tavern mode and sits next to the game dropdown. A styling toggle, not
     a rewrite switch — the classic path is byte-for-byte the old renderer.
     **The `.vseg` class is what styles the active button, and nothing carried
     it until today**: the JS set `class="on"` on a span that had no class, so
     the shipped Classic | Tavern toggle gave NO visible sign of which viewer
     was active. Both spans carry it now. */
  /* The segment control itself (2026-10-09, fix list round 1 item 9 / round 2
     item 8: "theme the Classic | Tavern toggle"). `.vseg` only ever described
     the ACTIVE state and the radii — the buttons themselves were whatever the
     browser draws, which is why the Live one read as a white pill with grey
     text. It is themed here for BOTH pages (the Settle Up pair sits in
     `.s-head`, whose own button rule agrees with this), and over the Tavern
     view it takes the tavern palette, so the control matches what it toggles. */
  .vseg { display:inline-flex; gap:0; }
  .vseg button { background:var(--panel); color:var(--dim);
                 border:1px solid var(--border); padding:6px 12px;
                 font:600 12px "Segoe UI", system-ui; cursor:pointer; }
  .vseg button:hover { color:var(--text-2); }
  .vseg button { border-radius:0; }
  #live-viewer-row .vseg button { padding:6px 14px; }
  .vseg button:first-child { border-radius:var(--radius) 0 0 var(--radius); }
  .vseg button:last-child { border-radius:0 var(--radius) var(--radius) 0;
                            border-left:none; }
  .vseg button.on { color:var(--text); background:var(--panel2);
                    border-color:rgba(255,255,255,.22); }
  .vseg button:disabled { opacity:.45; cursor:default; color:var(--dim); }
  /* Over the Tavern view: the same control in the tavern's own colours, with
     the design's selection amber for the active half (§7: amber is selection). */
  #app.tavern-on #live-viewer-row .vseg button {
    background:var(--tpanel); color:var(--tmute); border-color:var(--tline);
    padding:6px 14px; min-height:44px; }
  #app.tavern-on #live-viewer-row .vseg button:hover { color:var(--ttext); }
  #app.tavern-on #live-viewer-row .vseg button.on {
    background:var(--tsel); color:var(--tonsel); border-color:var(--tsel); }
  /* An id beats the UA's [hidden] rule, so hiding this has to be said. */
  #settle-mode[hidden] { display:none; }
  /* The Tavern palette (REPLAY_VIEWER_DESIGN.md §6), SCOPED to .tavern so the
     classic viewer and the live overlay keep their own tokens untouched.
     Gold is attack only; --tsel is the selection accent. Contrast per §7:
     --thp on --tcard is ~4.5:1 at 15px bold — revisit with real art. */
  .tavern { --tbg:#17110d; --tpanel:#231913; --tcard:#33261d; --tline:#5a4332;
            --ttext:#f1e6d2; --tmute:#b09c84; --tsel:#e0a43a;
            --tonbuff:#10140f;   /* text on a --tbuff fill */
            --tonsel:#14110c;   /* text on a --tsel fill */
            --tatk:#f4c95d; --thp:#e8664f; --tbuff:#8fd06a;
            --twin:#7cc66b; --tloss:#e8664f; --ttie:#b09c84;
            --tk-roll:#3a2d22; --tk-buy:#35592f; --tk-sell:#7a3328;
            --tk-level:#7a6320; --tk-play:#2c4f7a; --tk-cast:#54397a;
            --tk-roll-t:#b09c84; --tk-buy-t:#e4f5da; --tk-sell-t:#ffe1db;
            --tk-level-t:#fff1c4; --tk-play-t:#dce9fb; --tk-cast-t:#eadcfb;
            /* Card sizing (2026-10-09, player call): the art FILLS the frame
               and the frame scales with the window, min the design's §4.2
               (88x120 summary, 130x172 step-through). The step board swaps
               --tcardw, so every rule below sizes off ONE variable. */
            --tcardw:clamp(88px, 6.6vw, 124px);
            --tstepw:clamp(130px, 9.6vw, 190px);
            background:var(--tbg); color:var(--ttext); border-radius:var(--radius);
            padding:10px 12px; }
  /* §8: "Visible focus ring (2px --sel, with offset) on all controls". Scoped to
     .tavern, so it reaches both Tavern viewers and leaves the classic pages with
     the browser's own ring. The 44px minimum targets are per control, below. */
  .tavern :focus-visible { outline:2px solid var(--tsel); outline-offset:2px; }
  .tavern .ts-head { font:600 13px "Segoe UI", system-ui; margin-bottom:8px; }
  .tavern .ts-head .tm { color:var(--tmute); font-weight:400; font-size:12px; }
  .tavern .ts-caveat { color:var(--tmute); font-size:12px; margin:4px 0 10px; }
  .tstrip { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }
  .tavern .tbtn2 { min-width:44px; height:48px; padding:0 10px;
                   border-radius:8px; border:1px solid var(--tline);
                   border-bottom:3px solid var(--tline); background:var(--tpanel);
                   color:var(--ttext); cursor:pointer; line-height:1.2;
                   font:600 13px "Segoe UI", system-ui; text-align:center; }
  .tavern .tbtn2 small { display:block; font-size:10px; font-weight:400;
                         color:var(--tmute); }
  .tavern .tbtn2.win { border-bottom-color:var(--twin); }
  .tavern .tbtn2.loss { border-bottom-color:var(--tloss); }
  .tavern .tbtn2.tie { border-bottom-color:var(--ttie); }
  .tavern .tbtn2.sel { background:var(--tsel); color:var(--tonsel);
                       border-color:var(--tsel); font-weight:700; }
  .tavern .tbtn2.sel small { color:var(--tonsel); }
  .tavern .turn { background:var(--tpanel); border:1px solid var(--tline);
                  color:var(--ttext); }
  /* Summary rail + tray + net tags (design §4.3/§4.4, build step 3). The rail
     sits LEFT and the boards take the rest (2026-10-09, player call) — it used
     to wrap ABOVE them, because the card's intrinsic width is wide and
     `flex-wrap:wrap` gave up rather than shrinking either side. */
  .twrap { display:flex; gap:14px; align-items:flex-start; flex-wrap:nowrap; }
  .tavern .twrap > .turn { flex:1 1 auto; min-width:0; }
  .tavern .rail { flex:0 0 330px; background:var(--tpanel);
                  border:1px solid var(--tline); border-radius:10px;
                  padding:10px; }
  /* Under ~900px there is no room for a 330px column beside a board: the rail
     goes back above it, which is the design's §5 narrow-width rule. */
  @media (max-width: 900px) {
    .twrap { flex-wrap:wrap; }
    .tavern .rail { flex:1 1 100%; }
  }
  .tavern .rail-h .rt { font-weight:700; font-size:13px; }
  .tavern .rchips { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 4px; }
  .tavern .chip { padding:3px 9px; border-radius:14px; background:var(--tcard);
                  border:1px solid var(--tline); font-size:12px; }
  .tavern .ig-h { color:var(--tmute); text-transform:uppercase; font-size:11px;
                  letter-spacing:.12em; margin:10px 0 4px; cursor:pointer;
                  user-select:none; }
  .tavern .iitem { padding:5px 8px; border-radius:6px; background:var(--tcard);
                   border:1px solid var(--tline);
                   border-left:3px solid var(--ttie); font-size:12px;
                   margin:3px 0; }
  .tavern .iitem.kept { border-left-color:var(--twin); }
  .tavern .iitem.sold { border-left-color:var(--tloss); }
  .tavern .iitem.flipped { border-left-color:var(--ttie); }
  .tavern .ishow { color:var(--tmute); background:none; border:none;
                   cursor:pointer; font-size:11px; padding:2px 0;
                   text-decoration:underline; }
  /* Cards, ONE component everywhere (2026-10-09, player call). The tile is a
     portrait: the art fills the frame and scales with the window
     (--tcardw; the step board swaps in --tstepw), and the name, stats and
     delta sit BELOW the art — in flow, the same order on every card, so no
     overlay can float over a name or clip a tag. The first version of this
     block put the name and stats on a dark strip OVER the art, and the three
     symptoms the fix list names were all that strip: a newly bought card's
     name printed on top of the frame, an overlay floating over Soul
     Rewinder's art, and a NEW tag hidden behind an overlay. The stat line is
     attack gold, health red (§6/§7); a delta is the buff green as one
     "+0/+3". */
  .tavern .tile { width:var(--tcardw); position:relative; padding:0; gap:1px;
                  align-items:stretch; text-align:left; background:none;
                  border:none; }
  .tavern .tile .thumb { width:100%; height:auto; aspect-ratio:88/116;
                         object-fit:cover; border-radius:8px; }
  .tavern .tile .thumb.ph { aspect-ratio:88/116; }
  /* The overlay's hover zoom is a 56px-tile trick (scale 4.5 on a 256px
     render). Over art that already fills the card it would be clipped by the
     frame, so it is off here — the hover CARD is the tooltip. */
  .tavern .tile img.thumb.canzoom:hover { transform:none; }
  /* Full names, on TWO lines (fix list round 2 item 3): truncating to one line
     with an ellipsis hid which of "Murloc Warleader" and "Murloc Tidecaller" a
     tile was, on a screen where the name is the only identifier. The hover
     tooltip still carries the whole card. */
  .tavern .tile .tname { width:100%; font-size:11px; line-height:1.25;
                         margin-top:2px; white-space:normal; overflow:hidden;
                         display:-webkit-box; -webkit-line-clamp:2;
                         -webkit-box-orient:vertical; }
  .tavern .tile .tsub { font-size:13px; font-weight:700; line-height:1.2; }
  .tavern .tile .tsub .stat-atk { color:var(--tatk); }
  .tavern .tile .tsub .stat-hp { color:var(--thp); }
  .tavern .tile .tsub .stat-sep { color:var(--tmute); font-weight:400; }
  /* NEW and SOLD ride a fixed corner OVER the art — never in the text flow
     below it, where they would shove the name around, and never behind an
     overlay (the clipping this replaces). */
  .tavern .tile .tag-new, .tavern .tile .tag-sold {
    position:absolute; top:4px; left:4px; z-index:2; font-size:10px;
    font-weight:700; padding:2px 5px; border-radius:4px; }
  .tavern .tile .tag-new { background:var(--tbuff); color:var(--tonbuff); }
  .tavern .tile .tag-sold { background:var(--tloss); color:var(--tonsel); }
  /* What the card IS, for the one kind that is not a minion: a tag in the other
     corner, never a different frame (fix list round 2 item 3). */
  .tavern .tile .tag-kind { position:absolute; top:4px; right:4px; z-index:2;
                            font-size:10px; font-weight:700; padding:2px 5px;
                            border-radius:4px; background:var(--tk-play);
                            color:var(--tk-play-t); }
  /* Net change: one buff-green "+0/+3" (2026-10-09, player call) — the buff
     is the fact, and per-stat gold/red is the base stats' job. */
  .tavern .tile .tdelta { font-size:12px; font-weight:700; color:var(--tbuff); }
  .tavern .tile .tsep { color:var(--tmute); }
  .tavern .tile.ghost { width:calc(var(--tcardw) * 0.864); opacity:.55; }
  .tavern .tile.ghost .thumb { border:1px dashed var(--tline); }
  /* Labels ABOVE their rows (2026-10-09, player call): a board is a full-width
     row of cards, and a label sitting beside it only stole width from them. */
  .tavern .brow.stacked { display:block; }
  .tavern .brow.stacked .blbl { display:block; margin:0 0 4px; }
  /* Battle face-off (design §4.5, build step 4). Your side warm, theirs
     cool; the result panel rides at right and drops under on narrow
     screens. */
  .faceoff-wrap { display:grid; grid-template-columns:1fr 210px; gap:10px; }
  .faceoff { display:flex; flex-direction:column; gap:8px; }
  .fside { border:1px solid var(--tline); border-radius:10px; padding:8px; }
  .fside.cool { background:rgba(70,100,140,.12); }
  .fside.warm { background:rgba(160,110,50,.14); }
  .fbadge { display:flex; gap:8px; align-items:baseline; font-weight:700;
            font-size:12px; margin-bottom:6px; }
  .fbadge .fm { color:var(--tmute); font-weight:400; font-size:11px; }
  .fboards { display:flex; flex-wrap:wrap; gap:6px; justify-content:center; }
  .fnone { color:var(--tmute); text-align:center; font-size:12px;
           padding:6px; }
  .vs { text-align:center; color:var(--tmute); font-weight:700;
        letter-spacing:.3em; font-size:12px; }
  .fresult { background:var(--tpanel); border:1px solid var(--tline);
             border-radius:10px; padding:8px 10px; font-size:12px;
             align-self:start; }
  .fresult .fout { font-weight:700; margin-bottom:6px; }
  .fresult .fout.won { color:var(--twin); }
  .fresult .fout.lost { color:var(--tloss); }
  .fresult .fout.tie, .fresult .fout.unk { color:var(--tmute); }
  .fresult .fk { color:var(--tmute); display:block; font-size:10px;
                 text-transform:uppercase; letter-spacing:.12em; }
  .fresult .fv { display:block; margin-bottom:6px; }
  @media (max-width: 900px) { .faceoff-wrap { grid-template-columns:1fr; } }
  /* Step-through (design §4.6, build step 5): the nav, the lettered track, the
     large board. Kind colors from §6; letters carry the kind so color is never
     the only signal. The mode toggle itself lives in the SETTLE HEADER next to
     the game dropdown (2026-10-09, player call), not over the boards. */
  .tavern .tstep { width:100%; }
  .tavern .stepnav { display:flex; gap:8px; align-items:center;
                     margin:0 0 8px; flex-wrap:wrap; }
  .tavern .snav { background:var(--tpanel); color:var(--ttext);
                  border:1px solid var(--tline); border-radius:8px;
                  min-width:44px; min-height:44px; cursor:pointer;
                  font:600 13px "Segoe UI", system-ui; }
  .tavern .snav:disabled { opacity:.4; cursor:default; }
  .tavern .splay { color:var(--tsel); }
  /* The action, in plain words, at reading size — it labels the board under it
     (2026-10-09, player call). It used to be 13px muted text squeezed into the
     control row, which is the one line that says what you are looking at. */
  .tavern .stepcap { color:var(--ttext); font:600 16px "Segoe UI", system-ui;
                     margin:0 0 6px; }
  .tavern .stepcap .scap-what { color:var(--tmute); font-weight:400;
                                font-size:13px; }
  .tavern .steptrack { display:flex; flex-wrap:wrap; gap:4px; margin:0 0 4px; }
  .tavern .stick { width:38px; height:44px; border-radius:6px;
                   border:1px solid var(--tline); color:var(--tmute);
                   background:var(--tcard); cursor:pointer;
                   font:700 14px "Segoe UI", system-ui; }
  .tavern .stick.k-roll { background:var(--tk-roll); }
  .tavern .stick.k-buy { background:var(--tk-buy); color:var(--tk-buy-t); }
  .tavern .stick.k-sell { background:var(--tk-sell); color:var(--tk-sell-t); }
  .tavern .stick.k-level { background:var(--tk-level);
                           color:var(--tk-level-t); }
  .tavern .stick.k-play { background:var(--tk-play); color:var(--tk-play-t); }
  .tavern .stick.k-cast { background:var(--tk-cast); color:var(--tk-cast-t); }
  .tavern .stick.sel { outline:2px solid var(--tsel); outline-offset:1px; }
  /* The legend: directly under the track (it labels the letters the track
     prints), and at readable size and contrast — 11px muted failed both
     (2026-10-09, player call). */
  .tavern .slegend { color:var(--ttext); font-size:13px; margin:2px 0 10px; }
  .tavern .stepboard { display:flex; flex-wrap:wrap; gap:8px; padding:10px;
                       background:var(--tpanel); border:1px solid var(--tline);
                       border-radius:10px; min-height:192px;
                       --tcardw:var(--tstepw); }
  .tavern .stepboard .tile .tsub { font-size:15px; font-weight:700; }
  .tavern .tile.affected { outline:2px solid var(--tsel); outline-offset:1px; }
  .s-empty { color:var(--dim); padding:16px 0; }
  /* The model's plan in the rail (2026-10-09, player call): folded, neutral,
     and away from the verdict vocabulary — the rail names it "Plan" and lets
     the text speak. */
  .tavern details.rplan { margin:10px 0 0; }
  .tavern details.rplan summary { cursor:pointer; color:var(--tmute);
                                  font-size:12px; text-transform:uppercase;
                                  letter-spacing:.12em; }
  .tavern details.rplan summary:hover { color:var(--ttext); }
  .tavern details.rplan .rplan-body { color:var(--ttext); font-size:12px;
                                      margin-top:5px; line-height:1.45; }
  /* --- Live, Tavern layout (LIVE_VIEW_DESIGN.md §4.2/§5/§7, 2026-10-09) -----
     Scoped to `.tavern.live` so these cannot leak into the Settle Up Tavern
     rules above, nor those into these: the two views share the TOKENS and the
     card component, nothing else. Facts only — no verdict, rank or imperative. */
  .tavern.live { padding:12px 14px; }
  .lv-status { display:flex; align-items:flex-end; gap:22px; flex-wrap:wrap;
               margin:0 0 12px; }
  .tavern.live .lv-hero { font:700 18px "Segoe UI", system-ui; }
  /* The hero slot is a sentence before the first shop of a game (fix list round
     2 item 2): muted and not bold, because it is a state, not a hero. */
  .tavern.live .lv-hero.waiting { font:600 15px "Segoe UI", system-ui;
                                  color:var(--tmute); }
  .tavern.live .lv-st { display:flex; flex-direction:column; }
  .tavern.live .lv-st small { font-size:11px; letter-spacing:.1em;
                              text-transform:uppercase; color:var(--tmute); }
  .tavern.live .lv-st b { font:600 26px "Segoe UI", system-ui; }
  /* §6.4: a value nobody read is a dash in --mute, never a guess. */
  .tavern.live .lv-st b.miss { color:var(--tmute); font-weight:400; }
  /* Gold is the currency colour, which is --atk's other job (§4.2/§7). */
  .tavern.live .lv-st.gold b:not(.miss) { color:var(--tatk); }
  /* The two columns of the Live page (fix list round 2 item 9): main + a 340px
     rail at >=1200px, STACKED from 700 to 1200, and a single-column pick grid
     under 700. The rail used to drop out at 900px, which left a 1000px window
     with a rail that could have fitted. */
  .tavern.live .lv-main { display:grid; grid-template-columns:minmax(0,1fr);
                          gap:14px; align-items:start; }
  @media (min-width: 1200px) {
    .tavern.live .lv-main { grid-template-columns:minmax(0,1fr) 340px; }
  }
  /* Shop screen (fix list round 1 item 4 / round 2 item 4): the taverner's row
     on top, then ONE panel holding the board and the hand side by side. */
  .tavern.live .lv-bh { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr);
                        gap:14px; align-items:start; }
  @media (max-width: 699.98px) {
    .tavern.live .lv-bh { grid-template-columns:1fr; }
  }
  .tavern.live .lv-bh > div { min-width:0; }
  .tavern.live .lv-inline { color:var(--tmute); font-size:12px; padding:2px 0; }
  .tavern.live .lv-pn { background:var(--tpanel); border:1px solid var(--tline);
                        border-radius:12px; padding:12px 14px;
                        margin:0 0 12px; }
  .tavern.live .lv-pn > h3 { margin:0 0 8px; font-size:12px; letter-spacing:.12em;
                             text-transform:uppercase; color:var(--tmute); }
  .tavern.live .lv-row { display:flex; flex-wrap:wrap; gap:12px; }
  .tavern.live .lv-card { display:flex; flex-direction:column;
                          align-items:center; }
  .tavern.live .lv-cap { display:block; width:var(--tcardw); margin-top:5px;
                         font-size:11px; color:var(--tmute);
                         text-align:center; }
  .tavern.live .lv-kv { display:flex; justify-content:space-between; gap:10px;
                        padding:7px 0; border-bottom:1px solid var(--tline);
                        font-size:13px; }
  .tavern.live .lv-kv span { color:var(--tmute); }
  .tavern.live .lv-kv b { font-weight:600; }
  .tavern.live .lv-kv b.miss { color:var(--tmute); font-weight:400; }
  .tavern.live .lv-tier { color:var(--tmute); font-style:normal;
                          font-size:11px; margin-left:6px; }
  .tavern.live .lv-lbl { color:var(--tmute); font-size:12px; margin:0 0 6px; }
  .tavern.live .lv-note { color:var(--tmute); font-size:11px; margin:8px 0 0; }
  .tavern.live .lv-empty { color:var(--tmute); font-size:12px; padding:4px 0; }
  .tavern.live .lv-tabs { display:flex; gap:0; margin:0 0 10px; }
  .tavern.live .lv-tabs button { background:var(--tpanel); color:var(--tmute);
                                 border:1px solid var(--tline); padding:6px 12px;
                                 min-height:44px;
                                 font:600 12px "Segoe UI", system-ui;
                                 cursor:pointer; }
  .tavern.live .lv-tabs button:first-child { border-radius:8px 0 0 8px; }
  .tavern.live .lv-tabs button:last-child { border-radius:0 8px 8px 0;
                                            border-left:none; }
  .tavern.live .lv-tabs button.on { background:var(--tsel); color:var(--tonsel);
                                    border-color:var(--tsel); }
  .tavern.live .lv-tribes { display:flex; flex-wrap:wrap; gap:6px;
                            align-items:center; margin:0 0 12px; }
  .tavern.live .lv-chip { padding:5px 11px; border-radius:14px;
                          background:var(--tcard); border:1px solid var(--tline);
                          font-size:12px; cursor:pointer; }
  /* Active = an amber outline, inactive = dimmed (fix list round 1 item 3). The
     amber is --tsel, the design's selection colour; nothing here is a verdict
     about the tribe, only about which chips are set. */
  .tavern.live .lv-chip.active { border:2px solid var(--tsel);
                                 color:var(--ttext); padding:4px 10px; }
  .tavern.live .lv-chip.dim { opacity:.5; }
  .tavern.live .lv-chip.dim:hover { opacity:.85; }
  /* Out of play is NOT a ban the player could undo (§4.2): struck through, and
     not clickable, so it can never read as one of the five. */
  .tavern.live .lv-chip.out { border-color:var(--tloss); color:var(--tmute);
                              text-decoration:line-through; cursor:default; }
  .tavern.live .lv-chip.picked { border-color:var(--tsel); }
  /* The design's §6.1 four dashed skeleton cards went with fix list round 2 item
     2 (the player's call: they read as thick dash bars carrying nothing). The
     sentence beside them says the same thing, and the class is gone entirely so
     no rule can quietly bring the bars back. */
  /* §4.3's pick screen: the controls row, the option columns (>=200px each, so
     a narrow window gets fewer of them rather than a squashed one — fix list
     round 1 item 2), the headline figure and §5's distribution bars. */
  .tavern.live .lv-pickctl { display:flex; flex-wrap:nowrap; gap:12px;
                             align-items:center; margin:0 0 10px;
                             overflow-x:auto; }
  .tavern.live .lv-chip.on { border-color:var(--tsel); color:var(--ttext); }
  .tavern.live .lv-chip.off { opacity:.45; cursor:default; }
  /* >=200px columns (fix list round 1 item 2), capped near the design's own
     column width so two options do not stretch to half the window each — the
     CARD is 130px and a 660px column around it reads as a mistake. Centered,
     because a pick screen with two options should look like two options. */
  .tavern.live .lv-opts { display:grid; gap:16px; justify-content:center;
                          grid-template-columns:repeat(auto-fit,
                                                 minmax(200px, 340px)); }
  @media (max-width: 699.98px) {
    .tavern.live .lv-opts { grid-template-columns:1fr; }
  }
  .tavern.live .lv-opt { display:flex; flex-direction:column;
                         align-items:center; gap:12px; }
  /* §5: a pick option's card is 130 wide. */
  .tavern.live .lv-opt { --tcardw:130px; }
  /* A FIXED-height name (fix list round 1 item 2): one line or two, the
     headline and the bars below it always start at the same height, so the
     options can be read across. */
  .tavern.live .lv-optname { font-weight:600; font-size:13px;
                             text-align:center; min-height:34px;
                             display:flex; align-items:center;
                             justify-content:center; }
  .tavern.live .lv-head { display:flex; flex-direction:column;
                          align-items:center; margin:4px 0; }
  .tavern.live .lv-head b { font:600 26px "Segoe UI", system-ui; }
  .tavern.live .lv-head small { font-size:11px; letter-spacing:.1em;
                                text-transform:uppercase; color:var(--tmute); }
  .tavern.live .lv-vs { color:var(--tmute); font-size:12px; font-style:normal; }
  .tavern.live .lv-opt .lv-kv { width:100%; }
  /* §5's distribution: eight bars, ONE neutral colour (no good/bad shading),
     a dashed divider between 4 and 5, labels below. */
  .tavern.live .lv-dist { display:flex; align-items:flex-end; gap:2px;
                          height:46px; margin:4px 0 0; }
  .tavern.live .lv-bar { display:flex; flex-direction:column;
                         justify-content:flex-end; align-items:center;
                         width:16px; height:100%; }
  .tavern.live .lv-bar i { display:block; width:100%; background:var(--tmute);
                           border-radius:2px 2px 0 0; }
  .tavern.live .lv-bar.after4 { border-left:1px dashed var(--tline);
                                padding-left:2px; }
  .tavern.live .lv-bar em { font-size:10px; color:var(--tmute);
                            font-style:normal; }
  .tavern.live .lv-guide { margin-top:8px; color:var(--tmute); font-size:12px; }
  /* §4.4's comp screens: the controls row, one column per source tier, the
     Browse row, §5's core slots (34x46 in Browse, 52x70 in Compare), the Detail
     split with its 88x120 core row and 76x100 flex row, and the compare
     columns. */
  .tavern.live .lv-ctl { display:flex; flex-wrap:wrap; gap:6px;
                         align-items:center; margin:0 0 10px; }
  .tavern.live .lv-cols { display:flex; flex-wrap:wrap; gap:16px;
                          align-items:flex-start; }
  .tavern.live .lv-ctier { flex:1 1 300px; min-width:260px; }
  .tavern.live .lv-ctier > h4 { margin:0 0 6px; font-size:11px;
                                letter-spacing:.12em; text-transform:uppercase;
                                color:var(--tmute); }
  /* A comp row is a GRID with fixed columns (fix list round 1 item 6:
     "consistent rows"): the slots, the owned count, the average placement and
     the compare box start at the same x down the whole column, which a flex row
     with `margin-left:auto` could not promise. */
  .tavern.live .lv-crow { display:grid;
                          grid-template-columns:minmax(0,1fr) auto 92px 58px 88px;
                          gap:10px; align-items:center; padding:7px 0;
                          border-bottom:1px solid var(--tline); font-size:12px; }
  @media (max-width: 699.98px) {
    .tavern.live .lv-crow { grid-template-columns:minmax(0,1fr) auto; }
  }
  .tavern.live .lv-cname { min-width:0; display:flex;
                           flex-wrap:wrap; gap:6px; align-items:baseline; }
  .tavern.live .lv-copen { cursor:pointer; text-decoration:underline; }
  .tavern.live .lv-crow.low .lv-cname, .tavern.live .lv-crow.low .lv-slots,
  .tavern.live .lv-crow.low .lv-owned, .tavern.live .lv-crow.low .lv-ap {
    opacity:.55; }
  .tavern.live .lv-owned { color:var(--ttext); font-weight:600;
                           white-space:nowrap; }
  .tavern.live .lv-ap { font-weight:600; }
  .tavern.live .lv-ap.miss { color:var(--tmute); font-weight:400; }
  .tavern.live .lv-chip.lowsamp { cursor:default; color:var(--tmute);
                                  font-size:11px; padding:2px 8px; }
  .tavern.live .lv-slots { display:flex; flex-wrap:wrap; gap:3px; }
  .tavern.live .lv-slot { display:inline-block; width:34px; height:46px;
                          border-radius:5px; background:var(--tcard);
                          border:2px solid var(--tbuff); box-sizing:border-box;
                          overflow:hidden; position:relative; }
  /* The core card's own art, size of the slot. Missing/banned are DIMMED rather
     than hidden — the comp still says which cards it wants. */
  .tavern.live .lv-slot .thumb { display:block; width:100%; height:100%;
                                 object-fit:cover; border-radius:0; }
  .tavern.live .lv-slot.miss { border:1px dashed var(--tline); }
  .tavern.live .lv-slot.miss .thumb, .tavern.live .lv-slot.banned .thumb {
    opacity:.35; filter:grayscale(1); }
  .tavern.live .lv-slot.banned { border:2px solid var(--tloss); }
  .tavern.live .lv-slot .thumb.ph { font-size:12px; color:var(--tmute);
                                    background:var(--tcard); }
  /* The legend is the slot element itself, so it cannot drift from the rows. */
  .tavern.live .lv-legend { display:flex; flex-wrap:wrap; gap:14px;
                            align-items:center; margin:10px 0 0; }
  .tavern.live .lv-legitem { display:inline-flex; align-items:center; gap:6px; }
  .tavern.live .lv-legend .lv-slot { width:20px; height:27px; }
  .tavern.live .lv-leglbl { color:var(--tmute); font-size:11px; }
  .tavern.live .lv-cmpcell { display:inline-flex; align-items:center; gap:6px;
                             justify-content:flex-start; }
  .tavern.live .lv-cmpbox { width:18px; height:18px; margin:0;
                            accent-color:var(--tsel); cursor:pointer; }
  .tavern.live .lv-cmpbox:disabled { cursor:default; }
  .tavern.live .lv-cmplbl { color:var(--tmute); font-size:11px;
                            cursor:pointer; }
  .tavern.live .lv-more { background:var(--tpanel); color:var(--ttext);
                          border:1px solid var(--tline); border-radius:8px;
                          padding:5px 10px; margin-top:6px; min-height:44px;
                          font:600 12px "Segoe UI", system-ui; cursor:pointer; }
  .tavern.live .lv-back { background:var(--tpanel); color:var(--ttext);
                          border:1px solid var(--tline); border-radius:8px;
                          min-height:44px; padding:0 12px;
                          font:600 12px "Segoe UI", system-ui; cursor:pointer; }
  .tavern.live .lv-cdhead { display:flex; flex-wrap:wrap; gap:8px;
                            align-items:center; margin:0 0 10px; }
  .tavern.live .lv-cdname { font:700 16px "Segoe UI", system-ui; }
  .tavern.live .lv-cdetail { display:grid;
                             grid-template-columns:minmax(0,1fr) 260px;
                             gap:14px; align-items:flex-start; }
  @media (max-width: 900px) {
    .tavern.live .lv-cdetail { grid-template-columns:1fr; }
  }
  .tavern.live .lv-core { --tcardw:88px; }
  .tavern.live .lv-flexcards { --tcardw:76px; margin-top:10px; }
  /* §5 gives the flex row its own ratio (76x100) rather than the card's
     88x116, so it cannot come from --tcardw alone. The ratio rides the ART
     now (2026-10-09): the tile is a column (art, then name in flow), so an
     aspect on the tile itself would fight the text below. */
  .tavern.live .lv-flexcards .tile .thumb { aspect-ratio:76/100; }
  .tavern.live .lv-cstat { background:var(--tcard); border:1px solid var(--tline);
                           border-radius:8px; padding:8px 10px; }
  .tavern.live .lv-cmpblock { margin-top:12px; }
  .tavern.live .lv-cmpcol { align-items:center; }
  .tavern.live .lv-cmpcol .lv-slot { width:52px; height:70px; }
  .tavern.live .lv-cmpchips { display:flex; flex-wrap:wrap; gap:6px;
                              justify-content:center; }
  .tavern.live .lv-gslot { margin-top:6px; }
  .tavern.live .lv-gtext { margin:0 0 6px; }
  .tavern.live .lv-gmd { white-space:pre-wrap; font:inherit; margin:0; }
  .tavern.live .lv-over { text-align:center; padding:22px 18px 26px; }
  .tavern.live .lv-overlabel { font:600 12px "Segoe UI", system-ui;
                               letter-spacing:.14em; text-transform:uppercase;
                               color:var(--tmute); margin:0 0 10px; }
  .tavern.live .lv-overbig { font:700 26px "Segoe UI", system-ui;
                             margin-bottom:16px; }
  .tavern.live .lv-gobtn { background:var(--tpanel); color:var(--ttext);
                           border:1px solid var(--tline); border-radius:8px;
                           min-height:44px;
                           padding:8px 14px; font:600 13px "Segoe UI", system-ui;
                           cursor:pointer; }
  /* §6.5's merged row: the checkbox, its label and what the answer DOES, on one
     line. It wraps rather than shrinking, and the 44px target is on the control
     itself (§8), not on the row. */
  .tavern.live .lv-saverow { display:flex; flex-wrap:wrap; gap:10px;
                             align-items:center; justify-content:center;
                             margin:12px 0 4px; font-size:13px; }
  .tavern.live .lv-saverow input { width:20px; height:20px; accent-color:var(--tsel); }
  .tavern.live .lv-saverow label { cursor:pointer; }
  .tavern.live .lv-saved { color:var(--tbuff); }
  .tavern.live .lv-fine { max-width:620px; margin:8px auto 0; }
  .turn { background:var(--panel); border:1px solid var(--border);
          border-radius:var(--radius); padding:10px 12px; margin-bottom:10px; }
  .turn.s-sticky { position:sticky; top:42px; z-index:9;
                   box-shadow:var(--shadow); }
  .turn.collapsed > *:not(.thead) { display:none; }
  .turn .thead { display:flex; gap:14px; align-items:baseline;
                 border-bottom:1px solid var(--gridline);
                 padding-bottom:6px; margin-bottom:8px; }
  .turn .thead.clickable { cursor:pointer; user-select:none; margin-bottom:0; }
  .turn:not(.collapsed) .thead.clickable { border-bottom:1px solid var(--gridline);
                                           margin-bottom:8px; }
  .turn.collapsed .thead.clickable { border-bottom:none; padding-bottom:6px; }
  .turn .caret { color:var(--dim); font-size:11px; }
  .tbtns { display:flex; gap:4px; margin:0 0 8px; }
  /* The three views of a turn: the TAB ROW sits above them, and the panel is
     as tall as the view on screen (2026-10-09, player call). The 2026-10-07
     shape stacked all three invisibly in one grid cell so a card never
     changed size — which read as ~400px of dead space under a short Shop
     view with the controls stranded at the bottom. With the tabs on top the
     reflow on switch is legible, so the hidden views come out of the layout
     with `display:none` (set by the JS). */
  .tviews { min-width:0; }
  .tbtn { background:transparent; color:var(--dim);
          border:1px solid var(--border); border-radius:var(--radius);
          padding:2px 10px; font:600 11px "Segoe UI", system-ui;
          cursor:pointer; text-transform:uppercase; }
  .tbtn:hover { color:var(--text-2); }
  .tbtn.on { color:var(--text); background:var(--panel2);
             border-color:rgba(255,255,255,.22); }
  .turn .tturn { font-weight:700; text-transform:uppercase; font-size:12px; }
  .turn .tmeta { color:var(--dim); font-size:12px; }
  .turn .comp { margin-left:auto; color:var(--gold); font-size:12px; }
  .brow { display:grid; grid-template-columns:86px 1fr; gap:10px;
          padding:2px 0; font-size:13px; }
  .brow .blbl { color:var(--dim); text-transform:uppercase; font-size:11px;
                padding-top:2px; }
  .brow .them { color:var(--text-2); }
  .brow-tiles { display:flex; flex-wrap:wrap; gap:6px; }
  .grw { color:var(--good); }
  .turn .note, .turn .q { font-size:12px; padding-top:4px; }
  .turn .note { color:var(--dim); }
  .turn .q { color:var(--warn); }
  .turn .phase { border-top:1px dashed var(--gridline); margin-top:8px;
                 padding-top:8px; font-size:13px; color:var(--text-2); }
  .turn .phase .pacted { color:var(--text); font-weight:600; }
  .turn .phase .pacted .pout { color:var(--dim); font-weight:400;
                               font-size:12px; }
  .turn .phase details.coach { margin-top:4px; }
  .turn .phase details.coach summary { cursor:pointer; color:var(--dim);
                                       font-size:12px; }
  .turn .phase details.coach summary:hover { color:var(--text-2); }
  .turn .phase .pplan { color:var(--text); margin-top:4px; }
  .turn .phase .v { font-weight:600; }
  .turn .phase .v-taken { color:var(--good); }
  .turn .phase .v-ignored { color:var(--bad); }
  .turn .phase .v-none, .turn .phase .v-ungraded, .turn .phase .v-pass {
    color:var(--dim); font-weight:400; }
  .turn .phase .pout { color:var(--dim); font-size:12px; }
</style>
</head>
<body>
<div id="wrap">
<div id="statebar">Waiting for the coach…</div>
<div id="freshness"></div>
<nav id="tabs">
<button class="tab on" data-tab="live">Another Round</button>
<button class="tab" data-tab="settle">Settle Up</button>
<button id="share-toggle" hidden></button>
</nav>
<div id="app">
<!-- ONE Classic | Tavern toggle per page (2026-10-09, player call). The live
     one used to sit in the TOP NAV, where it looked global and rode along to
     the Settle Up tab beside that tab's own toggle — two controls, one of
     them unthemed there (the nav's `#tabs button` rules outranked the
     segment styling). It lives at the top of the LIVE page now, the same
     place the Settle Up toggle sits in its header. -->
<div id="live-viewer-row">
<span id="live-viewer" class="vseg" title="Live page style — Tavern is the
reference layout (LIVE_VIEW_DESIGN.md): the same facts, no verdicts">
<button data-v="classic" class="on">Classic</button>
<button data-v="tavern">Tavern</button>
</span>
</div>
<section id="col-decide"></section>
<section id="col-ref"></section>
<!-- The Tavern Live view's own container (2026-10-09). It is separate from the
     two classic panes on purpose: the Tavern renderer clears ITS container, so
     switching back to Classic finds #col-decide and #col-ref still there. A
     shared container meant the first toggle to Tavern destroyed the classic
     panes and the way back threw - measured in a browser, not guessed. -->
<div id="live-tavern" hidden></div>
</div>
<section id="settle">
<div class="s-head">
<select id="settle-select"><option value="">Loading saved replays…</option></select>
<span id="settle-mode" class="vseg" hidden
      title="How to read this game: Summary is the turn plus its action rail;
Step through replays the turn one action at a time">
<button data-m="summary" class="on">Summary</button>
<button data-m="step">Step through</button>
</span>
<span id="settle-viewer" class="vseg" title="Settle Up viewer style — Tavern is
the single-turn design (REPLAY_VIEWER_DESIGN.md)">
<button data-v="classic" class="on">Classic</button>
<button data-v="tavern">Tavern</button>
</span>
<button id="settle-rebuild" title="Re-derive this saved game from its own
source log — upgrades older saves to the current viewer's data (replays
the game; the session log must still exist)">Rebuild</button>
<button id="settle-folder" title="Open the folder the saved replays live in">Open folder</button>
</div>
<div id="settle-game"><div class="s-empty">Pick a saved game to see it turn by turn.</div></div>
</section>
<div id="release-tag" hidden></div>
</div>
<script>
//: Per-run access key (2026-10-08 audit): the server mints one at startup and
//: answers nothing without it, so a local process cannot read the live board
//: (or the opponent's name in it) or flip the share consent. The server puts
//: the REAL key here as it serves the page; every fetch below rides it through
//: auth(). Card art (/img, /card) is exempt: it is not data, and an <img src>
//: cannot carry a header.
const BL_TOKEN = "__BL_TOKEN__";
function auth(u) {
  return u + (u.includes("?") ? "&" : "?")
    + "token=" + encodeURIComponent(BL_TOKEN);
}
let _lastPayload = null;
//: The last payload the page RENDERED, so the viewer toggle can redraw from it
//: instead of waiting up to 300ms for the next poll (2026-10-09).
let _lastParsed = null;
let _etag = null;
let _pollBusy = false;
//: Epoch seconds of the advice currently on screen, and how old it may get
//: before the page says so. The ticker below is separate from render()
//: because render() only runs when the payload CHANGES: once live.py wedges,
//: the server answers 304 forever and nothing would ever redraw the age.
let _generated = null;
//: Epoch MILLISECONDS of the last ANSWER from the coach, whatever its status —
//: a 304 counts, because it is the server saying it is still there. This is the
//: only honest liveness signal the page has, and it is the reason the line below
//: stopped accusing a working coach: advice that has not changed says nothing
//: about whether the coach is alive. Between buy phases there is nothing to
//: push, and that gap is a median 81 seconds (measured over 13 real buy phases)
//: against the 8 this used to alarm on — so for most of the time a player had
//: the overlay open, it told them a healthy coach was "frozen, not live".
let _lastAnswer = 0;
//: True when the last poll came back 403 (2026-10-08): the server does not
//: accept this tab's access key. It is its own state rather than an age,
//: because no amount of waiting fixes it — each run mints a new key, so this
//: is what a tab left open across a restart meets.
let _keyRefused = false;
const STALE_AFTER = 8;   // when to say how old the advice is
const LOST_AFTER = 6;    // seconds with NO answer at all before it is the coach
//: The whole decision the freshness line makes, as a pure function so the suite
//: can run it under node instead of trusting the wording by eye. `alarm` is true
//: only when the coach stopped talking; old advice on its own never alarms.
//: A refused key outranks both readings: that is the server saying this tab is
//: not allowed to read the advice, not the coach being quiet.
function freshnessLine(ageSec, silentSec, keyRefused) {
  if (keyRefused) {
    return {alarm: true,
            text: 'This overlay is from an earlier run — open it again from '
                  + 'the launcher'};
  }
  const ago = ageSec >= 120 ? Math.floor(ageSec / 60) + ' min'
             : ageSec >= 60 ? '1 min'
             : Math.max(0, Math.round(ageSec)) + 's';
  if (silentSec > LOST_AFTER) {
    return {alarm: true,
            text: 'Lost contact with the coach — last read ' + ago + ' ago'};
  }
  if (ageSec < STALE_AFTER) return {alarm: false, text: ''};
  return {alarm: false,
          text: 'Read from ' + ago + ' ago — it updates when your next shop '
                + 'opens'};
}
async function poll() {
  if (_pollBusy) return;  // a slow response must not pile up ticks
  _pollBusy = true;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(auth('/analysis'), {
      signal: ctrl.signal,
      headers: _etag ? {'If-None-Match': _etag} : undefined,
    });
    clearTimeout(timer);
    // A refused key is not an answer, and not advice that went quiet either
    // (2026-10-08): the server is saying it will not serve this tab. Left
    // unsaid, the freshness line reported it as old advice and told the player
    // to wait for the next shop.
    _keyRefused = (r.status === 403);
    if (!_keyRefused) _lastAnswer = Date.now();
    if (r.status !== 304) {          // 304 = unchanged: header only, no body,
      const raw = await r.text();    // no JSON.parse, no DOM work
      _etag = r.headers.get('ETag');
      if (raw !== _lastPayload) {    // unchanged payloads never rebuild the
        _lastPayload = raw;          // DOM (rebuilding every second made
        const parsed = JSON.parse(raw);  // thumbnails flicker)
        _generated = parsed.generated || null;
        render(parsed);
      }
    }
  } catch (e) { /* keep last frame — the freshness ticker reports it */ }
  finally { _pollBusy = false; }
}
function tickFreshness() {
  const node = document.getElementById('freshness');
  if (!node) return;
  const silent = (Date.now() - _lastAnswer) / 1000;
  // Nothing to say at all: no advice yet AND the coach is answering. A refused
  // key is always said, however fresh the frame it is sitting next to.
  if (_generated == null && !_keyRefused && silent <= LOST_AFTER) {
    node.className = ''; node.textContent = ''; return;
  }
  const age = _generated == null ? 0 : Date.now() / 1000 - _generated;
  const line = freshnessLine(age, silent, _keyRefused);
  node.className = line.alarm ? 'on' : (line.text ? 'info' : '');
  node.textContent = line.text;
}
setInterval(tickFreshness, 1000);
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
// Per-card display metadata from the payload ({tier, text}) — golden ids
// resolve to their base id like the server's own cache does.
let CARDS = {};
const _warmed = new Set();
function cardMeta(cid) {
  return CARDS[String(cid || '').replace(/_G$/, '')] || {};
}
// The tier badge in every name: "*1 Suspicious Prisoner guard". Cards the
// meta DBs carry no tier for (heroes, trinkets) show bare names.
function badgeName(cid, name) {
  const meta = cardMeta(cid);
  return (meta.tier ? '*' + meta.tier + ' ' : '') + (name || '');
}
// Hover tooltip: the full HearthstoneJSON render (framed card with text) when
// upstream has it, else the card text from the meta DB, else nothing (and
// the old portrait zoom stays active). The page pre-warms /card fetches for
// every card in the payload, so the first hover of a phase may still be
// loading but every later hover is instant.
const tip = document.createElement('div');
tip.id = 'tip';
tip.hidden = true;
document.body.appendChild(tip);
let tipCid = null;
function hoverCard(elm, cid, name) {
  const meta = cardMeta(cid);
  const id = String(cid || '').replace(/_G$/, '');
  tipCid = id;
  let shown = false;
  const show = node => {
    if (tipCid !== id) return;  // a later hover superseded this one
    tip.innerHTML = '';
    tip.appendChild(node);
    const r = elm.getBoundingClientRect();
    tip.style.left =
      Math.max(4, Math.min(r.left - 100, window.innerWidth - 300)) + 'px';
    tip.style.top =
      Math.max(4, Math.min(r.bottom + 2, window.innerHeight - 400)) + 'px';
    tip.hidden = false;
    shown = true;
    elm.classList.remove('canzoom');  // tooltip replaces the portrait zoom
  };
  // Text box first (instant, from the meta DB) when we have text.
  if (meta.text) {
    const box = el('div', 'tipbox');
    box.appendChild(el('div', 'tipname', badgeName(cid, name)));
    box.appendChild(el('div', 'tiptext', meta.text));
    show(box);
  }
  // The full render upgrades the tooltip when upstream has it; a 404 keeps
  // the text box — or, with no text either, the old portrait zoom.
  const big = new Image();
  big.className = 'tiprender';
  big.onload = () => show(big);
  big.onerror = () => { if (tipCid === id && !shown) tipCid = null; };
  big.src = '/card/' + id + '.png';
}
function leaveCard() { tipCid = null; tip.hidden = true; }
function box(title, body) {
  const b = el('div', 'box');
  b.appendChild(el('h3', null, title));
  if (body) b.appendChild(body);
  return b;
}
// Card ids upstream has NO art for at all (the /img and /card chains both
// 404'd), fetched once from GET /artmiss: thumb() renders the placeholder
// directly, so they stop paying a 404 round-trip per tile per rebuild. The
// list is portrait misses only — a card whose tooltip render is missing
// still gets its tile. Keyed by the EXACT id requested — /img does not
// strip the golden _G suffix.
const MISSES = new Set();
fetch(auth('/artmiss')).then(r => r.json()).then(j => {
  (j.misses || []).forEach(cid => MISSES.add(cid));
}).catch(() => {});
// Card art thumbnail (img_cache/ via /img/<id>.png, fetched on demand from
// the portrait source — see PORTRAIT_URLS). Hides itself gracefully when no
// art is cached and upstream has none either.
// Hover shows the full card render (framed layout WITH text) via /card/,
// falling back to a text box from the meta DB, then to the old portrait zoom.
function thumbPh(cid, name) {
  const ph = document.createElement('span');
  ph.className = 'thumb ph';
  ph.textContent = (name || '?').trim().charAt(0).toUpperCase();
  ph.onmouseenter = () => hoverCard(ph, cid, name);
  ph.onmouseleave = leaveCard;
  return ph;
}
function thumb(cid, name) {
  if (MISSES.has(cid)) return thumbPh(cid, name);
  const img = document.createElement('img');
  img.className = 'thumb canzoom';
  img.src = '/img/' + cid + '.png';
  img.alt = '';
  img.onmouseenter = () => hoverCard(img, cid, name);
  img.onmouseleave = leaveCard;
  img.onerror = () => {
    // No art available for this id (both chains 404'd — see _fetch_render):
    // a same-size placeholder keeps every row aligned. The id joins MISSES so
    // sibling tiles of the same card skip the 404 too.
    MISSES.add(cid);
    img.replaceWith(thumbPh(cid, name));
  };
  return img;
}
// A horizontal game-like card tile: thumb on top, name below, sub-line
// (price / score / count) under that. `sub` may be a string or a ready-made
// element (the Tavern's two-color stat line), which is appended as-is.
function tile(cid, name, sub, opts) {
  opts = opts || {};
  const t = el('div', 'tile' + (opts.cls ? ' ' + opts.cls : ''));
  // The plain-text full name, alongside the hover card render: a name that had
  // to wrap or clamp is still readable in full by hovering anywhere on the tile
  // (fix list round 2 item 3).
  t.title = name || '';
  const img = thumb(cid, name);
  if (opts.golden) img.classList.add('golden');
  t.appendChild(img);
  // `noname`: the pick screen names an option ONCE, in the fixed-height line
  // under it (fix list round 1 item 2 / round 2 item 1 — the tile's own caption
  // is clamped to the card's width and read as a truncated second name).
  if (!opts.noname) {
    const nm = el('div', 'tname', badgeName(cid, name));
    if (opts.n > 1) nm.appendChild(el('span', 'xcount', '  ×' + opts.n));
    t.appendChild(nm);
  }
  if (sub) {
    const s = el('div', 'tsub');
    if (sub.nodeType) s.appendChild(sub);
    else s.textContent = sub;
    t.appendChild(s);
  }
  return t;
}
// The stat line under a Tavern card: attack gold, health red (design §6/§7),
// as one "4/4" the eye splits. BOTH unknown (a passed-through minion carries
// no stats at all) means no line — "?/?" is a question the page cannot
// answer, not a stat (2026-10-09, player call).
function statSub(m) {
  if (!m || (m.atk == null && m.health == null)) return null;
  const s = document.createElement('span');
  s.appendChild(el('span', 'stat-atk', String(m.atk ?? '?')));
  s.appendChild(el('span', 'stat-sep', '/'));
  s.appendChild(el('span', 'stat-hp', String(m.health ?? '?')));
  return s;
}
// Comps panel: one playable comp as a clickable row. Clicking expands its
// required cards (core, then addons) — owned faded, banned-this-game struck
// out, missing fully opaque, same language as the Looking-for box; clicking
// again collapses. The open set survives the rebuilds (a rebuild
// drops the DOM but re-opens whatever was open). The collapsed row already
// says how much of the core you own, so expanding is only for the detail.
const _openComps = new Set();
// Expanded bodies are cached keyed by slug + the exact rows (core/addons
// with their owned/banned flags — those are compTiles' only inputs, and
// keying on them is what keeps a just-bought card from still reading
// "have"/"missing"). appendChild re-parents, so the <img>s persist across
// the full-DOM rebuilds instead of being re-requested every tick.
const _compBodyCache = new Map();
function compBody(c) {
  const key = c.slug + '|' + JSON.stringify([c.core, c.addons]);
  let node = _compBodyCache.get(key);
  if (!node) {
    node = el('div', 'cbodyinner');
    // The curated guidance that ships with the comp DB. Until 2026-10-02 it
    // was read by nothing: an expanded row showed card chips only, so the
    // written advice (and all 20 mined guides) never reached a player.
    const g = el('div', 'cguidance');
    if (c.difficulty) {
      g.appendChild(el('div', 'cline', 'Difficulty: ' + c.difficulty));
    }
    if (c.when_to_commit) {
      g.appendChild(el('div', 'cline', 'Commit when: ' + c.when_to_commit));
    }
    if (c.summary) g.appendChild(el('div', 'cline dim', c.summary));
    (c.enablers || []).forEach(e => {
      g.appendChild(el('div', 'cline dim', '· ' + e));
    });
    if (g.children.length) node.appendChild(g);
    node.appendChild(compTiles(c));
    // Prose and the full guide are fetched on first expand and the resulting
    // node cached per slug (the body itself is cached across full-DOM
    // rebuilds, so the fetched text survives the 3/s re-render).
    const slot = el('div', 'cguideslot');
    node.appendChild(slot);
    if (c.has_guide) loadGuide(c.slug, slot);
    if (_compBodyCache.size > 300) _compBodyCache.clear();
    _compBodyCache.set(key, node);
  }
  return node;
}
const _guideCache = new Map();
function loadGuide(slug, slot) {
  const cached = _guideCache.get(slug);
  if (cached) { slot.appendChild(cached); return; }
  fetch(auth('/guide/' + slug)).then(r => r.ok ? r.json() : null).then(j => {
    if (!j) return;
    const wrap = el('div', 'cguidefull');
    if (j.how_to_play) wrap.appendChild(el('div', 'cline', j.how_to_play));
    if (!j.how_to_play && !j.markdown) {
      // Say so rather than showing an empty box: this comp has no written
      // guide yet, and the commit line above is all the curated advice.
      wrap.appendChild(el('div', 'cline dim',
        'No written guide for this comp yet — the commit line is the '
        + 'curated advice.'));
    }
    if (j.markdown) {
      wrap.appendChild(el('div', 'cline dim',
        j.curated ? 'Full guide' : 'Full guide (mined from commentary)'));
      wrap.appendChild(el('pre', 'cguidemd', j.markdown));
    }
    _guideCache.set(slug, wrap);
    slot.appendChild(wrap);
  }).catch(() => { /* offline: the commit line is still on screen */ });
}
function compTiles(c) {
  const tiles = el('div', 'tiles');
  [['core', 'core'], ['addons', 'addons']].forEach(([_label, key]) => {
    (c[key] || []).forEach(x => {
      const sub = x.banned ? 'banned' : (x.owned ? 'have' : null);
      const cls = 'comprow ' + (x.banned ? 'bannedrow'
                   : x.owned ? 'owned' : 'missing');
      tiles.appendChild(tile(x.card, x.name, sub, {cls: cls}));
    });
  });
  return tiles.children.length
    ? tiles : el('div', 'none', 'no card list in the meta DB');
}
function compRow(c) {
  const open = _openComps.has(c.slug);
  // Inside the ban-detection window the panel lists EVERY comp; a row whose
  // tribe the pool hasn't confirmed yet is dimmed and labeled — it could
  // still be banned, and it stays until the 5/5 set lands.
  const unconf = c.tribe_confirmed === false;
  const head = el('div', 'crowhead');
  const arrow = el('span', 'carrow', open ? '▾' : '▸');
  head.appendChild(arrow);
  const core = c.core || [];
  head.appendChild(el('span', 'cname', c.name));
  head.appendChild(el('span', 'cstat',
    core.length + ' core · '
    + core.filter(x => x.owned).length + ' owned'
    + (unconf ? ' · tribe unconfirmed' : '')));
  const body = el('div', 'cbody');
  // Collapsed rows build their tiles lazily (on first expand) so a 21-comp
  // panel doesn't queue 100+ card fetches up front; an open row reuses the
  // cached body (see _compBodyCache).
  body.hidden = !open;
  if (open) body.appendChild(compBody(c));
  head.onclick = () => {
    const nowOpen = !_openComps.has(c.slug);
    if (nowOpen) _openComps.add(c.slug); else _openComps.delete(c.slug);
    head.classList.toggle('open', nowOpen);
    arrow.textContent = nowOpen ? '▾' : '▸';
    body.hidden = !nowOpen;
    if (nowOpen && !body.children.length) body.appendChild(compBody(c));
  };
  const wrap = el('div', 'crow' + (unconf ? ' unconf' : ''));
  wrap.appendChild(head);
  wrap.appendChild(body);
  return wrap;
}
// (The step-kind chip map lived here: LV/PICK/BUY/SELL/ROLL/CAST/PLAY/HOLD/
// SWAP/DISC, one per kind in value._STEP_KINDS. It went with the numbered plan
// — the chips labelled instructions, and the live page does not render any
// (2026-10-06, PIVOT.md). value._STEP_KINDS still exists: it is how the plan's
// steps are typed for the review and the corpus.)
// The two end-of-game POSTs, ONE place each (2026-10-09): the classic card and
// the Tavern game-over card both offer them, and the 409 branch below is the
// normal race rather than an error — the review replays the game twice
// off-thread (~10 s) while the card appears the moment the game ends, so a
// premature click has to stay retryable ("it failed to save my replay",
// 2026-10-07). Two copies of that rule is how one of them loses it.
async function postAutoSave(cb, revert) {
  cb.disabled = true;
  try {
    const r = await fetch(auth('/review/auto-save'), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: cb.checked}),
    });
    if (!r.ok) revert();                 // the file on disk is the truth
  } catch (e) {
    revert();
  }
  cb.disabled = false;
  poll();
}
async function postSaveReplay(btn) {
  btn.disabled = true;
  try {
    const r = await fetch(auth('/review/save'), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: '{}',
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok) { btn.textContent = 'Saved ✓'; return; }
    btn.disabled = false;
    btn.textContent = r.status === 409 ? 'Still building — try again'
                                       : (j.error || 'Save failed');
  } catch (e) {
    btn.textContent = 'Save failed';
    btn.disabled = false;
  }
}
//: Take the Tavern layout off screen. It has its own container, so this only
//: clears that container and the class its renderer set — with neither present
//: the classic page is exactly what it always was. A viewer that is no longer
//: drawing must not leave its last frame behind: the first-run card is CLASSIC
//: even in Tavern mode (§6.5 has the game-over card, and there is no design for
//: a first run), and it used to draw behind a stale Tavern screen.
function lvClearTavern() {
  const lt = document.getElementById('live-tavern');
  if (lt) { lt.hidden = true; lt.innerHTML = ''; }
  document.getElementById('app').classList.remove('tavern-on');
  // The classic strip is the classic renderer's, and it fills it right after
  // this. It is UNHIDDEN here rather than there so the two viewers cannot both
  // leave it hidden (fix list round 2 item 7 hides it while it is empty).
  const bar = document.getElementById('statebar');
  if (bar) bar.hidden = false;
}
function renderWelcome(a) {
  const decide = document.getElementById('col-decide');
  const ref = document.getElementById('col-ref');
  const statebar = document.getElementById('statebar');
  renderShareToggle(a.share);
  renderRelease(a.release);
  decide.innerHTML = '';
  ref.innerHTML = '';
  statebar.textContent = '';
  // This card carries its own headline, so the strip is not just blank — an
  // empty one is a rounded bar with nothing in it (fix list round 2 item 7).
  statebar.hidden = true;
  const card = el('div', 'welcome');
  // `title` only exists on the end-of-game card ("Game over"); a first-run card
  // is headed by the product name.
  card.appendChild(el('h1', 'w-title', a.title || a.product || "Bob's Ledger"));
  card.appendChild(el('div', 'w-tag', a.tagline || ''));
  card.appendChild(el('div', 'w-status', a.status || ''));
  card.appendChild(el('div', 'w-hint', a.hint || ''));
  if (a.steps) card.appendChild(el('pre', 'w-steps', a.steps));
  card.appendChild(el('div', 'w-priv', a.privacy || ''));
  // The question, only while it is a question. Once it has an answer the
  // control lives in the corner (`renderShareToggle`), where it stays
  // reachable for the whole session instead of only on this card.
  if (a.share && a.share.ask) card.appendChild(shareRow(a.share));
  // The review (2026-10-06, PIVOT.md Phase 2). The plan is not on this page
  // any more — this is where a player goes to see it, and the whole point is
  // that it appears only once the game it describes is over. A plain link
  // rather than a fetch: the report is a standalone page, and opening it in
  // its own tab is what lets a player keep it.
  if (a.game_over) {
    // Save the replay (2026-10-06 tab work): persists this game's review so
    // the Settle Up tab can bring it back. A click is one POST; the button
    // reports its own outcome in place rather than navigating. The old
    // "Settle up" link went when the tab landed (2026-10-07) — the plan is
    // read in the tab now, over saved games.
    const row = el('div', 'w-share');
    const auto = a.auto_save || {};
    // The checkbox (2026-10-07): when it is on, the replay is written while
    // the review builds — no click — so the button would only make a second
    // copy. The answer lives on disk behind /review/auto-save, and the poll
    // redraws this card, so what it shows cannot lag the click.
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'save-all-replays';
    cb.checked = !!auto.enabled;
    const lbl = document.createElement('label');
    lbl.htmlFor = cb.id;
    lbl.className = 'w-share-q';
    lbl.textContent = auto.label || 'Save every replay automatically';
    cb.onchange = () => postAutoSave(cb, () => { cb.checked = !cb.checked; });
    if (auto.enabled) {
      row.appendChild(el('span', 'w-share-q',
                         'Saved to the Settle Up tab automatically ✓'));
    } else {
      const save = el('button', 'w-share-btn', 'Save replay');
      save.onclick = () => postSaveReplay(save);
      row.appendChild(save);
    }
    row.appendChild(cb);
    row.appendChild(lbl);
    card.appendChild(row);
  }
  decide.appendChild(card);
}
// Consent lives on the welcome card, because that is the one screen every
// player sees before there is anything to advise, and because the privacy
// sentence above it is now built from the answer. The poll that follows
// redraws the card from the server's state, so the words can't lag the click.
function postShare(share) {
  fetch(auth('/share'), {method: 'POST',
                   headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({share: share})}).then(poll);
}
function shareRow(s) {
  const row = el('div', 'w-share');
  if (!s || !s.ask) return row;   // decided: the corner control owns it now
  row.appendChild(el('span', 'w-share-q', s.question || ''));
  const button = (label, choice) => {
    const b = el('button', 'w-share-btn', label);
    b.onclick = () => postShare(choice);
    return b;
  };
  row.appendChild(button(s.yes || 'Yes, share', true));
  row.appendChild(button(s.no || 'No thanks', false));
  return row;
}
// The corner sharing control (2026-10-07). Rendered from EVERY payload, not
// just the welcome card, so "stop sharing" is one click away for the whole
// session instead of only at a game's start or end. Hidden while the question
// is unanswered: the card asks, and two controls asking at once is how a
// consent question turns into a shrug.
function renderShareToggle(s) {
  const b = document.getElementById('share-toggle');
  if (!b) return;
  if (!s || s.ask) { b.hidden = true; return; }
  const on = s.status === 'on';
  b.hidden = false;
  b.textContent = s.toggle || (on ? 'Stop sharing' : 'Turn sharing on');
  b.title = on
    ? 'Sharing one small summary per game: your decisions and the outcome, '
      + 'with no names. Click to stop.'
    : 'Nothing is being shared. Click to send a summary of each game from '
      + 'now on.';
  b.onclick = () => postShare(!on);
}
// The release stamp (2026-10-07): "release: <version>" bottom-right, from
// every payload — live, welcome and game-over alike, so a screenshot always
// names the release. Pure in the version, like freshnessLine(), so the
// suite can run it under node; renderRelease is the DOM glue.
function releaseTag(v) {
  if (!v) return {hidden: true, text: ''};
  return {hidden: false, text: 'release: ' + v};
}
function renderRelease(v) {
  const tag = document.getElementById('release-tag');
  if (!tag) return;
  const t = releaseTag(v);
  tag.hidden = t.hidden;
  tag.textContent = t.text;
}
// --- Live, Tavern layout (LIVE_VIEW_DESIGN.md, 2026-10-09) ------------------
// The same payload the classic page draws, laid out as REFERENCE MATERIAL:
// facts, counts and statistics — never a verdict, a ranking or an imperative
// (§1), and never a guessed number (§6.4). Every row appears only when its data
// exists (§5), and a value that was not read is a dash.
//
// It is scoped to `.tavern.live`, so the Settle Up Tavern rules and these
// cannot leak into each other: the two views share the TOKENS, not the
// components. The classic renderer below is untouched — that is what the
// toggle's Classic side means, exactly as it does for the review.
let _liveViewer = 'classic';
try { _liveViewer = localStorage.getItem('bl-live-viewer') || 'classic'; }
catch (e) { /* private mode */ }
//: Which rail tab is open. Session-only: the design persists the pick screen's
//: own order/stats choices (§4.3), not this.
//: §4.1's second tab row — `Shop | Comps | Lobby` — is the SCREEN selector, so
//: the facts table is not one of its tabs: it lives in the rail beside every
//: screen (§4.2 puts the facts table in the rail, and reference material is
//: worth more visible than hidden). Session-only, like the comp view state.
let _liveTab = 'shop';
const LIVE_TABS = [['shop', 'Shop'], ['comps', 'Comps'], ['lobby', 'Lobby']];

function lvOrdinal(p) {
  const suf = ([11, 12, 13].includes(p % 100)) ? 'th'
    : ({1: 'st', 2: 'nd', 3: 'rd'}[p % 10] || 'th');
  return p + suf;
}
//: Unread is a dash in --mute, never a guess, and never the classic page's "?"
//: (§6.4 — a "?" next to a number reads as part of the number).
function lvVal(v) { return v == null || v === '' ? '—' : String(v); }

function lvPanel(title, body) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, title));
  p.appendChild(body);
  return p;
}
//: One label/value row (§5): label in --mute, value in --text.
function lvKV(label, value) {
  const d = el('div', 'lv-kv');
  d.appendChild(el('span', null, label));
  d.appendChild(el('b', value == null || value === '—' ? 'miss' : null,
                   lvVal(value)));
  return d;
}
//: A card with its one-line caption UNDERNEATH (§4.2), rather than the tile's
//: name over the art: the caption is the data line, and it needs the width.
//: `opts.kind` adds a corner tag naming what the card IS ("Spell") — one art
//: treatment for every card, with the kind said in a tag rather than drawn as a
//: different frame (fix list round 2 item 3).
function lvCard(cid, name, cap, opts) {
  const wrap = el('div', 'lv-card');
  const t = tile(cid, name, null, {});
  if (opts && opts.kind) t.appendChild(el('span', 'tag-kind', opts.kind));
  wrap.appendChild(t);
  wrap.appendChild(el('span', 'lv-cap', cap));
  return wrap;
}
function lvEmptyRow(text) { return el('div', 'lv-empty', text); }

//: §4.2 status bar: the hero, then six numbers. Gold takes the currency colour;
//: everything else is --text, and nothing here is a judgement. Before the first
//: shop of a game there is no hero to name, and the slot says what the page is
//: waiting for instead (fix list round 2 item 2); a number nobody has read is a
//: dash in --mute (§6.4), not a guess.
function lvStatus(a) {
  const bar = el('div', 'lv-status');
  bar.appendChild(a.hero
    ? el('span', 'lv-hero', a.hero)
    : el('span', 'lv-hero waiting', 'Waiting for the next shop to open'));
  const st = (label, value, cls) => {
    const d = el('span', 'lv-st' + (cls ? ' ' + cls : ''));
    d.appendChild(el('small', null, label));
    const unread = value == null || value === '';
    d.appendChild(el('b', unread ? 'miss' : null, lvVal(unread ? null : value)));
    return d;
  };
  bar.appendChild(st('Gold', a.gold, 'gold'));
  bar.appendChild(st('Tier', a.tier));
  bar.appendChild(st('HP', a.health == null ? null
                     : a.health + (a.armor ? '+' + a.armor : '')));
  bar.appendChild(st('Turn', (a.scenario || {}).turns));
  bar.appendChild(st('Place', a.current_place ? lvOrdinal(a.current_place)
                                              : null));
  return bar;
}
//: The waiting state (fix list round 2 item 2): the status bar with everything
//: dashed, and one line saying what the page is waiting for. The design's §6.1
//: asked for four dashed skeleton cards here; the player's call replaces them —
//: they read as "thick dash bars" with no information in them, and the sentence
//: says the same thing.
function lvWaiting(a) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, 'Shop'));
  p.appendChild(el('p', 'lv-note', 'Reading the shop. This updates when your '
                                   + 'next shop opens.'));
  if (a.status) p.appendChild(el('p', 'lv-inline', a.status));
  return p;
}
//: §4.2's ONE tribe row. Out-of-play tribes are struck through and never read
//: as a ban the player could undo; tapping any chip corrects the set, which is
//: what makes every comp filter downstream exact.
//: ACTIVE is an amber outline, INACTIVE is dimmed (fix list round 1 item 3), and
//: a tribe that is out of play appears ONCE — it is in the roster AND in
//: `out_of_pool`, so iterating both printed Naga twice.
function lvTribes(a) {
  const row = el('div', 'lv-tribes');
  row.appendChild(el('span', 'lv-lbl', a.bans_manual
    ? 'Lobby tribes · tap to correct'
    : 'Lobby tribes · ' + (a.tribes_seen || 0) + '/5 confirmed'));
  const oop = new Set(a.out_of_pool || []);
  const picked = new Set(a.bans_manual ? (a.banned || []) : []);
  (a.tribe_roster || []).filter(t => !oop.has(t)).forEach(t => {
    const on = picked.has(t);
    const chip = el('span', 'lv-chip ' + (on ? 'active' : 'dim'), t);
    chip.title = on ? 'Banned in this game — tap to clear'
                    : 'In play — tap to ban';
    chip.onclick = () => {
      if (picked.has(t)) picked.delete(t);
      else picked.add(t);
      postBans([...picked]);
      chip.classList.toggle('active');
      chip.classList.toggle('dim');
    };
    row.appendChild(chip);
  });
  // Out of play, LAST and struck through. The payload's roster includes these
  // (it is the canonical list of tribes), so the filter above is what keeps the
  // row from saying Naga twice.
  oop.forEach(t => {
    const chip = el('span', 'lv-chip out', t);
    chip.title = 'Out of play: rotated by a patch, so no lobby can offer it. '
               + 'Not a ban.';
    row.appendChild(chip);
  });
  return row;
}
//: §4.2 Facts tab. The numbers, and only the numbers: the classic strip's
//: "FRAGILE — … a 14-hit ends it" and its "favored/behind" forecast are
//: verdicts, and they are replaced here by the same values as rows.
//: "Lethal at" is gone (fix list round 1 item 5 / round 2 item 6): it printed
//: effective HP a second time under a second name.
function lvFacts(a) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, 'Facts'));
  const fr = a.fragility || {};
  if (fr.eff_health != null) p.appendChild(lvKV('Effective HP', fr.eff_health));
  if (fr.last_hit != null) p.appendChild(lvKV('Took last fight', fr.last_hit));
  if (fr.recent3 != null) {
    p.appendChild(lvKV('Last 3 fights', '−' + fr.recent3));
  }
  if (fr.cap != null) p.appendChild(lvKV('Damage cap', fr.cap));
  // Board stats, you vs last seen (§1): "51 vs ~59 (lobby avg)", never
  // "favored" or "strong". An exact read is the opponent we fought; the lobby
  // figure is a median over the lobby's recent fights and says so (fix list
  // round 1 item 5: "you vs lobby avg", not a bare "lobby").
  const bs = a.board_stats;
  let vs = null;
  if (bs != null && a.opp_stats != null) {
    vs = bs + ' vs ' + a.opp_stats
       + (a.opp_age ? ' (seen ' + a.opp_age + ' round'
          + (a.opp_age === 1 ? '' : 's') + ' ago)' : '');
  } else if (bs != null && a.opp_lobby != null) {
    vs = bs + ' vs ~' + a.opp_lobby + ' lobby avg';
  } else if (bs != null) {
    vs = String(bs);
  }
  p.appendChild(lvKV('Board stats — you vs lobby avg', vs));
  if (a.level_cost != null) {
    p.appendChild(lvKV('Level up', a.tier != null && a.tier < 6
      ? 'tier ' + a.tier + ' → ' + (a.tier + 1) + ' for ' + a.level_cost + 'g'
      : a.level_cost + 'g'));
  }
  p.appendChild(el('p', 'lv-note',
    'Reference only. Numbers are observational, not causal.'));
  return p;
}
//: §4.4's comp screens, and the state they read. Everything here is a VIEW
//: choice (which comp is open, how the list is ordered, which tribes are shown),
//: never a choice about the game, so none of it is persisted and none of it
//: touches the analysis.
let _liveComp = null;              // slug while Detail is open, else Browse
let _liveCompSort = 'tier';        // tier | overlap | avg_place (default tier)
let _liveCompFilter = new Set();   // tribe labels; empty = every tribe in play
let _liveCompMore = new Set();     // tier groups whose rows past the cap show
let _liveCompare = new Set();      // up to three slugs, in the order picked
const LIVE_COMP_ROWS = 5;          // §4.4: "about five visible rows"
const LIVE_COMPARE_MAX = 3;        // §4.4: "Up to three comps"

//: A comp's `tribe` and the lobby's set are the same canonical vocabulary
//: ("Murloc", "Mech"). A compound ("Demon/Quilboar") matches on any shared part
//: — the rule `tribes.matches` applies on the server — and "All" (the
//: Amalgam-class marker) is in every tribe. A comp with no tribe is Mixed.
function lvTribeHit(tribe, want) {
  const parts = t => String(t || '').split('/').map(s => s.trim().toLowerCase());
  if (!tribe) return false;
  if (String(tribe).toLowerCase() === 'all') return true;
  return parts(tribe).some(p => parts(want).includes(p));
}
function lvCompTribe(c) { return c.tribe || 'Mixed'; }

//: §5's core slot: 34x46 in Browse, 52x70 in Compare (one CSS rule each), 5px
//: radius; owned = a 2px --buff border on --tcard, missing = 1px dashed --line
//: at 50% opacity. The slot carries the card's own ART, dimmed when you do not
//: own it (fix list round 1 item 6) — a row of coloured rectangles said nothing
//: about WHICH core cards a comp wants. The hover shows the full card render
//: (the same `thumb` handler the tiles use) and the tooltip names it, so the
//: state is never carried by colour alone (§8).
function lvSlot(x, bare) {
  const state = x.banned ? 'banned'
              : x.owned ? 'board' : x.in_hand ? 'hand' : 'miss';
  const s = el('span', 'lv-slot ' + state);
  if (!bare && x.card) s.appendChild(thumb(x.card, x.name));
  s.title = (x.name || x.card || '') + (x.card ? ' — ' : '')
          + (state === 'banned' ? 'banned this game'
             : state === 'board' ? 'on board'
             : state === 'hand' ? 'in hand' : 'not owned');
  return s;
}
function lvSlotCap(x) {
  return x.banned ? 'banned this game'
       : x.owned ? 'on board' : x.in_hand ? 'in hand' : 'not owned';
}
function lvSlots(cards) {
  const wrap = el('span', 'lv-slots');
  (cards || []).forEach(x => wrap.appendChild(lvSlot(x)));
  if (!wrap.children.length) wrap.appendChild(el('span', 'lv-empty', 'no core list'));
  return wrap;
}
//: What the slot colours mean (fix list round 1 item 6: "legend for any slot
//: colors"). The swatches are the slot element itself, so the legend cannot
//: drift from what the rows draw.
function lvSlotLegend() {
  const row = el('div', 'lv-legend');
  [['board', 'on board'], ['hand', 'in hand'],
   ['miss', 'not owned'], ['banned', 'banned this game']].forEach(([cls, label]) => {
    const item = el('span', 'lv-legitem');
    item.appendChild(lvSlot({owned: cls === 'board', in_hand: cls === 'hand',
                             banned: cls === 'banned'}, true));
    item.appendChild(el('span', 'lv-leglbl', label));
    row.appendChild(item);
  });
  return row;
}
//: §4.4 counts a core card owned when it is on the board OR IN HAND. The
//: payload's `owned` flag is the classic panel's board-only rule, so the Tavern
//: count reads both — the design's own wording, and the board is not the only
//: place a comp piece can be.
function lvOwned(cards) {
  return (cards || []).filter(x => x && (x.owned || x.in_hand)).length;
}

//: §4.4 Browse, one row:
//: `[Comp name + tribe] [core-card slots] [N of M owned] [avg placement]`.
//: The average placement comes from this project's own corpus and is a dash when
//: the corpus has never seen the comp — absent beats invented.
function lvCompRow(a, c) {
  const core = c.core || [];
  const st = c.stats || null;
  const row = el('div', 'lv-crow');
  if (st && st.low_sample) row.classList.add('low');
  const name = el('span', 'lv-cname');
  const open = el('b', 'lv-copen', c.name || c.slug);
  open.title = 'Open the comp';
  open.onclick = () => { _liveComp = c.slug; renderLiveTavern(a); };
  name.appendChild(open);
  name.appendChild(el('i', 'lv-tier', c.meta_tier ? c.meta_tier + ' tier'
                          : (c.provisional ? 'provisional' : 'no published tier')));
  name.appendChild(el('i', 'lv-tier', lvCompTribe(c)));
  if (c.tribe_confirmed === false) {
    name.appendChild(el('i', 'lv-tier', 'tribe unconfirmed'));
  }
  if (st && st.low_sample) {
    name.appendChild(el('span', 'lv-chip lowsamp', 'low sample'));
  }
  row.appendChild(name);
  row.appendChild(lvSlots(core));
  row.appendChild(el('b', 'lv-owned',
                     lvOwned(core) + ' of ' + core.length + ' owned'));
  row.appendChild(el('b', 'lv-ap' + (st && st.avg_place != null ? '' : ' miss'),
                     st && st.avg_place != null ? st.avg_place.toFixed(2) : '—'));
  const picked = _liveCompare.has(c.slug);
  const full = !picked && _liveCompare.size >= LIVE_COMPARE_MAX;
  // A CHECKBOX, not a chip (fix list round 1 item 6): "compare" is a
  // selection you make about up to three rows, and a checkbox is what that
  // looks like. It is disabled (with the reason in its title) once three are
  // ticked rather than silently doing nothing.
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'lv-cmpbox';
  cb.id = 'lv-cmp-' + String(c.slug || 'x').replace(/[^A-Za-z0-9_-]/g, '');
  cb.checked = picked;
  cb.disabled = full;
  if (full) {
    cb.title = 'Compare holds up to ' + LIVE_COMPARE_MAX + ' comps — untick one '
             + 'to add another.';
  }
  cb.onchange = () => {
    if (_liveCompare.has(c.slug)) _liveCompare.delete(c.slug);
    else if (_liveCompare.size < LIVE_COMPARE_MAX) _liveCompare.add(c.slug);
    renderLiveTavern(a);
  };
  const lbl = document.createElement('label');
  lbl.htmlFor = cb.id;
  lbl.className = 'lv-cmplbl';
  lbl.textContent = 'compare';
  const cell = el('span', 'lv-cmpcell');
  cell.appendChild(cb);
  cell.appendChild(lbl);
  row.appendChild(cell);
  return row;
}

//: The player's own ordering, applied INSIDE each tier group. "Source tier" is
//: the payload's order (the source's label, then the name), which is the
//: default; sorting by overlap or by average placement is opt-in, exactly like
//: the pick screen's Order control. A comp the corpus has never seen sorts last
//: rather than at zero.
function lvCompSortRows(rows) {
  const byName = (x, y) => (x.name || '').localeCompare(y.name || '');
  if (_liveCompSort === 'overlap') {
    rows.sort((x, y) => lvOwned(y.core) - lvOwned(x.core) || byName(x, y));
  } else if (_liveCompSort === 'avg_place') {
    const ap = c => (c.stats || {}).avg_place;
    rows.sort((x, y) => {
      const vx = ap(x), vy = ap(y);
      if (vx == null && vy == null) return byName(x, y);
      if (vx == null) return 1;
      if (vy == null) return -1;
      return vx - vy;
    });
  }
  return rows;
}

//: §4.4 Browse: the lobby-tribe filter, the sort control, one column per source
//: tier (S left, A right, more tiers by wrapping), about five rows each with a
//: `+ N more`, and Compare underneath once two comps are picked.
function lvCompsBrowse(a) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, 'Comps'));
  const all = a.comps || [];
  if (!all.length) {
    p.appendChild(lvEmptyRow('No comps read yet — they appear once the bans '
                             + 'resolve.'));
    return p;
  }
  // §4.4: comps for out-of-play tribes are hidden — they cannot be built at all
  // this patch, so a filter that revealed one would be offering a comp nobody
  // can play. Counted, because "some are hidden" is a fact worth stating.
  const oop = a.out_of_pool || [];
  const inplay = all.filter(c => !(c.tribe && oop.some(t => lvTribeHit(c.tribe, t))));
  const hidden = all.length - inplay.length;
  const labels = [];
  inplay.forEach(c => {
    const t = lvCompTribe(c);
    if (!labels.includes(t)) labels.push(t);
  });
  const ctl = el('div', 'lv-ctl');
  ctl.appendChild(el('span', 'lv-lbl', 'Lobby tribes'));
  labels.forEach(t => {
    const on = _liveCompFilter.has(t);
    const chip = el('span', 'lv-chip' + (on ? ' on' : ''), t);
    chip.onclick = () => {
      if (on) _liveCompFilter.delete(t); else _liveCompFilter.add(t);
      renderLiveTavern(a);
    };
    ctl.appendChild(chip);
  });
  if (_liveCompFilter.size) {
    const clear = el('span', 'lv-chip', 'All tribes');
    clear.onclick = () => { _liveCompFilter.clear(); renderLiveTavern(a); };
    ctl.appendChild(clear);
  }
  ctl.appendChild(el('span', 'lv-lbl', 'Sort'));
  [['tier', 'Source tier'], ['overlap', 'Overlap'],
   ['avg_place', 'Avg placement']].forEach(([v, label]) => {
    const chip = el('span', 'lv-chip' + (_liveCompSort === v ? ' on' : ''), label);
    chip.onclick = () => { _liveCompSort = v; renderLiveTavern(a); };
    ctl.appendChild(chip);
  });
  p.appendChild(ctl);
  const rows = inplay.filter(c => !_liveCompFilter.size
                                  || _liveCompFilter.has(lvCompTribe(c)));
  const groups = [];
  rows.forEach(c => {
    const key = c.meta_tier || (c.provisional ? 'provisional' : '—');
    let g = groups.find(x => x.key === key);
    if (!g) {
      g = {key: key, label: c.meta_tier ? c.meta_tier + ' tier'
                     : (c.provisional ? 'Provisional' : 'No published tier'),
           rows: []};
      groups.push(g);
    }
    g.rows.push(c);
  });
  const cols = el('div', 'lv-cols');
  groups.forEach(g => {
    const sorted = lvCompSortRows(g.rows.slice());
    const col = el('div', 'lv-ctier');
    col.appendChild(el('h4', null, g.label + ' · ' + sorted.length));
    const show = _liveCompMore.has(g.key) ? sorted : sorted.slice(0, LIVE_COMP_ROWS);
    show.forEach(c => col.appendChild(lvCompRow(a, c)));
    if (sorted.length > show.length) {
      const more = el('button', 'lv-more',
                      '+ ' + (sorted.length - show.length) + ' more');
      more.onclick = () => { _liveCompMore.add(g.key); renderLiveTavern(a); };
      col.appendChild(more);
    }
    cols.appendChild(col);
  });
  p.appendChild(cols);
  // The slot colours get a LEGEND (fix list round 1 item 6), drawn from the slot
  // element itself so it cannot drift from the rows. The paragraph under it
  // keeps the two facts the legend cannot show: where the numbers come from, and
  // that some comps are not listed at all.
  p.appendChild(lvSlotLegend());
  p.appendChild(el('p', 'lv-note',
    'Slots are the comp\'s core cards, with their art dimmed when you do not '
    + 'own them. Average placement is this project\'s own game corpus — '
    + 'observational, not causal.'
    + (hidden ? ' ' + hidden + ' comp' + (hidden === 1 ? '' : 's')
                + ' hidden: their tribe is out of play this patch.' : '')));
  const picked = [..._liveCompare].map(s => inplay.find(c => c.slug === s))
                                 .filter(Boolean);
  if (picked.length >= 2) p.appendChild(lvCompCompare(picked));
  return p;
}

//: §5's headline stat + distribution + rows for one comp. The headline is the
//: average placement (the one number this project's corpus can put beside a
//: comp), the bars are the 1-to-8 placement shares, and the rows are counts.
function lvCompStats(c) {
  const wrap = el('div', 'lv-cstat');
  const st = c.stats;
  if (!st) {
    // §6.2's shape, for comps: say what is missing rather than showing a zero.
    wrap.appendChild(el('p', 'lv-note',
                        'No corpus record for this comp yet.'));
    return wrap;
  }
  if (st.avg_place != null) {
    const head = el('div', 'lv-head');
    head.appendChild(el('b', null, st.avg_place.toFixed(2)));
    head.appendChild(el('small', null, 'avg place'));
    wrap.appendChild(head);
  }
  wrap.appendChild(el('div', 'lv-vs',
    st.games + ' game' + (st.games === 1 ? '' : 's')
    + ' in this project\'s own corpus'));
  // §5: every stat block carries a source line. The dataset and the sample size
  // are above; the PATCH is what this data cannot state — the corpus records no
  // per-game patch, so §6.3's marker has nothing to read and the absence is said
  // out loud rather than papered over with the current patch.
  wrap.appendChild(el('p', 'lv-note',
    'Own corpus · no per-game patch recorded, so none is claimed · '
    + 'observational, not causal.'));
  if (st.dist) wrap.appendChild(lvBars(st.dist));
  const rows = [['Games', String(st.games)]];
  if (st.top4_pct != null) rows.push(['Top 4', st.top4_pct + '%']);
  if (st.first_pct != null) rows.push(['1st place', st.first_pct + '%']);
  rows.slice(0, 5).forEach(([k, v]) => wrap.appendChild(lvKV(k, v)));
  if (rows.length > 5) {
    wrap.appendChild(el('div', 'lv-note',
                        '+ ' + (rows.length - 5) + ' more stats'));
  }
  if (st.low_sample) {
    wrap.appendChild(el('span', 'lv-chip lowsamp', 'low sample'));
  }
  return wrap;
}

//: The comp guide, fetched on first expand and cached per slug. It is NOT the
//: classic panel's `loadGuide` node: that one is built from the classic classes,
//: and a node cached across the whole page would carry the wrong palette into
//: this panel (the same reason the two viewers keep their own tiles).
const _lvGuideCache = new Map();
function lvLoadGuide(slug, slot) {
  const cached = _lvGuideCache.get(slug);
  if (cached) { slot.appendChild(cached); return; }
  fetch(auth('/guide/' + slug)).then(r => r.ok ? r.json() : null).then(j => {
    if (!j) return;
    const wrap = el('div', 'lv-gdoc');
    if (j.how_to_play) wrap.appendChild(el('p', 'lv-gtext', j.how_to_play));
    if (!j.how_to_play && !j.markdown) {
      wrap.appendChild(el('p', 'lv-note',
                          'No written guide for this comp yet.'));
    }
    if (j.markdown) wrap.appendChild(el('pre', 'lv-gmd', j.markdown));
    _lvGuideCache.set(slug, wrap);
    slot.appendChild(wrap);
  }).catch(() => { /* offline: the panel still names what it is */ });
}

//: §4.4 Detail: the header chips, the core row at 88x120 with a caption per
//: card, the flex row at 76x100, the statistics beside them, and the guide
//: collapsed by default.
function lvCompDetail(a, c) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, 'Comps'));
  const head = el('div', 'lv-cdhead');
  const back = el('button', 'lv-back', '◀ Comps');
  back.onclick = () => { _liveComp = null; renderLiveTavern(a); };
  head.appendChild(back);
  head.appendChild(el('span', 'lv-cdname', c.name || c.slug));
  head.appendChild(el('span', 'lv-chip', c.meta_tier ? c.meta_tier + ' tier'
                                   : (c.provisional ? 'provisional'
                                      : 'no published tier')));
  head.appendChild(el('span', 'lv-chip', lvCompTribe(c)));
  if (c.difficulty) head.appendChild(el('span', 'lv-chip', c.difficulty));
  p.appendChild(head);
  const body = el('div', 'lv-cdetail');
  const cards = el('div', 'lv-cdcards');
  [['Core', 'core'], ['Flex cards', 'addons']].forEach(([label, key]) => {
    const cards_ = c[key] || [];
    if (!cards_.length) return;
    const box = el('div', key === 'core' ? 'lv-core' : 'lv-flexcards');
    box.appendChild(el('div', 'lv-lbl', label));
    const row = el('div', 'lv-row');
    cards_.forEach(x => row.appendChild(
      lvCard(x.card, x.name, lvSlotCap(x))));
    box.appendChild(row);
    cards.appendChild(box);
  });
  body.appendChild(cards);
  body.appendChild(lvCompStats(c));
  p.appendChild(body);
  const det = document.createElement('details');
  det.className = 'lv-guide';
  det.appendChild(el('summary', null, 'Guide text'));
  const slot = el('div', 'lv-gslot');
  det.appendChild(slot);
  det.ontoggle = () => {
    if (det.open && !slot.children.length) lvLoadGuide(c.slug, slot);
  };
  p.appendChild(det);
  return p;
}

//: §5's Compare: up to three comps in the pick screen's own column layout, each
//: with the same statistics in the same order. The columns are in the order the
//: player picked them, so nothing here is ordered by which comp is better.
function lvCompCompare(picked) {
  const p = el('div', 'lv-pn lv-cmpblock');
  p.appendChild(el('h3', null, 'Compare'));
  const wrap = el('div', 'lv-opts wide');
  picked.forEach(c => {
    const core = c.core || [];
    const col = el('div', 'lv-opt lv-cmpcol');
    col.appendChild(el('div', 'lv-optname', c.name || c.slug));
    const chips = el('div', 'lv-cmpchips');
    chips.appendChild(el('span', 'lv-chip', c.meta_tier ? c.meta_tier + ' tier'
                                       : (c.provisional ? 'provisional'
                                          : 'no published tier')));
    chips.appendChild(el('span', 'lv-chip', lvCompTribe(c)));
    col.appendChild(chips);
    col.appendChild(lvSlots(core));
    col.appendChild(el('b', 'lv-owned',
                       lvOwned(core) + ' of ' + core.length + ' owned'));
    col.appendChild(lvCompStats(c));
    wrap.appendChild(col);
  });
  p.appendChild(wrap);
  p.appendChild(el('p', 'lv-note',
    'The same statistics, in the same order, one column per comp. The order is '
    + 'the order you picked them in.'));
  return p;
}

//: The Comps tab (§4.4): Browse, or the one comp whose Detail is open.
function lvCompsScreen(a) {
  const open = _liveComp
    ? (a.comps || []).find(c => c.slug === _liveComp) : null;
  return open ? lvCompDetail(a, open) : lvCompsBrowse(a);
}

//: §4.2 Lobby tab: what the seats we have SEEN are committed to, and the last
//: board the next opponent staged. "of N seen seats" — an unseen seat is
//: unknown, not empty.
function lvLobby(a) {
  const p = el('div', 'lv-pn');
  p.appendChild(el('h3', null, 'Lobby'));
  const rows = a.tribe_pressure || [];
  if (rows.length) {
    rows.forEach(r => {
      p.appendChild(lvKV(r.tribe, r.seats + ' of ' + r.of
                               + ' seen seats (2+ copies)'));
    });
  } else {
    p.appendChild(lvEmptyRow('No seats sighted yet.'));
  }
  const oc = a.opp_comp;
  if (oc && oc.cards && oc.cards.length) {
    const wrap = el('div', 'lv-row');
    oc.cards.forEach(c => {
      wrap.appendChild(lvCard(c.card, c.name || c.card,
                              (c.n > 1 ? '×' + c.n : '') + (c.golden ? ' ★' : '')));
    });
    p.appendChild(el('div', 'lv-lbl lv-opp', 'Next opponent · '
      + (oc.hero_name || oc.hero || 'unknown hero')
      + (oc.name ? ' · ' + oc.name : '')
      + ' · as of round ' + oc.turn));
    p.appendChild(wrap);
  }
  if ((a.opp_trinkets || []).length) {
    p.appendChild(lvKV('Their trinkets', a.opp_trinkets.join(', ')));
  }
  return p;
}
//: The tavern row (§4.2): game order, price and pool left. The tier is not in
//: this payload, so that part of the caption is omitted rather than guessed.
function lvShop(a) {
  const body = el('div');
  const rows = a.shop_rank || [];
  if (!rows.length) {
    // §6.1's sentence, without its four dashed skeleton cards: the player's
    // call (fix list round 2 item 2) is that they read as thick dash bars with
    // no information in them. The status bar above says the same thing about
    // the hero slot.
    body.appendChild(el('p', 'lv-note',
      'Reading the shop. This updates when your next shop opens.'));
    return body;
  }
  const wrap = el('div', 'lv-row');
  rows.forEach(s => {
    const bits = [];
    if (s.price != null) bits.push(s.price + 'g');
    if (s.pool) bits.push(s.pool);
    wrap.appendChild(lvCard(s.card, s.name, bits.join(' · ') || '—',
                            s.tag === 'spell' ? {kind: 'Spell'} : null));
  });
  body.appendChild(wrap);
  return body;
}
//: §4.2 board row: the caption is the comp role the value pass already names
//: ("comp core", "off-comp filler"), which is a fact about membership.
//: One tribe a lobby has banned reads "<Tribe> — out of play" here (fix list
//: round 1 item 7 / round 2 item 5). The reason string itself ("banned tribe —
//: can't grow") is the value pass's, shared with the classic page and pinned by
//: its own test, so the tavern caption is built from DATA — the minion's tribe
//: plus the flag the payload carries — rather than by rewriting that sentence.
function lvBoard(a) {
  const body = el('div');
  const rows = a.sell_rank || [];
  if (!rows.length) {
    body.appendChild(el('p', 'lv-inline', 'empty'));
    return body;
  }
  const wrap = el('div', 'lv-row');
  rows.forEach(s => {
    const cap = s.off_play
      ? ((s.tribe || 'Tribe') + ' — out of play')
      : (s.why || (s.score != null ? String(Math.round(s.score)) : '—'));
    wrap.appendChild(lvCard(s.card, s.name, cap));
  });
  body.appendChild(wrap);
  return body;
}
function lvHand(a) {
  const body = el('div');
  const rows = a.hand || [];
  if (!rows.length) {
    body.appendChild(el('p', 'lv-inline', 'empty'));
    return body;
  }
  const wrap = el('div', 'lv-row');
  rows.forEach(s => wrap.appendChild(lvCard(s.card, s.name, 'hand')));
  body.appendChild(wrap);
  return body;
}
//: The board and the hand, ONE panel with the two side by side (fix list round
//: 2 item 4). Each half says "empty" inline rather than showing a sentence where
//: a row of cards would be, so the panel does not change shape when the board is
//: wiped.
function lvBoardHand(a) {
  const grid = el('div', 'lv-bh');
  [['Your board', lvBoard(a)], ['Your hand', lvHand(a)]].forEach(([label, body]) => {
    const half = el('div');
    half.appendChild(el('div', 'lv-lbl', label));
    half.appendChild(body);
    grid.appendChild(half);
  });
  return grid;
}
//: §4.3's two opt-in controls, session state. "As offered" is the default and
//: the screen never ranks unless the player asks for an order — the server's
//: rows arrive score-ordered, so rendering them as they come would hand the
//: player the model's ranking while the wording pretended otherwise.
let _livePickOrder = 'offered';
let _livePickHidden = new Set();
const LIVE_ORDER_LABELS = {pick_rate: 'picked %', avg_placement: 'avg place'};

//: The rows an option can show, in the design's order, each emitted only when
//: its data exists (§5). The key doubles as the Stats-shown toggle.
//: `pick_rate` is NOT one of them: it is the headline figure ("31% · Picked"),
//: and the row that repeated it ("Picked in 31% of games") was the duplicate the
//: fix list names (round 2 item 1). It stays available as an ORDER, which reads
//: the stats directly rather than through this list.
function lvStatRows(st) {
  const rows = [];
  if (st.avg_placement != null) {
    rows.push(['avg_placement', 'Avg place', st.avg_placement.toFixed(2)]);
  }
  if (st.top4 != null) rows.push(['top4', 'Top 4', st.top4.toFixed(0) + '%']);
  if (st.tier != null) rows.push(['tier', 'Tier', 'T' + st.tier]);
  if (st.tribe) rows.push(['tribe', 'Tribe', st.tribe]);
  return rows;
}
const LIVE_STAT_LABELS = {pick_rate: 'picked %', avg_placement: 'avg place',
                          top4: 'top 4', tier: 'tier', tribe: 'tribe'};

//: §5's distribution: eight bars, placements 1 to 8, one neutral colour (no
//: good/bad shading), a dashed divider between 4 and 5, labels below.
function lvBars(dist) {
  const wrap = el('span', 'lv-dist');
  for (let p = 1; p <= 8; p++) {
    const v = dist[String(p)];
    const bar = el('span', 'lv-bar' + (p > 4 ? ' after4' : ''));
    const fill = el('i');
    fill.style.height = v == null ? '0' : Math.max(2, Math.min(100, v)) + '%';
    bar.appendChild(fill);
    bar.appendChild(el('em', null, String(p)));
    bar.title = 'Placement ' + p + ': ' + (v == null ? '—' : v + '%');
    wrap.appendChild(bar);
  }
  return wrap;
}

//: §4.3's canonical pick screen. Options in the order the GAME offered them
//: unless the player picks another order; each with its headline figure, its
//: distance from the offered average, the distribution, and its stat rows.
//: Nothing here reads the classic panel's fact STRING — the numbers come from
//: `choice.option_stats`, which is also why the phrasing the design bans
//: ("fits your board") cannot reach this screen.
function lvPick(a) {
  const ch = a.choice;
  const stats = ch.option_stats || {};
  const rows = ch.ranked.slice();
  if (_livePickOrder === 'pick_rate' || _livePickOrder === 'avg_placement') {
    const key = _livePickOrder;
    const val = r => (stats[r[1]] || {})[key];
    rows.sort((x, y) => {
      const vx = val(x), vy = val(y);
      if (vx == null && vy == null) return (x[4] ?? 0) - (y[4] ?? 0);
      if (vx == null) return 1;                 // a missing value sorts last
      if (vy == null) return -1;
      return key === 'pick_rate' ? vy - vx : vx - vy;
    });
  } else {
    rows.sort((x, y) => (x[4] ?? 0) - (y[4] ?? 0));
  }
  const body = el('div');
  const redraw = () => renderLiveTavern(a);
  body.appendChild(lvPickControls(ch, stats, redraw));
  const rates = rows.map(r => (stats[r[1]] || {}).pick_rate)
                    .filter(v => v != null);
  const avg = rates.length
    ? rates.reduce((s, v) => s + v, 0) / rates.length : null;
  body.appendChild(el('p', 'lv-note',
    'Source: population statistics scraped from hsreplay.net, read from the '
    + 'shipped meta DB · observational, not causal. '
    + (avg == null ? 'Shown in the order offered.'
                   : 'Offered average: ' + avg.toFixed(1) + '% picked.')));
  const wide = rows.length <= 3;
  const wrap = el('div', 'lv-opts' + (wide ? ' wide' : ''));
  rows.forEach(([name, cid]) => {
    const st = stats[cid] || {};
    const col = el('div', 'lv-opt');
    // The art carries no caption of its own: the name under it is the ONE name
    // (round 1 item 2), at a fixed height so the headline figures line up.
    col.appendChild(tile(cid, name, null, {noname: true}));
    col.appendChild(el('div', 'lv-optname', name));
    if (st.pick_rate != null) {
      // "31% · Picked", one decimal (round 1 item 2 / round 2 item 1). The
      // label says what the number IS, and the row that used to repeat it is
      // gone.
      const head = el('div', 'lv-head');
      head.appendChild(el('b', null, st.pick_rate.toFixed(1) + '%'));
      head.appendChild(el('small', null, 'Picked'));
      if (avg != null) {
        const d = st.pick_rate - avg;
        head.appendChild(el('i', 'lv-vs',
          (d >= 0 ? '+' : '−') + Math.abs(d).toFixed(1) + ' vs offered avg'));
      }
      col.appendChild(head);
    }
    if (st.dist) col.appendChild(lvBars(st.dist));
    const shown = lvStatRows(st).filter(([k]) => !_livePickHidden.has(k));
    shown.slice(0, 5).forEach(([_k, label, value]) => {
      col.appendChild(lvKV(label, value));
    });
    if (shown.length > 5) {
      col.appendChild(el('div', 'lv-note',
                         '+ ' + (shown.length - 5) + ' more stats'));
    }
    if (!lvStatRows(st).length) {
      col.appendChild(el('div', 'lv-note',
                         'No data for this card on this patch yet.'));
    }
    wrap.appendChild(col);
  });
  body.appendChild(wrap);
  const guides = ch.guides || {};
  const named = rows.filter(r => guides[r[0]]);
  if (named.length) {
    const det = document.createElement('details');
    det.className = 'lv-guide';
    det.appendChild(el('summary', null, 'Guide text'));
    named.forEach(r => det.appendChild(el('div', 'lv-kv',
                                           r[0] + ' — ' + guides[r[0]])));
    body.appendChild(det);
  }
  return lvPanel('Choose one', body);
}
//: The type tabs (auto-selected: only the choice on screen has data), the
//: Stats-shown toggles, and the Order control.
function lvPickControls(ch, stats, redraw) {
  const bar = el('div', 'lv-pickctl');
  [['hero', 'Hero'], ['trinket', 'Trinket'], ['discover', 'Discover']]
    .forEach(([k, label]) => {
      const active = ch.kind === k;
      const c = el('span', 'lv-chip' + (active ? ' on' : ' off'), label);
      if (!active) {
        c.title = 'Only the pick on screen has data — the other types are not '
                + 'in this payload.';
      }
      bar.appendChild(c);
    });
  const keys = [];
  const orderKeys = [];
  Object.keys(stats).forEach(cid => {
    lvStatRows(stats[cid]).forEach(([k]) => {
      if (!keys.includes(k)) keys.push(k);
    });
    Object.keys(stats[cid] || {}).forEach(k => {
      if (LIVE_STAT_LABELS[k] && !orderKeys.includes(k)) orderKeys.push(k);
    });
  });
  if (keys.length) {
    bar.appendChild(el('span', 'lv-lbl', 'Stats shown'));
    keys.forEach(k => {
      const on = !_livePickHidden.has(k);
      const c = el('span', 'lv-chip' + (on ? ' on' : ''), LIVE_STAT_LABELS[k]);
      c.onclick = () => {
        if (on) _livePickHidden.add(k);
        else _livePickHidden.delete(k);
        redraw();
      };
      bar.appendChild(c);
    });
  }
  const orders = [['offered', 'As offered']];
  // The order options read the STATS, not the visible rows: "By picked %" is the
  // most useful sort there is, and the headline no longer leaves a row behind to
  // hang it on (fix list round 2 item 1).
  if (orderKeys.includes('pick_rate')) orders.push(['pick_rate', 'By picked %']);
  if (orderKeys.includes('avg_placement')) {
    orders.push(['avg_placement', 'By avg place']);
  }
  bar.appendChild(el('span', 'lv-lbl', 'Order'));
  orders.forEach(([v, label]) => {
    const c = el('span', 'lv-chip' + (_livePickOrder === v ? ' on' : ''), label);
    c.onclick = () => { _livePickOrder = v; redraw(); };
    bar.appendChild(c);
  });
  return bar;
}
//: §6.5: "Merge `Saved to the Settle Up tab automatically ✓` and the `Save
//: every replay automatically` checkbox into ONE row." The classic card asks the
//: question and reports the answer in two separate rows; here the checkbox and
//: what it does sit together, and the Save button appears only while the answer
//: is off (offering a click that would write a second copy is not a fact, it is
//: a way to make a mess).
function lvSaveRow(a) {
  const row = el('div', 'lv-saverow');
  const auto = a.auto_save || {};
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.id = 'lv-save-all';
  cb.checked = !!auto.enabled;
  const lbl = document.createElement('label');
  lbl.htmlFor = cb.id;
  lbl.textContent = auto.label || 'Save every replay automatically';
  cb.onchange = () => postAutoSave(cb, () => { cb.checked = !cb.checked; });
  row.appendChild(cb);
  row.appendChild(lbl);
  if (auto.enabled) {
    row.appendChild(el('span', 'lv-saved',
                       'Saved to the Settle Up tab automatically ✓'));
  } else {
    const save = el('button', 'lv-gobtn', 'Save replay');
    save.onclick = () => postSaveReplay(save);
    row.appendChild(save);
  }
  return row;
}
//: §6.5's game-over card, in the Tavern layout. It needs its OWN entry point:
//: the end-of-game payload is `welcome: true` with no board, and `render`
//: returned at the welcome branch before the viewer was ever consulted — so
//: `lvGameOver` inside `renderLiveTavern` was unreachable in a real session,
//: and only this suite's direct render made it look alive (2026-10-09).
function renderTavernGameOver(a) {
  const app = document.getElementById('app');
  const box = document.getElementById('live-tavern');
  // The page chrome is the same in both viewers, and `render` returns before it
  // reaches this branch: without these two the corner sharing control and the
  // release stamp would keep whatever the last live payload left there.
  renderShareToggle(a.share);
  renderRelease(a.release);
  app.classList.add('tavern-on');
  box.hidden = false;
  box.innerHTML = '';
  // The classic strip is the other viewer's; this card has its own numbers, and
  // leaving a stale one behind the card is how two disagreeing copies appear.
  const bar = document.getElementById('statebar');
  bar.innerHTML = '';
  bar.hidden = true;
  const root = el('div', 'tavern live');
  const p = el('div', 'lv-pn lv-over');
  const go = a.game_over || {};
  // §6.5 with a label and room around it (fix list round 1 item 8): the big
  // line is what the player looks for, so it says what it is.
  p.appendChild(el('div', 'lv-overlabel', 'Game over'));
  p.appendChild(el('div', 'lv-overbig',
    (go.placement ? lvOrdinal(go.placement) : '—')
    + (go.turn ? ' · Round ' + go.turn : '')));
  const open = el('button', 'lv-gobtn', 'Open in Settle Up');
  open.onclick = () => showTab('settle');
  p.appendChild(open);
  p.appendChild(lvSaveRow(a));
  if (a.status) p.appendChild(el('p', 'lv-note', a.status));
  // "Keep the sharing summary as small secondary text" (§6.5) — the same
  // sentence the classic card shows, at 11px, because it is a standing fact
  // rather than something this card is asking for.
  if (a.privacy) p.appendChild(el('p', 'lv-note lv-fine', a.privacy));
  root.appendChild(p);
  box.appendChild(root);
}

function renderLiveTavern(a) {
  const app = document.getElementById('app');
  const box = document.getElementById('live-tavern');
  // The classic panes are HIDDEN, not destroyed: `#live-tavern` is the tavern
  // view's own container, so the classic renderer's sections survive a toggle
  // and coming back to Classic works (2026-10-09 — the first version cleared
  // `#app` and the way back threw).
  app.classList.add('tavern-on');
  box.hidden = false;
  box.innerHTML = '';
  // The tavern status bar carries these facts now, so the classic strip is
  // cleared rather than left showing a second, differently-worded copy — and
  // HIDDEN, because an empty strip is a rounded bar with nothing in it.
  const bar = document.getElementById('statebar');
  bar.innerHTML = '';
  bar.hidden = true;
  const root = el('div', 'tavern live');
  // No game-over band here: that card arrives on its own payload (`welcome:
  // true`), which `render` sends to `renderTavernGameOver` instead of to this
  // renderer — a live payload with a board never carries one.
  root.appendChild(lvStatus(a));
  root.appendChild(lvTribes(a));
  // §4.1's tab row, above the two columns: it selects the screen, and the facts
  // rail is beside every screen rather than one of the tabs.
  const tabs = el('div', 'lv-tabs');
  LIVE_TABS.forEach(([key, label]) => {
    const b = el('button', _liveTab === key ? 'on' : null, label);
    b.onclick = () => {
      _liveTab = key;
      // Leaving the tab drops the open Detail: a comp screen you come back to
      // is the list, which is also what the Comp tab being clicked again means.
      _liveComp = null;
      renderLiveTavern(a);
    };
    tabs.appendChild(b);
  });
  root.appendChild(tabs);
  const main = el('div', 'lv-main');
  const left = el('div', 'lv-col');
  if (_liveTab === 'comps') {
    // §4.4 lives in the MAIN column: its two tier columns, mini-card slots and
    // compare columns need the width, and a 340px rail is the compact form the
    // design's §4.2 keeps for the Facts table.
    left.appendChild(lvCompsScreen(a));
  } else if (_liveTab === 'lobby') {
    left.appendChild(lvLobby(a));
  } else if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    // The pick screen replaces the shop view while a choice is on screen
    // (§4.1) — and it is the whole left column, because choosing is what the
    // player is doing.
    left.appendChild(lvPick(a));
  } else {
    // The taverner's row on top, then board and hand in ONE panel (fix list
    // round 1 item 4 / round 2 item 4). A shop nobody has read yet says so on
    // its own screen instead of drawing four skeleton bars.
    const shop = a.shop_rank || [];
    left.appendChild(shop.length
      ? lvPanel('Tavern', lvShop(a))
      : lvWaiting(a));
    left.appendChild(lvPanel('Board and hand', lvBoardHand(a)));
  }
  main.appendChild(left);
  const rail = el('div', 'lv-rail');
  rail.appendChild(lvFacts(a));
  main.appendChild(rail);
  root.appendChild(main);
  box.appendChild(root);
}
function setLiveViewer(v) {
  _liveViewer = v === 'tavern' ? 'tavern' : 'classic';
  try { localStorage.setItem('bl-live-viewer', _liveViewer); }
  catch (e) { /* private mode */ }
  document.querySelectorAll('#live-viewer button').forEach(
    b => { b.className = b.dataset.v === _liveViewer ? 'on' : ''; });
  // Re-render from the payload already on screen: the poll would do it within
  // 300ms, but a toggle that waits reads as a control that did nothing.
  if (_lastParsed) render(_lastParsed);
}

function render(a) {
  _lastParsed = a;   // the viewer toggle re-renders from this, not a refetch
  if (a.welcome) {
    // §6.5's game-over card is the ONE welcome payload the Tavern viewer draws;
    // a first run has no Tavern design, so it keeps the classic card — and the
    // Tavern layout is cleared first, or that card would appear behind a stale
    // Tavern screen (the container kept its last frame and `tavern-on` still
    // hid the panes).
    if (_liveViewer === 'tavern' && a.game_over) {
      renderTavernGameOver(a);
      return;
    }
    lvClearTavern();
    renderWelcome(a);
    return;
  }
  // Every live payload carries the sharing state too, so the corner control
  // does not vanish the moment the first buy phase arrives (2026-10-07).
  renderShareToggle(a.share);
  renderRelease(a.release);
  const app = document.getElementById('app');
  const statebar = document.getElementById('statebar');
  // A rebuild discards the hovered element without a mouseleave — drop the
  // tooltip with the old frame so it can't outlive its card.
  leaveCard();
  CARDS = a.cards || {};
  // value.py's constants, mirrored to the client (the JS used to hard-code
  // its own copies — two definitions that could drift).
  const TH = a.thresholds || {};
  const decide = document.getElementById('col-decide');
  const ref = document.getElementById('col-ref');
  decide.innerHTML = '';
  ref.innerHTML = '';
  statebar.innerHTML = '';
  // The classic renderer is the one that fills the strip, so it is the one that
  // shows it again (the welcome and Tavern paths hide it, item 7 of the round-2
  // fix list).
  statebar.hidden = false;
  if (!a || !a.board) { statebar.textContent = 'No game yet.'; return; }
  // Pane grouping: DECIDE = the turn's decision (never scrolled away),
  // REFERENCE = scout intel and shopping lists. The headers re-render with
  // the panes (render() clears each section wholesale).
  decide.appendChild(el('h2', 'pane-h', 'Decide'));
  ref.appendChild(el('h2', 'pane-h', 'Reference'));
  // Ban-picker sync (see the state block near the bottom): a new game
  // reseeds from the server; a settled manual set overwrites stale local
  // taps (unless we tapped in the last 3s — the POST may still be in
  // flight); while the player is mid-tapping during detection, local wins.
  const gameNo = a.game_no ?? null;
  if (gameNo !== _banPickGame) {
    _banPickGame = gameNo;
    _banPick = new Set(a.bans_manual ? (a.banned || []) : []);
    _banPickAt = 0;
    _compBodyCache.clear();  // a new game invalidates every owned/banned flag
  } else if (a.bans_manual && Date.now() - _banPickAt > 3000) {
    const srv = new Set(a.banned || []);
    if (srv.size !== _banPick.size || [...srv].some(t => !_banPick.has(t))) {
      _banPick = srv;
    }
  }
  // Pre-warm the /card renders for everything on screen so hovers are
  // instant (one-time per card: the server caches downloads in
  // img_cache/card/, and misses are remembered server-side).
  Object.keys(CARDS).forEach(cid => {
    if (!_warmed.has(cid)) {
      _warmed.add(cid);
      new Image().src = '/card/' + cid + '.png';
    }
  });

  // Tavern Live (2026-10-09, LIVE_VIEW_DESIGN.md): the same payload in the
  // reference layout. It branches HERE — after the shared setup above (the ban
  // picker's sync, CARDS, the art pre-warm) and before the classic strip is
  // built — so both viewers get that setup and exactly one draws the page.
  if (_liveViewer === 'tavern') { renderLiveTavern(a); return; }
  // Classic: the two panes are the page again. This only clears the tavern
  // container and the class its renderer set — with neither present the classic
  // page is exactly what it always was.
  lvClearTavern();

  // STATE STRIP — stat tiles (label over value), then the chip row.
  // Hero name leads as the trust anchor; the numbers use tabular figures so
  // they don't shift width as they tick.
  function statTile(label, value, valCls) {
    const t = el('span', 'tile');
    t.appendChild(el('span', 'lbl', label));
    t.appendChild(el('span', 'val' + (valCls ? ' ' + valCls : ''),
                     String(value)));
    return t;
  }
  statebar.appendChild(el('span', 'tile', a.hero || '?'));
  statebar.appendChild(statTile('Gold', a.gold ?? '?', 'gold'));
  statebar.appendChild(statTile('Tier', a.tier ?? '?'));
  if (a.health != null) {
    const fr = a.fragility || {};
    const dying = (a.health + (a.armor || 0)) <= (TH.dying_hp || 12);
    statebar.appendChild(statTile('HP',
      a.health + (a.armor ? '+' + a.armor : ''),
      dying ? 'bad' : (fr.band === 'fragile' ? 'warn' : null)));
  }
  const turns = (a.scenario || {}).turns;
  if (turns) statebar.appendChild(statTile('Turn', turns));
  if (a.current_place) {
    // Live leaderboard standing (Plan 5 lever 1). Ordinal only — no lobby
    // size exists in any payload, and inventing "of 8" would be wrong in
    // Duos and after late-game deaths.
    const p = a.current_place;
    const suf = ([11, 12, 13].includes(p % 100))
      ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[p % 10] || 'th');
    // Same rule value.situation_line uses: from t8, 5th-or-worse is the
    // "spike, not greed" zone.
    statebar.appendChild(statTile('Place', p + suf,
      (p >= 5 && turns >= 8) ? 'warn' : null));
  }
  if (a.scout) {
    statebar.appendChild(el('span', 'lbl', a.scout));
  }
  if (a.forecast) {
    // The next-fight verdict: the mark + the verdict word carry the state;
    // the color reinforces (never the reverse).
    const fav = a.forecast.startsWith('favored');
    const behind = a.forecast.startsWith('behind');
    const mark = fav ? '✓ ' : (behind ? '✕ ' : '');
    const cls = fav ? 'good' : (behind ? 'bad' : null);
    statebar.appendChild(el('span', cls, mark + a.forecast));
  }
  const triggers = (a.scenario || {});
  const active = Object.entries(triggers)
    .filter(([k, v]) => v && !k.endsWith('_total') && k !== 'turns');
  active.forEach(([k, v]) => {
    statebar.appendChild(el('span', 'lbl',
      k.replace('play_', '') + ' ' + v));
  });
  if (a.banned && a.banned.length) {
    statebar.appendChild(el('span', 'lbl', 'Banned:'));
    a.banned.forEach(t => statebar.appendChild(el('span', 'banned', t)));
  }
  // Out of play (rotated by a patch): NOT banned this game — the pool cannot
  // offer it in any lobby (Naga since 36.6.1). Its own labeled, struck-through
  // state, so a rotated tribe never reads as a ban the player could undo.
  if (a.out_of_pool && a.out_of_pool.length) {
    statebar.appendChild(el('span', 'lbl', 'Out of play:'));
    a.out_of_pool.forEach(t => statebar.appendChild(el('span', 'oop', t)));
  }

  // SITUATION — what is true right now. This pane was headed "Do this now"
  // and carried the numbered plan; the plan is not in the payload any more
  // (2026-10-06, PIVOT.md), so what is left is the state: where the build
  // stands, how close this hero is to dying, what the offers cost, and — when
  // one is pending — the options a pick is choosing between. A pending pick
  // still leads, because it gates everything else on the screen.
  const instr = el('div', 'box instructions');
  instr.appendChild(el('h3', null, 'Situation'));
  // The situation read: direction, strength, danger — the model's read of the
  // game, in one line.
  if (a.situation) instr.appendChild(el('div', 'situation', a.situation));
  // DANGER — its own line, not clause three of a long row. The 2026-09-18 loss
  // is the reason it exists: 14 HP, bled 10 in two of three fights, every level
  // gate legal by construction, and the plan read as "the build is about to
  // take off" — 8th place with 10 gold unspent. The number that decides the turn
  // is not the HP but the NEXT HIT, so that is what this says.
  if (a.fragility && a.fragility.band !== 'steady') {
    const fr = a.fragility;
    const dying = fr.band === 'dying';
    const danger = el('div', 'danger ' + fr.band);
    // Mark + word carry the state; color only reinforces it.
    danger.appendChild(el('span', 'dmark', dying ? '■ ' : '▲ '));
    danger.appendChild(el('span', null,
      (dying ? 'DYING — ' : 'FRAGILE — ')
      + fr.eff_health + ' effective HP'
      + (fr.last_hit ? ', took ' + fr.last_hit + ' last fight' : '')
      + ' — a ' + fr.eff_health + '-hit ends it'
      + (fr.recent3 ? ' · bled ' + fr.recent3 + ' over the last 3 fights' : '')
      + (fr.cap ? ' · damage cap ' + fr.cap : '')));
    instr.appendChild(danger);
  }
  // The empty-shop gap (after a buy/roll the offers vanish from the log for
  // a second or two before the game re-prints them) holds the last read —
  // saying so makes the lag legible instead of looking like a freeze
  // (2026-09-07 'the coach has seized up' report).
  if ((!a.shop_rank || !a.shop_rank.length) && (a.board || []).length) {
    instr.appendChild(el('div', 'none',
      'reading the new shop… (this read is from your last action)'));
  }
  // A PENDING PICK — the options, and what is known about each. The "PICK X"
  // line and the "if locked, pick Y" fallback are gone (2026-10-06, PIVOT.md):
  // the hero pick is the most consequential decision of the game, and naming
  // one was the plainest instruction the app produced. Each option's facts
  // stay — they come from the reference DBs the rest of the page reads — and
  // the choice is the player's.
  //
  // **IN THE GAME'S OWN ORDER, and the facts are statistics rather than a
  // score (2026-10-07).** The server returns these rows score-ordered (row 0
  // is the pick the review grades), so the order it arrives in is a MODEL
  // OPINION, and rendering it would hand the player a ranking while the
  // wording pretended otherwise. `order` is the option's position in the list
  // the game showed, which is the order this panel uses — the same rule the
  // tavern row has followed since 2026-10-06. The old sub-line printed the
  // blended 0-10 score, an index nobody can read; the facts beside it now name
  // the population statistics it was built from (pick rate, average placement,
  // top-4 share) and what the option is relative to the comp on screen.
  if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    const rows = a.choice.ranked.slice().sort((x, y) => (x[4] ?? 0) - (y[4] ?? 0));
    instr.appendChild(el('div', 'none',
      'Your pick — the options, and what is known about each:'));
    const alts = el('div', 'tiles');
    rows.forEach(([n, c, s, w]) => {
      alts.appendChild(tile(c, n, w != null && w !== '' ? w : null));
    });
    instr.appendChild(alts);
    // What each offered trinket actually does for this build (2026-10-02).
    // The curated guides shipped in the DB and were rendered nowhere; here
    // they answer the one question the pick panel raises and the stats
    // cannot: what do I do with it once I take it.
    const pickGuides = a.choice.guides || {};
    rows.forEach(([n]) => {
      if (!pickGuides[n]) return;
      instr.appendChild(el('div', 'cline', n + ' — ' + pickGuides[n]));
    });
  }
  // The numbered plan is NOT rendered here any more (2026-10-06, PIVOT.md).
  // `value.top_move` still computes it, `decision_log` still records it, and
  // the post-game review still reads it back — the live page is the one place
  // it must not appear. It is not merely hidden: render_json() drops the keys
  // (LIVE_VERDICT_KEYS), so there is nothing here to draw. The step-chip
  // vocabulary went with it, and test_live_view.py fails if either returns.
  // Level/roll reference: the button's real price. An analysis without a
  // level_cost (never the live loop's case) shows no level line at all —
  // tier+1 was the old wrong model, never a fallback price.
  if (a.tier && a.tier < 6 && a.level_cost != null) {
    const cost = a.level_cost;
    instr.appendChild(el('div', 'footline',
      a.gold !== null && a.gold >= cost
        ? 'Level available: tier ' + a.tier + ' → ' + (a.tier + 1)
          + ' for ' + cost + 'g'
        : 'Level costs ' + cost + 'g — '
          + Math.max(0, cost - (a.gold ?? 0)) + ' short'));
  }
  // Opponents' trinkets — read from the log (2026-09-08 ground truth): free
  // scout intel the player cannot see in game.
  // The Dark gifts line that used to sit here was REMOVED (2026-09-23, player
  // call: "remove that list of Dark gifts on the coaching page. That is
  // accomplishing nothing."). It listed gifts the player already owns, which the
  // game itself shows on the board — real estate in the Decide column spent
  // restating known state. The analysis still carries `dark_gifts` for telemetry
  // and the corpus; only the overlay stopped rendering it.
  if (a.opp_trinkets && a.opp_trinkets.length) {
    instr.appendChild(el('div', 'footline',
      'Their trinkets: ' + a.opp_trinkets.join(', ')));
  }
  decide.appendChild(instr);

  // NEXT OPPONENT — the announced seat's last-known composition (phase 2,
  // lobby.py): exact when their board staged, aged since. The subtitle
  // names the round so a 3-round-old preview never reads current. Hand and
  // shop are invisible to the log, so this is their BOARD, not everything
  // they hold.
  if (a.opp_comp && a.opp_comp.cards && a.opp_comp.cards.length) {
    const oc = a.opp_comp;
    const body = el('div');
    body.appendChild(el('div', 'footline',
      (oc.hero_name || oc.hero || 'unknown hero')
      + (oc.name ? ' · ' + oc.name : '')
      + ' — as of round ' + oc.turn));
    const tiles = el('div', 'tiles');
    oc.cards.forEach(c => {
      tiles.appendChild(tile(c.card, c.name,
                             c.n > 1 ? '×' + c.n : null,
                             {golden: c.golden}));
    });
    body.appendChild(tiles);
    ref.appendChild(box('Next opponent', body));
  }

  // (The plan's buy card lived here, to glow the matching shop tile. The row
  // is in the game's own order now and nothing is highlighted — 2026-10-06.)

  // HAND — what is in it and what each card is worth. Casting from hand is
  // free and a stuck minion plays for free (log ground truth), so the score
  // here is a value read, not a price. The ACTION VERB the plan attaches to
  // each row ("cast" / "play" / "hold") is gone from the payload — a verb is
  // an instruction — so this box lists the hand; what to do with it is the
  // player's (2026-10-06, PIVOT.md).
  if (a.hand && a.hand.length) {
    const tiles = el('div', 'tiles');
    a.hand.forEach(s => {
      tiles.appendChild(tile(s.card, s.name,
                             s.score != null ? s.score.toFixed(0) : null,
                             {golden: s.golden}));
    });
    decide.appendChild(box('Your hand', tiles));
  }

  // HAND ENGINE — a hand-charge kit (Bream Counter + Diremuck Forager is
  // the known one): the charger grows IN HAND and the deployer summons it
  // at start of combat. Each fact is a live check; the 2026-09-10 game
  // died with both broken and nothing on screen said so. The checks state
  // what is true; they used to carry the instruction ("play your chargers").
  if (a.engine) {
    const e = a.engine;
    const body = el('div', 'engrow');
    const bit = (text, cls) => body.appendChild(el('span', 'engbit' + (cls ? ' ' + cls : ''), text));
    if (e.on_board) bit('✓ ' + e.deployer_name + ' on board', 'ok');
    else bit('✗ ' + e.deployer_name + ' NOT on board', 'bad');
    if (e.space) bit('✓ slot free', 'ok');
    else bit('✗ board full — the summon needs a free slot', 'bad');
    bit(e.charging + ' charging');
    decide.appendChild(box('Hand engine', body));
  }

  // YOUR BOARD — every minion with its value number and its composition role
  // (comp core, engine piece, filler...). One row, lowest first. This box used
  // to be "Sell", split into "Safe to sell" and "Do not sell": both labels are
  // verdicts, and the split is exactly the sort of "sell this one" the live
  // path no longer gives (2026-10-06, PIVOT.md). The numbers and the roles are
  // facts about your own board; what to do about them is the player's call.
  const sellTiles = el('div', 'tiles');
  (a.sell_rank || []).forEach(s => {
    // Board minions only — a hand card can't be sold until it's played
    // (player rule 2026-09-09), so render_json keeps hand entries out.
    const sub = s.score.toFixed(0)
      + (s.why ? ' · ' + s.why : '')
      + (s.fuel ? ' · destroy-spell fuel' : '');
    sellTiles.appendChild(tile(s.card, s.name, sub,
                               {golden: s.golden, n: s.n}));
  });
  ref.appendChild(box('Your board', sellTiles.children.length
    ? sellTiles : el('div', 'none', '—')));

  // TARGET COMP — the comp the model reads this board as closest to, as
  // horizontal tiles: missing pieces fully opaque, owned pieces faded. The
  // wording used to be "what you're hunting" / "committing to X", which is a
  // direction to build in; what is left is the comp's own contents and which
  // of them you hold (2026-10-06, PIVOT.md). A PROVISIONAL comp (mined from our
  // own games, no published comp exists for the tribe) is labelled here and in
  // the comp-direction rows so the player can tell it apart at a glance.
  if (a.target_comp) {
    const ev = a.target_comp_evidence || {};
    const body = el('div', 'target',
      'closest comp: ' + a.target_comp
      + (a.target_comp_provisional
         ? '  [provisional' + (ev.games ? ' — ' + ev.games + ' of our games' : '')
           + (ev.top4 != null ? ', top4 ' + ev.top4 : '') + ']'
         : ''));
    const tc = a.target_cards || {};
    const list = el('div', 'tiles');
    [['core', 'core'], ['addons', 'addons']].forEach(([_label, key]) => {
      (tc[key] || []).forEach(c => {
        // Banned-tribe piece of a hybrid comp (e.g. the Dragon in a naga
        // comp): shown struck-out, never as a hunt target.
        const sub = c.banned ? 'banned' : (c.owned ? 'have' : null);
        const cls = 'comprow ' + (c.banned ? 'bannedrow'
                     : c.owned ? 'owned' : 'missing');
        list.appendChild(tile(c.card, c.name, sub, {cls: cls}));
      });
    });
    body.appendChild(list);
    // How to actually play the thing being committed to (2026-10-02). The
    // written guidance for every comp shipped in meta/comps.json and was read
    // by nothing, so a player was told which cards to hunt and never how the
    // build works.
    const g = a.target_comp_guide;
    if (g && (g.how_to_play || g.when_to_commit)) {
      const guide = el('div', 'cguidance');
      if (g.difficulty) {
        guide.appendChild(el('div', 'cline', 'Difficulty: ' + g.difficulty));
      }
      if (g.when_to_commit) {
        guide.appendChild(el('div', 'cline', 'Commit when: ' + g.when_to_commit));
      }
      if (g.how_to_play) guide.appendChild(el('div', 'cline', g.how_to_play));
      (g.enablers || []).forEach(e => {
        guide.appendChild(el('div', 'cline dim', '· ' + e));
      });
      body.appendChild(guide);
    }
    // "Looking for (comp/pivot)" was a shopping list heading. The box is now
    // the comp's contents, so the heading says whose contents they are.
    ref.appendChild(box('Comp pieces', body));
  }

  // COMP DIRECTION — commit-readiness meter: how close each candidate comp
  // is to the 2-core-hit commit threshold, BEFORE comp_target declares a
  // target. The committed comp glows gold; pre-commit, the top candidate's
  // missing core is shown as tiles (the cards that move the meter).
  if (a.comp_progress && a.comp_progress.length) {
    const body = el('div');
    a.comp_progress.forEach(r => {
      const row = el('div', 'mrow' + (r.name === a.target_comp ? ' locked' : ''));
      // A real meter, not pips: the track is a light step of the same ramp
      // so the state reads across the whole bar, and the fill's color is
      // severity (gold = committed/ready, warn = one away). The text state
      // beside it always carries the meaning — the meter never acts alone.
      const n = Math.min(r.hits, 2);
      const meter = el('span', 'meter'
        + (r.name === a.target_comp || r.ready ? ' met'
           : (r.tribe_hits || 0) >= 2 ? ' near' : ''));
      const fill = el('span', 'fill');
      fill.style.width = (n / 2 * 100) + '%';
      meter.appendChild(fill);
      row.appendChild(meter);
      row.appendChild(el('span', 'mname',
        r.name + (r.provisional ? ' [prov]' : '')));
      row.appendChild(el('span', 'mstat',
        (r.name === a.target_comp
          // "pivoting — committed" / "committed" was a direction to keep
          // going; target_state is out of the live payload (2026-10-06), so
          // what is left is the same word the box above uses: which comp the
          // model reads this board as closest to, and how far along it is.
          ? 'closest comp'
          : r.ready ? 'at the commit threshold'
          : r.leaning ? 'leaning · openers on board'
          : (r.tribe_hits || 0) >= 2
            ? 'one core card away · tribe signal'
            : 'one core card away')
        + (r.hits > 2 ? ' (' + r.hits + ' hits)' : '')
        + (r.leaning && r.lean_hits > 2 ? ' (' + r.lean_hits + ' openers)' : '')));
      body.appendChild(row);
    });
    if (!a.target_comp && (a.comp_progress[0].needs || []).length) {
      const t = el('div', 'tiles');
      a.comp_progress[0].needs.forEach(c => t.appendChild(tile(c.card, c.name)));
      body.appendChild(t);
    }
    ref.appendChild(box('Comp direction', body));
  }

  // LOBBY PRESSURE — tribe commitment across SEEN seats (phase 2): who is
  // contesting what, for pivot/deny context. "of" counts only seats we've
  // sighted; unseen seats are unknown, not empty — the label says "seen".
  if (a.tribe_pressure && a.tribe_pressure.length) {
    const body = el('div');
    a.tribe_pressure.forEach(r => {
      body.appendChild(el('div', 'footline',
        r.tribe + ' — ' + r.seats + ' of ' + r.of + ' seen seats (2+ copies)'));
    });
    ref.appendChild(box('Lobby pressure', body));
  }

  // TAVERN — the offers as a horizontal card row, in the order the game
  // shows them. Each card carries its price, its value score, whether it is a
  // piece of the closest comp or a spell, and how many are left in the shared
  // pool beyond OUR holdings (opponent holdings aren't subtracted yet, so that
  // chip is a floor, not a lobby total — analysis/pool_availability.md).
  //
  // It used to be "Tavern (ranked)": sorted most-valuable-first by
  // value.shop_ranking, with the plan's pick glowing gold and the slot
  // arbiter's veto printed over it. The ordering and the glow ARE the
  // recommendation — a tier score beside a card is a fact, a row ordered by
  // it and one tile lit up is a verdict (2026-10-06, PIVOT.md) — so
  // render_json re-sorts by live_coach's `shop_offers` (the log's own order)
  // and buy_step_card / buy_step_swap_veto are not in the payload at all.
  if (a.shop_rank && a.shop_rank.length) {
    const body = el('div');
    const tiles = el('div', 'tiles');
    a.shop_rank.forEach(s => {
      const sub = (s.price != null ? s.price + 'g · ' : '') + s.score.toFixed(0)
        + (s.tag ? ' · ' + s.tag : '')
        + (s.pool ? ' · ' + s.pool : '');
      tiles.appendChild(tile(s.card, s.name, sub, {golden: s.golden}));
    });
    body.appendChild(tiles);
    ref.appendChild(box('Tavern', body));
  } else {
    ref.appendChild(box('Tavern', el('div', 'none', 'offer not parsed yet')));
  }

  // PLAYABLE COMPS — the bottom panel: grouped by meta tier (S/A/B, the
  // server pre-sorts), each comp a clickable row that expands into its
  // required cards with owned/banned flags. Click again to collapse.
  // This is the game-level list — what the tribe bans still allow — meant
  // to be readable on turn 1. While the 5/5 ban set streams in (~turn 3-5)
  // the panel lists EVERY comp (what this game might allow), dimming rows
  // of not-yet-confirmed tribes; the header says so the full list doesn't
  // read as "all tribes confirmed".
  const compsBody = el('div');
  if (a.tribes_detecting || a.bans_manual) {
    // Ban picker: the reveal screen shows the 5 banned tribes at t0 and
    // the pool inference only converges minutes later — tapping them here
    // makes every downstream comp filter exact for the whole game
    // (2026-09-19; the ban list is provably not in any log).
    const line = el('div', 'none', a.bans_manual
      ? 'bans set by you — tap to correct'
      : 'bans still resolving — ' + (a.tribes_seen || 0)
        + '/5 tribes confirmed · dimmed comps could still be banned · '
        + 'tap the 5 banned tribes to set them now:');
    compsBody.appendChild(line);
    const chips = el('div', 'banchips');
    // The reveal screen lists the CURRENT pool's tribes, so an out-of-play
    // tribe (Naga since 36.6.1) is not on it and is not tappable here either.
    const oopSet = new Set(a.out_of_pool || []);
    (a.tribe_roster || []).filter(t => !oopSet.has(t)).forEach(t => {
      const c = el('span', 'chip' + (_banPick.has(t) ? ' picked' : ''), t);
      c.onclick = () => {
        if (_banPick.has(t)) _banPick.delete(t); else _banPick.add(t);
        _banPickAt = Date.now();
        c.classList.toggle('picked');
        postBans([..._banPick]);
      };
      chips.appendChild(c);
    });
    compsBody.appendChild(chips);
  }
  if (a.comps && a.comps.length) {
    let lastTier = null;
    a.comps.forEach(c => {
      // A provisional (mined) comp has no published tier by definition: label
      // the group "Provisional" instead of letting a null read as "Unranked",
      // which would look like a real comp whose tier is merely unknown. A
      // comp promoted out of the mined corpus (Aberrations - Deity Feed) has
      // the same problem for the same reason, so it gets its own label rather
      // than a tier nobody published (2026-10-02).
      const tier = c.provisional ? 'prov'
        : c.meta_tier ? c.meta_tier
        : (c.tier_missing ? 'nopub' : '?');
      if (tier !== lastTier) {
        lastTier = tier;
        compsBody.appendChild(el('div', 'cptier',
          tier === '?' ? 'Unranked'
            : tier === 'nopub'
              ? 'No published tier (promoted from our own games)'
            : tier === 'prov' ? 'Provisional (mined from our own games)'
            : tier + ' tier'));
      }
      compsBody.appendChild(compRow(c));
    });
  } else if (!a.tribes_detecting) {
    compsBody.appendChild(el('div', 'none', '—'));
  }
  ref.appendChild(box('Playable comps', compsBody));
}
// Ban-picker state, deliberately OUTSIDE render(): the app rebuilds every
// poll second and would wipe in-progress taps. Per game: when the payload's
// game_no changes, seed from the server (a fresh game clears manual bans).
// Once tapping, local state wins for 3s so a poll can't flicker the chip
// back before the POST lands; after that the server (via bans_manual) is
// authoritative and self-heals any missed POST.
let _banPick = new Set(), _banPickGame = null, _banPickAt = 0;
function postBans(list) {
  fetch(auth('/bans'), {method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({banned: list})});
}
// 300ms: the live loop pushes up to ~3/s and the advice itself costs ~5ms —
// the 1s browser poll was the perceived lag. Between pushes the server
// answers a header-only 304, so the faster tick is nearly free.
setInterval(poll, 300);
poll();
// The manual escape hatch (the Clear button) went with the tab work
// (2026-10-07): a new game clears automatically, and the card the button
// blanked is the same one Save now lives on. POST /clear stays for tests
// and tooling; the page just has no button for it.
// ---- Tabs (2026-10-06) -------------------------------------------------
// Another Round is the live overlay above; Settle Up browses SAVED games.
// The review data never rides /analysis (test_live_view pins that) — the
// tab fetches /review/list and /review/game, both served from the store,
// both covering only games that are over.
function showTab(name) {
  const live = name !== 'settle';
  document.getElementById('app').className = live ? '' : 'off';
  document.getElementById('settle').className = live ? '' : 'on';
  document.querySelectorAll('#tabs .tab').forEach(b =>
    b.className = 'tab' + (b.dataset.tab === name ? ' on' : ''));
  try { localStorage.setItem('bl-tab', name); } catch (e) { /* private mode */ }
  if (!live) loadSettleList();
}
document.querySelectorAll('#tabs .tab').forEach(b =>
  b.onclick = () => showTab(b.dataset.tab));
function gameLabel(row) {
  const who = row.hero || 'Run';
  const did = row.placement != null ? ' — ' + row.placement
            + (row.placement === 1 ? 'st' : row.placement === 2 ? 'nd'
             : row.placement === 3 ? 'rd' : 'th') : '';
  const when = (row.created || '').replace('T', ' ');
  return `${who}${did} · ${row.turns ?? '?'} turns · ${when}`;
}
let _settleListLoaded = false;
async function loadSettleList() {
  const sel = document.getElementById('settle-select');
  let games = [];
  try {
    const r = await fetch(auth('/review/list'));
    games = (await r.json()).games || [];
  } catch (e) { /* leave the dropdown saying it could not load */ }
  if (!games.length) {
    sel.innerHTML = '<option value="">No saved replays yet</option>';
    document.getElementById('settle-game').innerHTML =
      '<div class="s-empty">Nothing saved yet. Finish a game and press '
      + '<b>Save replay</b> on the end-of-game card — it then shows up here, '
      + 'turn by turn.</div>';
    return;
  }
  const cur = sel.value;
  sel.innerHTML = '';
  for (const g of games) {
    const o = document.createElement('option');
    o.value = g.id; o.textContent = gameLabel(g);
    sel.appendChild(o);
  }
  sel.value = games.some(g => g.id === cur) ? cur : games[0].id;
  if (!_settleListLoaded || sel.value !== cur) {
    _settleListLoaded = true;
    loadSettleGame(sel.value);
  }
}
async function loadSettleGame(id) {
  const box = document.getElementById('settle-game');
  if (!id) return;
  box.innerHTML = '<div class="s-empty">Loading…</div>';
  let j;
  try {
    const r = await fetch(auth('/review/game?id=' + encodeURIComponent(id)));
    j = await r.json();
  } catch (e) {
    box.innerHTML = '<div class="s-empty">Could not load that game.</div>';
    return;
  }
  if (!j.ok) { box.innerHTML = '<div class="s-empty">' + (j.error || 'Not found.') + '</div>'; return; }
  renderSettleGame(j.rep || j);
}
// The viewer flag (2026-10-08): 'classic' is the shipped renderer, untouched;
// 'tavern' is the REPLAY_VIEWER_DESIGN.md build (single turn + strip + warm
// palette), grown behind this branch. The choice persists per browser.
let _viewer = 'classic';
let _settleRep = null;
let _tavernTurn = null;
// Within Tavern: Summary (rail + card) or Step through (design §4.6). The
// choice persists; a rep without steps forces Summary and the toggle says
// why. _tavernStep/_tavernPlayTimer are the step-through's position and
// autoplay handle.
let _tavernMode = 'summary';
let _tavernStep = 0;
let _tavernPlayTimer = null;
try { _tavernMode = localStorage.getItem('bl-settle-mode') || 'summary'; }
catch (e) { /* private mode */ }
try { _viewer = localStorage.getItem('bl-settle-viewer') || 'classic'; }
catch (e) { /* private mode */ }
function renderSettleGame(rep) {
  _settleRep = rep;   // remembered so the toggle can re-render without a refetch
  if (_viewer === 'tavern') return renderTavernGame(rep);
  hideSettleMode();   // the mode belongs to the Tavern viewer only
  const box = document.getElementById('settle-game');
  box.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'turn s-sticky';   // stays put while the turns scroll
  const t = rep.totals || {};
  head.innerHTML = '<div class="thead"><span class="tturn">'
    + (rep.hero || 'Saved game') + '</span><span class="tmeta">'
    + (rep.placement != null ? 'finished ' + rep.placement : '')
    + ' · ' + (t.taken ?? 0) + ' plans taken, ' + (t.ignored ?? 0)
    + ' ignored · ' + (rep.created || '') + '</span></div>'
    + (rep.caveat ? '<div class="note">' + rep.caveat + '</div>' : '');
  box.appendChild(head);
  const phases = rep.phases || [];
  const turns = (rep.timeline || {}).turns || [];
  const seen = new Set();
  for (const r of turns) {
    box.appendChild(settleTurnCard(r, phases.filter(p => p.turn === r.turn)));
    if (r.turn != null) seen.add(r.turn);
  }
  // Phases whose turn has no timeline card (measured: the FINAL DUEL is
  // turn 16 of a 15-turn timeline — the game ends without a shop, so no
  // snapshots exist for it) belong to the story's last card, not a
  // mystery "Turn ?".
  const rest = phases.filter(p => !seen.has(p.turn));
  if (rest.length && turns.length) {
    const lastCard = box.lastChild;
    const extra = document.createElement('div');
    extra.className = 'brow';
    extra.innerHTML = '<span class="blbl">End of game</span>'
      + '<span>the final duel\'s phases, below</span>';
    lastCard.appendChild(extra);
    for (const p of rest) lastCard.appendChild(phaseRow(p));
  } else if (rest.length) {
    box.appendChild(settleTurnCard(
      {turn: '?', gold: '—', stats: {}, spend: {}, commitment: {}, notes: []},
      rest));
  }
}
// One strip button's result marker (REPLAY_VIEWER_DESIGN.md §4.1), pure so
// the suite can run it under node. The result is never color-only: the glyph
// carries it. An unknown winner (the fight-unreadable family) and an unknown
// HP line (the final turn has no next advisory to measure against) get their
// own states rather than a guess.
// --- Summary rail helpers (REPLAY_VIEWER_DESIGN.md §4.3/§4.4). Pure, so the
// --- suite runs them under node; the DOM assembly reads them in tavernRail.
// Run-length collapse, over the WHOLE group (2026-10-09, player call): the
// same card bought twice in a turn — at steps 2 and 9, say — is one row
// ("En-Djinn Blazer ×2"), in first-seen order. The old rule merged adjacent
// repeats only, so a non-adjacent repeat read as two different cards. Items
// are {card, name} (named at serve time) or plain id strings (reps saved
// before the rail).
function runLength(seq) {
  const out = [];
  const byKey = new Map();
  for (const x of seq || []) {
    const key = typeof x === 'string' ? x : (x.name || x.card);
    const id = typeof x === 'string' ? x : x.card;
    let run = byKey.get(key);
    if (!run) {
      run = {key: key, label: key, n: 0, id: id};
      byKey.set(key, run);
      out.push(run);
    }
    run.n += 1;
  }
  return out;
}
// Which sold ids were bought THIS phase (design: "flipped"). Those never
// touch the Opened or Ended boards, so the rail and the tray are the only
// places they appear. Keys are card ids.
function flipKinds(bought, sold) {
  const boughtIds = new Set((bought || []).map(x => x.card || x));
  const out = {};
  for (const s of sold || []) {
    const id = s.card || s;
    out[id] = boughtIds.has(id) ? 'flipped' : 'sold';
  }
  return out;
}
// Net changes of the Ended board vs the Opened one, matched by ENTITY id —
// a board's own entities persist through the shop; across turns they are
// re-created with fresh ids, which is why this is per turn. Reps saved
// before 2026-10-07 carry no eid and get no tags: a missing fact beats a
// wrong one.
function boardDelta(opened, ended) {
  const base = {};
  for (const m of opened || []) if (m && m.eid != null) base[m.eid] = m;
  const out = {};
  for (const m of ended || []) {
    if (!m || m.eid == null) continue;
    const was = base[m.eid];
    out[m.eid] = was
      ? {isNew: false, datk: (m.atk ?? 0) - (was.atk ?? 0),
         dhealth: (m.health ?? 0) - (was.health ?? 0)}
      : {isNew: true, datk: 0, dhealth: 0};
  }
  return out;
}
// --- Battle face-off helpers (design §4.5). Pure, node-tested.
function outcomeText(winner) {
  return winner === 'us' ? 'You won the fight'
    : winner === 'them' ? 'You lost the fight'
    : winner === 'tie' ? 'A tie — both boards died'
    : 'Outcome not readable';
}
// --- Step-through helpers (design §4.6). Pure, node-tested.
function stepWords(st) {
  const name = st.cardName || st.card || '';
  // A hero power arrives pre-labelled ("hero power" — the server has no
  // id->power-name row to offer), and "Cast hero power" reads backwards:
  // the power is USED, not cast from hand (2026-10-09, player call: never
  // show a card id, and say what the action was).
  if (name === 'hero power') {
    return {cast: 'Used hero power', play: 'Used hero power',
            sell: 'Sold hero power', buy: 'Bought hero power'}[st.k]
      || 'Used hero power';
  }
  return {roll: 'Rolled the tavern', level: 'Leveled up',
          buy: 'Bought ' + name, sell: 'Sold ' + name,
          play: 'Played ' + name, cast: 'Cast ' + name}[st.k] || '(action)';
}
function stepLetter(k) {
  return {roll: 'R', level: 'L', buy: 'B', sell: 'S',
          play: 'P', cast: 'C'}[k] || '•';
}
function stepKindClass(k) {
  return {roll: 'k-roll', level: 'k-level', buy: 'k-buy',
          sell: 'k-sell', play: 'k-play', cast: 'k-cast'}[k] || '';
}
// The card the current action targeted (2026-10-09, player call). Only a BUY
// or a PLAY puts a card on the board, so only those can highlight one; a sell's
// card is the ghost beside the board, and a roll or a level-up touches no card
// at all. The old rule — "the first eid here that was not on the previous
// board" — outlined card 1 for "Leveled up", because step 1 has no previous
// board to compare against and every tile therefore looked new.
function stepDiff(cur, kind, card) {
  if (kind !== 'buy' && kind !== 'play') return {highlight: null};
  for (const m of cur || []) {
    if (m.eid != null && m.card === card) return {highlight: m.eid};
  }
  return {highlight: null};
}
// The hero's HP line for the badge: effective HP at this turn's buy end and
// at the next one (which is what the fight cost). Old reps and a final turn
// have no next reading — an explicit ? beats a guess.
function hpLine(eff, nextEff) {
  if (eff == null && nextEff == null) return '';
  return 'HP ' + (eff ?? '?') + ' → ' + (nextEff ?? '?');
}
// Minions left on the WINNING side (the losing board died; a tie or an
// unreadable fight leaves no honest single number). A WIN whose survivor
// board was never read — the last turn of a game whose log ends before the
// next shop stages — is ALSO unreadable: "0" on a won fight reads as
// "won with nothing", which is a lie the data never told (2026-10-09).
function minionsLeft(winner, battleEnd, theirsSurvivors) {
  if (winner === 'us') return (battleEnd || []).length || null;
  if (winner === 'them') return (theirsSurvivors || []).length || null;
  return null;
}
function stripMark(winner, dmg) {
  // What the FIGHT COST, not who won (2026-10-09, player call): HP dropped is
  // a loss marker, no drop cost nothing. The winner is the fallback when the
  // cost is unreadable, and no reading at all is a dash — the old "?" was
  // rendered inside the turn number ("1? −5"), which reads as the number.
  if (dmg != null) {
    const cost = dmg > 0 ? '−' + dmg : dmg < 0 ? '+' + (-dmg) : '0';
    return {ch: (dmg > 0 ? '▼ ' : '▲ ') + cost, cls: dmg > 0 ? 'loss' : 'win'};
  }
  if (winner === 'us') return {ch: '▲', cls: 'win'};
  if (winner === 'them') return {ch: '▼', cls: 'loss'};
  if (winner === 'tie') return {ch: '=', cls: 'tie'};
  return {ch: '—', cls: ''};
}
// The Tavern viewer (REPLAY_VIEWER_DESIGN.md, build-order steps 1-2): the
// warm palette, a turn strip with the result markers, ONE turn on screen at
// a time. The turn itself is the classic card — same tabs, same notes, same
// honesty — dropped into the palette-scoped root; the Summary rail and
// Step-through from the design land here later.
function renderTavernGame(rep) {
  const box = document.getElementById('settle-game');
  box.innerHTML = '';
  const root = document.createElement('div');
  root.className = 'tavern';
  const t = rep.totals || {};
  const head = document.createElement('div');
  head.className = 'ts-head';
  head.innerHTML = '<span>' + (rep.hero || 'Saved game') + '</span>'
    + '<span class="tm"> '
    + (rep.placement != null ? '· finished ' + rep.placement + ' ' : '')
    + '· ' + (rep.created || '') + '</span>';
  root.appendChild(head);
  const turns = (rep.timeline || {}).turns || [];
  const phases = rep.phases || [];
  const hasSteps = turns.some(r => (r.steps || []).length);
  const effMode = _tavernMode === 'step' && hasSteps ? 'step' : 'summary';
  // The Summary | Step through toggle lives in the SETTLE HEADER next to the
  // game dropdown (2026-10-09, player call), not over the boards: it is wired
  // once at startup and refreshed here — which mode is on, and WHY Step through
  // is unavailable rather than hiding it (an old save carries no per-action
  // boards).
  refreshSettleMode(effMode, hasSteps);
  if (rep.caveat) {
    const cav = document.createElement('div');
    cav.className = 'ts-caveat';
    cav.textContent = rep.caveat;
    root.appendChild(cav);
  }
  if (!turns.some(r => r.turn === _tavernTurn)) {
    _tavernTurn = turns.length ? turns[0].turn : null;
  }
  const strip = document.createElement('div');
  strip.className = 'tstrip';
  for (const r of turns) {
    const b = document.createElement('button');
    b.className = 'tbtn2' + (r.turn === _tavernTurn ? ' sel' : '');
    const m = stripMark(r.winner, r.damage_taken);
    if (m.cls) b.classList.add(m.cls);
    b.innerHTML = (r.turn ?? '?') + '<small>' + m.ch + '</small>';
    b.onclick = () => {
      stopTavernPlay();
      _tavernStep = 0;
      _tavernTurn = r.turn;
      renderSettleGame(rep);
    };
    strip.appendChild(b);
  }
  root.appendChild(strip);
  const row = turns.find(r => r.turn === _tavernTurn);
  let card = null;
  if (row && effMode === 'step') {
    root.appendChild(renderTavernSteps(row));
  } else if (row) {
    // Design §3: rail 330px left, the turn's card right. The card is THE
    // settleTurnCard — same tabs, notes and honesty — with the tavern-only
    // extras (rail, passed-through tray, Ended net tags, Battle face-off)
    // gated on the flag. The face-off's HP line needs the NEXT turn's
    // effective-HP reading, which only the caller has.
    //
    // The model's plan rides the RAIL in this viewer (2026-10-09, player
    // call), folded under a neutral label — the phase row's "coaching —
    // not taken" summary read as advice, and its "You: bought… — next
    // fight: −N HP" line duplicated the rail and the Result view. So the
    // card gets NO phase rows here; every phase this turn (plus any
    // final-duel phase with no shop of its own, which the classic viewer
    // attaches to the last card) lands in the rail's Plan section, once.
    const idx = turns.indexOf(row);
    const nextEff = idx >= 0 && turns[idx + 1] ? turns[idx + 1].eff : null;
    const seen = new Set(turns.map(r => r.turn));
    const isLast = row === turns[turns.length - 1];
    const railPhases = phases.filter(p => p.turn === row.turn
        || (isLast && !seen.has(p.turn)));
    const wrap = document.createElement('div');
    wrap.className = 'twrap';
    wrap.appendChild(tavernRail(row, railPhases));
    card = settleTurnCard(row, [], {tavern: true, hero: rep.hero,
                                    nextEff: nextEff});
    wrap.appendChild(card);
    root.appendChild(wrap);
  }
  box.appendChild(root);
}
// The Summary rail (design §4.3): what the turn cost and did, grouped and
// collapsed. A group opens by default while it is SHORT — five rows or fewer
// (2026-10-09, player call: the old fixed open/closed per group meant a
// nine-buy turn opened a wall of rows and a two-row Economy stayed shut) —
// and longer groups cap at 8 with a show-all. The model's plan rides here
// too, folded under a neutral label (`phases`), because "coaching — not
// taken" read as advice and the app is reference-only; the plan text itself
// is a fact about the model, and the review is where it is allowed (PIVOT.md).
function tavernRail(r, phases) {
  const took = r.took || {}, sp = r.spend || {}, ev = r.shop_events || {};
  const stats = r.stats || {};
  const boardEnd = stats.buy_end;
  const buys = took.bought || [], sells = took.sold || [];
  const plays = took.plays || [], casts = took.spell_ids || [];
  const nRolls = sp.rolls ?? 0, levelled = !!ev.tier_up;
  const kinds = flipKinds(buys, sells);
  const nAct = buys.length + sells.length + plays.length + casts.length
    + nRolls + (levelled ? 1 : 0);
  // No opening snapshot (the final turn family): the value chip would print
  // a drop that never happened — the old reps carry `growth` measured against
  // a board this turn never had (2026-10-09, player call). New saves carry
  // None there (turn_review stops measuring without a baseline); this gate
  // is what keeps the OLD saves honest without a rebuild.
  const noSnapshot = r.turn !== 1 && !(r.buy_start || []).length;
  const rail = document.createElement('div');
  rail.className = 'rail';
  const h = document.createElement('div');
  h.className = 'rail-h';
  h.innerHTML = '<span class="rt">Turn ' + (r.turn ?? '?') + ' · ' + nAct
    + ' action' + (nAct === 1 ? '' : 's') + '</span>';
  rail.appendChild(h);
  const chips = document.createElement('div');
  chips.className = 'rchips';
  const chip = t => chips.appendChild(el('span', 'chip', t));
  // "1 casts" and "1 rolls" were reaching the player (measured 2026-10-08 by
  // running the rail against a one-cast turn): these chips are the design's
  // §4.3 summary, so they have to read as English at 1 as well as at 9.
  // "+1 bought" / "−1 sold" already do — they are participles, not plurals.
  const count = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');
  // The turn's numbers are the CHIPS' job, and the only copy of them
  // (2026-10-09, player call): the turn header's "8g · board 22 stats +8 ·
  // spent 5g" repeated three of these — one copy, here.
  if (r.gold != null) chip(r.gold + 'g at open');
  if (!noSnapshot && boardEnd != null) chip('board ' + boardEnd);
  if (buys.length) chip('+' + buys.length + ' bought');
  if (sells.length) chip('−' + sells.length + ' sold');
  if (nRolls) chip(count(nRolls, 'roll'));
  if (levelled) chip('1 level-up');
  if (casts.length) chip(count(casts.length, 'cast'));
  if (ev.played != null) chip(count(ev.played, 'card') + ' played');
  if (sp.total != null) chip(sp.total + 'g spent');
  if (!noSnapshot && stats.growth != null) {
    chip('value ' + (stats.growth >= 0 ? '+' : '') + stats.growth);
  }
  if (ev.hero_power) chip('hero power');
  for (const tr of (ev.trinkets || [])) chip('trinket: ' + tr);
  if (!chips.children.length) chip('nothing recorded this turn');
  rail.appendChild(chips);
  // One collapsible group. `items` are already the named entries; kindOf
  // names the left-edge color. Longer than the cap: first 8, then a
  // show-all that re-renders the group expanded (per group, not global).
  const group = (title, entries, kindOf) => {
    const runs = runLength(entries);
    if (!runs.length) return;          // an empty group is noise, not a header
    // Open while short (≤5 rows), folded once longer — the number of rows,
    // not the group's name, decides (2026-10-09, player call).
    const open = runs.length <= 5;
    const gh = document.createElement('div');
    gh.className = 'ig-h';
    gh.textContent = (open ? '▾ ' : '▸ ') + title;
    const body = document.createElement('div');
    body.style.display = open ? '' : 'none';
    const CAP = 8;
    const shown = document.createElement('div');
    const draw = n => {
      shown.innerHTML = '';
      for (const run of runs.slice(0, n)) {
        const d = document.createElement('div');
        d.className = 'iitem ' + (kindOf(run) || 'kept');
        d.textContent = run.label + (run.n > 1 ? ' ×' + run.n : '');
        shown.appendChild(d);
      }
      if (runs.length > n) {
        const more = document.createElement('button');
        more.className = 'ishow';
        more.textContent = 'show all ' + runs.length;
        more.onclick = () => draw(runs.length);
        shown.appendChild(more);
      }
    };
    draw(Math.min(runs.length, CAP));
    gh.onclick = () => {
      const closed = body.style.display === 'none';
      body.style.display = closed ? '' : 'none';
      gh.textContent = (closed ? '▾ ' : '▸ ') + title;
    };
    rail.appendChild(gh);
    rail.appendChild(body);
    body.appendChild(shown);
  };
  const kindFor = run => {
    const k = kinds[run.id];
    return k === 'flipped' ? 'flipped' : k === 'sold' ? 'sold' : 'kept';
  };
  // Economy items are pre-rendered labels ({name}), which runLength passes
  // through as-is.
  const eco = [];
  if (nRolls) eco.push({name: 'Rolled ×' + nRolls});
  if (levelled) eco.push({name: 'Level up'});
  group('Economy', eco, () => 'kept');
  group('Buys', buys, kindFor);
  group('Sells', sells, run => (kinds[run.id] === 'flipped'
                                ? 'flipped' : 'sold'));
  group('Plays', plays.concat(casts), () => 'kept');
  // The worth-a-look flags, under the chips as the design keeps them.
  for (const q of r.sell_questions || []) {
    const d = document.createElement('div');
    d.className = q.rebuild ? 'note' : 'q';
    d.textContent = q.rebuild
      ? ('~ rebuilt the board: sold ' + q.sold_count + ' — a repositioning, '
         + 'not a one-for-one choice')
      : ('? sold ' + (q.sold_name || 'a card') + ' (' + (q.role || '?')
         + ') while keeping ' + (q.kept_filler_names || []).join(', '));
    rail.appendChild(d);
  }
  // The model's plan, folded, under a neutral label. One copy: the phase
  // rows that used to carry it (and the verdict word) are classic-only now.
  for (const p of phases || []) {
    const det = document.createElement('details');
    det.className = 'rplan';
    det.appendChild(el('summary', null, 'Plan'));
    det.appendChild(el('div', 'rplan-body',
                       p.plan || '(no plan recorded for this phase)'));
    rail.appendChild(det);
  }
  return rail;
}
// The Step-through (design §4.6, build step 5): scrubber over the turn's
// actions, each with the board as it stood right after it. The sold card
// shows dimmed with a SOLD tag — it is the one action whose result is an
// absence on the board. Play steps on a timer; the design's reduced-motion
// note is satisfied by there being no transition to disable.
function stopTavernPlay() {
  if (_tavernPlayTimer) {
    clearInterval(_tavernPlayTimer);
    _tavernPlayTimer = null;
  }
}
function tavernStepNav(delta) {
  stopTavernPlay();
  _tavernStep = Math.max(0, _tavernStep + delta);
  renderSettleGame(_settleRep);
}
function tavernTogglePlay() {
  if (_tavernPlayTimer) {
    stopTavernPlay();
  } else {
    _tavernPlayTimer = setInterval(() => {
      const r = ((_settleRep || {}).timeline || {}).turns
        .find(x => x.turn === _tavernTurn);
      const steps = (r || {}).steps || [];
      if (_tavernStep >= steps.length - 1) {
        stopTavernPlay();
      } else {
        _tavernStep += 1;
      }
      renderSettleGame(_settleRep);
    }, 900);
  }
  renderSettleGame(_settleRep);
}
function renderTavernSteps(row) {
  const steps = row.steps || [];
  if (_tavernStep > steps.length - 1) {
    _tavernStep = Math.max(0, steps.length - 1);
  }
  const st = steps[_tavernStep];
  const col = document.createElement('div');
  col.className = 'tstep';
  const nav = document.createElement('div');
  nav.className = 'stepnav';
  const mk = (label, fn, dis) => {
    const b = el('button', 'snav', label);
    b.disabled = !!dis;
    b.onclick = fn;
    return b;
  };
  nav.appendChild(mk('◀ Prev', () => tavernStepNav(-1), _tavernStep <= 0));
  const play = mk(_tavernPlayTimer ? '❚❚ Pause' : '▶ Play',
                  tavernTogglePlay, !steps.length);
  play.className = 'snav splay';
  nav.appendChild(play);
  nav.appendChild(mk('Next ▶', () => tavernStepNav(1),
                     _tavernStep >= steps.length - 1));
  col.appendChild(nav);
  // The track, then the legend DIRECTLY under it (2026-10-09, player call), so
  // the letters are explained where they are read. Every tick carries its
  // action as a hover tooltip.
  const track = document.createElement('div');
  track.className = 'steptrack';
  steps.forEach((s, i) => {
    const t = el('button', 'stick ' + stepKindClass(s.k)
                 + (i === _tavernStep ? ' sel' : ''));
    t.textContent = stepLetter(s.k);
    t.title = 'Step ' + (i + 1) + ': ' + stepWords(s);
    t.onclick = () => {
      stopTavernPlay();
      _tavernStep = i;
      renderSettleGame(_settleRep);
    };
    track.appendChild(t);
  });
  col.appendChild(track);
  col.appendChild(el('div', 'slegend',
    'R roll · B buy · S sell · L level up · P play · C cast'));
  // The caption is the board's own label and the action in plain words, at
  // reading size (2026-10-09, player call). It was 13px muted text inside the
  // control row — the one line that says what you are looking at.
  const cap = document.createElement('div');
  cap.className = 'stepcap';
  if (steps.length) {
    cap.appendChild(el('span', 'scap-what',
                       'Your board after step ' + (_tavernStep + 1) + ' of '
                       + steps.length + ' — '));
    cap.appendChild(el('span', null, stepWords(st)));
  } else {
    cap.textContent = 'No step data for this turn';
  }
  col.appendChild(cap);
  const boardWrap = document.createElement('div');
  boardWrap.className = 'stepboard';
  const diff = stepDiff(st ? st.board : [], st ? st.k : null,
                        st ? st.card : null);
  for (const m of (st ? st.board : [])) {
    const t = tile(m.card, m.name || m.card, statSub(m), {golden: m.golden});
    if (diff.highlight != null && m.eid === diff.highlight) {
      t.classList.add('affected');
    }
    boardWrap.appendChild(t);
  }
  if (st && st.k === 'sell') {
    // The sold card is an absence on the board — shown dimmed with SOLD.
    const t = tile(st.card, st.cardName || st.card, '', {cls: 'ghost sold-now'});
    t.appendChild(el('span', 'tag-sold', 'SOLD'));
    boardWrap.appendChild(t);
  }
  col.appendChild(boardWrap);
  return col;
}
// One board row of a turn card: card tiles when the stored board is
// structured (the server joins display names at serve time), the text the
// standalone page uses when it is not. Art rides /img like everywhere else,
// so tiles hover to the full card render for free.
function boardTiles(list, tags, tav) {
  const wrap = document.createElement('span');
  wrap.className = 'brow-tiles';
  for (const m of list || []) {
    // Tavern tiles carry the two-color stat line (attack gold, health red);
    // the classic tiles keep their plain "?/?-when-unknown" string — the
    // viewer flag's contract leaves the shipped renderer alone.
    const sub = tav ? statSub(m) : (m.atk ?? '?') + '/' + (m.health ?? '?');
    const t = tile(m.card, m.name || m.card, sub, {golden: m.golden});
    // Net-change tags (Tavern, design §4.4): NEW for a minion that is on the
    // Ended board but was not on the Opened one; otherwise the stat delta.
    // Keyed by entity id and only present when the rep carries eids — an
    // old save simply shows no tags.
    const tag = tags && m.eid != null ? tags[m.eid] : null;
    if (tag && tag.isNew) t.appendChild(el('span', 'tag-new', 'NEW'));
    else if (tag && (tag.datk || tag.dhealth)) {
      // Attack and health SEPARATELY, each signed — "+0/+3" (2026-10-09, player
      // call). One green number for both ("+2+2") is two numbers that read as
      // one, and it cannot say which stat moved.
      const signed = n => { n = n || 0; return (n >= 0 ? '+' : '') + n; };
      const d = el('span', 'tdelta');
      d.appendChild(el('span', 'tdatk', signed(tag.datk)));
      d.appendChild(el('span', 'tsep', '/'));
      d.appendChild(el('span', 'tdhp', signed(tag.dhealth)));
      t.appendChild(d);
    }
    wrap.appendChild(t);
  }
  return wrap;
}
function boardRow(lbl, list, text, cls, tags, stacked, tav) {
  const d = document.createElement('div');
  d.className = 'brow' + (stacked ? ' stacked' : '');
  d.innerHTML = '<span class="blbl">' + lbl + '</span>';
  if (list && list.length) d.appendChild(boardTiles(list, tags, tav));
  else {
    const s = document.createElement('span');
    if (cls) s.className = cls;
    s.textContent = text || '—';
    d.appendChild(s);
  }
  return d;
}
// One side of the Battle face-off (design §4.5): a hero badge line and the
// board centered under it, tinted warm (yours) or cool (theirs).
function faceSide(label, meta, list, text, tint) {
  const d = document.createElement('div');
  d.className = 'fside ' + tint;
  const b = document.createElement('div');
  b.className = 'fbadge';
  b.innerHTML = '<span>' + label + '</span>'
    + (meta ? '<span class="fm">' + meta + '</span>' : '');
  d.appendChild(b);
  if (list && list.length) {
    const row = document.createElement('div');
    row.className = 'fboards';
    for (const m of list) {
      row.appendChild(tile(m.card, m.name || m.card, statSub(m),
                           {golden: m.golden}));
    }
    d.appendChild(row);
  } else {
    d.appendChild(el('div', 'fnone', text || '—'));
  }
  return d;
}
// One advised phase, the way a player reads it (2026-10-07): what THEY did
// first, the cost of it next to that, and the model's line folded away
// underneath — there to open, never shouting.
function phaseRow(p) {
  const d = document.createElement('div');
  d.className = 'phase';
  const acted = document.createElement('div');
  acted.className = 'pacted';
  acted.textContent = 'You: ' + (p.acted || '(no actions recorded)');
  d.appendChild(acted);
  if (p.outcome != null || p.outcome_note) {
    const out = document.createElement('span');
    out.className = 'pout';
    out.textContent = p.outcome != null
      ? (' — next fight: ' + (p.outcome > 0 ? '+' : '') + p.outcome + ' HP')
      : ' — ' + (p.outcome_note || '');
    acted.appendChild(out);
  }
  const det = document.createElement('details');
  det.className = 'coach';
  const sum = document.createElement('summary');
  sum.textContent = p.verdict ? ('coaching — ' + p.verdict) : 'coaching';
  const plan = document.createElement('div');
  plan.className = 'pplan';
  plan.textContent = p.plan || '(no plan recorded for this phase)';
  det.appendChild(sum);
  det.appendChild(plan);
  d.appendChild(det);
  return d;
}
function settleTurnCard(r, phases, opts) {
  // opts.tavern (2026-10-08) turns on the Tavern-only extras — the
  // passed-through tray and the Ended board's net-change tags — without
  // touching a single pixel of the classic rendering (the viewer flag's
  // whole contract). Everything below reads `tav` once.
  const tav = !!(opts && opts.tavern);
  const s = r.stats || {}, sp = r.spend || {}, c = r.commitment || {};
  const ev = r.shop_events || {};
  // No opening snapshot (the final turn family — the last turn of a game
  // whose log ends before the fight staged): nothing about this turn's
  // boards or growth is computable, and the old save renders a fake
  // "board 0 stats −1020" and a "value −1020" chip out of a missing
  // baseline (2026-10-09, player call). New saves carry no such numbers
  // (turn_review refuses to measure without one); this branch is what the
  // OLD saves render instead of the guess.
  const noSnapshot = r.turn !== 1 && !(r.buy_start || []).length;
  const card = document.createElement('div');
  card.className = 'turn';
  const head = document.createElement('div');
  head.className = 'thead clickable';
  // The Tavern header is the turn and the comp target ONLY (2026-10-09,
  // player call): its gold / board / growth / spent numbers are the rail's
  // chips now, and a fact printed twice on one card is the duplication the
  // rail exists to remove. The classic header keeps every number it had.
  head.innerHTML = '<span class="caret">▾</span>'
    + '<span class="tturn">Turn ' + (r.turn ?? '?') + '</span>'
    + (tav ? '' : '<span class="tmeta">' + (r.gold ?? '—') + 'g · board '
       + (s.buy_end ?? '—') + ' stats'
       + (s.growth != null ? ' <span class="grw">' + (s.growth > 0 ? '+' : '')
          + s.growth + '</span>' : '')
       + ' · spent ' + (sp.total ?? '—') + 'g</span>')
    + (c.target ? '<span class="comp">' + c.target + '</span>' : '');
  // Click the title bar to fold the card down to just that bar (2026-10-07):
  // a 15-turn game is a lot of scrolling, and the headline row is the index.
  head.onclick = () => {
    const closed = card.classList.toggle('collapsed');
    head.querySelector('.caret').textContent = closed ? '▸' : '▾';
  };
  card.appendChild(head);
  // Three views of one turn (2026-10-07): the shop from open to close, the
  // fight after beginning-of-combat effects, and the result — who survived
  // and what it cost. **Shop is the default** (2026-10-07): it is the view the
  // player's own decisions are read from, and the one that carries the phase
  // rows and the turn's events. Old saves carry none of the new fields; every
  // row falls back to the text the standalone page still renders.
  //
  // The TABS SIT ABOVE their views, and the card is as tall as the view on
  // screen (2026-10-09, player call). The 2026-10-07 arrangement put the
  // buttons UNDER a one-cell grid whose three bodies shared the tallest
  // view's height invisibly — which read as ~400px of dead space under a
  // short Shop view, with the controls at the bottom like a footnote.
  // `display:none` takes each hidden view out of the layout, so the panel
  // fits its content; switching tabs reflows what is below, which is the
  // trade, and the tab row on top is what makes that legible.
  const btns = document.createElement('div');
  btns.className = 'tbtns';
  const views = document.createElement('div');
  views.className = 'tviews';
  const bodies = {};
  const sections = [['shop', 'Shop'], ['battle', 'Battle'],
                    ['aftermath', 'Result']];
  for (const [key, label] of sections) {
    const b = el('button', 'tbtn' + (key === 'shop' ? ' on' : ''), label);
    const body = document.createElement('div');
    body.className = 'tbody';
    body.style.display = key === 'shop' ? '' : 'none';
    b.onclick = () => {
      for (const [k] of sections) {
        bodies[k].style.display = k === key ? '' : 'none';
      }
      btns.querySelectorAll('.tbtn').forEach(x => x.className = 'tbtn');
      b.className = 'tbtn on';
    };
    btns.appendChild(b);
    bodies[key] = body;
    views.appendChild(body);
  }
  card.appendChild(btns);
  card.appendChild(views);
  const row = (lbl, text, cls) => {
    const d = document.createElement('div');
    d.className = 'brow';
    d.innerHTML = '<span class="blbl">' + lbl + '</span><span'
      + (cls ? ' class="' + cls + '"' : '') + '></span>';
    d.lastChild.textContent = text || '—';
    return d;
  };
  const sellFlags = document.createElement('div');
  for (const q of r.sell_questions || []) {
    const d = document.createElement('div');
    d.className = q.rebuild ? 'note' : 'q';
    d.textContent = q.rebuild
      ? ('~ rebuilt the board: sold ' + q.sold_count + ' ('
         + (q.sold_name || 'cards') + ' and others) — a repositioning, '
         + 'not a one-for-one choice')
      : ('? sold ' + (q.sold_name || 'a card') + ' (' + (q.role || '?')
         + ') while keeping ' + (q.kept_filler_names || []).join(', ')
         + ' — worth a look, not a verdict');
    sellFlags.appendChild(d);
  }
  const phaseRows = document.createElement('div');
  for (const p of phases) phaseRows.appendChild(phaseRow(p));
  // BATTLE — the fight after beginning-of-combat effects, both sides from
  // the same (peak) burst so the rows are honest relative to each other.
  // Opponent on top, mirroring the in-game combat view (2026-10-07).
  if (opts && opts.tavern) {
    // Design §4.5: the face-off — their board top, VS, yours below (your
    // side tinted warm, theirs cool), the result panel at right. The boards
    // are the same peak burst the classic rows use; the panel is the same
    // outcome wording the Result view carries.
    const wrap = document.createElement('div');
    wrap.className = 'faceoff-wrap';
    const fo = document.createElement('div');
    fo.className = 'faceoff';
    fo.appendChild(faceSide('Opponent', '', (r.combat_peak || {}).theirs,
                            r.combat_theirs_text || '—', 'cool'));
    fo.appendChild(el('div', 'vs', 'VS'));
    fo.appendChild(faceSide(opts.hero || 'You',
                            hpLine(r.eff, opts.nextEff),
                            (r.combat_peak || {}).ours,
                            r.combat_ours_text || '(no board read)', 'warm'));
    wrap.appendChild(fo);
    const left = minionsLeft(r.winner, r.battle_end, r.theirs_survivors);
    const panel = document.createElement('div');
    panel.className = 'fresult';
    panel.appendChild(el('div', 'fout ' +
      (r.winner === 'us' ? 'won' : r.winner === 'them' ? 'lost'
       : r.winner === 'tie' ? 'tie' : 'unk'), outcomeText(r.winner)));
    const line = (k, v) => {
      const d = document.createElement('div');
      d.innerHTML = '<span class="fk">' + k + '</span>';
      d.appendChild(el('span', 'fv', v));
      return d;
    };
    panel.appendChild(line('Minions left',
      left == null ? '—' : String(left)));
    panel.appendChild(line('HP taken', r.damage_taken == null ? '—'
      : r.damage_taken > 0 ? String(r.damage_taken)
      : r.damage_taken === 0 ? '0' : '−' + (-r.damage_taken) + ' (gained)'));
    wrap.appendChild(panel);
    bodies.battle.appendChild(wrap);
  } else {
    bodies.battle.appendChild(boardRow('Opponent brought',
      (r.combat_peak || {}).theirs, r.combat_theirs_text, 'them'));
    bodies.battle.appendChild(boardRow('You brought',
      (r.combat_peak || {}).ours, r.combat_ours_text || '(no board read)'));
  }
  for (const n of r.notes || []) {
    const d = document.createElement('div');
    d.className = 'note';
    d.textContent = n;
    bodies.battle.appendChild(d);
  }
  // SHOP — open to close, with the turn's events and the action list. The board
  // labels sit ABOVE their rows in Tavern (`tav`): a board is a full-width row
  // of cards, and a label beside it only took width from them (2026-10-09).
  bodies.shop.appendChild(r.turn === 1
    ? boardRow('Opened with', null, 'New game — nothing came before',
               null, null, tav)
    : noSnapshot
      ? boardRow('Opened with', null,
                 'No opening board recorded for this turn.', null, null, tav)
      : boardRow('Opened with', r.buy_start,
                 '(no shop snapshot — a skipped turn?)', null, null, tav));
  // The fight's summoned leftovers are removed from this board before it is
  // drawn (turn_review._opening_board), and the removal is SAID rather than
  // silently shortening the row: "the minions you opened with" is a fact the
  // player can check against what they saw.
  if (r.buy_start_removed) {
    const l = document.createElement('div');
    l.className = 'note';
    l.textContent = r.buy_start_removed + ' of these were leftover summoned '
      + 'copies from the previous fight, still in play in the log — removed, '
      + 'because a board holds 7';
    bodies.shop.appendChild(l);
  }
  // The Ended row is the OPENING board plus the turn's work — with no
  // opening snapshot AND no ended board there is no honest row, and an
  // empty one ("Ended with —") reads as "sold everything". Hidden, not
  // zeroed (2026-10-09). A turn with no snapshot that still staged a shop
  // keeps its Ended row: that board was read.
  if (!noSnapshot || (r.buy_end || []).length) {
    bodies.shop.appendChild(boardRow('Ended with', r.buy_end, r.buy_end_text,
      null, tav ? boardDelta(r.buy_start, r.buy_end) : null, tav));
  }
  if (tav) {
    // Passed through (design §4.4): minions bought AND sold this phase —
    // they never touch either board, so this tray is the only place their
    // card art appears. Ghost styling, hidden when there are none.
    const kinds = flipKinds((r.took || {}).bought, (r.took || {}).sold);
    const pool = ((r.took || {}).bought || []).concat((r.took || {}).sold || []);
    const flipped = Object.keys(kinds).filter(k => kinds[k] === 'flipped')
      .map(id => {
        const src = pool.find(x => (x.card || x) === id);
        return typeof src === 'string' ? {card: src, name: src} : src;
      });
    if (flipped.length) {
      const tray = document.createElement('div');
      tray.className = 'brow stacked';
      tray.innerHTML = '<span class="blbl">Passed through</span>';
      const wrap = document.createElement('span');
      wrap.className = 'brow-tiles';
      for (const m of flipped) {
        // A passed-through minion carries no stats in the took lists, so
        // statSub answers null and the ghost draws its name alone — the
        // "?/?" this tray used to print was a question, not a stat
        // (2026-10-09, player call).
        wrap.appendChild(tile(m.card, m.name || m.card, statSub(m),
                              {cls: 'ghost'}));
      }
      tray.appendChild(wrap);
      bodies.shop.appendChild(tray);
    }
  }
  // THE TURN line and the worth-a-look flags are CLASSIC-only (2026-10-09,
  // player call). In Tavern the rail already carries the flags, and the line's
  // numbers live in the rail's chips — the same facts printed twice, in two
  // vocabularies, is the duplication the rail exists to remove.
  if (!tav) {
    const evLine = document.createElement('div');
    evLine.className = 'brow';
    const evBits = [];
    if (ev.played != null) evBits.push('played ' + ev.played + ' card'
                                       + (ev.played === 1 ? '' : 's'));
    if (sp.total != null) evBits.push('spent ' + sp.total + 'g');
    if (s.growth != null) evBits.push('value ' + (s.growth >= 0 ? '+' : '')
                                      + s.growth);
    if (ev.tier_up) evBits.push('LEVELED UP');
    if (ev.hero_power) evBits.push('hero power');
    if ((ev.trinkets || []).length) evBits.push('trinket: '
                                                + ev.trinkets.join(', '));
    evLine.innerHTML = '<span class="blbl">The turn</span><span></span>';
    evLine.lastChild.textContent = evBits.join(' · ') || '—';
    bodies.shop.appendChild(evLine);
    bodies.shop.appendChild(sellFlags);
  }
  bodies.shop.appendChild(phaseRows);
  // RESULT — combat ends when one board dies, so the winner comes from the
  // fight, and exactly one side holds survivors (both on a tie).
  const w = r.winner;
  const resLine = document.createElement('div');
  resLine.className = 'brow';
  resLine.innerHTML = '<span class="blbl">Result</span><span></span>';
  resLine.lastChild.textContent =
      w === 'us' ? 'You won the fight'
    : w === 'them' ? 'You lost the fight'
    : w === 'tie' ? 'A tie — both boards died'
    : '(fight result not readable)';
  bodies.aftermath.appendChild(resLine);
  bodies.aftermath.appendChild(boardRow('You survived with',
    w === 'them' ? [] : r.battle_end,
    w === 'them' ? '— none' : r.battle_end_text, null, null, tav));
  bodies.aftermath.appendChild(boardRow('They survived with',
    w === 'them' ? r.theirs_survivors : [],
    w === 'them' ? '' : (w === 'tie' ? '— none — a tie' : '— none'),
    null, null, tav));
  // Same removal as the Shop view's opening board — this row IS that board, one
  // turn later — so it is disclosed in the same breath (2026-10-07).
  if (r.battle_end_removed) {
    const l = document.createElement('div');
    l.className = 'note';
    l.textContent = r.battle_end_removed + ' of these were leftover summoned '
      + 'copies from the fight, still in play in the log — removed, because a '
      + 'board holds 7';
    bodies.aftermath.appendChild(l);
  }
  const dmg = document.createElement('div');
  dmg.className = 'brow';
  dmg.innerHTML = '<span class="blbl">Damage taken</span><span></span>';
  dmg.lastChild.textContent = r.damage_taken != null
    ? (r.damage_taken > 0 ? r.damage_taken + ' HP'
       : r.damage_taken === 0 ? 'none' : 'none — you GAINED '
         + (-r.damage_taken) + ' effective HP')
    : '(not measured on this turn)';
  bodies.aftermath.appendChild(dmg);
  return card;
}
// Restore the last tab, defaulting to the live overlay.
let _tab = 'live';
try { _tab = localStorage.getItem('bl-tab') || 'live'; } catch (e) {}
showTab(_tab);
document.getElementById('settle-select').onchange = e => loadSettleGame(e.target.value);
// The Settle Up viewer flag (2026-10-08). Classic stays the default: the new
// design is being built behind the Tavern branch and is not done yet.
function setSettleViewer(v) {
  _viewer = v === 'tavern' ? 'tavern' : 'classic';
  try { localStorage.setItem('bl-settle-viewer', _viewer); }
  catch (e) { /* private mode */ }
  document.querySelectorAll('#settle-viewer button').forEach(
    b => { b.className = b.dataset.v === _viewer ? 'on' : ''; });
  if (_settleRep) renderSettleGame(_settleRep);
}
document.querySelectorAll('#settle-viewer button').forEach(b => {
  b.onclick = () => setSettleViewer(b.dataset.v);
  b.className = b.dataset.v === _viewer ? 'on' : '';
});
// The Live viewer flag (2026-10-09, LIVE_VIEW_DESIGN.md). Classic is the
// shipped renderer and stays the default; the choice persists per browser under
// its own key, exactly like the Settle Up flag above.
document.querySelectorAll('#live-viewer button').forEach(b => {
  b.onclick = () => setLiveViewer(b.dataset.v);
  b.className = b.dataset.v === _liveViewer ? 'on' : '';
});
// The Summary | Step through toggle in the Settle Up header (2026-10-09). It
// sits next to the game dropdown, so it is markup rather than something the
// renderer builds; the renderer only says which mode is on and whether Step
// through is available. The choice persists under its own key.
function refreshSettleMode(mode, hasSteps) {
  const seg = document.getElementById('settle-mode');
  if (!seg) return;
  seg.hidden = false;
  seg.querySelectorAll('button').forEach(b => {
    b.className = b.dataset.m === mode ? 'on' : '';
    b.disabled = b.dataset.m === 'step' && !hasSteps;
    b.title = b.disabled
      ? 'This saved game predates step-through — newer saves carry the '
        + 'per-action boards (Rebuild re-derives one from its log)'
      : '';
  });
}
function hideSettleMode() {
  const seg = document.getElementById('settle-mode');
  if (seg) seg.hidden = true;
}
document.querySelectorAll('#settle-mode button').forEach(b => {
  b.onclick = () => {
    if (b.disabled) return;
    stopTavernPlay();
    _tavernMode = b.dataset.m === 'step' ? 'step' : 'summary';
    try { localStorage.setItem('bl-settle-mode', _tavernMode); }
    catch (e) { /* private mode */ }
    if (_settleRep) renderSettleGame(_settleRep);
  };
});
// Keyboard (design §5), Tavern viewer only — Classic is untouched. Left and
// Right walk turns (Summary) or steps (Step-through); Shift+Left/Right walks
// turns while stepping; Space plays/pauses; Home and End jump to the ends.
// Ignored while typing, and only on the Settle Up tab.
document.addEventListener('keydown', e => {
  if (_viewer !== 'tavern'
      || document.getElementById('settle').className !== 'on') {
    return;
  }
  const tag = (e.target.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  const turns = ((_settleRep || {}).timeline || {}).turns || [];
  if (!turns.length) return;
  const idx = turns.findIndex(r => r.turn === _tavernTurn);
  const stepping = _tavernMode === 'step';
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const d = e.key === 'ArrowRight' ? 1 : -1;
    e.preventDefault();
    if (stepping && !e.shiftKey) {
      stopTavernPlay();
      _tavernStep = Math.max(0, _tavernStep + d);
      renderSettleGame(_settleRep);
    } else {
      const ni = Math.min(turns.length - 1, Math.max(0, idx + d));
      if (ni !== idx) {
        stopTavernPlay();
        _tavernStep = 0;
        _tavernTurn = turns[ni].turn;
        renderSettleGame(_settleRep);
      }
    }
  } else if (e.key === ' ' && stepping) {
    e.preventDefault();
    tavernTogglePlay();
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault();
    stopTavernPlay();
    _tavernTurn = turns[e.key === 'Home' ? 0 : turns.length - 1].turn;
    _tavernStep = e.key === 'End' ? 1e9 : 0;
    renderSettleGame(_settleRep);
  }
});
// The saved replays are plain JSON files; this just points Explorer at them.
document.getElementById('settle-folder').onclick = async () => {
  const b = document.getElementById('settle-folder');
  try {
    const r = await fetch(auth('/review/open-folder'), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: '{}',
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      b.textContent = j.error || 'Could not open';
      setTimeout(() => { b.textContent = 'Open folder'; }, 2500);
    }
  } catch (e) {
    b.textContent = 'Could not open';
    setTimeout(() => { b.textContent = 'Open folder'; }, 2500);
  }
};
// Rebuild the selected saved game from its own source log (2026-10-08):
// older saves upgrade to the current viewer's data — the Step-through's
// per-action boards most visibly. Slow by nature (it replays the game);
// the button says so while it works and reports the reason on failure.
document.getElementById('settle-rebuild').onclick = async () => {
  const b = document.getElementById('settle-rebuild');
  const id = document.getElementById('settle-select').value;
  if (!id) return;
  b.disabled = true;
  b.textContent = 'Rebuilding…';
  try {
    const r = await fetch(auth('/review/rebuild'), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      b.textContent = j.error || 'Could not rebuild';
      setTimeout(() => { b.textContent = 'Rebuild'; }, 4000);
      return;
    }
    await loadSettleList();
    await loadSettleGame(id);
    b.textContent = 'Rebuild';
  } catch (e) {
    b.textContent = 'Could not rebuild';
    setTimeout(() => { b.textContent = 'Rebuild'; }, 4000);
  } finally {
    b.disabled = false;
  }
};
</script>
</body>
</html>
"""


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.analysis = None
        # The serialized /analysis body and its ETag, built once per push
        # (update_analysis) instead of once per request — the page polls at
        # 300ms and a 304 between pushes is a header, not ~40KB of JSON.
        # The fresh-boot payload is the WELCOME state, not "{}": an empty
        # frame must teach, not render blank panels.
        self.payload = welcome_payload()
        self.etag = hashlib.sha1(self.payload).hexdigest()
        # The player-set banned tribes (POST /bans), or None when not set.
        # The ban reveal is on screen at t0 and the pool inference needs
        # minutes to converge, so a 5-tap override at hero pick is the
        # precise path (2026-09-19; the list itself is not in any log).
        self.manual_bans = None
        # The finished game's review (settle_up.render_html), or None. Built
        # off-thread by live.py when a game ends, because it REPLAYS the game
        # and the monitor's tick has to keep answering the log (2026-10-06).
        self.review = None
        self.review_label = None
        # The same review as its plain-dict rep — what POST /review/save
        # persists into replay_store. The HTML is for the page; the rep is
        # for the store (the tab re-renders it live, with card art).
        self.review_rep = None


#: The deliberate empty state (fresh boot, a new game's first tick, or a
#: manual Clear): the product's welcome — never the previous game's panel
#: dressed up as live advice. render() on the page draws it.
#:
#: Built per call rather than frozen at import, because the privacy sentence
#: now DESCRIBES the consent state instead of asserting a policy. The old
#: fixed line ("Nothing leaves your machine unless you share a session")
#: promised a feature that did not exist, and would have become false the
#: moment reports started being sent — a sentence that cannot drift from what
#: the code does is the only kind worth printing (2026-10-03).
def share_status():
    """(status, sent) for the card, never raising.

    Imported lazily and defended on purpose: the overlay must still draw if
    the sharing machinery is unhappy. A card that fails to render because
    telemetry broke is a worse bug than the telemetry being broken.
    """
    try:
        import share
        return share.status(), share.sent_count()
    except Exception:  # noqa: BLE001
        return "undecided", 0


def set_share_choice(share_it):
    """Record the player's answer. Returns the new status, or 'unknown'."""
    try:
        import share
        return share.set_choice(share_it)
    except Exception:  # noqa: BLE001
        return "unknown"


def _ordinal(n):
    """1st, 2nd, 3rd … 11th, 21st. A lobby seats eight, so 1st-8th is all the
    card can ever show, but a general helper costs three lines and "11st" would
    be a wrong nobody would trust anything else after."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _game_over_line(game_over):
    """One sentence about how the game ended, from what we actually know.

    The placement is in the analysis (`current_place`), so the card can name it
    rather than say "the game ended" — and every branch has to read as English
    with the fields missing, because a coach that attached to a finished session
    never advised at all and knows none of them.
    """
    place = game_over.get("placement")
    turn = game_over.get("turn")
    if place == 1:
        line = "First place — well played."
    elif isinstance(place, int) and 1 < place <= 8:
        line = f"You placed {_ordinal(place)}."
    else:
        line = "That game is finished."
    if turn:
        line += f" Round {turn}."
    return line


def _welcome_hint():
    """The first-run hint, led by the cause that can actually apply here.

    There are two reasons a player sees this card with no advice, and this
    card used to name only one of them: file logging off. A player whose game
    is installed on another drive was therefore told to fix a setting that was
    already right — the launcher had just switched it on — while the coach
    looked at a folder that does not hold their game. `config` resolves the
    client root now, so which cause it is can be answered here instead of
    guessed.

    No path from this machine appears in the text: this string is drawn in the
    overlay and ends up in every screenshot of it, which is why
    `config.config_hint()` is an env-var form in the first place.
    """
    logging_fix = (f"put this in {config.config_hint()} yourself "
                   f"(create the file if it is not there):")
    if os.path.isdir(os.path.join(config.HS_DIR, "Logs")):
        return ("Never seen a board read? Hearthstone only writes the log this "
                f"reads when file logging is ON. Run {config.launcher()} again "
                f"and say yes to let it turn that on for you — or {logging_fix}")
    return ("Never seen a board read? There is no Hearthstone log folder where "
            "the coach looked, so the game is probably installed somewhere else "
            "— the console window behind this page says how to point the coach "
            "at it, once. (If the game IS in the usual place, then file "
            f"logging is off: run {config.launcher()} again and say yes, or "
            f"{logging_fix})")


def share_state():
    """The consent question and its answer, in one shape for both payloads.

    The page's corner control renders from this, and it renders on EVERY
    payload — not just the welcome card — because a control that can only be
    reached at a game's start or end is not actually reversible mid-game
    (2026-10-07). `toggle` is the control's label; the question's own buttons
    come from `yes`/`no`.

    **A PAGE payload, not an analysis field.** It is added in `render_json`
    (and here), so it never reaches `decision_log` and therefore never reaches
    `session_report.SPEC` — the whitelist with teeth refuses any analysis key
    it does not name, and "how many reports this machine has sent" has no
    business in the corpus.
    """
    status, sent = share_status()
    return {"status": status,
            "ask": status == "undecided",
            "sent": sent,
            "question": "Send a summary of each game to help improve "
                        "the coach?",
            "yes": "Yes, share summaries",
            "no": "No thanks",
            "toggle": "Stop sharing" if status == "on" else "Turn sharing on"}


def auto_save_state():
    """The save-every-replay answer, for the end-of-game card's checkbox.

    A PAGE payload exactly like `share_state`: attached in `welcome_payload`
    and nowhere in the analysis, so it cannot reach `decision_log` and
    therefore cannot reach `session_report.SPEC`. The checkbox changes what
    happens WITHOUT a click — when the answer is yes, live.py writes the
    replay while the review builds (`auto_save_current_review`) — so the
    card renders the answer and yields the Save button to "Saved
    automatically" while it stands.
    """
    return {"enabled": replay_store.auto_save_enabled(),
            "label": "Save every replay automatically"}


_release_cache = None


def _release_stamp():
    """Which release this overlay was served by, for the corner stamp.

    `update.local_version()` is the one answer — the VERSION file on an
    install, the git sha in a checkout — memoized because render_json runs
    on every advice push and the answer cannot change under a running
    process (live.py restarts on update, so neither can the memo outlive
    the code that took it). A PAGE field exactly like `share`: attached in
    `render_json` and `welcome_payload`, never in the analysis, so it
    cannot reach `decision_log` or the report whitelist.
    """
    global _release_cache
    if _release_cache is None:
        try:
            import update
            _release_cache = update.local_version() or ""
        except Exception:  # noqa: BLE001 - a missing stamp beats a dead page
            _release_cache = ""
    return _release_cache


def welcome_payload(game_over=None):
    """The card the overlay shows when there is nothing to advise.

    TWO occasions wear this card, and they must not look alike:

    * a fresh start, or a manual Clear — the player needs the log.config steps;
    * the end of a game — the player needs to know the coach is still there.

    Until 2026-10-04 both drew the SAME card, so a finished game and a dead coach
    were indistinguishable on screen. The field report that produced this: the
    coach had advised through the whole final buy phase (turn 15), shared the
    complete game (268 advisories, 268 in the cloud) and stopped exactly when
    combat began — which is right, there is no shop to advise on — and the player
    watching the recap asked whether it had crashed. `game_over` carries what the
    last analysis knew, so the card can say what happened.
    """
    status, sent = share_status()
    if status == "on":
        privacy = ("Sharing one small summary per game — your decisions and "
                   "the outcome, with no names, no chat and no file paths"
                   + (f" ({sent} shared so far)." if sent else "."))
    elif status == "off":
        privacy = ("Not sharing: nothing leaves your machine. Games played "
                   "while this was off have not been sent, and turning it on "
                   "starts from the next game.")
    else:
        # The scope is said HERE, where the question is asked, because a yes
        # used to reach back and upload the games already recorded (2026-10-04).
        privacy = ("Nothing has been sent, and nothing will be until you "
                   "answer — and then only for games you play from that point "
                   "on. Sharing means one small summary per game: your "
                   "decisions and the outcome, with no names, no chat and no "
                   "file paths.")
    payload = {
        "welcome": True,
        "product": "Bob's Ledger",
        "tagline": "A real-time Hearthstone Battlegrounds coach",
        "status": "Waiting for your next buy phase — the board read appears here "
                  "the moment your shop opens.",
        "privacy": privacy,
        "share": share_state(),
        "auto_save": auto_save_state(),
        "release": _release_stamp(),
    }
    if game_over:
        payload["title"] = "Game over"
        # Only the fields we actually have: a null the page would have to
        # special-case is worse than an absent one (the convention
        # session_report.OMIT exists for the same reason).
        payload["game_over"] = {k: v for k, v in game_over.items()
                               if v is not None}
        payload["tagline"] = _game_over_line(game_over)
        payload["status"] = ("The coach is still running, watching for your "
                             "next game — the board read starts again the "
                             "moment your next shop opens.")
        # The plan itself is still never on this page (PIVOT.md): the card
        # offers SAVE, and the plan is read in the Settle Up tab, over saved
        # games. (The /review standalone page remains reachable by URL for
        # the just-finished game; it lost its button when the tab landed —
        # 2026-10-07, "we just don't need it anymore".)
    else:
        payload["hint"] = _welcome_hint()
        # The block live.py's console message has always claimed this card
        # shows.
        payload["steps"] = ("[Power]\nLogLevel=1\nFilePrinting=true\n"
                            "ConsolePrinting=false\nScreenshots=false")
    return json.dumps(payload).encode()


_state = _State()


def clear_analysis(keep_bans=False):
    """Reset the overlay to the welcome state.

    Fired on a new game's CREATE_GAME — the previous game's panel must
    never survive into the next one, and the manual bans wipe with it (the
    5/5 family ban differs per game). The page's Clear button passes
    keep_bans=True: mid-game, a wipe should blank the screen, not throw
    away a deliberate 5-tap ban set.
    """
    with _state.lock:
        _state.analysis = None
        _state.payload = welcome_payload()
        _state.etag = hashlib.sha1(_state.payload).hexdigest()
        if not keep_bans:
            _state.manual_bans = None


def show_game_over(analysis=None, placement=None, turn=None):
    """Replace the finished game's panel with the end-of-game card.

    Called the moment the log says the game ended. The panel must go — the plan
    it holds is advice for a game that is over — but the replacement must not be
    the first-run card: that is what made a finished game look like a dead coach
    (2026-10-04). `analysis` is whatever was last pushed, or None when the coach
    never advised; only its summary values are read, so nothing of the plan
    survives.

    `placement` comes from `LiveCoach.final_placement()` and is preferred over
    the analysis's `current_place`, which is a different reading: the last
    advisory is taken BEFORE the final fight resolves and before the game writes
    its last place, so the card could report a standing the game later revised
    (measured 2026-10-07: 4 against a true 3 on the 2026-10-06 13:00 game).

    `turn` is the round the game ended on, from the coach's own action count.
    It exists as an argument because the RESTART path has an analysis of None —
    the catch-up never advises — and the card still has to say "Round 12"
    rather than fall back to a dash (2026-10-09).
    """
    analysis = analysis or {}
    game_over = {"placement": placement if placement is not None
                 else analysis.get("current_place"),
                 "turn": turn
                 if turn is not None
                 else (analysis.get("turn")
                       or (analysis.get("scenario") or {}).get("turns")),
                 "health": analysis.get("health"),
                 "tier": analysis.get("tier")}
    with _state.lock:
        _state.analysis = None
        _state.payload = welcome_payload(game_over=game_over)
        _state.etag = hashlib.sha1(_state.payload).hexdigest()


def set_review(html_text, label=None, rep=None):
    """Hand the finished game's review to the overlay, for /review to serve.

    The pivot's other half (PIVOT.md §4 Phase 2): the model's plan is not in the
    live payload at all, and this is how a player gets to see it — after the
    game, on a page of its own. `live.py` builds it off-thread when a game ends,
    because building it replays the game.

    A review that fails to build leaves `review` as it was, so /review answers
    "still putting it together" rather than a broken page. The plain-dict
    `rep` rides along for POST /review/save (the Settle Up tab's store);
    the HTML alone cannot be saved, because rendering is one-way.
    """
    body = (html_text or "").encode("utf-8")
    with _state.lock:
        _state.review = body or None
        _state.review_label = label
        _state.review_rep = rep if body else None


def review_meta():
    """(is it ready, its label) — for tests and for the pending page."""
    with _state.lock:
        return _state.review is not None, _state.review_label


def current_review_rep():
    """The finished game's review dict, or None (nothing built yet this run)."""
    with _state.lock:
        return _state.review_rep


def _review_response():
    """(code, headers, body) for GET /review. Pure, like _analysis_response —
    so the pending path is testable without a socket."""
    with _state.lock:
        body = _state.review
    headers = {"Cache-Control": "no-store"}
    if body is None:
        return 200, headers, _review_pending_page().encode("utf-8")
    return 200, headers, body


def _json_response(code, obj):
    return code, {"Cache-Control": "no-store"}, json.dumps(obj).encode("utf-8")


def _review_list_response():
    """(code, headers, body) for GET /review/list — the Settle Up tab's
    dropdown. Reads the store, not memory: saved games survive restarts."""
    return _json_response(200, {"ok": True, "games": replay_store.list()})


def _action_label(names, cid):
    """A display label for an ACTION's card, never a raw id.

    Hero powers have no id->name row in any DB this ships: heroes.json
    carries each power's TEXT keyed by hero name, not the power's id, so
    `BG32_HERO_001p` used to reach the Step-through caption verbatim
    ("Cast BG32_HERO_001p"). The fix list's rule is what happens instead —
    name the kind ("hero power") when the name cannot be looked up, and
    never show a card id. A hero-power-shaped id (`...HERO...p`, the game's
    own convention) is the only shape this rewrites; everything else still
    goes through `value.display_name`, whose own contract — unknown ids come
    back as themselves — is what `_acted`'s raw-id fallback relies on.
    """
    cid = str(cid or "")
    if "HERO" in cid.upper() and re.search(r"p\d?$", cid):
        return "hero power"
    return value.display_name(names, cid)


def _name_timeline_boards(rep):
    """A copy of the rep with a display name on every timeline minion.

    The stored rep keeps card IDS (it is data, not rendering); the tab draws
    card tiles, which want names. Joined at SERVE time rather than stored,
    so the file stays canonical and a renamed card fixes old saves. The
    name DB lives behind _load_bg_names, the same one the live page's
    server side uses.
    """
    try:
        names = _load_bg_names()
    except Exception:  # noqa: BLE001 - unnamed ids beat a dead endpoint
        return rep
    out = json.loads(json.dumps(rep))   # a deep copy, cheaply
    for row in (out.get("timeline") or {}).get("turns") or []:
        for board in (row.get("buy_end"), row.get("battle_end"),
                      row.get("buy_start"), row.get("theirs_survivors"),
                      (row.get("combat_start") or {}).get("ours"),
                      (row.get("combat_start") or {}).get("theirs"),
                      (row.get("combat_peak") or {}).get("ours"),
                      (row.get("combat_peak") or {}).get("theirs")):
            for m in board or []:
                # Naming only: the golden flag is ALREADY on the minion, because
                # board_state._minion strips the `_G` suffix off the card id and
                # keeps the flag beside it. Measured on a 15-turn rep: 0 board
                # ids end in `_G`, 91 minions carry golden. A draft also set
                # `golden` here from a `_G` id — a case this path cannot produce.
                m["name"] = value.display_name(names, m.get("card"))
        # The Summary rail's action lists (2026-10-08): ids in the stored rep,
        # named the same way at serve time. Plain-string lists (every rep
        # saved before the rail existed) become the same {card, name} shape
        # here, so the renderer sees one shape regardless of save age.
        took = row.get("took") or {}
        for key in ("bought", "sold", "plays", "spell_ids"):
            lst = took.get(key)
            if isinstance(lst, list):
                took[key] = [
                    item if isinstance(item, dict) else
                    {"card": item, "name": _action_label(names, item)}
                    for item in lst
                ]
        # The Step-through's per-action boards name like every other board,
        # and each step's own action card gets a cardName for the caption.
        for st in row.get("steps") or []:
            st["cardName"] = _action_label(names, st.get("card"))
            for m in st.get("board") or []:
                m["name"] = value.display_name(names, m.get("card"))
    return out


def _review_game_response(rid):
    """(code, headers, body) for GET /review/game?id=... — one stored review,
    the whole rep, for the tab to render."""
    stored = replay_store.load(rid or "")
    if stored is None:
        return _json_response(404, {"error": f"no saved replay {rid!r}"})
    stored["rep"] = _name_timeline_boards(stored.get("rep") or {})
    return _json_response(200, dict(stored, ok=True))


def _review_save_response():
    """(code, headers, body) for POST /review/save — the end-of-game card's
    Save button. Persists the review that was built when the game ended.

    409 is the honest "nothing to save": no game has finished this run, or
    the build failed (the pending page already says which)."""
    rep = current_review_rep()
    if rep is None:
        return _json_response(
            409, {"error": "no finished game to save yet — the review "
                           "builds when a game ends"})
    out = replay_store.save(rep)
    return _json_response(200, dict(out, ok=True))


def _review_rebuild_response(body):
    """(code, headers, body) for POST /review/rebuild — re-derive one saved
    replay from its own source log (2026-10-08).

    Old saves predate later pipeline additions (the Step-through's
    per-action boards); the store's `session`+`log`+`game` pointer makes
    them upgradable in place. 409 carries the reason — usually Hearthstone
    having rotated the session log away."""
    rid = (body or {}).get("id") or ""
    if not rid:
        return _json_response(400, {"error": "no replay id"})
    fresh, err = settle_up.rebuild(rid)
    if err:
        return _json_response(409, {"error": err})
    return _json_response(200, dict(ok=True, id=rid, rep=fresh))


def auto_save_current_review():
    """Write the finished game's replay when the checkbox's answer is yes.

    This is the checkbox's whole promise (2026-10-07): the player turns it on
    once, and every finished game lands in the store as its review builds —
    live.py calls this from the SAME background build that produces the
    review, so no click and no second replay of the game. Returns the saved
    id, or None when the answer is no or nothing has finished. A failed write
    returns None rather than raising: the review the player is about to read
    matters more than the copy of it.
    """
    if not replay_store.auto_save_enabled():
        return None
    rep = current_review_rep()
    if rep is None:
        return None
    try:
        return replay_store.save(rep)["id"]
    except OSError:
        return None


def _review_auto_save_response(enabled):
    """(code, headers, body) for POST /review/auto-save — the card's
    checkbox. The route parses the body; this persists the answer and is
    pure in its argument, like _review_save_response is in the state."""
    replay_store.set_auto_save(enabled)
    return _json_response(200, {"ok": True, "enabled": bool(enabled)})


def _review_open_folder_response():
    """(code, headers, body) for POST /review/open-folder — the Settle Up
    tab's Open folder button. The browser cannot open a local directory;
    this asks the machine to (Explorer on Windows). 500 with the reason
    when the OS refuses, so the button can say so in place."""
    err = replay_store.open_dir()
    if err:
        return _json_response(500, {"error": err})
    return _json_response(200, {"ok": True})


def _review_pending_page():
    """What /review says before the review exists.

    Two honest cases, and the page names which: a game is being reviewed right
    now (the build replays it, so it takes a few seconds), or nothing has
    finished yet this run. It also names the command that works on any past
    game, because the overlay's review only ever covers the game that just
    ended — the logs are on disk and `settle_up.py` reads them.
    """
    ready, _label = review_meta()
    if _state.analysis is not None:
        line = "A game is in progress. The review appears here when it ends."
    else:
        line = ("No finished game this session yet. Start a game and the "
                "review appears here when it ends — or run "
                "<code>python app\\settle_up.py --latest</code> in the window "
                "you started the coach from, for any game already in the log.")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Settle Up</title>
<style>
  body {{ margin:0; background:#0d0d0d; color:#fff; padding:40px;
    font:15px/1.5 "Segoe UI", system-ui, sans-serif; }}
  .wrap {{ max-width:560px; margin:0 auto; }}
  h1 {{ color:#ffd97a; font-size:22px; margin:0 0 6px; }}
  p {{ color:#c3c2b7; }}
  code {{ background:#242422; padding:1px 5px; border-radius:3px; }}
</style></head><body><div class=wrap>
<h1>Settle Up</h1>
<p>{line}</p>
</div></body></html>"""


def store_manual_bans(tribes):
    """Set the manual banned-tribe list; an empty list clears it.

    Only canonical display names (tribes.DISPLAY_TRIBES) are accepted;
    everything else is dropped. Returns the list that stuck (sorted).
    """
    from tribes import DISPLAY_TRIBES
    roster = set(DISPLAY_TRIBES)
    clean = sorted({t for t in (tribes or [])
                    if isinstance(t, str) and t in roster})
    with _state.lock:
        _state.manual_bans = clean if clean else None
    return clean


def latest_manual_bans():
    """The manual banned tribes, or None when the player hasn't set any."""
    with _state.lock:
        return list(_state.manual_bans) if _state.manual_bans is not None \
            else None


@lru_cache(maxsize=1)
def _meta_rows():
    """(minions, spells, trinkets) as id→record maps. The meta DB reads are
    already lru_cached, but rebuilding these three dicts on every analysis
    push (up to ~3/s) was pure waste — they change only on a meta refresh
    (i.e. on process restart, which is the documented live.py contract)."""
    return ({m.get("id"): m for m in meta.minions()},
            {s.get("id"): s for s in meta.spells()},
            {t.get("id"): t for t in meta.trinkets()})


#: The long-form per-comp guides. Written for the player, and until
#: 2026-10-02 read by nothing at all: 20 files of mined commentary sat in
#: the release while the panel showed a comp's name, tier and card chips.
_GUIDE_DIR = os.path.join(_HERE, "meta", "guides")
_GUIDE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _plain_card_text(text):
    """The meta DB cites cards as `[[Name||id]]` (comps.json, and the curated
    trinket guides). The overlay shows the name: the id is for the scraper,
    not the player."""
    if not text:
        return None
    return re.sub(r"\[\[([^\]|]+)(?:\|\|[^\]]*)?\]\]", r"\1", text).strip() or None


def _enabler_lines(text):
    """`common_enablers` is newline-separated; the panel wants the lines."""
    plain = _plain_card_text(text)
    return [ln.strip() for ln in plain.splitlines() if ln.strip()] if plain else []


def _guide_display(markdown):
    """Guide markdown as readable plain text.

    Deliberately not a Markdown renderer: the overlay shows this in a <pre>,
    so the only transformation is dropping the syntax the reader would
    otherwise see (`#` markers, `**` emphasis, `>` quote prefixes) while
    keeping every word — including the attribution block, which is the
    provenance of the advice.
    """
    out = []
    for line in markdown.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s?", "", line)
        line = line.replace("**", "")
        out.append(line.rstrip())
    return "\n".join(out).strip()


#: Opening paragraph per comp slug, for the target box (see render_json).
_guide_openings = {}


def _guide_opening(markdown, limit=420):
    """The first real paragraph of a guide.

    Used as the target comp's on-screen summary when the comp has no
    `how_to_play` line: three comps lack one (including the maintainer's own
    Aberrations - Deity Feed), and their mined guides already say how the
    build works — so the panel quotes what exists instead of showing nothing,
    and instead of us inventing strategy text.
    """
    if not markdown:
        return None
    para = []
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            if para:
                break
            continue
        if text.startswith("#") or text.startswith(">"):
            continue        # title and provenance, not the pitch
        para.append(text)
    joined = " ".join(para).strip().replace("**", "")
    if not joined:
        return None
    return joined if len(joined) <= limit else joined[:limit].rsplit(" ", 1)[0] + "…"


def comp_guide(slug, comp):
    """The payload for GET /guide/<slug>: what the panel shows when a player
    expands a comp.

    Fetched on demand rather than pushed: ~2 KB of prose x 35 comps has no
    business in a payload the browser pulls three times a second, and nobody
    reads a guide they have not opened (the same reason art is fetched on
    demand). `curated` says whether there is a written `how_to_play` line;
    `markdown` is the mined guide. A comp with neither says so in the panel
    rather than looking empty.
    """
    out = {
        "slug": slug,
        "name": (comp or {}).get("name"),
        "difficulty": (comp or {}).get("difficulty"),
        "summary": _plain_card_text((comp or {}).get("summary")),
        "when_to_commit": _plain_card_text((comp or {}).get("when_to_commit")),
        "enablers": _enabler_lines((comp or {}).get("common_enablers")),
        "how_to_play": _plain_card_text((comp or {}).get("how_to_play")),
        "curated": bool((comp or {}).get("how_to_play")),
        # Both guide-derived fields are always present, None when the comp
        # has no guide file: a consumer should not have to guess the shape
        # from which comp it asked about.
        "markdown": None,
        "opening": None,
    }
    path = os.path.join(_GUIDE_DIR, f"{slug}.md")
    raw = None
    if _GUIDE_SLUG.match(slug or "") and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            raw = None
    if raw is not None:
        out["markdown"] = _guide_display(raw)
        # Computed from the RAW markdown: _guide_display has already stripped
        # the `#`, so heading detection on its output would hand back the
        # title as the opening paragraph.
        out["opening"] = _guide_opening(raw)
    return out


def _comps_by_slug():
    """The comp DB keyed by slug, for the on-demand guide route."""
    return {slug: c for slug, c in (meta.comps() or {}).items()
            if isinstance(c, dict)}


def _canon_tribe(raw):
    """A log tribe tag ("BEAST", "DEMON/QUILBOAR") as the meta DB's own name.

    `value.normalize` is the very canonicalizer `value.sell_reason` compares
    against, so a caption built from this cannot disagree with the reason about
    which tribe a minion belongs to.
    """
    if not raw:
        return None
    return value.normalize(raw) or raw


#: A comp with fewer games than this in our own corpus is flagged `low sample`#: rather than hidden (LIVE_VIEW_DESIGN.md §5/§11). It is a GAMES count because
#: that is what the corpus records — a threshold invented from a percentage would
#: be a number nobody measured, and the scraped tables carry no sample size at
#: all, so their low-sample marker stays unwritten (the §11 question, recorded
#: rather than guessed).
COMP_LOW_SAMPLE_GAMES = 10


def _comp_stats(rec):
    """One comp's corpus record -> §5's components, or None when there is none.

    From `meta/corpus_stats.json` — this project's OWN games, written by
    `replay_stats.py --save` — which is also why it is the one stats table the
    licensing question in §9 does not touch. Emits the average placement, the
    1-to-8 placement distribution as shares of the games played, and the top-4 /
    first-place shares; a comp the corpus has never seen returns None so the
    view can say so instead of drawing a zero (§5: a row appears only when the
    data exists).
    """
    rec = rec or {}
    try:
        games = int(rec.get("games") or 0)
    except (TypeError, ValueError):
        return None
    if games <= 0:
        return None
    places = [p for p in (rec.get("places") or []) if isinstance(p, int)]
    st = {
        "games": games,
        "low_sample": games < COMP_LOW_SAMPLE_GAMES,
        # Shares, not counts: the bars are an 8-slice picture of the same games
        # the `games` figure names, and a placement nothing finished in is a
        # real zero here (it is a share of a known sample).
        "dist": {str(p): round(100.0 * places.count(p) / games, 1)
                 for p in range(1, 9)},
    }
    if rec.get("avg_place") is not None:
        st["avg_place"] = round(float(rec["avg_place"]), 2)
    if places:
        st["top4_pct"] = round(100.0 * sum(1 for p in places if p <= 4) / games)
        st["first_pct"] = round(100.0 * places.count(1) / games)
    return st


def render_json(analysis):
    """Enrich coach.analyze output with card names for frontend display.

    This builds the LIVE view, so it is also where the verdicts stop: every
    name in LIVE_VERDICT_KEYS is dropped here, and nothing below may re-add
    one (the explicit assignments that used to copy top_move's buy step are
    gone with it). The analysis itself is untouched — it is what
    `decision_log.record()` writes and what the review reads back.
    """
    names = _load_bg_names()
    a = dict(analysis)
    for _k in LIVE_VERDICT_KEYS:
        a.pop(_k, None)
    # When this advice was produced. The page shows its age once it stops
    # being fresh, so a wedged live.py cannot pass for a live one (2026-10-02):
    # the overlay is only written on a successful analyze, and a frozen frame
    # used to look exactly like live advice.
    a["generated"] = time.time()
    # The sharing state rides every live payload: the corner control has to be
    # reachable for the whole session, not only on the welcome card (2026-10-07).
    a["share"] = share_state()
    # The release stamp rides with it (2026-10-07), for the same reason: a
    # screenshot should name the release without anyone digging for it.
    a["release"] = _release_stamp()
    a["board"] = [dict(m, name=names.get(m["card"], m["card"])) for m in analysis["board"]]
    # Group duplicate board minions (Fauna Whisperer ×2 with different stats
    # used to show as two confusing rows); score = the instance you'd sell
    # first, so the safe→keep order still reads right.
    grouped = {}
    sell = []
    for c, v in analysis["sell_rank"]:
        g = grouped.get(c)
        if g is None:
            g = {"card": c, "name": names.get(c, c), "score": round(v), "n": 1,
                 "golden": any(m["card"] == c and m.get("golden")
                               for m in analysis["board"])}
            grouped[c] = g
            sell.append(g)
        else:
            g["n"] += 1
            g["score"] = min(g["score"], round(v))
    # Lowest score first. This used to be the "safe to sell | do not sell"
    # split — the two group labels ARE a verdict, so they are gone (2026-10-06,
    # PIVOT.md) and what is left is a sorted list of your own board with each
    # minion's number and its composition role. The row is a fact about the
    # board, not an instruction about it.
    sell.sort(key=lambda g: g["score"])
    # Hand minions are NOT in the Sell row: a hand minion can't be sold —
    # it has to be played first (player-corrected 2026-09-09, superseding
    # the 2026-09-05 "hand minions are sellable too" note that put hand
    # cards under "Safe to sell"). The hand box carries the play advice;
    # the plan's full-board play step already names the board filler to
    # sell for room, and that's the card that's actually sellable.
    # Butchering fuel (2026-09-08, the comp page): with a destroy-cost spell
    # in hand, a safe-to-sell UNDEAD is worth more dead-by-cast than sold —
    # the cast gives permanent +5 Attack to ALL Undead and frees the same
    # slot, where selling gives 1 gold. Annotated so the Sell row and the
    # hand's cast steps point the same direction.
    spell_db = _load_spell_db()
    card_db = _load_card_db()
    holding_destroy = any("destroy a friendly"
                          in ((spell_db.get(s["card"]) or {}).get("text")
                              or "").lower()
                          for s in analysis.get("hand", []))
    if holding_destroy:
        for g in sell:
            race = ((card_db.get(g["card"]) or {}).get("race") or "")
            if g["score"] < SELL_FILLER_SCORE and "Undead" in (race or ""):
                g["fuel"] = True
    # WHY each Sell row sits there (2026-09-10 ask): the score alone can't
    # tell "comp core" (a keep!) from "stats only" (a safe sell) — the
    # reason rides each row from the same inputs the scoring used, so the
    # two can't disagree.
    board_by_card = {}
    for m in analysis["board"]:
        board_by_card.setdefault(m["card"], m)
    tc = analysis.get("target_cards") or {}
    core_ids = {c["card"] for c in (tc.get("core") or [])
                if isinstance(c, dict) and c.get("card")}
    addon_ids = {c["card"] for c in (tc.get("addons") or [])
                 if isinstance(c, dict) and c.get("card")}
    target_comp, target_slug = None, None
    for _slug, _c in (analysis.get("playable_comps") or {}).items():
        if isinstance(_c, dict) and _c.get("name") == analysis.get("target_comp"):
            target_comp, target_slug = _c, _slug
            break
    banned_tribes = set(analysis.get("banned") or [])
    for g in sell:
        board_minion = board_by_card.get(g["card"], {})
        g["why"] = sell_reason(board_minion, card_db.get(g["card"]),
                               comp=target_comp,
                               core=core_ids, addons=addon_ids,
                               banned_tribes=banned_tribes)
        # WHICH tribe the caption needs, and whether this row is the banned-tribe
        # one: the Tavern board caption reads "<Tribe> — out of play" instead of
        # the value pass's "banned tribe — can't grow" (fix list round 1 item 7),
        # and it is built from these two facts rather than by rewriting the
        # shared string the classic page and `test_hand_engine` both pin.
        # `normalize` is the same canonicalizer `sell_reason` compared with, so a
        # board minion logged as BEAST reads "Beast" and not the raw tag.
        g["tribe"] = _canon_tribe(board_minion.get("tribe"))
        g["off_play"] = (g["why"] == "banned tribe — can't grow")
    a["sell_rank"] = sell
    # Hand-charge engine status (2026-09-10: the Forager/Counter kit died
    # silently — the overlay now shows deployer on board? space? charging).
    a["engine"] = hand_engine(analysis.get("hand") or [], analysis["board"])
    # The hand, as FACTS: what is in it, what it is worth. value.hand_plan
    # also returns an action per row ("cast" / "play" / "hold") and the plan's
    # reason for it, and both ride the analysis the decision log keeps — but a
    # verb is an instruction, and the live page does not carry instructions
    # (2026-10-06, PIVOT.md). Dropped here rather than in hand_plan(), so the
    # review keeps the plan it needs.
    hand_rows = []
    for s in analysis.get("hand", []):
        row = {k: v for k, v in s.items() if k not in ("verb", "why")}
        row["name"] = names.get(s["card"], s["card"])
        hand_rows.append(row)
    a["hand"] = hand_rows
    # Tag shop entries by comp membership (core/addon) or kind (spell), so the
    # shop list shows why each card matters without opening the comp DB.
    # Each row also carries its tavern price: minions a FLAT 3 (the patch's
    # default for ALL tiers — the log's tag=479 minion costs are stale legacy
    # tier costs; 2026-09-06 log charged 3 for tags saying 1, player-confirmed),
    # spells their own per-spell price. A wrong price ("thinks minions cost 1
    # gold") is otherwise instantly misleading.
    tc = analysis.get("target_cards") or {}
    core = {c["card"] for c in tc.get("core", [])}
    addons = {c["card"] for c in tc.get("addons", [])}
    spell_db = _load_spell_db()
    spells = set(spell_db)
    # A hand-charge kit's deployer (2026-09-10): the tag names WHY the shop
    # row matters when the comp sets don't — "deploys hand" = the engine
    # piece that summons the chargers back onto the board.
    deployers = {k["deployer"] for r in (analysis.get("hand") or [])
                 for k in [HAND_DEPLOY_KITS.get(r.get("card"))] if k}
    from value import _buy_prices
    prices = _buy_prices(analysis)
    # Pool availability chips (phases 1-2, analysis/pool_availability.md):
    # the shared pool minus what WE hold, minus what FRESH seats hold
    # (sightings <= 2 rounds old — lobby.py). Stale seats are excluded, not
    # guessed at; the wording stays "pool left", never a lobby total.
    held = dict(analysis.get("own_pool") or {})
    for c, n in (analysis.get("opp_pool") or {}).items():
        held[c] = held.get(c, 0) + n
    # THE TAVERN ROW IS IN THE GAME'S OWN ORDER (2026-10-06, PIVOT.md).
    # value.shop_ranking returns most-valuable-first, and a best-first row IS
    # the recommendation — the ranking is the verdict, not just the score
    # beside it. live_coach hands us `shop_offers` (the offers in the order the
    # log lists them), so each tile keeps every FACT — its price, its pool
    # count, whether it is a comp piece, its value score — and loses the
    # ordering that made one of them "the" buy. `buy_this` (the named headline)
    # is in LIVE_VERDICT_KEYS, so the page cannot name one either.
    #
    # setdefault: two copies of the same minion CAN sit in one tavern, and
    # tavern_offers() does not dedupe while shop_rank does. First occurrence
    # wins, which is how a player reads the row.
    _order = {}
    for _i, _cid in enumerate(analysis.get("shop_offers") or []):
        _order.setdefault(_cid, _i)
    if _order:
        _ranked = sorted(analysis.get("shop_rank", []),
                         key=lambda cv: _order.get(cv[0], 1 << 30))
    else:
        # No offer list: an analysis recorded before this field existed (the
        # review renders old records), or a shop that has not parsed. Sort by
        # card id rather than leaving value.shop_ranking's order in place —
        # arbitrary is fine, best-first is the one thing this row must never
        # silently become again.
        _ranked = sorted(analysis.get("shop_rank", []), key=lambda cv: str(cv[0]))
    a["shop_rank"] = [dict(card=c, name=names.get(c, c), score=round(v),
                           price=prices.get(c),
                           pool=(pool.chip(c, held)
                                 if held is not None else None),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else
                                "deploys hand" if c.rstrip("_G") in deployers
                                else None))
                      for c, v in _ranked]
    # Next-opponent composition (phase 2): the seat's last-known board as
    # named tiles, golden-flagged, biggest first. Age rides along — the box
    # says "as of round N" so a stale preview never reads current.
    oc = analysis.get("opp_comp")
    if oc:
        cards = [{"card": c, "name": names.get(c, c), "n": n,
                  "golden": c in (oc.get("goldens") or [])}
                 for c, n in sorted(oc["cards"].items(),
                                    key=lambda kv: (-kv[1], kv[0]))]
        a["opp_comp"] = dict(oc, cards=cards)
    # Pre-commit "leads" tagging (comp meter): with no target committed yet,
    # shop cards that are unowned core of the leading candidate get a "leads
    # <tribe>" tag — that's the card the meter is waiting on. Once a target
    # exists the core/addon tags above take over.
    progress = analysis.get("comp_progress") or []
    if not analysis.get("target_comp") and progress:
        lead = progress[0]
        leads_set = set(lead.get("needs") or [])
        if leads_set:
            label = "leads " + (lead.get("tribe") or lead.get("name") or "")
            a["shop_rank"] = [dict(row, tag=label if row["card"] in leads_set
                                   else row["tag"])
                              for row in a["shop_rank"]]
    a["target_cards"] = analysis.get("target_cards")
    # The committing comp's own guidance, right where the player looks for the
    # plan. Only the target (one comp, a few hundred bytes) rides the payload;
    # every other comp's prose and guide comes from /guide/<slug> on expand.
    if target_comp:
        how_to_play = _plain_card_text(target_comp.get("how_to_play"))
        if not how_to_play:
            # Three comps have no curated `how_to_play` line (including
            # Aberrations - Deity Feed, which the plan commits to most often).
            # Their mined guide already explains the build, so quote its
            # opening instead of showing nothing — and without us inventing
            # strategy text. Cached: a guide changes only on a meta refresh,
            # which is a process restart (the same contract as _meta_rows).
            opening = _guide_openings.get(target_slug)
            if opening is None:
                opening = comp_guide(target_slug, target_comp)["opening"] or ""
                _guide_openings[target_slug] = opening
            how_to_play = opening or None
        a["target_comp_guide"] = {
            "slug": target_slug,
            "difficulty": target_comp.get("difficulty"),
            "when_to_commit": _plain_card_text(
                target_comp.get("when_to_commit")),
            "how_to_play": how_to_play,
            "enablers": _enabler_lines(target_comp.get("common_enablers")),
        }
    else:
        a["target_comp_guide"] = None
    # Commit-readiness meter (per-candidate core hits) — pre-commit the
    # player is otherwise blind to direction until comp_target fires. The
    # missing-core ids are named here so the UI can show them as tiles
    # ("these lead to <comp>") without a client-side id->name map.
    a["comp_progress"] = [
        dict(r, needs=[{"card": cid, "name": names.get(cid, cid)}
                       for cid in (r.get("needs") or [])])
        for r in progress
    ]
    # Playable comps, rich rows for the bottom comps panel (2026-09-09): the
    # analysis carries a slug->comp dict; the UI groups them by meta tier and
    # each row expands into its required cards, so it needs the full shopping
    # list with owned/banned flags — not just names. owned = on the board
    # (same rule as the target-comp box: the board is what fights), banned =
    # a banned-tribe core piece of a hybrid comp (_blocked_core — can't be
    # bought this game). Sorted meta-tier first so the panel can group.
    # game_comps (2026-09-11) is the live coach's game-level list for this
    # panel — during the ban-detection window it's ALL comps, each with
    # _tribe_confirmed so unconfirmed rows can dim; playable_comps remains
    # the evidence-only advisory filter and is the fallback for analyses
    # without game_comps (coach.py, tests).
    pc = analysis.get("game_comps") or analysis.get("playable_comps") or {}
    if isinstance(pc, dict):
        comp_items = list(pc.items())
    else:
        comp_items = [(c.get("name"), c) for c in (pc or [])
                      if isinstance(c, dict)]
    board_ids = {m["card"] for m in analysis["board"]}
    # Hand minions are owned too, and the Tavern comp screens count them
    # (LIVE_VIEW_DESIGN.md §4.4: "owned (board or hand)"). `owned` keeps the
    # classic panel's board-only rule — the board is what fights — and the
    # second flag rides along so the tavern view can tell board from hand
    # without changing what the shipped panel shows.
    hand_ids = {s["card"] for s in (analysis.get("hand") or [])
                if isinstance(s, dict) and s.get("card")}
    corpus_comps = (meta.corpus_stats().get("comps") or {})
    tier_rank = {"S": 0, "A": 1, "B": 2}
    comp_rows = []
    for slug, comp in comp_items:
        if not isinstance(comp, dict) or not comp.get("name"):
            continue
        blocked = set(comp.get("_blocked_core") or [])

        def rows(ids_, _blocked=blocked):
            return [{"card": cid, "name": names.get(cid, cid),
                     "owned": cid in board_ids,
                     "in_hand": cid in hand_ids,
                     "banned": cid in _blocked}
                    for cid in (ids_ or [])]

        comp_rows.append({
            "slug": slug,
            "name": comp["name"],
            "meta_tier": comp.get("meta_tier"),
            # The comp's tribe, for the Browse filter and the "Mixed" label
            # (§4.4). None is not missing data: `menagerie` has no single tribe
            # and the design renders exactly that case as `Mixed`.
            "tribe": comp.get("tribe"),
            # Its own corpus statistics, or None when the corpus never saw it.
            "stats": _comp_stats(corpus_comps.get(comp["name"])),
            # A comp with no published tier is NOT "Unranked" — that reads as
            # a real comp whose tier is merely unknown. Aberrations - Deity
            # Feed was promoted from our own mined corpus, so it has no
            # hsreplay tier to show; the panel labels the group accordingly.
            "tier_missing": not comp.get("meta_tier"),
            # Mined from our own corpus rather than published (value.
            # _is_provisional): the panel groups these under "Provisional"
            # instead of a tier, and they sort LAST — a comp with no published
            # tier must never appear above a real S/A/B comp.
            "provisional": bool(comp.get("provisional")),
            "evidence": comp.get("evidence"),
            # The curated guidance. Short fields ride the payload (a few
            # hundred bytes total); the prose and the mined guide are fetched
            # by /guide/<slug> when a row is expanded — see comp_guide().
            "difficulty": comp.get("difficulty"),
            "summary": _plain_card_text(comp.get("summary")),
            "when_to_commit": _plain_card_text(comp.get("when_to_commit")),
            "enablers": _enabler_lines(comp.get("common_enablers")),
            "has_guide": bool(comp.get("guide") or comp.get("how_to_play")),
            # Tribe confirmed in this lobby? Absent (True) once the bans
            # resolve; False only inside the detection window, where the
            # panel dims the could-still-be-banned rows.
            "tribe_confirmed": comp.get("_tribe_confirmed", True),
            "core": rows(comp.get("core")),
            "addons": rows(comp.get("addons")),
        })
    comp_rows.sort(key=lambda c: (1 if c["provisional"] else 0,
                                  tier_rank.get(c["meta_tier"], 3),
                                  c["name"] or ""))
    a["comps"] = comp_rows
    # The Buy box's mirrors of top_move's steps (buy_step_card / buy_step_roll)
    # and the slot arbiter's veto are GONE from the live view — they are three
    # spellings of "buy this one", i.e. LIVE_VERDICT_KEYS (2026-10-06). It also
    # retires a field that had already gone dead: buy_roll_text was copied on
    # every push and read by no line of the page.
    # The curated guide for each offered trinket. 110 of the 220 trinket rows
    # carry one and nothing rendered them — on the one screen where a wrong
    # pick costs the whole game, and where the panel already shows pick% and
    # average placement. Attached by NAME because the trinket DB is keyed by
    # name and the ids drift per patch (choices._load_trinket_db matches the
    # same way).
    _choice = analysis.get("choice") or {}
    if _choice.get("kind") == "trinket" and _choice.get("ranked"):
        _by_name = {t.get("name"): _plain_card_text(t.get("guide"))
                    for t in meta.trinkets() if t.get("guide")}
        _guides = {row[0]: _by_name[row[0]] for row in _choice["ranked"]
                   if row and row[0] in _by_name}
        if _guides:
            a["choice"] = dict(_choice, guides=_guides)
    # The options' statistics as NUMBERS, for the Tavern pick screen
    # (LIVE_VIEW_DESIGN.md §4.3/§5, 2026-10-09): a headline figure, "±x vs the
    # offered average", the placement distribution as bars. The classic panel
    # keeps its fact strings; the Tavern one renders these, which is also what
    # keeps the phrasing the design bans ("fits your board") off that screen —
    # it lives in the strings, not in the numbers. Attached to whatever
    # `a["choice"]` already is, so the trinket guides above survive.
    _rows = (_choice.get("ranked") or [])
    if _rows:
        _stats = choices.option_stats(_choice.get("kind"),
                                     [(r[0], r[1]) for r in _rows if r and len(r) > 1])
        if _stats:
            a["choice"] = dict(a.get("choice") or _choice, option_stats=_stats)
    # Scout strip (gates 3+4): our stat total vs the next opponent's
    # last-known board (exact — we fought them), else the lobby median /
    # corpus baseline (~ estimate).
    bs = analysis.get("board_stats")
    their = analysis.get("opp_stats")
    approx = their is None
    if their is None:
        their = analysis.get("lobby_opp")
    if their is None:
        their = analysis.get("baseline_opp")
    a["scout"] = (f"you {bs} stats · "
                  f"{'~' if approx else ''}{int(their)} theirs"
                  if bs is not None and their else None)
    # The NUMBERS behind that strip, for the Tavern Live view's facts table
    # (LIVE_VIEW_DESIGN.md §1/§4.2, 2026-10-09). `scout` and `forecast` are
    # verdict-bearing STRINGS ("favored", "strong", "behind") and the new view
    # shows numbers only, so it needs the numbers rather than a parse of the
    # words — deriving facts back out of a rendered string is the same mistake
    # `_top_move_text` had to undo for the plan's step cards.
    a["board_stats"] = bs
    a["opp_stats"] = None if approx else their
    a["opp_lobby"] = int(their) if (approx and their) else None
    a["opp_age"] = analysis.get("opp_age")
    # The next-fight verdict (stat ratio + our keyword edges) rides the
    # scout strip so "will the next fight kill me" is on screen.
    a["forecast"] = analysis.get("forecast")
    # Opponents' trinkets (visible in the log, 2026-09-08 ground truth) — free
    # intel the player cannot see in game. `dark_gifts` is DROPPED from the
    # payload since 2026-09-23 (the overlay no longer renders it: it listed gifts
    # the player already owns and the game already shows). render_json copies the
    # whole analysis, so the drop has to be explicit — leaving the key would keep
    # shipping state the page has no use for.
    a.pop("dark_gifts", None)
    a["opp_trinkets"] = analysis.get("opp_trinkets") or []
    # Thresholds the JS would otherwise hard-code — value.py's constants are
    # the single source; the page reads them with fallbacks so an old payload
    # still renders. `sell_safe_below` was here too, for the safe/keep split
    # the Sell box used to draw; that split was a verdict, so the constant no
    # longer has a consumer on the page (2026-10-06) — SELL_FILLER_SCORE still
    # gates the destroy-spell fuel tag below, server-side.
    a["thresholds"] = {"dying_hp": DYING_HEALTH}
    # Per-card display metadata for the overlay (2026-09-09): the tavern tier
    # for the '*N' name badge and the card text for the hover tooltip — so
    # cards whose full render isn't upstream (new sets, trinkets) still get
    # their text. Golden ids resolve to their base card; heroes carry no
    # tier/text in the DBs, so pick-panel names badge nothing.
    ids = set()
    ids.update(g["card"] for g in sell)
    ids.update(s["card"] for s in analysis.get("hand", []))
    ids.update(r["card"] for r in a["shop_rank"])
    ids.update(c["card"] for key in ("core", "addons")
               for c in (tc.get(key) or []))
    # The comps panel's shopping lists ride the same tooltip metadata.
    for comp in a["comps"]:
        for key in ("core", "addons"):
            ids.update(r["card"] for r in comp[key])
    # comp meter needs: the RENDERED rows (a["comp_progress"]) carry needs as
    # {card, name} dicts; the raw analysis rows carry needs as bare card-id
    # strings (value.comp_progress), and c["card"] on those raised
    # "string indices must be integers" — crashing every analysis push once
    # the meter had a candidate with unowned core (i.e. most of the game).
    ids.update(c["card"] for r in a["comp_progress"]
               for c in (r.get("needs") or []))
    choice = analysis.get("choice") or {}
    ids.update(row[1] for row in (choice.get("ranked") or [])
               if len(row) > 1 and row[1])
    mrows, srows, trows = _meta_rows()
    cards = {}
    for cid in sorted(ids):
        base = cid[:-2] if cid.endswith("_G") else cid
        rec = mrows.get(base) or srows.get(base) or {}
        entry = {}
        if rec.get("tier"):
            entry["tier"] = rec["tier"]
        text = rec.get("text") or (trows.get(base) or {}).get("description")
        if text:
            entry["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", text))
        if entry:
            cards[base] = entry
    a["cards"] = cards
    return a


def update_analysis(analysis):
    """Store the latest rendered analysis for the overlay to serve."""
    data = json.dumps(render_json(analysis)).encode()
    etag = hashlib.sha1(data).hexdigest()
    with _state.lock:
        _state.analysis = json.loads(data)
        _state.payload = data
        _state.etag = etag


def latest_analysis():
    with _state.lock:
        return _state.analysis


def _analysis_response(if_none_match=None):
    """(code, headers, body) for GET /analysis. Pure, so the 304 path is
    testable without a socket. ETag/304 rather than SSE: the transport is
    BaseHTTPRequestHandler (HTTP/1.0, no keep-alive) and the client is
    loopback — a 304 costs microseconds and reuses the request path that
    already exists."""
    with _state.lock:
        payload, etag = _state.payload, _state.etag
    headers = {"Cache-Control": "no-cache"}
    if etag:
        headers["ETag"] = f'"{etag}"'
    if if_none_match and etag and etag in if_none_match:
        return 304, headers, b""
    return 200, headers, payload


#: Who the overlay answers. Binding 127.0.0.1 keeps other MACHINES out; it
#: does not keep other PAGES out. A browser will happily POST to
#: http://127.0.0.1:8747 from any site it is showing — a cross-origin "simple
#: request" is sent without a preflight, and the attacker does not need to read
#: the reply — and with a hostname that resolves to loopback (DNS rebinding) it
#: can read replies too, because neither Host nor Origin was ever checked.
#:
#: Measured before this guard existed: a POST carrying
#: `Origin: https://evil.example` and `Content-Type: text/plain` flipped the
#: sharing consent from undecided to ON, and `GET /analysis` with
#: `Host: evil.example` returned the live analysis. So a page the player merely
#: visited could opt them into uploads, and (during play) read the overlay's
#: state, which includes the opponent's handle (2026-10-03).
#:
#: Three rules, cheapest first:
#:   * Host must be a loopback name — a rebinding page sends its own hostname.
#:   * Origin, when present, must be a loopback origin.
#:   * A POST must be application/json. A cross-origin page can send only
#:     text/plain, form-encoded or multipart without a preflight; demanding
#:     JSON forces one, and the browser then refuses on our behalf because no
#:     CORS headers are ever sent.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

#: The per-run access key (2026-10-08 audit). "" until start_server() makes
#: one, and an empty key authorizes NOTHING — so a handler built by hand (the
#: tests do that) refuses everything it is asked to check rather than falling
#: open. Never a constant: a key written into the source is a key whoever
#: reads the source already has.
_TOKEN = ""

#: The cookie a key-carrying request sets, so a BARE address keeps working in
#: the browser that has been let in once (2026-10-09, the maintainer's call:
#: "requiring the token in the url ... is very inconvenient", and a bookmark
#: of `http://127.0.0.1:8747/` is how a second monitor gets the overlay).
#: The KEY STAYS THE KEY: nothing is weakened, this only saves the player from
#: pasting a value the launcher already knows. What keeps it from re-opening
#: the audit finding is the rest of the guard, which is what actually defends
#: against another origin: SameSite=Strict (a page on another site cannot make
#: the browser send it at all), HttpOnly (this page's script has no use for it
#: — its key is substituted into the markup), and _foreign_caller's
#: Host/Origin/JSON checks, which refuse a cross-site caller even when a cookie
#: rides along.
_TOKEN_COOKIE = "bl_token"

#: How long the browser keeps that cookie. A week is arbitrary but generous;
#: the value stops working the moment the coach restarts, so the only thing
#: being decided here is how often a stale one has to be replaced.
_TOKEN_COOKIE_DAYS = 7


def _host_only(value):
    """The hostname inside a Host header or an Origin: lowercased, no port.

    "" when there is nothing usable — including the literal origin "null",
    which is what a sandboxed frame or a file:// page sends. Neither is our
    page, so the caller refuses it.
    """
    v = (value or "").strip().lower()
    if not v or v == "null":
        return ""
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if v.startswith("["):                      # [::1]:8747
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if ":" in v else v


class _Handler(BaseHTTPRequestHandler):
    #: The request's non-key query parameters, filled by _authorized. A class
    #: attribute so a handler that somehow reaches a route without having been
    #: authorized reads an empty mapping rather than raising.
    query_params = {}
    #: True once a request has proved the key by carrying it in the address, so
    #: the response hands the browser a cookie for the bare address. Set by
    #: _authorized, read by _send.
    _grant_key_cookie = False

    def _authorized(self):
        """False (after sending a 403) when the per-run access key is absent.

        The 2026-10-08 audit's remaining finding: the Host/Origin guard is
        browser-shaped — any LOCAL process can still read the live board and
        the opponent's composition, or flip the share consent, because the
        server is loopback and unauthenticated. Every request now carries
        the key start_server generated: ?token= on the URL (the page's own
        fetches ride auth(); the printed/opened URL embeds it) or an
        X-BL-Token header. Card art under /img/ and /card/ is exempt — it is
        not data, and the tooltips load it from a bare <img src> that cannot
        carry a header.

        The key is also taken OUT of the request here, and self.path is left
        as the PATH ALONE with the remaining parameters in self.query_params.
        That split is what keeps routing honest: every route below compares
        self.path, so `/analysis?token=…` has to arrive as /analysis rather
        than miss and fall through to the overlay page — a 200 carrying HTML
        where the page's own poll expects JSON, which is an overlay that never
        updates and never says why.
        """
        path, _, query = self.path.partition("?")
        given, params = None, {}
        for part in (query.split("&") if query else ()):
            if not part:
                continue
            key, _, value = part.partition("=")
            if key == "token":
                if given is None:
                    given = value
            else:
                params.setdefault(key, value)
        self.path = path
        self.query_params = params
        if path.startswith("/img/") or path.startswith("/card/"):
            return True
        from_url = given is not None
        if given is None:
            given = self.headers.get("X-BL-Token") or None
        cookie_key = self._cookie_key()
        if given is None:
            given = cookie_key
        if not _TOKEN or not given or not hmac.compare_digest(
                given.encode("utf-8", "replace"), _TOKEN.encode("utf-8")):
            self._send(403, "text/plain",
                       b"403 - this overlay needs its access key. Open it "
                       b"from the launcher, or copy the address the coach "
                       b"printed (it ends in ?token=...).")
            return False
        # The address proved the key and this browser did not already have it:
        # leave it in a cookie, so the next BARE load of this address is
        # authorized too. Not on every request — the page's own fetches all
        # carry ?token=, and re-announcing an identical cookie three times a
        # second is noise with nothing behind it.
        if from_url and cookie_key != _TOKEN:
            self._grant_key_cookie = True
        return True

    def _cookie_key(self):
        """This run's key out of the request's cookies, or None.

        Parsed with http.cookies rather than by splitting the header: a
        cookie's value may be quoted or percent-ish, and a hand-rolled split
        is how `bl_token="abc"` becomes a value that never matches.
        """
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except CookieError:
            return None
        morsel = jar.get(_TOKEN_COOKIE)
        return morsel.value if morsel else None

    def _foreign_caller(self):
        """True when this request did not come from the overlay's own page.

        Refuses it (403) as a side effect, so a caller only has to return.
        """
        host = _host_only(self.headers.get("Host"))
        if host and host not in _LOOPBACK_HOSTS:
            self._send(403, "text/plain", b"bad host")
            return True
        origin = self.headers.get("Origin")
        if origin is not None and _host_only(origin) not in _LOOPBACK_HOSTS:
            self._send(403, "text/plain", b"bad origin")
            return True
        return False

    def do_GET(self):
        if self._foreign_caller():
            return
        if not self._authorized():
            return
        if self.path.rstrip("/") == "/analysis":
            code, headers, body = _analysis_response(
                self.headers.get("If-None-Match"))
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review":
            # The model's plan, after the game (2026-10-06, PIVOT.md). Served
            # from the same loopback server as the overlay so the end-of-game
            # card can link to it without writing a file anywhere, and
            # no-store because it is replaced every game.
            code, headers, body = _review_response()
            self._send(code, "text/html; charset=utf-8", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review/list":
            # The Settle Up tab's dropdown: every saved game. Separate
            # endpoint from /review on purpose — the tab renders its own
            # view from the rep, and the standalone page stays exactly that.
            code, headers, body = _review_list_response()
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review/game":
            # One stored review's full rep, for the tab to render. The id is
            # read from the query rather than matched out of self.path: the
            # path is what routing uses, so the access key (?token=) and any
            # future parameter stay out of the route table entirely — a
            # `?token=` appended to this URL used to miss the regex and serve
            # the overlay page instead. The id charset is replay_store's own
            # filename charset, and it refuses a wandering id itself.
            code, headers, body = _review_game_response(
                self.query_params.get("id") or "")
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/artmiss":
            # Served BEFORE the /img regex (the pattern would otherwise not
            # match this path, but the ordering keeps the routes obvious).
            self._send(200, "application/json",
                       json.dumps({"misses": _active_misses()}).encode())
            return
        m = re.match(r"^/img/([A-Za-z0-9_]+)\.png$", self.path)
        if m:
            cid = m.group(1)
            path = os.path.join(ART_CACHE, f"{cid}.png")
            if not os.path.exists(path) and _can_retry(cid):
                # On-demand: fetch the PORTRAIT now so the hero/trinket/
                # minion art appears on the next UI poll instead of never.
                # The tile is 56x56 with object-fit:cover, so a framed
                # 256x388 card render would be cropped here — the square raw
                # art is what this endpoint is for (PORTRAIT_URLS).
                _fetch_render(cid)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    # Art is content-addressed by card id — cacheable hard.
                    self._send(200, "image/png", f.read(),
                               headers={"Cache-Control":
                                        "public, max-age=604800"})
                return
            self._send(404, "text/plain", b"no art cached",
                       headers={"Cache-Control": "no-store"})
            return
        m = re.match(r"^/guide/([a-z0-9-]+)$", self.path)
        if m:
            # The comp guide, on demand: a player opening a row is a human
            # event, so this never belongs in the 3/s payload. 404 for an
            # unknown slug rather than an empty 200 — the panel then knows
            # to say "no guide" instead of rendering a blank box.
            comp = _comps_by_slug().get(m.group(1))
            if comp is None:
                self._send(404, "text/plain", b"no such comp",
                           headers={"Cache-Control": "no-store"})
                return
            body = json.dumps(comp_guide(m.group(1), comp),
                              ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body,
                       headers={"Cache-Control": "no-cache"})
            return
        if self.path.startswith("/guide/"):
            # Anything else under /guide/ is a malformed slug or a traversal
            # attempt. Answer 404 rather than falling through to the overlay
            # page: a JSON endpoint that returns HTML on a bad request hides
            # bugs on both sides.
            self._send(404, "text/plain", b"no such guide",
                       headers={"Cache-Control": "no-store"})
            return
        m = re.match(r"^/card/([A-Za-z0-9_]+)\.png$", self.path)
        if m:
            # The hover tooltip's full render (framed card WITH text),
            # cached in img_cache/card/. Golden ids resolve to the base
            # card. Its own source chain and its own miss list: a hero is
            # missing from the Battlegrounds render and a current-patch
            # minion from the generic one (CARD_URLS).
            cid = m.group(1)
            if cid.endswith("_G"):
                cid = cid[:-2]
            path = os.path.join(CARD_DIR, f"{cid}.png")
            if not os.path.exists(path) and _can_retry(cid, card=True):
                _fetch_render(cid, dest_dir=CARD_DIR, urls=CARD_URLS, card=True)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    self._send(200, "image/png", f.read(),
                               headers={"Cache-Control":
                                        "public, max-age=604800"})
                return
            self._send(404, "text/plain", b"no card render cached",
                       headers={"Cache-Control": "no-store"})
            return
        # The page itself: no-cache so a Phase-2 CSS edit is picked up on
        # refresh (it previously had no validator at all, and Chrome's
        # heuristic caching served stale markup).
        self._send(200, "text/html; charset=utf-8", _page_html().encode(),
                   headers={"Cache-Control": "no-cache"})

    def do_POST(self):
        if self._foreign_caller():
            return
        if not self._authorized():
            return
        # Application/json is required, not merely expected: it is the line a
        # cross-origin page cannot cross without a preflight.
        ctype = (self.headers.get("Content-Type")
                 or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._send(415, "text/plain",
                       b"expected Content-Type: application/json")
            return
        if self.path.rstrip("/") == "/bans":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "application/json", b'{"error":"bad json"}')
                return
            banned = store_manual_bans(payload.get("banned"))
            self._send(200, "application/json",
                       json.dumps({"ok": True, "banned": banned}).encode())
            return
        if self.path.rstrip("/") == "/share":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "application/json", b'{"error":"bad json"}')
                return
            if not isinstance(payload.get("share"), bool):
                self._send(400, "application/json",
                           b'{"error":"share must be true or false"}')
                return
            state = set_share_choice(payload["share"])
            # The card must redraw with the new sentence, and the page polls
            # with If-None-Match: leaving the old payload/etag in place would
            # serve a 304 and the player would watch their click do nothing.
            with _state.lock:
                _state.payload = welcome_payload()
                _state.etag = hashlib.sha1(_state.payload).hexdigest()
            self._send(200, "application/json",
                       json.dumps({"ok": True, "status": state}).encode())
            return
        if self.path.rstrip("/") == "/clear":
            # The page's Clear button: blank the overlay but keep the
            # player's manual bans (mid-game, a wipe should not throw away
            # a deliberate 5-tap ban set).
            clear_analysis(keep_bans=True)
            self._send(200, "application/json", b'{"ok": true}')
            return
        if self.path.rstrip("/") == "/review/save":
            # The end-of-game card's Save button: persist this game's review
            # into replay_store. The one verdict-shaped write the page can
            # trigger, and only after the game it describes is over.
            code, headers, body = _review_save_response()
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review/rebuild":
            # The Settle Up header's Rebuild button: re-derive a saved game
            # from its own source log, in place. Slow by nature (it replays
            # the game) and 409 with the reason when the log is gone.
            n = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "application/json", b'{"error":"bad json"}')
                return
            code, headers, body = _review_rebuild_response(payload)
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review/auto-save":
            # The end-of-game card's checkbox (2026-10-07): persist the
            # save-every-replay answer. From then on the replay is written
            # as the review builds, with no click — which is why the answer
            # lives on disk and not in the page.
            n = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "application/json", b'{"error":"bad json"}')
                return
            if not isinstance(payload.get("enabled"), bool):
                self._send(400, "application/json",
                           b'{"error":"enabled must be true or false"}')
                return
            code, headers, body = _review_auto_save_response(payload["enabled"])
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/review/open-folder":
            # The Settle Up tab's Open folder button: the replays are plain
            # JSON files and a player may want them as such.
            code, headers, body = _review_open_folder_response()
            self._send(code, "application/json", body, headers=headers)
            return
        self._send(404, "text/plain", b"no such endpoint")

    def _send(self, code, ctype, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if self._grant_key_cookie and _TOKEN:
            # Persistent, because the whole point is a bookmark on a second
            # monitor: a session cookie dies with the browser and brings the
            # complaint straight back. The key itself is per RUN, so a cookie
            # older than this run is refused exactly like a stale URL is —
            # opening the launcher's address is what refreshes it. No `Secure`:
            # the overlay is plain http on loopback, and a Secure cookie would
            # simply never be stored.
            self.send_header(
                "Set-Cookie",
                f"{_TOKEN_COOKIE}={_TOKEN}; Path=/; HttpOnly; SameSite=Strict; "
                f"Max-Age={_TOKEN_COOKIE_DAYS * 86400}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence request logging
        pass


def _page_html():
    """The overlay page, with this run's access key in its script.

    The page's own fetches carry the key through auth(), so the markup that
    reaches the browser must hold the REAL one. _HTML keeps the placeholder
    on purpose: the substitution is what is testable, and a page that shipped
    the literal `__BL_TOKEN__` would 403 on every poll with the overlay
    looking alive.
    """
    return _HTML.replace("__BL_TOKEN__", server_token())


def _port_in_use(port, host="127.0.0.1", timeout=0.4):
    """Is something already answering on this port?

    Windows lets a second socket bind a port another process is LISTENING on
    (SO_REUSEADDR means something different there than on POSIX), so
    start_server() could bind "successfully" and then serve nothing: every
    request went to the first process, and a second live.py showed a
    permanently frozen overlay with no error at all (found 2026-10-02 — an
    audit's leftover live.py held 8747 and a fresh server silently got no
    traffic). Probing first turns that into a visible fact.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def start_server(port=DEFAULT_PORT):
    """Start the overlay server in a background thread; returns the server.

    Threading: an on-demand art fetch blocks that request for up to ~5s —
    on the single-threaded server it would stall /analysis polling.

    A port that already answers is stepped over rather than hijacked, and
    said out loud: the alternative is an overlay that never updates while
    looking perfectly healthy.

    Generates the per-run access token (2026-10-08 audit): the overlay's
    loopback server carries the live board, the opponent's composition and
    the consent and share state — exactly what a local process should not
    be able to read or flip. Every request is checked against it
    (_Handler._authorized) except card art; overlay_url() is the address
    that carries it, and live.py both prints and opens that one.
    """
    global _TOKEN
    _TOKEN = secrets.token_urlsafe(16)
    if port and _port_in_use(port):
        alt = port + 1
        while alt < port + 10 and _port_in_use(alt):
            alt += 1
        print(f"Note: port {port} is already answering — another Bob's Ledger "
              f"overlay is probably running (an old one shows stale advice). "
              f"Serving on {alt} instead.")
        port = alt
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def server_token():
    """This run's overlay access token, for the URL live.py prints/opens."""
    return _TOKEN


def overlay_url(server, path="/"):
    """The overlay's own address, access key included.

    live.py prints and opens THIS, and it is the only place the key reaches a
    browser: the page a player lands on is the one that hands its script the
    key. The key rides the query rather than a header because a page load
    cannot set one — and nothing here needs escaping, since token_urlsafe's
    alphabet is [A-Za-z0-9_-] and every path this is used with is plain.
    """
    return (f"http://127.0.0.1:{server.server_address[1]}{path}"
            f"?token={server_token()}")


def main():
    import sys
    port = DEFAULT_PORT
    for a in sys.argv[1:]:
        # There was no argument handling at all here: `coach_ui.py --help`
        # started the server and blocked forever, and `--port` without `=`
        # crashed on a split() index (2026-10-02).
        if a in ("-h", "--help"):
            print("usage: python coach_ui.py [--port=N]\n"
                  "  serves the overlay on 127.0.0.1 (live.py starts it for "
                  "you); Ctrl+C to stop.")
            return 0
        if a == "--port":
            print("--port needs a value: --port=8747 (try --help)")
            return 2
        if not a.startswith("--port="):
            print(f"unknown argument: {a} (try --help)")
            return 2
        try:
            port = int(a.split("=", 1)[1])
        except ValueError:
            print(f"--port needs a number: {a} (try --help)")
            return 2
    server = start_server(port)
    # The server's OWN port, not the requested one: a busy 8747 is stepped
    # over, and this line used to name the port the player could not use.
    print(f"Coach UI serving at {overlay_url(server)}  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
