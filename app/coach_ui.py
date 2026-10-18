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

# macOS + a python.org build ship no CA bundle, so every https call here fails
# with CERTIFICATE_VERIFY_FAILED until OpenSSL is pointed at one (MEASURED
# 2026-10-16 — see `config.trust_store`). It has to run BEFORE the first
# request, which is why it is at import and not inside a helper.
config.trust_store()

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

#: Fields the live page no longer reads, dropped from the payload with the
#: classic renderer (tossed 2026-10-14; their last reader went 2026-10-13,
#: bebfb4f).
#:
#: A SECOND LIST, DELIBERATELY NOT MERGED WITH THE ONE ABOVE. LIVE_VERDICT_KEYS
#: is the pivot: the plan is computed, recorded, and shown only after the fact.
#: These seven are one layer down and a different reason entirely — the live page
#: had two renderers, the Classic one was deleted, and each of these was read by
#: no line that is left. Merging them would put two unrelated meanings in one
#: list, and then neither question could be audited: "is the model's plan off the
#: page" (the pivot) is not the question "can any page code still read this"
#: (dead payload weight).
#:
#: They kept shipping because the page's view is `dict(analysis)` plus this
#: function's own derivations, and nothing had ever asked, key by key, which of
#: those a page could still render. So the DERIVATIONS ALL STAY — dropping the
#: key in render_json is the whole change, and keeping the producer is what lets
#: `test_live_view` prove the absence is the DROP rather than a name that stopped
#: existing anywhere.
#:
#:   thresholds        the dying-HP threshold coloured the classic strip's HP
#:                     tile. render_json invented this key; the analysis never
#:                     carried it, and value.DYING_HEALTH is untouched.
#:   comp_progress     render_json derives the pre-commit "leads <tribe>" shop
#:                     tag from it (above) and that derivation still reads the
#:                     ANALYSIS. The analysis field is read by replay_review,
#:                     turn_review, session_report's whitelist and value's own
#:                     producer, so it stays — the review and the corpus are
#:                     what it is FOR (PIVOT.md).
#:   engine            render_json's own copy of value.hand_engine's answer, for
#:                     the classic "Hand engine" row. Nothing else read it.
#:   scout             the classic "you N stats · ~M theirs" strip. The seat and
#:                     lobby SCOUT (live_coach._scout, lobby.LobbyScout) is a
#:                     different thing with the same word in its name and is
#:                     untouched, as are board_stats / opp_stats / opp_lobby —
#:                     the numbers the Tavern Facts table reads.
#:   shop_offers       render_json's own offer-ORDER fallback for `shop_rank`
#:                     (above), and that derivation is its only reader anywhere.
#:                     The analysis field stays BECAUSE of it: the page's row
#:                     order comes from this list, so without the field every
#:                     shop row would fall back to sorting by card id — the
#:                     arbitrary-but-honest branch, which is not the game's
#:                     order. session_report names it in DROPPED_FROM_ANALYSIS,
#:                     so it is also one of the keys the report never sends.
#:   target_cards      render_json's core/addon shop tags. The analysis field is
#:                     read by value.py, turn_review and coach.py.
#:   target_comp_guide render_json's target-comp guide box, and nothing else.
#:
#: test_live_view.py carries the pivot's three halves onto this set, with the
#: control that matters: with the set emptied every one of the seven comes back.
LIVE_UNREAD_KEYS = frozenset({
    "thresholds",         # the classic strip's HP tile
    "comp_progress",      # render_json's "leads <tribe>" tag (derived above)
    "engine",             # the classic "Hand engine" row
    "scout",              # the classic scout strip
    "shop_offers",        # render_json's offer-order fallback for shop_rank
    "target_cards",       # render_json's core/addon shop tags
    "target_comp_guide",  # render_json's target-comp guide box
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
_art_epoch_cache = (0.0, "0")    # (monotonic seconds, value) — see art_epoch()


def art_epoch():
    """A short token that changes whenever the art cache does.

    Art is served with a WEEK-LONG max-age because it is content-addressed by
    card id — and the id does not pin the picture. MEASURED 2026-10-17: 106
    cached portraits turned out to hold card RENDERS, and the repair was invisible
    for up to seven days because `/img/<id>.png` never changed and the browser
    never asked again. A correct file behind a week-long cache is a file nobody
    sees.

    So the page versions every art URL with this token: a changed cache is a
    changed URL, the browser fetches it once, and every load in between keeps the
    hard cache. mtimes only — no image work — memoised for a second so a page load
    and its assets do not each stat 1,200 files.
    """
    global _art_epoch_cache
    import time as _time
    now = _time.monotonic()
    if now - _art_epoch_cache[0] < 1.0:
        return _art_epoch_cache[1]
    newest = 0.0
    for d in (ART_CACHE, CARD_DIR):
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        newest = max(newest, e.stat().st_mtime)
                    except OSError:
                        pass
        except OSError:
            pass                      # no cache dir yet: the epoch stays 0
    value = str(int(newest))
    _art_epoch_cache = (now, value)
    return value


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
  /* (The STATE STRIP lived here: stat tiles, the trigger chips, the ban and
     out-of-play lists, the next-fight forecast. It was the classic live page's
     header row, and the Tavern view answers all of it in `lvStatus` and
     `lvFacts` with rows rather than a strip. Nothing writes to it any more, so
     the element and its rules went with the renderer on 2026-10-13 — a live
     rule for a class nothing carries is how a removed control comes back.) */
  /* (The tribe picker's chip row lived here — `.inplaychips`, the five in the
     tavern, red-with-a-line-through until 2026-10-13 inverted it to an
     affirmative mark. The Tavern view has its own row (`.lv-tribes`), and the
     `/bans` + `/in_play` route keeps serving it; only this renderer's copy of
     the picker is gone.) */
  /* ONE COLUMN (2026-10-13). The two-pane page is gone: DECIDE held the turn's
     decision and was sticky, REFERENCE scrolled beside it. With a single
     renderer the shell has one element left — the welcome and game-over card's
     slot — so the second track, the sticky rule and the pane-stack rule had
     nothing to lay out. NEVER set overflow here: it clips the 4.5x hover zoom. */
  #app { display:grid; grid-template-columns:minmax(0,1fr);
         gap:8px; align-items:start; }
  /* The short-window fallback. Kept as a flex COLUMN rather than deleted with
     the two-pane layout: it is the branch the browser suite measures the live
     view in (a 1400x900 window lands here), and `flex-basis` being a height in
     it is the bug fix list round 1 item 1 was about. */
  @media (max-width:1199.98px), (max-height:899px) {
    #app { display:flex; flex-direction:column; }
  }
  /* (The SITUATION BOX lived here — `.instructions`, the gold-bordered card
     that led the page, with its `.situation` read, its `.danger` fragility band
     (`.fragile`/`.dying` + `.dmark`) and its `.footline` rows, plus the
     `.box`/`.box h3` panel they were built from. Every one of them was rendered
     by the classic live page, which went on 2026-10-13; the Tavern view answers
     the same questions in `lvFacts`/`lvBoardHand` panels, and its own fragility
     band is a row. A rule whose class nothing carries is how a removed control
     comes back, so the rules went with the renderer.) */
  /* (The plan-step rules lived here: the kind chip, the action, the tag, the
     reason, the hover clone, and "step 1 is the view's ONE hero". All of it
     styled the numbered plan, which the live page no longer renders — the step
     vocabulary went with it on 2026-10-06, PIVOT.md. The `.hero` rule's whole
     premise was that one line was the answer.) */
  /* Horizontal game-like card tiles: thumb on top, name below. (The `.tiles`
     flex ROW was the classic page's card container: the Tavern view puts its
     cards in `.lv-row`, `.brow-tiles`, `.lv-opts` and `.lv-slots`. It went with
     that renderer on 2026-10-13, and `.tile` itself survives — the Tavern card
     IS this component, restyled under `.tavern`.) */
  .tile { display:flex; flex-direction:column; align-items:center; gap:2px;
          width:104px; min-width:0; text-align:center; }
  .tile .thumb { width:56px; height:56px; }
  .tile .tname { font-size:12px; line-height:1.25; width:104px; overflow:hidden;
                 text-overflow:ellipsis; white-space:nowrap; }
  .tile .tsub { font-size:11px; color:var(--text-2); }
  /* THE SMALL TILE (2026-10-17): the step-through's tavern and hand rows. The
     live tile is 56px; these are 32px — the board keeps the live size, and the
     two rows that only give context sit clearly below it. */
  .tile.mini { width:64px; }
  .tile.mini .thumb { width:32px; height:32px; border-radius:4px; }
  .tile.mini .tname { font-size:10px; width:64px; line-height:1.15; }
  .tile.mini .tsub { font-size:10px; }
  .stepmini { display:flex; align-items:flex-start; gap:10px; margin:4px 0 2px; }
  .stepmini.dim .minitiles { opacity:.72; }
  .minilbl { font-size:10px; letter-spacing:.09em; color:var(--dim);
             padding-top:5px; min-width:52px; }
  .mininote { font-size:10px; color:var(--dim); padding-top:6px; }
  .minitiles { display:flex; flex-wrap:wrap; gap:8px; }
  /* (`.tile.buynow` — the plan's pick glowing gold in the shop row — went with
     the ranking itself: one lit tile is the recommendation the live page no
     longer makes, 2026-10-06.) */
  /* (The sell groups lived here: "Safe to sell | Do not sell" as two labelled
     columns with a divider and good/bad name colors. Both labels are verdicts;
     the box is "Your board" now, one row of numbers and roles.) */
  /* (The HAND ENGINE row (`engrow`/`engbit`) and the target-comp tile states
     (`comprow`/`missing`/`bannedrow`) lived here. Both were the classic live
     page's boxes — the engine checks and the "comp pieces" hunt list — and went
     with it on 2026-10-13. `hand_engine` still computes the engine and
     `render_json` still builds the key; `LIVE_UNREAD_KEYS` is what keeps it off
     the page (2026-10-14). It is the RENDERING that is gone.) */
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
  /* POINTER-EVENTS:NONE IS LOAD-BEARING (2026-10-17). The tip is placed just
     under the tile and clamped up when there is no room below, so on a low row
     it lands OVER the tile it describes. A tip that takes the pointer then
     fights the tile: entering it fires the tile's mouseleave, which hides it,
     which puts the pointer back on the tile, which fires mouseenter — a flicker
     with no stable state. MEASURED: the maintainer's report, "it either doesn't
     show up or blinked in and out", on the ENDED WITH row and not the row above
     it, which is exactly the clamp's geometry. */
  #tip { position:fixed; z-index:50; max-width:300px; pointer-events:none; }
  .tiprender { display:block; width:256px; border-radius:8px;
               box-shadow:0 8px 24px var(--shadow); }
  .tipbox { background:var(--panel2); border:1px solid var(--border);
            border-radius:var(--radius); padding:6px 9px; max-width:280px;
            box-shadow:0 8px 24px var(--shadow); }
  .tipname { font-weight:700; font-size:13px; }
  .tiptext { font-size:12px; color:var(--text-2); margin-top:2px; }
  /* (The classic COMPONENTS PANEL's rules lived here — `cptier` tier headers,
     the `crowhead`/`crow`/`carrow`/`cname`/`cstat`/`cbody` rows with their
     `unconf` state, the `cguidance`/`cline` advice block and the
     `cguideslot`/`cguidefull`/`cguidemd` fetched-guide node. The panel, its
     helpers and the `/guide/<slug>` renderer went on 2026-10-13; the Tavern
     comps screen has its own vocabulary (`lv-crow`, `lv-copen`, `lv-meta`,
     `lv-gmd`) and its own `lvLoadGuide`. The classic picker's `.chips`/`.chip`
     row went with them — the Tavern tribe row is `.lv-tribes`/`.lv-chip`.) */
  /* (The plan's per-step line and its gold step number lived here. The plan is
     not rendered on the live page any more — 2026-10-06, PIVOT.md.) */
  /* (THE TARGET-COMP BOX, THE COMP-DIRECTION METER AND THE PANE HEADERS lived
     here: `.target`, the `tag-core`/`tag-spell`/`tag-addon` shop tags, the
     `.mrow` meter with its `meter`/`near`/`met`/`fill`/`mname`/`mstat`/`locked`
     parts, `.pane-h` (the "Decide | Reference" headers), `.score` and
     `.xcount`. All of them were rendered by the classic live page and went with
     it on 2026-10-13 — the Tavern comps screen states the same facts as rows
     and slots, and the pane headers died with the two-pane shell. `.none`
     survives: the Tavern panels use it for an empty row.) */
  .none { color:var(--dim); font-style:italic; }
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
  #freshness.info { display:block; color:var(--tmute); font-weight:400; }
  /* Tabs (2026-10-06): Another Round is the live overlay this page has
     always been; Settle Up is the saved-game browser. A tab is a plain
     toggle — the live poll keeps running either way, and switching never
     clears live state. */
  #tabs { display:flex; gap:4px; margin:2px 0 8px; }
  #tabs .tab { background:var(--tpanel); color:var(--tmute);
               border:1px solid var(--tline); border-radius:var(--radius);
               padding:5px 14px; font:600 13px "Segoe UI", system-ui;
               cursor:pointer; }
  #tabs .tab:hover { color:var(--ttext); }
  #tabs .tab.on { color:var(--ttext); background:var(--tcard);
                  border-color:var(--tsel); }
  /* The sharing control (2026-10-07): a quiet line at the right end of the tab
     row, not a button on a card. It has to be reachable for as long as sharing
     is ON — that is what keeps the answer reviewable and reversible — and the
     card it used to live on is only on screen at a game's start or end, so it
     was invisible for the whole game it was describing. Muted deliberately
     (--tmute, no border until hover): a control that decides whether data leaves
     the machine should be easy to find and hard to hit by accident. */
  #tabs #share-toggle { margin-left:8px; background:none;
                        border:1px solid transparent; color:var(--tmute);
                        font:400 12px "Segoe UI", system-ui;
                        padding:4px 8px; cursor:pointer; opacity:.55; }
  #tabs #share-toggle:hover { opacity:1; color:var(--ttext);
                              border-color:var(--tline); }
  #tabs #share-toggle[hidden] { display:none; }
  /* (The Live viewer flag's row lived here — `#live-viewer-row`, right-aligned
     on this nav row since round-3 item 7, and hidden by `showTab` while Settle
     Up was open because that page had its own. Both flags went on 2026-10-13
     with the choice they offered, and so did the two rules.) */
  /* The live view's own container. It is HIDDEN, not destroyed: the welcome and
     game-over card lives in `#col-decide`, and hiding rather than replacing is
     what keeps the card working across a live frame.
     **It FILLS the window (2026-10-09, fix list round 1).** `#app` is a grid
     above 1200x900 and a flex COLUMN at or below it, and the container was a
     grid rule with `flex:1 1 100%` as its size in the flex case — where
     `flex-basis` is a height, so it did not stretch across. Measured before the
     fix: 815px of a 1384px window. `width:100%` is what holds in both branches,
     and since 2026-10-13 the base `#app` rule is one column, so the
     `grid-template-columns` override has nothing left to override. */
  #app.tavern-on #live-tavern { width:100%; min-width:0; }
  #app.tavern-on > #col-decide { display:none; }
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
  .s-head select { background:var(--tcard); color:var(--ttext);
                   border:1px solid var(--tline); border-radius:var(--radius);
                   padding:6px 8px; font:14px "Segoe UI", system-ui;
                   min-width:360px; }
  .s-head button { background:var(--tpanel); color:var(--tmute);
                   border:1px solid var(--tline); border-radius:var(--radius);
                   padding:6px 12px; font:600 12px "Segoe UI", system-ui;
                   cursor:pointer; }
  .s-head button:hover { color:var(--ttext); }
  /* The ONE segment control left in the Settle Up header (2026-10-09): Summary
      | Step through, next to the game dropdown. It was one of two — the other
      was `Classic | Tavern`, which picked the reviewer and went on 2026-10-13
      with the choice.
     **The `.vseg` class is what styles the active button, and nothing carried
     it until 2026-10-09**: the JS set `class="on"` on a span with no class, so
     the shipped control gave NO visible sign of which half was active. */
     It is themed here for the control's home in `.s-head`, whose own button
     rule agrees with this. **The palette REACHES the header now** (2026-10-15):
     the chrome elements that sit outside both views — `#freshness`, `#tabs`,
     `.s-head` — carry `.tavern` themselves, so the top of the page wears the
     same brown as the views under it. They did not before: this rule was written
     when `.tavern` could not reach the nav, and a tavern override for the nav row
     had been deleted with the live viewer flag, which left the top of the page on
     the old cool shell tokens while everything below it was brown. Scoped to the
     chrome rather than to `#wrap`: the containers were `width:auto` without the
     palette's `--tcardw`/`--tstepw` and taking the whole page's tokens made it
     scroll, which the layout tests caught (1356px box -> 1332). */
  /* The segment control itself (2026-10-09, fix list round 1 item 9 / round 2
     item 8: "theme the Classic | Tavern toggle"). `.vseg` only ever described
     the ACTIVE state and the radii — the buttons themselves were whatever the
     browser draws, which is why the toggle read as a white pill with grey text.
     It is themed here for the control's home in `.s-head`, whose own button
     rule agrees with this. */
  .vseg { display:inline-flex; gap:0; }
  .vseg button { background:var(--tpanel); color:var(--tmute);
                 border:1px solid var(--tline); padding:6px 12px;
                 font:600 12px "Segoe UI", system-ui; cursor:pointer; }
  .vseg button:hover { color:var(--ttext); }
  .vseg button { border-radius:0; }
  .vseg button:first-child { border-radius:var(--radius) 0 0 var(--radius); }
  .vseg button:last-child { border-radius:0 var(--radius) var(--radius) 0;
                            border-left:none; }
  .vseg button.on { color:var(--ttext); background:var(--tcard);
                    border-color:var(--tsel); }
  .vseg button:disabled { opacity:.45; cursor:default; color:var(--dim); }
  /* An id beats the UA's [hidden] rule, so hiding this has to be said. */
  #settle-mode[hidden] { display:none; }
  /* The Tavern palette (REPLAY_VIEWER_DESIGN.md §6), SCOPED to `.tavern` so
     `meta/`'s own pages and the standalone review keep the shell tokens. Both
     of this page's views carry it now (2026-10-13): the live view and the
     review. Gold is attack only; --tsel is the selection accent. Contrast per
     §7: --thp on --tcard is ~4.5:1 at 15px bold — revisit with real art. */
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
     .tavern, so it reaches both of this page's Tavern views and leaves the shell
     (the nav, the sharing control, the Settle Up header) with the browser's own
     ring. The 44px minimum targets are per control, below. */
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
  /* How many copies one card stands for, on the fallback paths that still group
     by card (a payload recorded before `board_cards`). */
  .tavern .tile .tag-count { position:absolute; top:4px; right:4px; z-index:2;
                             font-size:10px; font-weight:700; padding:2px 5px;
                             border-radius:4px; background:var(--tcard);
                             color:var(--ttext);
                             border:1px solid var(--tline); }
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
  /* THE LAYOUT IS BY WINDOW WIDTH (fix list round 4 item 5, corrected
     2026-10-13 on the maintainer's own call: "if the window is ~1920 wide, then
     three columns. Otherwise collapse it"). Two modes:
       * >=1650px of window: THREE COLUMNS — Tavern + board | Comps |
         Facts + opponent + lobby, and no tabs, because every screen is visible;
       * below that: one column of collapsible sections with a one-line summary
         in each header, and the Facts table pinned above them (the section
         headers and the facts strip are the same rules at 1600px as at 900px).
     WHY 1650 AND NOT 1800 (lowered 2026-10-15, the maintainer's own MacBook):
     on a 16" MacBook Pro a maximised window measures ~1728px of viewport, so the
     1800 this rule asked for NEVER FIRED on the machine it was being read on.
     1650 is the floor rather than a rounder smaller number: `#wrap` caps the PAGE
     at 1600px, and MEASURED 2026-10-13 the tavern box reaches that cap at about
     1640px of window. Below it the box is still growing, so firing earlier would
     hand the columns less than the width they were measured at; at or above it
     they get exactly 622|622|300.
     WHY A WINDOW RULE AND NOT THE BOX's, which is what this rule asked FIRST
     (at 1180px of box, i.e. a ~1250px window): the container's width cannot
     answer "is this a big desktop window". `#wrap` caps the PAGE at 1600px, so
     MEASURED 2026-10-13 at 1920x1080 the tavern box is 1572px — and a 1650px
     window gives it 1572px too, because the cap is reached before the window is.
     Past ~1640px of window the box stops growing, so a container query makes
     "1920" indistinguishable from "1650" and puts the columns on for both.
     1800 was chosen because a maximized window on a 1920x1080 screen measures
     1904px of VIEWPORT (measured in the harness), so a literal 1920 would never
     fire there. It turned out to be too high for a laptop: 1650 fires on a
     maximised 16" MacBook Pro and still does not fire at 1600.
     THE BOX IS STILL MEASURED, which is why 1650 is safe rather than assumed —
     and the measurement corrects the first version's arithmetic, which claimed a
     short window left the box only 1432px: MEASURED 2026-10-13 in the harness,
     the box is 1572px at 1920x1080, at 1850x800, AND at 1700x1080 — every one of
     them is the `#wrap` cap, so the columns are always 622|622|300 wide. The
     accordion's widest box is 1525px at a 1600x1080 window. Since the comps
     panel's two tier columns already fit in the 499px the old single-column
     layout gave them, 622 is generous, not tight. */
  .tavern.live .lv-body { min-width:0; }
  .tavern.live .lv-main { display:grid; grid-template-columns:minmax(0,1fr);
                          gap:14px; align-items:start; }
  /* Both arrangements are in the DOM and exactly one is displayed. The
     displayed one is ALWAYS a grid, so `grid-template-columns` below never
     applies to the hidden one — a hidden element is not laid out at all. */
  .tavern.live .lv-layout-cols { display:none; }
  .tavern.live .lv-layout-acc { display:grid; }
  /* The rail keeps the facts table only while the box is too narrow for three
     columns (fix list round 2 item 9's 340px rail). It used to drop out at
     900px, which left a 1000px window with a rail that could have fitted. */
  @media (min-width: 1200px) {
    .tavern.live .lv-main { grid-template-columns:minmax(0,1fr) 340px; }
  }
  @media (min-width: 1650px) {
    /* TWO COLUMNS, AND COMPS TAKES THE ROOM THE REFERENCE COLUMN USED TO HOLD
       (2026-10-16, the maintainer's call: "the COMPS section should take up as
       much space as the Comps and Facts do together"). It was 1fr 1fr 300px —
       622/622/300 in a 1572px box — and the screenshot that prompted this shows
       the third column nearly EMPTY at the start of a game: Facts is eight short
       rows, "Next opponent" says no board seen, "Lobby" says no seats sighted.
       Meanwhile Comps is a list of twenty-odd rows in a 520px column with dead
       space beside it.

       So the reference panels move under the board (column one) and the comps
       list gets column two, which is now `1.5fr` against column one's `1fr`:
       MEASURED, that is 623px + 14px gap + 935px, and 935 is what 622 + 300 + the
       gap came to — the request, exactly. The 1fr/1.5fr ratio is what holds that
       split at every width instead of only at 1572px.

       Facts under the board rather than somewhere new: they are reference for the
       board the player is looking at, which is what the old rail argued for at
       941x156 in a 971px column (fix list round 4 item 4). */
    .tavern.live .lv-layout-cols { display:grid;
      grid-template-columns:minmax(0,1fr) minmax(0,1.5fr); }
    .tavern.live .lv-layout-acc { display:none; }
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
                             text-transform:uppercase; color:var(--tmute);
                             display:flex; align-items:baseline; flex-wrap:wrap; }
  /* ---------------------------------------------------------------------
     THE ACCORDION, EVERY WINDOW UNDER 1650px (fix list round 4 item 5,
     2026-10-13). Every section is on the page at once, each header carries a
     ONE-LINE summary of what is under it, and the Facts table is a strip pinned
     above them.

     WHY THE SUMMARY IS IN THE HEADER AND NOT A SECOND ELEMENT: the header is
     the click target and the only thing visible while a section is shut, so a
     line under it would either be hidden with the body or sit outside the
     control. The `<h3>` holds the title TEXT NODE first and the line in a
     `<span class="lv-sum">`, which is what keeps `.lv-pn > h3` reading exactly
     the panel names it always read — several tests pin those verbatim.

     A `<details>`/`<summary>` pair would have given the toggle for free, but
     then the SAME panel would be a details in one mode and a div in the other,
     and the open state would be the browser's rather than the page's — which is
     the one thing item 5 cannot delegate: the shop is re-read every 5 seconds
     and re-renders the whole view, so the state has to be read back from
     storage on every render (see `lvCollapsed`). */
  .tavern.live .lv-pn.shut > *:not(h3) { display:none; }
  .tavern.live .lv-pn.shut > h3 { margin-bottom:0; }
  .tavern.live .lv-acc > h3 { cursor:pointer; display:flex; align-items:baseline;
                              gap:10px; flex-wrap:wrap;
                              padding:12px 0; min-height:44px; }
  .tavern.live .lv-acc > h3::before { content:'▸'; font-size:11px;
                                      color:var(--tmute); }
  .tavern.live .lv-acc:not(.shut) > h3::before { content:'▾'; }
  .tavern.live .lv-acc > h3:hover { color:var(--ttext); }
  .tavern.live .lv-acc > h3:focus-visible { outline:2px solid var(--tsel);
                                            outline-offset:2px; }
  /* The one-line summary is a FACT, and the typography says so: the title keeps
     the uppercase muted label treatment, the line is sentence case in --ttext. */
  .tavern.live .lv-sum { text-transform:none; letter-spacing:0; font-size:11px;
                         color:var(--ttext); font-weight:400; }
  /* THE PINNED FACTS STRIP. Sticky, not fixed: the page scrolls as a whole
     (there is no scrolling pane on this view), so a fixed strip would sit over
     whatever scrolled under it while a sticky one stops at the top of the
     scroller and stays there. Measured at 1100x900: the strip's top stays 84px
     while the tavern panel above it moves 0 -> -300px (see
     `TestTheAccordionLayout`). `top:0` and an opaque background, because a
     transparent sticky strip is text with rows sliding through it. */
  .tavern.live .lv-pin { position:sticky; top:0; z-index:3;
                         background:var(--tpanel); margin-bottom:12px; }
  .tavern.live .lv-pin > h3::before { content:none; }
  @media (max-width: 1799.98px) {
    /* In the accordion the strip is one row of the stack, so it takes the full
       width of the column it sits in — a 300px reference table beside 800px of
       sections would read as a column that lost its column. */
    .tavern.live .lv-pin { width:100%; }
    .tavern.live .lv-pin .lv-kv { display:inline-flex; width:100%; }
  }
  /* The one place the not-confirmed-yet state is said (round 3 item 4). */
  .tavern.live .lv-hnote { text-transform:none; letter-spacing:0;
                           font-size:11px; color:var(--tmute); }
  /* A CONTROL ON THE HEADING LINE (2026-10-16): the comps sort chips. The
     heading's own type is uppercase and letter-spaced, so the control opts out of
     both, and `margin-left:auto` puts it at the far end of the line — after the
     summary — where it reads as belonging to the LIST rather than to the panel's
     name. The extra specificity over `.lv-ctl` is deliberate: that rule sets its
     own bottom margin and its own chip padding, and this has to win wherever the
     two happen to sit relative to each other in the file. */
  .tavern.live .lv-pn > h3 .lv-hctl { margin:0 0 0 auto; text-transform:none;
                                      letter-spacing:0; }
  .tavern.live .lv-pn > h3 .lv-hctl .lv-lbl { text-transform:none;
                                              letter-spacing:0; font-size:11px; }
  .tavern.live .lv-pn > h3 .lv-hctl .lv-chip { padding:2px 9px; font-size:11px; }
  .tavern.live .lv-row { display:flex; flex-wrap:wrap; gap:12px; }
  .tavern.live .lv-card { display:flex; flex-direction:column;
                          align-items:center; }
  /* COMPACT OFFER ROWS (2026-10-16, the maintainer's call: "people don't need to
     see what's in the tavern ... they can just look at the screen ... we can
     definitely de-emphasize it quite a lot"). The tavern was a row of full card
     tiles — the largest block of pixels on the page, restating cards the player
     is already looking at, with the facts this page actually ADDS (price, pool
     left) in 11px type underneath them. Now: a 34px thumbnail for recognition,
     the name, then those facts, one offer per cell.

     A GRID, not a stack, and that is the part worth measuring. MEASURED: five
     offers as full tiles occupy one line of ~205px in the wide column (five 114px
     tiles fit 622px), so a one-per-line stack would have been ~275px — TALLER
     than what it replaced, while claiming to save space. `auto-fill` gives the
     wide column two cells and the full-width accordion three, so five offers are
     3 rows (~165px) and 2 rows (~110px) respectively. What the tavern costs in
     pixels goes DOWN in both arrangements, which a stack would not have done.

     SAME DOM, only direction and size: `.lv-card` > `.tile` + `.lv-cap` is what
     `lvCard` built before, so every reader of those classes (this suite's driver
     included) still finds them and the change stays reversible. The game's own
     offer order is untouched — read row-major, offer three is still the third
     card on screen. */
  .tavern.live .lv-shoprow { display:grid; row-gap:0; column-gap:18px;
                             grid-template-columns:repeat(auto-fill,
                                                        minmax(240px, 1fr)); }
  .tavern.live .lv-shoprow .lv-card { flex-direction:row; align-items:center;
                                      gap:9px; width:100%; padding:4px 0;
                                      border-bottom:1px solid var(--tline); }
  .tavern.live .lv-shoprow .lv-card:last-child { border-bottom:none; }
  .tavern.live .lv-shoprow .tile { width:auto; flex-direction:row;
                                   align-items:center; gap:9px; }
  .tavern.live .lv-shoprow .tile .thumb { width:34px; height:46px;
                                          aspect-ratio:auto; flex:none; }
  .tavern.live .lv-shoprow .tile .thumb.ph { aspect-ratio:auto; }
  /* The name is the thing most worth width here, so it stops being a fixed
     104px column and takes what it needs. */
  .tavern.live .lv-shoprow .tile .tname { width:auto; }
  /* The facts are the point of the panel, so they stop being 11px --tmute under
     a picture and become 12px in the row's own text colour. */
  .tavern.live .lv-shoprow .lv-cap { width:auto; margin-top:0; font-size:12px;
                                     color:var(--ttext); }
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
  /* THE ONE PLACE A COMP ROW IS DIMMED: the out-of-play block (item B.1), which
     says in words why its rows are there and groups them by tribe (§8). It is
     the BLOCK that dims them rather than a per-row `unavail` class the renderer
     had to derive from `tribe_available`: a row is in this block because its
     tribe is out of play, which is the same statement, and a payload without
     the mark (an older record) still gets a dimmed block. */
  .tavern.live .lv-oop .lv-crow { opacity:.55; }
  .tavern.live .lv-lbl { color:var(--tmute); font-size:12px; margin:0 0 6px; }
  /* The read's age, ON the panel (fix list round 4 item 3(b)): the same
     --tmute as the other secondary lines, one line under the heading. */
  .tavern.live .lv-read { color:var(--tmute); font-size:11px;
                          margin:-4px 0 8px; }
  /* Tavern mix / their mix (fix list round 4 items 3(b) and 4): the label and
     its counts on one wrapping line, chips like the tribe row's but inert —
     nothing here is tappable, so they carry no cursor. */
  .tavern.live .lv-mix { display:flex; flex-wrap:wrap; gap:6px;
                         align-items:center; margin:10px 0 0; }
  .tavern.live .lv-mix .lv-lbl { margin:0 4px 0 0; }
  .tavern.live .lv-mixchip { padding:3px 9px; border-radius:12px;
                             background:var(--tcard); border:1px solid var(--tline);
                             font-size:11px; color:var(--ttext); }
  /* The rolled-past row (fix list round 4 item 3(c)): the shop's own row
     treatment, under its own label, separated from the offers above it by a
     rule so a card that is GONE cannot be read as one still on offer. */
  .tavern.live .lv-passed { margin:12px 0 0; padding-top:10px;
                            border-top:1px solid var(--tline); }
  .tavern.live .lv-passed .lv-lbl { margin:0 0 8px; }
  .tavern.live .lv-note { color:var(--tmute); font-size:11px; margin:8px 0 0; }
  .tavern.live .lv-empty { color:var(--tmute); font-size:12px; padding:4px 0; }
  /* The tab row's own rules went with the tab row (fix list round 4 item 5):
     `.lv-tabs` has no element to style at any width now, and a live rule for a
     class nothing carries is how a removed control comes back by accident. */
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
  /* MARKED AVAILABLE (fix list round 4 item 1): the row used to mark only the
     BANNED tribes (amber, manual mode) and read as "these five are in", which
     is the opposite of what it meant. Availability is the positive mark now,
     and it comes from the payload's own `tribes_available` — one owner for the
     rule, computed where the bans land. */
  .tavern.live .lv-chip.avail { border:1px solid var(--tbuff);
                                color:var(--ttext); }
  /* Out of play is NOT a ban the player could undo (§4.2): struck through, and
     not clickable, so it can never read as one of the five. */
  .tavern.live .lv-chip.out { border-color:var(--tloss); color:var(--tmute);
                              text-decoration:line-through; cursor:default; }
  .tavern.live .lv-chip.picked { border-color:var(--tsel); }
  /* The design's §6.1 four dashed skeleton cards went with fix list round 2 item
     2 (the player's call: they read as thick dash bars carrying nothing). The
     sentence beside them says the same thing, and the class is gone entirely so
     no rule can quietly bring the bars back. */
  /* §4.3's pick screen, RE-CUT 2026-10-14 into compact HORIZONTAL cards. The
     controls row, then the source line, then the options: art on the left,
     content on the right. This screen has to fit a ~900px-tall window without
     scrolling, so every number below is a budget rather than a taste. */
  .tavern.live .lv-pickctl { display:flex; flex-wrap:nowrap; gap:12px;
                             align-items:center; margin:0 0 8px;
                             overflow-x:auto; }
  /* The chips do NOT shrink (round 4 item 5, measured 2026-10-13): the row is
     `nowrap`, and once the comps column narrowed the pick panel to 469px the
     chips were squeezed instead — 79px of row, which is the row plus a
     horizontal scrollbar, i.e. the page answering "too narrow" by wrapping one
     chip's text onto a second line. `flex:none` keeps each chip its own width and
     lets the row scroll sideways, which is what `overflow-x:auto` is for. */
  .tavern.live .lv-pickctl .lv-chip,
  .tavern.live .lv-pickctl .lv-lbl { flex:none; }
  .tavern.live .lv-chip.on { border-color:var(--tsel); color:var(--ttext); }
  .tavern.live .lv-chip.off { opacity:.45; cursor:default; }
  /* THE OPTION GRID, by WINDOW width: one row of four above 1500, two by two
     from 700 to 1500, one column under 700. Fixed tracks rather than
     `auto-fit`: a Lesser Trinket often offers TWO options, and auto-fit would
     fit seven 200px tracks across a 1500px strip and draw both cards thin, in
     the corner of it. Four tracks is the wide mock's own shape and it does not
     change with the offer count.
     The ROW gap is 8px rather than 10: MEASURED 2026-10-14 at 1100x700 (a 549px
     viewport), the pick panel ends at 541px with the 2x2 grid — the design's
     "fits a ~900px-tall window without scrolling" is about the tab-and-status
     chrome above the panel as much as about the cards. */
  .tavern.live .lv-pickgrid { display:grid; gap:8px 14px;
                              grid-template-columns:1fr; }
  @media (min-width: 700px) {
    .tavern.live .lv-pickgrid {
      grid-template-columns:repeat(2, minmax(0, 1fr)); }
  }
  @media (min-width: 1500px) {
    .tavern.live .lv-pickgrid {
      grid-template-columns:repeat(4, minmax(200px, 1fr)); }
  }
  /* The source line: ONE line, ellipsised, with the whole sentence on the
     hover — and a 12px gap before the cards it is the source FOR. */
  .tavern.live .lv-source { white-space:nowrap; overflow:hidden;
                            text-overflow:ellipsis; margin:0 0 12px; }
  /* THE OPTION CARD: art left, content right, and a floor under its height so a
     card carrying less data does not make its row shorter — the grid jumping
     under the player's cursor as the payload is re-read is what that floor is
     for.
     THE FLOOR IS THE DESIGN'S 144px, AND IT GIVES ON A SHORT WINDOW: the art's
     own clamp(64px, 14vh, 128px) exists so four options keep fitting a ~900px
     window, and a flat 144px floor under a 77px art undoes exactly that —
     MEASURED 2026-10-14 at 1100x700 (a 549px viewport): a 2x2 grid of 144px
     cards put the pick panel's bottom at 580px, i.e. 31px past the fold, which
     is the one thing the redesign is for. 48px is the card's own padding plus
     the two lines the content needs beside the art. */
  .tavern.live .lv-optcard { display:flex; gap:12px; align-items:flex-start;
                             min-height:min(144px, calc(clamp(64px, 14vh, 128px) + 48px));
                             padding:10px 12px;
                             box-sizing:border-box; background:var(--tcard);
                             border:1px solid var(--tline); border-radius:10px; }
  /* The art is 72x96 at the nominal window (3/4), and the HEIGHT is what gives
     on a short one — clamp(64px, 14vh, 128px) — with the width following from
     the ratio so the art can never squash. Under 700px the card is alone in
     its column and the design's own 56x76 applies. */
  .tavern.live .lv-pickart { flex:none; height:clamp(64px, 14vh, 128px);
                             aspect-ratio:3/4; border-radius:7px;
                             overflow:hidden; background:var(--tcard); }
  .tavern.live .lv-pickart .thumb { display:block; width:100%; height:100%;
                                    object-fit:cover; border-radius:0; }
  .tavern.live .lv-pickart .thumb.ph { display:flex; align-items:center;
                                       justify-content:center; font-size:20px;
                                       color:var(--tmute); }
  @media (max-width: 699.98px) {
    .tavern.live .lv-pickart { height:76px; }
  }
  .tavern.live .lv-optbody { flex:1 1 auto; min-width:0;
                             display:flex; flex-direction:column; gap:3px; }
  /* Bold 15px, at most two lines: a hero name is one or two words, and a third
     line would push the numbers past the card's budget. */
  .tavern.live .lv-pname { font-weight:700; font-size:15px; line-height:1.2;
                           display:-webkit-box; -webkit-line-clamp:2;
                           -webkit-box-orient:vertical; overflow:hidden; }
  /* The ONE muted line: the hero power, or a discover's tier and tribe. One
     line, with the whole text on the hover. */
  .tavern.live .lv-psub { font-size:11px; color:var(--tmute);
                          white-space:nowrap; overflow:hidden;
                          text-overflow:ellipsis; }
  /* ONE line: the figure, what it is, and the distance from the offered
     average. `nowrap` because the design says one line, and ellipsised rather
     than wrapped because a wrapped "+3.4 vs offered avg" reads as a second
     stat under the first. */
  .tavern.live .lv-phead { display:flex; align-items:baseline; gap:6px;
                           margin:2px 0 1px; white-space:nowrap;
                           overflow:hidden; text-overflow:ellipsis; }
  .tavern.live .lv-phead b { font:700 18px "Segoe UI", system-ui; }
  .tavern.live .lv-phead small { font-size:10px; letter-spacing:.1em;
                                 text-transform:uppercase; color:var(--tmute); }
  .tavern.live .lv-phead .lv-vs { font-size:11px; }
  /* 13px rows with 5px of padding — two of them beside the headline are what
     fits next to the art. */
  .tavern.live .lv-optbody .lv-kv { font-size:13px; padding:5px 0; }
  .tavern.live .lv-pmore, .tavern.live .lv-pnodata { margin:0; }
  .tavern.live .lv-pnodata { color:var(--tmute); font-size:12px; }
  /* §4.4's Compare block is the only reader of `.lv-opts`/`.lv-opt` now: the
     pick screen draws `.lv-optcard` instead (2026-10-14), which is what lets
     the two screens have different shapes without one restyling the other. */
  .tavern.live .lv-opts { display:grid; gap:16px; justify-content:center;
                          grid-template-columns:repeat(auto-fit,
                                                 minmax(200px, 340px)); }
  @media (max-width: 699.98px) {
    .tavern.live .lv-opts { grid-template-columns:1fr; }
  }
  .tavern.live .lv-opt { display:flex; flex-direction:column;
                         align-items:center; gap:12px; }
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
     a dashed divider between 4 and 5, labels below. The COMP detail screen is
     the only reader since 2026-10-14 — a compact pick card has no room for
     eight bars, and the design's own card list does not ask for them. */
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
  /* ONE TIER COLUMN, FULL WIDTH (2026-10-16, the maintainer's call after the
     widened panel: "let's make each entry bigger. One per line"). It ran one
     group per 440px column for a few hours, which was the right answer while the
     panel was 622px and the width had to be bought from the row — but the panel
     is 935px now, and two 440px columns spent that width on narrow rows instead
     of on bigger ones.
     The floor and the half-width cap both go with it. They existed to stop two
     groups OVERLAPPING when a flat floor was wider than the column it sat in
     (measured in the real browser at 1400x900, 499px of panel) — a risk that
     cannot arise for a full-width group: `max-width:100%` is the box, and flex
     wraps something that does not fit.
     The tier headers still stick to the top of the page as it scrolls (round 3
     item 3). */
  .tavern.live .lv-cols { display:flex; flex-wrap:wrap; gap:18px;
                          align-items:flex-start; }
  .tavern.live .lv-ctier { flex:1 1 100%; min-width:0; max-width:100%;
                           min-height:0; }
  /* A lone tier takes the whole width rather than half of it. */
  .tavern.live .lv-ctier:only-child { max-width:100%; }
  .tavern.live .lv-ctier > h4 { position:sticky; top:0; z-index:2;
                                background:var(--tpanel);
                                margin:0 0 6px; padding:4px 0;
                                font-size:11px;
                                letter-spacing:.12em; text-transform:uppercase;
                                color:var(--tmute); }
  /* A comp row is a GRID with fixed columns (fix list round 1 item 6:
     "consistent rows"; round 3 item 2 added the tracks, round 4 item 6 fixed
     their contents; item B.2 moved the tribe into the name cell): checkbox 22 |
     name+tribe | owned 64 | marks | core slots [| avg 64]. The avg track EXISTS
     only when the WHOLE list has corpus data (round 3 item 5 for the "column of
     dashes" half, round 4 item 6 for the list-wide half, and the out-of-play
     block shares the decision so both lists line up) — so it is a property of
     `lv-cols`, not of one tier group. The compare checkbox is IN FLOW in its own
     cell: nothing is positioned over anything. */
  .tavern.live .lv-crow { display:grid;
                          grid-template-columns:22px minmax(0,1fr) auto auto;
                          gap:12px; align-items:center; padding:10px 0;
                          border-bottom:1px solid var(--tline); font-size:13px; }
  /* SIX TRACKS WITH THE AVG COLUMN, FIVE WITHOUT (fix list round 4 item 6):
     checkbox | name+tribe | marks | strip | owned [| avg]. The avg track is
     decided for the WHOLE list (`lv-cols.has-avg`), so every row in every tier
     group has the same columns. */
  .tavern.live .lv-ctier.has-avg .lv-crow {
    grid-template-columns:22px minmax(0,1fr) auto auto 64px; }
  /* THE OUT-OF-PLAY BLOCK'S ROWS have no Compare box, so the first track is the
     name. Everything else is the same, which is what "the same on every row"
     means — one row shape, one variant of it. */
  .tavern.live .lv-oop .lv-crow {
    grid-template-columns:minmax(0,1fr) auto auto; }
  .tavern.live .lv-oop.has-avg .lv-crow {
    grid-template-columns:minmax(0,1fr) auto auto 64px; }
  @media (max-width: 699.98px) {
    .tavern.live .lv-crow,
    .tavern.live .lv-ctier.has-avg .lv-crow {
      grid-template-columns:22px minmax(0,1fr) auto; }
    .tavern.live .lv-oop .lv-crow,
    .tavern.live .lv-oop.has-avg .lv-crow {
      grid-template-columns:minmax(0,1fr) auto; }
  }
  .tavern.live .lv-meta { display:flex; flex-wrap:wrap; gap:6px;
                          align-items:center; }
  .tavern.live .lv-meta .lv-tier { margin-left:0; }
  /* [name / tribe]: the tribe is on the line UNDER the name (item B.2) — in
     --ttext like every other word on the row, because green is the OWNED
     colour here and nothing else. The whole cell carries the full name as its
     title, so a name that clamps to two lines is still readable. */
  .tavern.live .lv-cname { min-width:0; display:flex; flex-direction:column;
                           align-items:flex-start; gap:1px; }
  .tavern.live .lv-cname .lv-copen { min-width:0; }
  .tavern.live .lv-crowtribe { color:var(--ttext); font-size:12px;
                               line-height:1.25; }
  /* The tribe and the owned count share one line (2026-10-16). Its own wrapper
     rather than nesting the count in `.lv-crowtribe`, so the tribe's own text
     stays the tribe. */
  .tavern.live .lv-crowtribeline { display:flex; align-items:baseline;
                                   min-width:0; }
  .tavern.live .lv-crowtribe .lv-uncf { color:var(--tmute);
                                        font-style:normal; }
  /* Two lines at most, then it ellipses (round 3 item 2) — a comp name is two
     words and a hyphen, and a third line pushed the slots out of line. */
  .tavern.live .lv-copen { cursor:pointer; text-decoration:none;
                           display:-webkit-box; -webkit-line-clamp:2;
                           -webkit-box-orient:vertical; overflow:hidden; }
  /* Underlined on HOVER only (round 3 item 6): every name in the list wearing a
     link underline made the column read as a wall of links. */
  .tavern.live .lv-copen:hover { text-decoration:underline; }
  .tavern.live .lv-crow.low .lv-cname, .tavern.live .lv-crow.low .lv-slots,
  .tavern.live .lv-crow.low .lv-owned, .tavern.live .lv-crow.low .lv-ap {
    opacity:.55; }
  .tavern.live .lv-owned { color:var(--ttext); font-weight:600;
                           white-space:nowrap; }
  .tavern.live .lv-ap { font-weight:600; }
  .tavern.live .lv-chip.lowsamp { cursor:default; color:var(--tmute);
                                  font-size:11px; padding:2px 8px; }
  /* THE OUT-OF-PLAY BLOCK (item B.1). A `<details>`: collapsed by default, the
     count on its summary so a shut block still says how much is behind it, and
     grouped by tribe inside. */
  .tavern.live .lv-oop { margin:14px 0 0; border-top:1px solid var(--tline);
                         padding-top:6px; }
  .tavern.live .lv-oopsum { cursor:pointer; color:var(--tmute); font-size:12px;
                            padding:4px 0; }
  .tavern.live .lv-oopgroup { color:var(--tmute); font-size:11px;
                              letter-spacing:.12em; text-transform:uppercase;
                              padding:8px 0 2px; }
  /* The core-card strip is a single NOWRAP row of 40x54 slots (round 3 item 2
     for the nowrap, item B.2 for the size): wrapping turned a six-card core
     into a ragged two-line block that pushed the owned count out of line. The
     slots SHRINK (round 3 pinned `flex:none`, and that is REVERSED here on
     measurement): six 40px slots are 255px, and with the avg track the fixed
     part of a row is 481px against the 471px a 499px comps panel has inside
     its padding — a `flex:none` strip pushes the row out of its own box. A
     slot gives up width before the row does, and `object-fit:cover` crops the
     art rather than squashing it. */
  .tavern.live .lv-slots { display:flex; flex-wrap:nowrap; gap:2px;
                           min-width:0; }
  .tavern.live .lv-slot { display:inline-block; width:46px; height:62px;
                          flex:0 1 auto; min-width:32px; border-radius:6px;
                          background:var(--tcard);
                          border:2px solid var(--tbuff); box-sizing:border-box;
                          overflow:hidden; position:relative; }
  /* The core card's own art, size of the slot. Missing/banned are DIMMED rather
     than hidden — the comp still says which cards it wants — at 75% (item B.2:
     the old 35% read as an empty box rather than as a card you do not own),
     with the greyscale carrying the state the opacity alone would not. */
  .tavern.live .lv-slot .thumb { display:block; width:100%; height:100%;
                                 object-fit:cover; border-radius:0; }
  .tavern.live .lv-slot.miss { border:1px dashed var(--tline); }
  .tavern.live .lv-slot.miss .thumb, .tavern.live .lv-slot.banned .thumb {
    opacity:.75; filter:grayscale(1); }
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
  /* A themed checkbox, not the browser's (round 3 item 6): the default control
     is a light-grey square that looks pasted onto the tavern palette. */
  .tavern.live .lv-cmpbox { appearance:none; width:18px; height:18px; margin:0;
                            border:1px solid var(--tline); border-radius:4px;
                            background:var(--tcard); cursor:pointer;
                            display:inline-grid; place-content:center;
                            flex:none; }
  .tavern.live .lv-cmpbox:hover { border-color:var(--tsel); }
  .tavern.live .lv-cmpbox:checked { background:var(--tsel);
                                    border-color:var(--tsel); }
  .tavern.live .lv-cmpbox:checked::after { content:'✓'; font-size:12px;
                                           font-weight:700;
                                           color:var(--tonsel); }
  .tavern.live .lv-cmpbox:disabled { opacity:.45; cursor:default; }
  /* (`.lv-cmplbl` — the visible "compare" word beside the box — went with item
     B.2, 2026-10-14: it collided with the comp name, and the box's tooltip and
     `aria-label` say what it is.) */
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
  .turn .comp { margin-left:auto; color:var(--gold); font-size:12px; }
  .brow { display:grid; grid-template-columns:86px 1fr; gap:10px;
          padding:2px 0; font-size:13px; }
  .brow .blbl { color:var(--dim); text-transform:uppercase; font-size:11px;
                padding-top:2px; }
  .brow-tiles { display:flex; flex-wrap:wrap; gap:6px; }
  .turn .note, .turn .q { font-size:12px; padding-top:4px; }
  .turn .note { color:var(--dim); }
  .turn .q { color:var(--warn); }
  /* (THE CLASSIC REVIEW'S PHASE ROWS lived here — `.turn .phase` with its
     `pacted` "You: bought…" line, its `pout` outcome, its folded `details.coach`
     ("coaching — taken") and the `v`/`v-taken`/`v-ignored`/`v-none`/`v-ungraded`
     /`v-pass` verdict vocabulary, plus the `s-sticky` turn header, the `tmeta`
     numbers, the `grw` growth span and the opponent row's `them` colour. The
     classic reviewer and `phaseRow` went on 2026-10-13; the verdict vocabulary
     is not lost — `settle_up._verdict` still produces it, the standalone
     `/review` page prints it, and the rail's Plan summary carries it here.) */
</style>
</head>
<body>
<div id="wrap">
<!-- NO STATE STRIP (2026-10-13). `#statebar` was the classic live page's stat
     tile row, and the Tavern view has its own status bar (`lvStatus`, inside
     `#live-tavern`). With one renderer left, nothing filled the strip, which
     left a rounded empty bar above the card — the thing fix list round 2 item 7
     hid it for. The element, its nine CSS rules and every line that touched it
     are gone rather than left hiding on every render: a live rule for something
     nothing writes to is how a removed control comes back. -->
<div id="freshness" class="tavern"></div>
<nav id="tabs" class="tavern">
<button class="tab on" data-tab="live">Another Round</button>
<button class="tab" data-tab="settle">Settle Up</button>
<button id="share-toggle" hidden></button>
<!-- NO VIEWER FLAG (2026-10-13). This row carried the Live page's
     `Classic | Tavern` toggle (round-3 fix list item 7) and the Settle Up
     header carried its own. Tavern is the ONLY style now, so both controls,
     both localStorage keys (`bl-live-viewer`, `bl-settle-viewer`) and the
     branch each one drove are gone — a stale value in a player's browser is
     read by nothing, which is what makes its absence harmless. -->
</nav>
<div id="app">
<!-- The welcome and game-over card's slot. It kept the id of the classic page's
     DECIDE pane because the card has always lived here and the id is what the
     suite and the dev replay driver read; the REFERENCE pane that was its
     sibling is gone with the classic page, and so is the second grid track (see
     the `#app` rule). -->
<section id="col-decide"></section>
<!-- The live view's own container, kept separate from the card slot on purpose:
     `renderLiveTavern` clears ITS container, so the card is never destroyed by
     a frame — it is only hidden while the live view draws. -->
<div id="live-tavern" hidden></div>
</div>
<section id="settle">
<div class="s-head tavern">
<select id="settle-select"><option value="">Loading saved replays…</option></select>
<span id="settle-mode" class="vseg" hidden
      title="How to read this game: Summary is the turn plus its action rail;
Step through replays the turn one action at a time">
<button data-m="summary" class="on">Summary</button>
<button data-m="step">Step through</button>
</span>
<!-- NO REVIEWER FLAG (2026-10-13). This is where the `Classic | Tavern` segment
     for the saved game sat. The review IS the Tavern layout now, so there is
     nothing to choose and no `bl-settle-viewer` key anywhere in the page. -->
<button id="settle-rebuild" title="Re-derive this saved game from its own
source log — upgrades older saves to this viewer's data (replays
the game; the session log must still exist)">Rebuild</button>
<button id="settle-folder" title="Open the folder the saved replays live in">Open folder</button>
</div>
<div id="settle-game"><div class="s-empty">Pick a saved game to see it turn by turn.</div></div>
</section>
<div id="release-tag" hidden></div>
</div>
<script>
//: Changes with the art cache, so a corrected picture gets a new URL (see
//: art_epoch in the server). A week-long art cache is only safe when this is in
//: the URL.
const __ART_V = '__ART_EPOCH__';
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
  // ...and the same age on the Tavern panel itself (fix list round 4 item
  // 3(b)). It rides this ticker rather than render(): the payload does not
  // change while the player is thinking, so a panel-only reading would stay
  // frozen at whatever it said when the panel was built.
  tickReadAge();
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
//: The text box is a FALLBACK for a slow render, not a first frame. Showing it
//: eagerly meant every hover flashed a text box and then swapped it for the card
//: render a moment later — a blink on every cached card, which is most of them.
//: It now appears only if the render has not arrived within this long.
let tipBoxTimer = null;
const TIP_BOX_DELAY = 150;
function hoverCard(elm, cid, name) {
  const meta = cardMeta(cid);
  const id = String(cid || '').replace(/_G$/, '');
  tipCid = id;
  let shown = false;
  let boxShared = null;
  if (tipBoxTimer) { clearTimeout(tipBoxTimer); tipBoxTimer = null; }
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
  // The text box, ready but NOT shown yet (see TIP_BOX_DELAY).
  if (meta.text) {
    boxShared = el('div', 'tipbox');
    boxShared.appendChild(el('div', 'tipname', badgeName(cid, name)));
    boxShared.appendChild(el('div', 'tiptext', meta.text));
    tipBoxTimer = setTimeout(() => {
      tipBoxTimer = null;
      if (tipCid === id && !shown) show(boxShared);
    }, TIP_BOX_DELAY);
  }
  // The full render upgrades the tooltip when upstream has it; a slow or 404
  // fetch falls back to the text box — or, with no text either, the portrait
  // zoom the tile already carries.
  const big = new Image();
  big.className = 'tiprender';
  big.onload = () => {
    if (tipBoxTimer) { clearTimeout(tipBoxTimer); tipBoxTimer = null; }
    show(big);
  };
  big.onerror = () => {
    if (tipBoxTimer) { clearTimeout(tipBoxTimer); tipBoxTimer = null; }
    if (tipCid !== id || shown) return;
    if (boxShared) show(boxShared);
    else tipCid = null;
  };
  big.src = '/card/' + id + '.png';
}
function leaveCard() {
  tipCid = null;
  tip.hidden = true;
  if (tipBoxTimer) { clearTimeout(tipBoxTimer); tipBoxTimer = null; }
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
  img.src = '/img/' + cid + '.png?v=' + __ART_V;
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
    t.appendChild(el('div', 'tname', badgeName(cid, name)));
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
// (The classic live view's CLICK-TO-EXPAND COMPS PANEL lived here — `compRow`,
// its lazily-built `compBody` behind `_compBodyCache`, the `compTiles` strip and
// the `/guide/<slug>` fetch in `loadGuide`, plus the `_openComps` open-set. The
// comps screen it fed went with the classic renderer on 2026-10-13; the Tavern
// layout's own comps screen (`lvCompsBody`, `lvCompDetail`, `lvLoadGuide`) is
// what renders the list now, and it shares none of this markup.)
// (The step-kind chip map lived here: LV/PICK/BUY/SELL/ROLL/CAST/PLAY/HOLD/
// SWAP/DISC, one per kind in value._STEP_KINDS. It went with the numbered plan
// — the chips labelled instructions, and the live page does not render any
// (2026-10-06, PIVOT.md). value._STEP_KINDS still exists: it is how the plan's
// steps are typed for the review and the corpus.)
// The two end-of-game POSTs, ONE place each (2026-10-09): the shell card and the
// Tavern game-over card both offer them (they are the same two actions on two
// cards), and the 409 branch below is the normal race rather than an error — the review replays the game twice
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
//: Take the live view off screen. It has its own container, so this only clears
//: that container and the class its renderer set; the card slot is left alone,
//: because `render` and `renderWelcome` are the only things that write there and
//: this is called one line before the card is drawn. A view that is no longer
//: drawing must not leave its last frame behind: the first-run card has no live
//: -view design (§6.5 has the game-over card), and it used to draw behind a
//: stale one.
//:
//: It no longer unhides a state strip (2026-10-13): the strip was the classic
//: renderer's, that renderer is gone, and "unhide what nothing fills" is how an
//: empty rounded bar comes back.
function lvClearTavern() {
  const lt = document.getElementById('live-tavern');
  if (lt) { lt.hidden = true; lt.innerHTML = ''; }
  document.getElementById('app').classList.remove('tavern-on');
}
function renderWelcome(a) {
  const decide = document.getElementById('col-decide');
  renderShareToggle(a.share);
  renderRelease(a.release);
  decide.innerHTML = '';
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
// THE live page (2026-10-13). It was built beside the classic renderer and
// chosen by a `Classic | Tavern` toggle; the maintainer removed the choice, so
// this is the only renderer a live payload reaches and the classic one, its CSS
// and its tests are gone. What the payload carries did NOT change with it:
// facts, counts and statistics — never a verdict, a ranking or an imperative
// (§1), and never a guessed number (§6.4). Every row appears only when its data
// exists (§5), and a value that was not read is a dash.
//
// It is scoped to `.tavern.live`, so the Settle Up Tavern rules and these
// cannot leak into each other: the two views share the TOKENS, not the
// components. There is no viewer variable and no persisted choice.
//: §4.1's tab row — `Shop | Comps | Lobby` — is GONE (fix list round 4 item 5,
//: 2026-10-13). It existed because the screens were exclusive; in the
//: three-column layout every one of them is on screen at once and everywhere
//: else they are collapsed sections of one column, so there is nothing left for
//: a tab row to select. The facts table was never one of its tabs, and it still
//: is not: it is the pinned strip in the accordion and column 3 in the
//: three-column layout.

function lvOrdinal(p) {
  const suf = ([11, 12, 13].includes(p % 100)) ? 'th'
    : ({1: 'st', 2: 'nd', 3: 'rd'}[p % 10] || 'th');
  return p + suf;
}
//: Unread is a dash in --mute, never a guess, and never a "?" (§6.4 — a "?"
//: next to a number reads as part of the number). The classic strip's "?" for an
//: unread gold/tier/HP went with the strip on 2026-10-13.
function lvVal(v) { return v == null || v === '' ? '—' : String(v); }

function lvPanel(title, body, withAge, note) {
  const p = el('div', 'lv-pn');
  const h = el('h3', null, title);
  // The panel's own besides-the-name note (`lv-hnote`), e.g. the not-confirmed
  // state the comps list says once (round 3 item 4).
  if (note) h.appendChild(el('span', 'lv-hnote', ' · ' + note));
  // The read's age rides the PANEL (fix list round 4 item 3(b)), under the
  // heading rather than inside it: the heading is the panel's name and several
  // tests read it verbatim.
  p.appendChild(h);
  if (withAge) p.appendChild(lvReadAge());
  p.appendChild(body);
  return p;
}
//: --- The layout's own state (fix list round 4 item 5, 2026-10-13) -----------
//: For each section, ONE record of what the player last chose: `+name` open,
//: `-name` shut, and a name with nothing stored at all. It is persisted in
//: localStorage under the page's own convention (`bl-…`, read in a try/catch —
//: private mode throws on both halves of the pair).
//:
//: A NAME, not an index or a bit: the sections are built in a different order in
//: each mode, and an index would open a different section after a resize.
//:
//: READ BACK ON EVERY RENDER, deliberately un-memoised. The shop is re-read every
//: 5 seconds and re-rendering the whole view is exactly how a section would pop
//: open or shut under the player's hands, so the state has to be re-applied from
//: storage each time — and an in-memory copy is not the same thing. Measured
//: 2026-10-13: with the value cached in a module variable, a toggle that had been
//: written but not yet re-read (or a storage that changed underneath the page)
//: rendered the OLD state, which is the failure this whole mechanism exists to
//: prevent.
function _lvStored() {
  let raw = null;
  try { raw = localStorage.getItem('bl-lv-open'); }
  catch (e) { /* private mode */ }
  // Parsed defensively: only a `+name`/`-name` token is kept, so a garbage or
  // half-written value costs the player their open/closed state and never the
  // page. The store is re-written from this on the next toggle, which is also
  // what keeps an unparseable value from living on forever.
  const out = [];
  String(raw || '').split(',').forEach(tok => {
    const t = tok.trim();
    if (t.length > 1 && (t[0] === '+' || t[0] === '-')) out.push(t);
  });
  return out;
}
//: The mode a section falls back to with nothing stored. The screens the player
//: is reading the game through are open — the shop and the board it buys for,
//: and the pick when the game is asking; the two they consult are shut, because
//: five open sections is a stack five screens tall. COMPS JOINS THE OPEN SET
//: (2026-10-15, the maintainer's call: "I just really want the Comps section to
//: be more visible") — it is the direction rather than a reference table, and it
//: is now the first section, so a shut one would be a header at the top of the
//: page saying nothing.
//:
//: READ BY THE ACCORDION ONLY. `lvSection` returns before it ever consults
//: `lvCollapsed` when its `acc` argument is false, so the three-column
//: arrangement has no open/closed state at all and always renders every
//: section's content — which is the point of that arrangement ("no tabs, because
//: every screen is visible"). Nothing in this map can fold the wide layout.
//:
//: A correction worth keeping: the commit that added Comps here (95532b6) also
//: claimed this default collapsed the wide layout's middle column to a bare
//: header. IT DID NOT AND COULD NOT — there is no collapse path in that
//: arrangement to reach. Measured at 1728x1070, `shut` is empty before and after;
//: only the accordion changed, and only there is this map worth reasoning about.
const LIVE_OPEN_BY_DEFAULT = {Comps: true, Tavern: true, 'Board and hand': true,
                              'Choose one': true};
function lvCollapsed(name) {
  const stored = _lvStored();
  const tok = stored.find(t => t.slice(1) === name);
  return tok ? tok[0] === '-' : !LIVE_OPEN_BY_DEFAULT[name];
}
function lvSetCollapsed(name, shut) {
  const stored = _lvStored().filter(t => t.slice(1) !== name);
  stored.push((shut ? '-' : '+') + name);
  try { localStorage.setItem('bl-lv-open', stored.join(',')); }
  catch (e) { /* private mode */ }
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
  // A count badge for a row that IS one card per element but wants to say how
  // many copies it stands for (the fallback path of a board row).
  if (opts && opts.badge) t.appendChild(el('span', 'tag-count', opts.badge));
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
  // The EMPTY shop says how old the read is too (fix list round 4 item 3):
  // the panel with nothing in it is exactly the one where a player wonders
  // whether the coach is stuck or the shop simply has not opened.
  p.appendChild(lvReadAge());
  p.appendChild(el('p', 'lv-note', 'Reading the shop. This updates when your '
                                   + 'next shop opens.'));
  if (a.status) p.appendChild(el('p', 'lv-inline', a.status));
  return p;
}
//: §4.2's ONE tribe row. Out-of-play tribes are struck through and never read
//: as a ban the player could undo; tapping any chip corrects the set, which is
//: what makes every comp filter downstream exact.
//: AVAILABILITY IS THE MARK (fix list round 4 item 1). A chip says what the
//: game can still offer (`tribes_available`, computed with the bans).
//: ONE MEANING PER COLOUR (2026-10-13): amber (`active`) is "you have set this
//: one", green (`avail`) is "the pool says it is in play", struck (`out`) is
//: "rotated out by a patch", dim is "not in your five". The tapped set is
//: `tribes_available` — the five in the tavern — NOT `banned`: seeding `picked`
//: from `banned` marked the complement amber, so the row read "these five are
//: in" over the five this lobby cannot offer, which is the inverted reading the
//: player reported (measured: every offer in session 2026-10-13_12_01_10 came
//: from the amber chips).
//: A tribe that is out of play appears ONCE — it is in the roster AND in
//: `out_of_pool`, so iterating both printed Naga twice.
function lvTribes(a) {
  const row = el('div', 'lv-tribes');
  row.appendChild(el('span', 'lv-lbl', a.bans_manual
    ? 'Lobby tribes · tap to correct'
    : 'Lobby tribes · ' + (a.tribes_seen || 0) + '/5 confirmed'));
  const oop = new Set(a.out_of_pool || []);
  const avail = new Set(a.tribes_available || []);
  const picked = new Set(a.bans_manual ? (a.tribes_available || []) : []);
  (a.tribe_roster || []).filter(t => !oop.has(t)).forEach(t => {
    const on = picked.has(t);
    // An absent `tribes_available` (an older payload) leaves every chip dim,
    // which is exactly how this row looked before — no invented mark.
    const can = avail.has(t);
    const chip = el('span',
                    'lv-chip ' + (on ? 'active' : (can ? 'avail' : 'dim')), t);
    chip.title = on ? 'In the tavern — tap to clear'
                    : (can ? 'In play — tap to say it is in the tavern'
                           : 'Not in this game — tap if that is wrong');
    chip.onclick = () => {
      if (picked.has(t)) picked.delete(t);
      else picked.add(t);
      postInPlay([...picked]);
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
//: "FRAGILE — … a 14-hit ends it" and its "favored/behind" forecast were
//: verdicts (the strip and that page are gone, 2026-10-13), and the same values
//: are rows here.
//: "Lethal at" is gone (fix list round 1 item 5 / round 2 item 6): it printed
//: effective HP a second time under a second name.
//: The BODY of the facts table (fix list round 4 item 5): `lvSection` wraps it,
//: so there is one `.lv-pn` per section. The heading is the wrapper's.
function lvFacts(a) {
  const p = el('div');
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
let _liveCompMore = new Set();     // tier groups whose rows past the cap show
let _liveCompare = new Set();      // up to three slugs, in the order picked
const LIVE_COMP_ROWS = 6;          // round 3 item 3: "cap ~6 rows per tier"
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
//: payload's `owned` flag is the server's board-only rule (it was the classic
//: panel's, and the flag itself is unchanged), so this count reads both — the
//: design's own wording, and the board is not the only place a comp piece can
//: be.
function lvOwned(cards) {
  return (cards || []).filter(x => x && (x.owned || x.in_hand)).length;
}

//: WHICH LIST DOES THIS COMP BELONG IN? (item B.1, 2026-10-14.) Three buckets,
//: and the design names all three:
//:   * a tribe KNOWN to be out of play — patch-rotated, `out_of_pool` (Naga
//:     since 36.6.1) — goes to the collapsed "Out of play · N" block at the
//:     bottom, dimmed and grouped by tribe;
//:   * a tribe this lobby has CONFIRMED and does not offer is not in this
//:     lobby, and a list headed "N in this lobby" cannot carry it: it is not
//:     listed at all, and the count of what that costs is stated in the note
//:     (silently shortening the list is what round 4 item 1 objected to);
//:   * everything else STAYS, which is the whole point of the middle bucket's
//:     opposite: while the 5/5 set is still streaming in, an unconfirmed tribe
//:     is not a banned one (`live_coach.available_tribes` fails OPEN for
//:     exactly that reason), so every tribe stays until the lobby rules it out.
//: Out of play is asked FIRST: such a comp is also `tribe_available === false`,
//: and the block it belongs in is the one that says WHY.
function lvOutOfPlay(c, oop) {
  return !!c.tribe && (oop || []).some(t => lvTribeHit(c.tribe, t));
}
function lvInLobby(a) {
  const oop = a.out_of_pool || [];
  return (a.comps || []).filter(c => !lvOutOfPlay(c, oop)
                                     && c.tribe_available !== false);
}
function lvOutOfPlayComps(a) {
  const oop = a.out_of_pool || [];
  return (a.comps || []).filter(c => lvOutOfPlay(c, oop));
}
//: Is this row's tribe still UNCONFIRMED? The payload publishes the COUNT of
//: confirmed tribes (`tribes_seen`) and the window flag (`tribes_detecting`),
//: not WHICH ones the pool has confirmed so far, so while the window is open
//: the honest mark is "this tribe is not confirmed yet" on every row that has a
//: tribe — and it is the same statement for all of them, which is why the flag
//: is the window's rather than a per-tribe guess. Mixed (no tribe) is never
//: unconfirmed: there is no tribe to confirm.
function lvCompUnconfirmed(c, a) {
  return !!a.tribes_detecting && !!c.tribe;
}
//: THE LIST IS RECOMPUTED ON EVERY TRIBE CHANGE (item B.1). The ROWS are
//: derived from the payload on every render, so that half is automatic; the two
//: pieces of VIEW state that point INTO the list are not. `_liveCompMore` holds
//: tier groups the player expanded, and `_liveCompare` holds ticked slugs — a
//: slug that has left the main list would keep a Compare column alive for a
//: comp the player can no longer see. Both are re-cut whenever the tribe state
//: changes. `_liveComp` (the open Detail) is deliberately NOT touched here:
//: closing the screen the player is reading under them is worse than a Detail
//: for a comp that just left the list, and the Back link is right there.
let _lvTribeKey = null;
function lvSyncCompsView(a) {
  const key = [a.game_no, a.bans_manual ? 'manual' : 'auto',
               a.tribes_detecting ? 'detecting' : 'ready',
               (a.tribes_available || []).join(','),
               (a.out_of_pool || []).join(',')].join('|');
  if (key === _lvTribeKey) return;
  _lvTribeKey = key;
  _liveCompMore = new Set();
  const keep = new Set(lvInLobby(a).map(c => c.slug));
  [..._liveCompare].forEach(s => { if (!keep.has(s)) _liveCompare.delete(s); });
}
//: A GAME ENDED: every view choice about the last game's list goes with it, so
//: the next game starts from the design's defaults rather than from whatever
//: was expanded, ticked or open when the last one finished.
function lvResetCompsView() {
  _lvTribeKey = null;
  _liveComp = null;
  _liveCompSort = 'tier';
  _liveCompMore = new Set();
  _liveCompare = new Set();
}

//: §4.4 Browse, one row, in the grid round 3 item 2 fixes and the layout item
//: B.1 re-cut (2026-10-14):
//: `[compare] [name / tribe] [core-card slots] [N of M owned] [avg]`.
//: `bare` is the OUT-OF-PLAY variant: the same row without the Compare box —
//: a comp nobody can build this patch has no business in a comparison.
//: `anyAvg` is false when the whole list has no corpus data, and then the last
//: cell is not rendered at all (round 3 item 5): a column of dashes was a
//: column of nothing.
function lvCompRow(a, c, anyAvg, bare) {
  const core = c.core || [];
  const st = c.stats || null;
  const row = el('div', 'lv-crow');
  if (st && st.low_sample) row.classList.add('low');
  const picked = _liveCompare.has(c.slug);
  const full = !picked && _liveCompare.size >= LIVE_COMPARE_MAX;
  if (!bare) {
    // A CHECKBOX, not a chip (fix list round 1 item 6): "compare" is a
    // selection you make about up to three rows, and a checkbox is what that
    // looks like. It is disabled (with the reason in its title) once three are
    // ticked rather than silently doing nothing. It sits IN FLOW at the start
    // of the row — nothing is positioned over the name (round 3 item 2).
    // NO TEXT LABEL (item B.2, 2026-10-14): the word "compare" sat in the row
    // and collided with the name, and a checkbox plus a tooltip is what the
    // design asks for. The accessible name moves to `aria-label`, so the box is
    // still announced as the comp it is for.
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'lv-cmpbox';
    cb.id = 'lv-cmp-' + String(c.slug || 'x').replace(/[^A-Za-z0-9_-]/g, '');
    cb.checked = picked;
    cb.disabled = full;
    cb.title = full
      ? 'Compare holds up to ' + LIVE_COMPARE_MAX + ' comps — untick one to add '
        + 'another.'
      : 'Add this comp to the comparison';
    cb.setAttribute('aria-label', 'Compare ' + (c.name || c.slug));
    cb.onchange = () => {
      if (_liveCompare.has(c.slug)) _liveCompare.delete(c.slug);
      else if (_liveCompare.size < LIVE_COMPARE_MAX) _liveCompare.add(c.slug);
      renderLiveTavern(a);
    };
    const cell = el('span', 'lv-cmpcell');
    cell.appendChild(cb);
    row.appendChild(cell);
  }
  // [name / tribe]: the name clamps to TWO lines and the tribe sits on the line
  // under it, in the row's own text colour. Green is the OWNED colour on this
  // screen and nothing else, so a tribe is never green.
  const name = el('span', 'lv-cname');
  name.title = c.name || c.slug;          // the full name, however it clamps
  const open = el('b', 'lv-copen', c.name || c.slug);
  open.title = 'Open the comp';
  open.onclick = () => { _liveComp = c.slug; renderLiveTavern(a); };
  name.appendChild(open);
  const tribe = el('span', 'lv-crowtribe', lvCompTribe(c));
  // ...and the unconfirmed marker only on a MAIN-LIST row: an out-of-play row
  // sits in a block that says its tribe is KNOWN to be out of play, which is the
  // opposite of "not confirmed yet" (item B.1).
  if (!bare && lvCompUnconfirmed(c, a)) {
    tribe.appendChild(el('i', 'lv-uncf', ' · unconfirmed'));
    tribe.title = 'The lobby has not confirmed its tribes yet (fewer than '
                + 'five are in), so this tribe is not ruled out.';
  }
  // THE COUNT RIDES THE TRIBE LINE, in a wrapper of its own (2026-10-16). It had
  // a 64px track after the name, worth 74px with the gap — and 74px is precisely
  // what a SECOND tier column needs, so the count moved up here and the panel's
  // new width pays for itself. Deliberately NOT inside `.lv-crowtribe`: that
  // element is the tribe's own text, and a reader (or this suite) asking for it
  // should get "Demon" and not "Demon · 0 of 5 owned".
  const tribeLine = el('span', 'lv-crowtribeline');
  tribeLine.appendChild(tribe);
  tribeLine.appendChild(el('i', 'lv-crowsep', ' · '));
  tribeLine.appendChild(el('b', 'lv-owned',
                           lvOwned(core) + ' of ' + core.length + ' owned'));
  name.appendChild(tribeLine);
  row.appendChild(name);
  // The optional marks. The TIER is the tier column's own header, so a row
  // repeats it only under the two opt-in sorts — where what you are reading is
  // a re-ordered column and the header no longer tells you the tier of the row
  // in front of you. The low-sample flag is about THIS row's numbers, so it
  // stays either way.
  const meta = el('span', 'lv-meta');
  if (_liveCompSort !== 'tier') {
    meta.appendChild(el('i', 'lv-tier', c.meta_tier ? c.meta_tier + ' tier'
                            : (c.provisional ? 'provisional'
                                             : 'no published tier')));
  }
  if (st && st.low_sample) {
    meta.appendChild(el('span', 'lv-chip lowsamp', 'low sample'));
  }
  row.appendChild(meta);
  row.appendChild(lvSlots(core));
  if (anyAvg) {
    // A row the corpus has never seen leaves its cell EMPTY rather than
    // printing a dash in a column that exists (item B.2: "no '—' on each row").
    const ap = st && st.avg_place != null ? st.avg_place.toFixed(2) : '';
    row.appendChild(el('b', 'lv-ap', ap));
  }
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

//: §4.4 Browse: the sort control, one column per source tier with a sticky
//: header, about six rows each with a `+ N more`, the collapsed out-of-play
//: block under them, and Compare underneath once two comps are picked.
//:
//: TWO LISTS SINCE 2026-10-14 (item B.1). The main list holds the comps this
//: game can still build — the panel header says how many, "N in this lobby" —
//: and the comps whose tribe is KNOWN to be out of play sit in a collapsed
//: block at the bottom, dimmed and grouped by tribe. A tribe the lobby has
//: confirmed and does not offer is in neither, and the note says how many rows
//: that is (see `lvInLobby`).
//:
//: The tribe FILTER row is gone (round 3 item 4): the page already has one tribe
//: row above the tabs, and a second set of the same chips inside this panel was
//: the duplicate.
//:
//: It returns the panel's BODY, not a panel (fix list round 4 item 5): every
//: section is wrapped by `lvSection` now, and a second `.lv-pn` inside one would
//: be a panel within a panel — two headers for one screen, and a driver read of
//: `.lv-pn > h3` would count the panel twice.
//: The list's ORDER control. "Source tier" is the payload's own order; overlap
//: and average placement are opt-in. It sits on the PANEL HEADING since
//: 2026-10-16: it decides the order of the list under it, so it reads better
//: beside that list's name than in a row of its own — and that row was a full
//: line of chrome before the first comp, in the tallest panel on the page.
//: `lv-ctl` stays on the container deliberately: it is the class every reader
//: (and this suite's driver) already uses to find these chips.
function lvCompsSort(a) {
  const ctl = el('div', 'lv-ctl');
  ctl.appendChild(el('span', 'lv-lbl', 'Sort'));
  [['tier', 'Source tier'], ['overlap', 'Overlap'],
   ['avg_place', 'Avg placement']].forEach(([v, label]) => {
    const chip = el('span', 'lv-chip' + (_liveCompSort === v ? ' on' : ''), label);
    chip.onclick = () => { _liveCompSort = v; renderLiveTavern(a); };
    ctl.appendChild(chip);
  });
  return ctl;
}
function lvCompsBody(a) {
  const p = el('div');
  const all = a.comps || [];
  if (!all.length) {
    p.appendChild(lvEmptyRow('No comps read yet — they appear once the bans '
                             + 'resolve.'));
    return p;
  }
  const inplay = lvInLobby(a);
  const outplay = lvOutOfPlayComps(a);
  // What is in neither list: comps of a tribe this lobby CONFIRMED and does not
  // offer. Stated, never silently shortened — the list is short because the
  // lobby is, and that is a fact about the game worth one clause.
  const dropped = all.length - inplay.length - outplay.length;
  const rows = inplay;
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
  // THE AVG COLUMN IS DECIDED FOR THE WHOLE LIST, not per tier group (fix list
  // round 4 item 6). Per group, one tier could carry the column and another not,
  // so the row's tracks changed as you scrolled — the opposite of "same order on
  // every row". It is hidden unless SOME comp in the list has a corpus average,
  // and then every column carries the track, including the rows the corpus has
  // never seen (which leave their cell EMPTY rather than printing a dash).
  // The out-of-play block shares the decision, so its rows line up with these.
  const hasAvg = all.some(c => (c.stats || {}).avg_place != null);
  if (hasAvg) cols.classList.add('has-avg');
  groups.forEach(g => {
    const sorted = lvCompSortRows(g.rows.slice());
    const col = el('div', 'lv-ctier');
    if (hasAvg) col.classList.add('has-avg');
    col.appendChild(el('h4', null, g.label + ' · ' + sorted.length));
    const show = _liveCompMore.has(g.key) ? sorted : sorted.slice(0, LIVE_COMP_ROWS);
    show.forEach(c => col.appendChild(lvCompRow(a, c, hasAvg)));
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
  // keeps the facts the legend cannot show: where the numbers come from, and
  // what is not in the list at all.
  p.appendChild(lvSlotLegend());
  p.appendChild(el('p', 'lv-note',
    'Slots are the comp\'s core cards, with their art dimmed when you do not '
    + 'own them. Average placement is this project\'s own game corpus — '
    + 'observational, not causal.'
    + (dropped ? ' ' + dropped + ' comp' + (dropped === 1 ? '' : 's')
                 + ' for tribes this lobby does not offer are not listed.' : '')));
  if (outplay.length) p.appendChild(lvOutOfPlayBlock(a, outplay, hasAvg));
  const picked = [..._liveCompare].map(s => inplay.find(c => c.slug === s))
                                 .filter(Boolean);
  if (picked.length >= 2) p.appendChild(lvCompCompare(picked));
  return p;
}

//: THE OUT-OF-PLAY BLOCK (item B.1): the comps whose tribe is KNOWN to be out of
//: play this patch, DIMMED, GROUPED BY TRIBE, and with NO Compare box — a comp
//: nobody can build has no business being compared. A `<details>` because it is
//: collapsed by default and "there is more here, on request" is exactly what the
//: element means, with the count on the summary so a shut block still says how
//: much is behind it. Hidden comps used to be counted in a sentence and not
//: listed at all (round 4 item 1 marked them instead, and this is the third
//: state: a tribe that is not banned but does not exist in this patch).
function lvOutOfPlayBlock(a, comps, anyAvg) {
  const det = document.createElement('details');
  det.className = 'lv-oop' + (anyAvg ? ' has-avg' : '');
  det.appendChild(el('summary', 'lv-oopsum', 'Out of play · ' + comps.length));
  const tribes = [];
  comps.forEach(c => {
    const t = lvCompTribe(c);
    let g = tribes.find(x => x.t === t);
    if (!g) { g = {t: t, rows: []}; tribes.push(g); }
    g.rows.push(c);
  });
  tribes.forEach(g => {
    det.appendChild(el('div', 'lv-oopgroup', g.t));
    const rows = el('div', 'lv-ooprows');
    g.rows.forEach(c => rows.appendChild(lvCompRow(a, c, anyAvg, true)));
    det.appendChild(rows);
  });
  return det;
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
//: classic panel's `loadGuide` node (that helper, its `/guide/<slug>` fetch and
//: its cache went with the classic renderer on 2026-10-13): a node cached across
//: the whole page would carry the wrong palette into this panel, which is the
//: same reason the live view and the review keep their own tiles.
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
//: collapsed by default. The BODY only (fix list round 4 item 5): `lvSection`
//: wraps it, so there is one `.lv-pn` per section and one header per screen.
function lvCompDetail(a, c) {
  const p = el('div');
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
  return open ? lvCompDetail(a, open) : lvCompsBody(a);
}

//: §4.2 Lobby tab: what the seats we have SEEN are committed to, and the last
//: board the next opponent staged. "of N seen seats" — an unseen seat is
//: unknown, not empty. The BODY only (fix list round 4 item 5): `lvSection`
//: wraps it, so the lobby is one panel with one header in both arrangements.
function lvLobbyBody(a) {
  const p = el('div');
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
//: Under it, what LEFT the shop this turn (fix list round 4 item 3(c)) and the
//: mix of tribes on offer (item 3(b)). One panel, one heading, and neither
//: section is ever left as a blank box: a section with nothing in it says so.
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
  // ONE LINE PER OFFER (2026-10-16) — the rules are `.lv-shoprow` in the CSS.
  // The markup is deliberately UNCHANGED (`lvCard`, so `.lv-card`, `.tile` and
  // `.lv-cap` all still exist): only the direction and the sizes moved, which is
  // what keeps this reversible and keeps every existing reader working. The
  // game's own offer order is untouched — that is what lets row three be
  // matched to the third card on screen.
  const wrap = el('div', 'lv-row lv-shoprow');
  rows.forEach(s => {
    const bits = [];
    if (s.price != null) bits.push(s.price + 'g');
    if (s.pool) bits.push(s.pool);
    wrap.appendChild(lvCard(s.card, s.name, bits.join(' · ') || '—',
                            s.tag === 'spell' ? {kind: 'Spell'} : null));
  });
  body.appendChild(wrap);
  body.appendChild(lvMix(a));
  body.appendChild(lvPassed(a));
  return body;
}
//: The tribe composition of the shop (fix list round 4 item 3(b)): "3 Beast ·
//: 2 Spell", counted per OFFER by the server so it matches the row above it to
//: the card. A shop with no mix (nothing parsed) draws nothing here — the
//: waiting sentence above already says why the panel is empty.
//: The same row carries the NEXT OPPONENT's mix (item 4): one component, two
//: callers, so the two can never disagree about how a mix is counted.
function lvMixRow(label, mixed) {
  if (!(mixed || []).length) return null;
  const row = el('div', 'lv-mix');
  row.appendChild(el('span', 'lv-lbl', label));
  mixed.forEach(m => row.appendChild(el('span', 'lv-mixchip',
                                        m.n + ' ' + m.tribe)));
  return row;
}
function lvMix(a) { return lvMixRow('Tavern mix', a.shop_mix) || el('div'); }
//: HOW LONG AGO THE SHOP WAS READ, on the panel itself (fix list round 4 item
//: 3(b)). The window's `#freshness` strip already says this once the advice is
//: 8s old, but that strip is about the ADVICE and sits above the card; the
//: question "is this shop current?" is asked while looking at the panel. It
//: ticks with the freshness ticker, because the payload does not change while
//: the player thinks and a number frozen at "read just now" would be a lie.
function lvReadAge() {
  // A CLASS, not an id: the arrangement puts the Tavern panel in the first
  // column AND in the accordion, so there are two of these lines in the DOM and
  // a duplicated id is a broken document — `getElementById` would pick one of
  // them by position and the other would sit empty forever.
  return el('div', 'lv-read');
}
function lvAgeText(sec) {
  if (sec == null) return '';
  if (sec < 1) return 'read just now';
  if (sec < 60) return 'read ' + Math.round(sec) + 's ago';
  return 'read ' + Math.floor(sec / 60) + ' min ago';
}
function tickReadAge() {
  const text = lvAgeText(_generated == null ? null : Date.now() / 1000 - _generated);
  document.querySelectorAll('.lv-read').forEach(n => { n.textContent = text; });
}
//: WHAT WAS ROLLED PAST THIS TURN (fix list round 4 item 3(c)). Every offer
//: that left the shop while it was open, one card per OFFER ENTITY — two
//: copies of one minion were two cards on screen and are two cards here. The
//: payload carries this turn's rows in the order they left, and the display
//: runs BACKWARDS from that: the generation the player just rolled away from
//: is the one they are looking for, and a heavy roll turn can leave 40 cards
//: behind it (measured 2026-10-12 on the 2026-10-12 game, turn 13). Nothing
//: here is keyed by card id — the whole point of the item is that the same id
//: can appear twice in one row.
function lvPassed(a) {
  const body = el('div', 'lv-passed');
  const rows = a.shop_passed || [];
  body.appendChild(el('div', 'lv-lbl',
    'Rolled past this turn · ' + rows.length));
  if (!rows.length) {
    // A section with nothing in it still says so, in the page's own sentence
    // vocabulary: a blank gap reads as "not parsed" (fix list round 4 item 3).
    body.appendChild(el('p', 'lv-note', 'Nothing rolled past yet this turn.'));
    return body;
  }
  const wrap = el('div', 'lv-row');
  rows.slice().reverse().forEach(s => {
    wrap.appendChild(lvCard(s.card, s.name, s.pool || '—',
                            s.tag === 'spell' ? {kind: 'Spell'} : null));
  });
  body.appendChild(wrap);
  return body;
}
//: THE NEXT OPPONENT'S NUMBER AND ITS AGE, built by ONE function so the panel
//: and its section summary cannot word the same facts differently (fix list
//: round 4 item 4). It was written for two boxes — this panel and the classic
//: Reference box — and the classic box went on 2026-10-13; one builder is still
//: what keeps the number and its age consistent.
//:
//: `opp_age` — not `opp_comp.turn` — is the "N rounds ago": it is the age of
//: the record `opp_stats` came from (live_coach's `_opp_boards`, a board we
//: FOUGHT), while `opp_comp.turn` is the buy-phase sighting the seat's staged
//: BOARD came from. Two records, two facts, so the panel labels each: the age
//: rides the number it belongs to, and the board says which round it is from.
//: `opp_lobby` is the median of the lobby's recent fights and says so.
function oppStatsLine(a) {
  if (a.opp_stats != null) {
    return a.opp_stats + (a.opp_age
      ? ' (seen ' + a.opp_age + ' round' + (a.opp_age === 1 ? '' : 's')
        + ' ago)' : '');
  }
  if (a.opp_lobby != null) return '~' + a.opp_lobby + ' lobby avg';
  return null;
}
// (The classic Reference box's mix line lived here — the same "3 Beast · 2
// Spell" the Tavern mix row prints. It went with the classic box on
// 2026-10-13: `lvOpponent` reads `oc.tribes` straight from the payload, so the
// formatter had one caller and that caller was the deleted page.)
//: THE NEXT OPPONENT (fix list round 4 item 4): hero, the board they staged,
//: what that board is worth, its tribe mix, and how long ago it was seen. Every
//: row is a fact the analysis already carries — `opp_comp` for the board,
//: `opp_stats`/`opp_lobby` for the number, `opp_age` for the age — and NOT the
//: seat's handle (`opp_comp.name`), which stays where it already is on the
//: Lobby tab: this is the panel a player screenshots. Nothing here says who is
//: favoured: §1 bans a verdict on the live page, for every viewer now that there
//: is one (2026-10-13).
function lvOpponent(a) {
  const p = el('div');
  const oc = a.opp_comp;
  if (!oc || !(oc.cards || []).length) {
    p.appendChild(lvEmptyRow('No opponent board seen yet.'));
    return p;
  }
  p.appendChild(lvKV('Hero', oc.hero_name || oc.hero || null));
  p.appendChild(lvKV('Their board stats', oppStatsLine(a)));
  p.appendChild(lvKV('Last seen', oc.turn ? 'round ' + oc.turn : null));
  const mix = lvMixRow('Their mix', oc.tribes);
  if (mix) p.appendChild(mix);
  const wrap = el('div', 'lv-row');
  oc.cards.forEach(c => {
    wrap.appendChild(lvCard(c.card, c.name || c.card,
                            (c.n > 1 ? '×' + c.n : '') + (c.golden ? ' ★' : ''),
                            c.n > 1 ? {badge: '×' + c.n} : null));
  });
  p.appendChild(wrap);
  return p;
}
//: §4.2 board row: the caption is the comp role the value pass already names
//: ("comp core", "off-comp filler"), which is a fact about membership.
//: One tribe a lobby has banned reads "<Tribe> — out of play" here (fix list
//: round 1 item 7 / round 2 item 5). The reason string itself ("banned tribe —
//: can't grow") is the value pass's, pinned by its own test and read by the
//: review, so the caption is built from DATA — the minion's tribe plus the flag
//: the payload carries — rather than by rewriting that sentence.
function lvBoard(a) {
  const body = el('div');
  // ONE CARD PER MINION (round-3 item 1): `board_cards` is per entity, so two
  // identical minions are two cards. It falls back to the grouped `sell_rank`
  // row (one row with ×N — that grouping was the classic Sell box's, and it is
  // still in the payload for the decision log and old records) for a payload
  // recorded before that field existed.
  const rows = a.board_cards
    ? a.board_cards
    : (a.sell_rank || []).map(s => ({card: s.card, name: s.name, why: s.why,
                                     score: s.score, tribe: s.tribe,
                                     off_play: s.off_play, n: s.n}));
  if (!rows.length) {
    body.appendChild(el('p', 'lv-inline', 'empty'));
    return body;
  }
  const wrap = el('div', 'lv-row');
  rows.forEach(s => {
    const cap = s.off_play
      ? ((s.tribe || 'Tribe') + ' — out of play')
      : (s.why || (s.score != null ? String(Math.round(s.score)) : '—'));
    wrap.appendChild(lvCard(s.card, s.name, cap,
                            s.n > 1 ? {badge: '×' + s.n} : null));
  });
  body.appendChild(wrap);
  return body;
}
function lvHand(a) {
  // ONE LINE, NO ART (2026-10-15, the maintainer's call: "people don't need to
  // see what's in the tavern or in their hand — they can just look at the
  // screen"). The hand is the clearest case of that: the game draws it
  // full-size, with the real card text, and it cannot be stale. A row of tiles
  // here spent the panel's width restating what is already on screen.
  //
  // What survives is the COUNT and the names, as text — enough to notice "did I
  // lose a card", which is the question a stale read could actually answer
  // wrongly. A tribe breakdown would be the better summary and the payload does
  // not carry one; that is a separate change if it turns out to be wanted.
  const body = el('div');
  const rows = a.hand || [];
  if (!rows.length) {
    body.appendChild(el('p', 'lv-inline', 'empty'));
    return body;
  }
  body.appendChild(el('p', 'lv-inline',
                      'hand ' + rows.length + ' · '
                      + rows.map(s => s.name || s.card).join(', ')));
  return body;
}
//: The board and the hand, ONE panel with the two side by side (fix list round
//: 2 item 4). Each half says "empty" inline rather than showing a sentence where
//: a row of cards would be, so the panel does not change shape when the board is
//: wiped. The HAND half is a sentence now whatever it holds (see `lvHand`); the
//: board half is still cards, because its per-minion values are the product.
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

//: The rows an option can show, each emitted only when its data exists (§5) and
//: each at ONE decimal (the compact card's own rule, 2026-10-14). The key
//: doubles as the Stats-shown toggle.
//: `pick_rate` is NOT one of them: it is the headline figure ("31.3% Picked"),
//: and the row that repeated it ("Picked in 31% of games") was the duplicate the
//: fix list names (round 2 item 1). It stays available as an ORDER, which reads
//: the stats directly rather than through this list.
//: `tier`/`tribe` are not rows either: they ARE a discover option's subline (see
//: `lvOptSub`), and a card this size printing "Tier 4 · Beast" and then a Tier
//: row and a Tribe row is the same duplication one line further down.
function lvStatRows(st) {
  const rows = [];
  if (st.avg_placement != null) {
    rows.push(['avg_placement', 'Avg place', st.avg_placement.toFixed(1)]);
  }
  if (st.top4 != null) rows.push(['top4', 'Top 4', st.top4.toFixed(1) + '%']);
  return rows;
}
const LIVE_STAT_LABELS = {pick_rate: 'picked %', avg_placement: 'avg place',
                          top4: 'top 4'};
//: At most this many stat rows on one compact card; what is left over is
//: counted on the line under them ("+ 2 more").
const LIVE_PICK_ROWS = 2;

//: The ONE muted line under an option's name (2026-10-14): the hero power for a
//: hero (`choices.option_stats` sources it — the DBs hold no per-hero armor),
//: "Tier 4 · Beast" for a discover, and nothing at all for a trinket, whose
//: data is its population numbers. An empty string means "no line", never a
//: dash: a card with no subline simply starts at its headline.
function lvOptSub(st) {
  if (st.sub) return st.sub;
  const bits = [];
  if (st.tier != null) bits.push('Tier ' + st.tier);
  if (st.tribe) bits.push(st.tribe);
  return bits.join(' · ');
}

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

//: §4.3's canonical pick screen, re-cut 2026-10-14 into COMPACT HORIZONTAL
//: cards: the art on the LEFT at a fixed 3/4 ratio, and to its right the name,
//: one muted line about the option, the headline figure with its distance from
//: the offered average, and at most two stat rows. The screen has to fit a
//: ~900px-tall window without scrolling, which is what "compact" buys: the old
//: card was a 130px column with the art on top, a fixed-height name under it,
//: the headline, EIGHT distribution bars and up to five rows — four options
//: were a screenful on their own, and the answer to "which hero" was below the
//: fold.
//:
//: Options in the order the GAME offered them unless the player picks another
//: order; nothing here ranks and no badge says which option is better. Nothing
//: here reads the option's fact STRING either (the classic pick panel's prose —
//: that panel is gone, 2026-10-13): the numbers come from
//: `choice.option_stats`, which is also why the phrasing the design bans
//: ("fits your board") cannot reach this screen.
//:
//: The BODY only (fix list round 4 item 5): `lvSection('Choose one', …)` wraps
//: it, so there is one `.lv-pn` and one heading per section — a screen inside a
//: panel inside a panel is two headings for one thing.
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
  // ONE line, ellipsised, with the whole sentence on the hover (§8: what a
  // truncation hides has to be reachable somewhere).
  const src = 'Source: population statistics scraped from hsreplay.net, read '
    + 'from the shipped meta DB · observational, not causal. '
    + (avg == null ? 'Shown in the order offered.'
                   : 'Offered average: ' + avg.toFixed(1) + '% picked.');
  const note = el('p', 'lv-note lv-source', src);
  note.title = src;
  body.appendChild(note);
  const wrap = el('div', 'lv-pickgrid');
  rows.forEach(([name, cid]) => {
    const st = stats[cid] || {};
    const card = el('div', 'lv-optcard');
    // The full name on the card as well as on its art: a name that clamps is
    // still readable in full by hovering anywhere on the option.
    card.title = name || '';
    // The art carries NO caption of its own (round 1 item 2): the name beside
    // it is the ONE name. Its size is the stylesheet's (72x96 nominal, height
    // clamped on a short window), so the grid cannot jump.
    const art = el('span', 'lv-pickart');
    art.appendChild(thumb(cid, name));
    card.appendChild(art);
    const col = el('div', 'lv-optbody');
    col.appendChild(el('div', 'lv-pname', name));
    const sub = lvOptSub(st);
    if (sub) {
      const line = el('div', 'lv-psub', sub);
      line.title = sub;
      col.appendChild(line);
    }
    if (st.pick_rate != null) {
      // ONE line: the figure, what it is, and the distance from the offered
      // average (round 1 item 2 / round 2 item 1). The row that used to repeat
      // the figure is gone.
      const head = el('div', 'lv-phead');
      head.appendChild(el('b', null, st.pick_rate.toFixed(1) + '%'));
      head.appendChild(el('small', null, 'Picked'));
      if (avg != null) {
        const d = st.pick_rate - avg;
        head.appendChild(el('i', 'lv-vs',
          (d >= 0 ? '+' : '−') + Math.abs(d).toFixed(1) + ' vs offered avg'));
      }
      col.appendChild(head);
    }
    // At most TWO rows, with the rest COUNTED on the line under them — the
    // number of stats an option has is a fact, and so is the fact that two of
    // them are not on screen.
    const shown = lvStatRows(st).filter(([k]) => !_livePickHidden.has(k));
    shown.slice(0, LIVE_PICK_ROWS).forEach(([_k, label, value]) => {
      col.appendChild(lvKV(label, value));
    });
    if (shown.length > LIVE_PICK_ROWS) {
      col.appendChild(el('div', 'lv-note lv-pmore',
                         '+ ' + (shown.length - LIVE_PICK_ROWS) + ' more'));
    }
    // §6.2: an option the DBs have nothing for says so, and says it on a card
    // of the SAME height — the patch detail the long sentence used to print
    // rides the hover, so the line stays as short as every other card's.
    if (st.pick_rate == null && !sub && !lvStatRows(st).length) {
      const nod = el('div', 'lv-pnodata', 'No data');
      nod.title = 'No data for this card on this patch yet.';
      col.appendChild(nod);
    }
    card.appendChild(col);
    wrap.appendChild(card);
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
  return body;
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
//: every replay automatically` checkbox into ONE row." The SHELL card (the
//: first-run/game-over card `renderWelcome` draws) asks the question and reports
//: the answer in two separate rows; here the checkbox and what it does sit
//: together, and the Save button appears only while the answer
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
  // The page chrome, which `render`'s welcome branch returns before: without
  // these two the corner sharing control and the release stamp would keep
  // whatever the last live payload left there.
  renderShareToggle(a.share);
  renderRelease(a.release);
  app.classList.add('tavern-on');
  box.hidden = false;
  box.innerHTML = '';
  // A GAME ENDED (item B.1): the comps view state — the open Detail, the sort,
  // the expanded tier groups and the ticked compare boxes — belongs to the game
  // that just finished, so it goes with it. The next game starts from the
  // design's defaults.
  lvResetCompsView();
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
  // sentence the shell card shows, at 11px, because it is a standing fact rather
  // than something this card is asking for.
  if (a.privacy) p.appendChild(el('p', 'lv-note lv-fine', a.privacy));
  root.appendChild(p);
  box.appendChild(root);
}

//: --------------------------------------------------------------------------
//: FIX LIST ROUND 4 ITEM 5, the layout half (2026-10-13). The view is built
//: from SECTIONS, and the WINDOW decides how they are arranged — the maintainer's
//: own call: "if the window is ~1920 wide, then three columns. Otherwise collapse
//: it" (the rule asks for 1650px of viewport, see the CSS block):
//:
//:   >=1650px of viewport  three columns, no tabs, every section on screen at once
//:   below that            one column, each section foldable, a one-line summary
//:                         in every header, and the Facts table pinned above them
//:
//: `lvPanelBody(title, a)` is the ONE place a section's content is chosen, so a
//: section cannot mean one thing in a column and another in the accordion.
function lvPanelBody(title, a) {
  if (title === 'Choose one') return lvPick(a);
  if (title === 'Tavern') {
    // The taverner's row: a shop nobody has read yet says so on its own panel
    // instead of drawing four skeleton bars (fix list round 2 item 2).
    return (a.shop_rank || []).length ? lvShop(a) : lvWaiting(a);
  }
  if (title === 'Board and hand') return lvBoardHand(a);
  if (title === 'Comps') return lvCompsScreen(a);
  if (title === 'Next opponent') return lvOpponent(a);
  if (title === 'Lobby') return lvLobbyBody(a);
  return lvFacts(a);
}
//: Is a pick on screen? §4.3: while the game is asking, choosing is what the
//: player is doing, so the pick screen REPLACES the tavern row rather than
//: sitting beside it — the same rule the tab row used to apply, applied to both
//: arrangements through one predicate so they cannot disagree.
function lvPicking(a) {
  return !!(a.choice && a.choice.ranked && a.choice.ranked.length);
}
//: The one state a section says in its header rather than its body: whether the
//: lobby's tribes are confirmed yet. Said once, in the header, and nowhere else
//: (round 3 item 4).
function lvCompsNote(a) {
  return a.tribes_detecting ? 'tribes not confirmed yet' : null;
}
//: THE ONE-LINE SUMMARY (item 5): a count and its noun, which is what fits on a
//: header line and is the same kind of fact every panel below already carries.
//: Deliberately NOT a judgement and not a second reading of the section — §1
//: is about words on the screen, and a header line is exactly where a verdict
//: would sneak in. Every string here is a count, a name the payload already
//: printed, or a dash.
function lvSectionLine(title, a) {
  const n = (xs) => (xs || []).length;
  if (title === 'Choose one') {
    // The source the game names ("Lesser Trinket"), and how many options are on
    // offer — two counts, no ranking. The server's rows arrive score-ordered
    // (§4.3) and nothing here may read that order.
    const ch = a.choice || {};
    const k = n(ch.ranked);
    return (ch.source ? ch.source + ' · ' : '')
         + k + (k === 1 ? ' option' : ' options');
  }
  if (title === 'Tavern') {
    const shop = n(a.shop_rank);
    return shop ? shop + (shop === 1 ? ' offer' : ' offers')
                : 'nothing read yet';
  }
  if (title === 'Board and hand') {
    return n(a.board_cards || a.sell_rank) + ' on board · '
         + n(a.hand) + ' in hand';
  }
  if (title === 'Comps') {
    // "N in this lobby" (item B.1, 2026-10-14): the main list holds the comps
    // this game can still build, so the count that belongs on its header is
    // that one. "12 of 16 available" described a list that no longer exists —
    // the 16 included comps of tribes this lobby does not offer.
    const comps = a.comps || [];
    if (!comps.length) return 'nothing read yet';
    return lvInLobby(a).length + ' in this lobby';
  }
  if (title === 'Next opponent') {
    const oc = a.opp_comp || {};
    return oc.hero_name || oc.hero || 'no board seen';
  }
  if (title === 'Lobby') {
    const rows = a.tribe_pressure || [];
    return rows.length
      ? rows.reduce((s, r) => s + (r.seats || 0), 0) + ' of ' +
        rows.reduce((s, r) => s + (r.of || 0), 0) + ' seen seats'
      : 'no seats sighted yet';
  }
  return '';
}
//: One section: the panel, with a clickable header that carries the summary
//: line, and — in `acc` mode — the player's stored open/closed state applied at
//: build time. The state is applied from `lvCollapsed` on EVERY render, which is
//: the whole point: the shop is re-read every 5 seconds
//: (`live.SHOP_REREAD_SECONDS`) and the page re-renders whenever the payload
//: string changes, so a class set only by the click handler would be wiped
//: every 5 seconds and the section would pop shut under the player's hands.
function lvSection(title, a, acc) {
  const note = title === 'Comps' ? lvCompsNote(a) : null;
  const p = lvPanel(title, lvPanelBody(title, a), title === 'Tavern', note);
  const line = lvSectionLine(title, a);
  if (line) p.querySelector('h3').appendChild(el('span', 'lv-sum', line));
  // THE COMPS SORT CONTROL RIDES ITS OWN HEADING (2026-10-16 — see
  // `lvCompsSort`). Not while a comp is OPEN: that is a different screen with
  // its own header and a Back control, and an order control for a list that is
  // not on screen would be a control with nothing to act on.
  if (title === 'Comps' && !_liveComp) {
    const ctl = lvCompsSort(a);
    ctl.classList.add('lv-hctl');
    p.querySelector('h3').appendChild(ctl);
  }
  if (!acc) return p;
  p.classList.add('lv-acc');
  if (title === 'Facts') {
    // FACTS IS NOT FOLDABLE AND IS PINNED (item 5): it is the strip the rest of
    // the page scrolls under, so it keeps no caret and no open/closed state.
    p.classList.add('lv-pin');
    return p;
  }
  if (lvCollapsed(title)) p.classList.add('shut');
  const h = p.querySelector('h3');
  // A role and a tabindex, because this is a real control on a div: the header
  // has to be reachable and operable from the keyboard (Enter/Space), the same
  // bargain the buttons it replaced already kept.
  h.setAttribute('role', 'button');
  h.setAttribute('tabindex', '0');
  h.setAttribute('aria-expanded', p.classList.contains('shut') ? 'false' : 'true');
  const flip = () => {
    const shut = p.classList.toggle('shut');
    h.setAttribute('aria-expanded', shut ? 'false' : 'true');
    lvSetCollapsed(title, shut);
  };
  h.onclick = flip;
  h.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); }
  };
  return p;
}
//: The three-column arrangement: the two screens the player reads the game
//: through on the left, Comps in the middle, and the reference material on the
//: right — facts, then the announced opponent, then the lobby. NO TABS: every
//: section is on screen, so a tab row would be a control that hides what is
//: already visible. The columns are FLAT CHILDREN of the arrangement, so "which
//: column is this panel in" is a `>` away and no column is a container of
//: another.
//:
//: The pick screen is NOT in a column any more (2026-10-14): `lvBody` puts it
//: ABOVE this arrangement, across the full width, because the design's wide mock
//: is one row of four and four 200px options are 800px — which no single column
//: of a three-column page has. The tavern row stays at the top of column one
//: either way, so a pick no longer hides the shop (or the comps, or the facts)
//: while it asks.
function lvColumns(a) {
  const one = el('div', 'lv-col');
  one.appendChild(lvSection('Tavern', a, false));
  one.appendChild(lvSection('Board and hand', a, false));
  // The reference material, UNDER the board it describes (2026-10-16). The old
  // third column was 300px of mostly-empty page at the start of a game, and the
  // comps list was the thing short of room — so the rail moved in with the
  // board, in the order the player reads it, and column two is comps alone.
  one.appendChild(lvSection('Facts', a, false));
  one.appendChild(lvSection('Next opponent', a, false));
  one.appendChild(lvSection('Lobby', a, false));
  const two = el('div', 'lv-col');
  two.appendChild(lvSection('Comps', a, false));
  return [one, two];
}
//: The accordion (every window under 1650px): one column, the facts strip pinned
//: at the top of it, then the same five sections in the order the player needs
//: them. The pick screen is above the whole arrangement (see `lvBody`), so it is
//: not one of the titles here.
//:
//: COMPS FIRST (2026-10-15, the maintainer's call: "I just really want the Comps
//: section to be more visible"). It used to be FOURTH of five and shut by
//: default, so reaching it meant scrolling past a tavern and a board the player
//: can already see on screen, then clicking to reveal it. The tavern is the most
//: redundant panel on this page — the same call that turned the hand into a line
//: — so it does not keep the top slot ahead of the thing the page exists to say:
//: what to build toward.
function lvAccordion(a) {
  const col = el('div', 'lv-col');
  col.appendChild(lvSection('Facts', a, true));
  ['Comps', 'Tavern', 'Board and hand', 'Next opponent', 'Lobby'].forEach(t => {
    col.appendChild(lvSection(t, a, true));
  });
  return [col];
}
//: The body of the view, holding BOTH arrangements so exactly one can be shown.
//: One of them is displayed by the `(min-width: 1650px)` media query — a WINDOW
//: rule since 2026-10-13, on the maintainer's own call, because `#wrap` caps this
//: page at 1600px and a box-width rule therefore cannot tell a 1920px window from
//: a 1700px one (see the CSS block's comment). Building both and letting CSS
//: choose is what keeps the two arrangements from disagreeing: `hidden` would be
//: a second mechanism saying the same thing, and JS cannot read the window width
//: at render time and stay right when the window is resized.
function lvBody(a) {
  const wrap = el('div', 'lv-body');
  // THE PICK STRIP, ABOVE THE DASHBOARD (2026-10-14). The design's wide mock is
  // one row of four options, and the point of it is that choosing does not
  // evict the rest of the page: the tavern row, the comps list and the facts
  // table stay on screen under the pick. So the pick panel is a sibling of both
  // arrangements, at their full width, rather than the first section of one of
  // them — `lvPicking` is still the ONE predicate that decides whether it is
  // there, so the two arrangements cannot disagree about it (`lvColumns` and
  // `lvAccordion` no longer ask). The panel carries `lv-pickstrip` so a reader
  // (and this suite's driver) can find the strip by name without having to know
  // which arrangement is on screen — a page-wide search for `.lv-pn` would find
  // the hidden arrangement's sections first.
  if (lvPicking(a)) {
    const pick = lvSection('Choose one', a, false);
    pick.classList.add('lv-pickstrip');
    wrap.appendChild(pick);
  }
  const cols = el('div', 'lv-main lv-layout-cols');
  lvColumns(a).forEach(c => cols.appendChild(c));
  const acc = el('div', 'lv-main lv-layout-acc');
  lvAccordion(a).forEach(c => acc.appendChild(c));
  wrap.appendChild(cols);
  wrap.appendChild(acc);
  return wrap;
}

function renderLiveTavern(a) {
  const app = document.getElementById('app');
  const box = document.getElementById('live-tavern');
  // The card slot is HIDDEN, not destroyed: `#live-tavern` is this view's own
  // container, so the card in `#col-decide` survives a live frame and a later
  // welcome payload re-renders it in place (2026-10-09 — the first version
  // cleared `#app` and the way back threw).
  app.classList.add('tavern-on');
  box.hidden = false;
  box.innerHTML = '';
  // The comps list is re-cut when the game's tribe state changes, BEFORE the
  // body is built — the body reads `_liveCompMore`/`_liveCompare` while it
  // renders, so a stale set would draw one frame of a list that no longer
  // exists (item B.1's "recompute on every tribe change").
  lvSyncCompsView(a);
  const root = el('div', 'tavern live');
  // No game-over band here: that card arrives on its own payload (`welcome:
  // true`), which `render` sends to `renderTavernGameOver` instead of to this
  // renderer — a live payload with a board never carries one.
  root.appendChild(lvStatus(a));
  root.appendChild(lvTribes(a));
  root.appendChild(lvBody(a));
  box.appendChild(root);
  // Fill the panel's read-age line NOW rather than waiting up to a second for
  // the freshness ticker: a panel that renders with an empty line and fills it
  // in a moment later reads as a panel that lost something.
  tickReadAge();
}
function render(a) {
  // The payload's own `generated` stamp is what the panel's read-age line
  // counts from. Set here as well as in poll() because the page can render a
  // payload without polling it — the tests' own driver calls render() directly
  // — and a read-age line that only ever appears on the poll path is a line
  // that silently goes missing (round 4 item 3(b)).
  if (a.generated) _generated = a.generated;
  if (a.welcome) {
    // §6.5's game-over card, or the first-run card. The live view is cleared
    // first, or a stale frame would sit behind the card (`tavern-on` still
    // hides the card slot, and the container kept its last frame).
    if (a.game_over) {
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
  // A rebuild discards the hovered element without a mouseleave — drop the
  // tooltip with the old frame so it can't outlive its card.
  leaveCard();
  CARDS = a.cards || {};
  // THE CARD SLOT IS EMPTIED (2026-10-13). It holds the welcome or game-over
  // card, and a live frame is not a card: `render` cleared it here before the
  // old renderer drew the two panes into it, and with one renderer it is one
  // line rather than a second page's worth of setup.
  document.getElementById('col-decide').innerHTML = '';
  // Pre-warm the /card renders for everything on screen so hovers are instant
  // (one-time per card: the server caches downloads in img_cache/card/, and
  // misses are remembered server-side).
  Object.keys(CARDS).forEach(cid => {
    if (!_warmed.has(cid)) {
      _warmed.add(cid);
      new Image().src = '/card/' + cid + '.png';
    }
  });
  // THE LIVE VIEW IS THE PAGE (2026-10-13). There is no viewer to branch on:
  // every non-welcome payload draws the Tavern layout, which is the style
  // LIVE_VIEW_DESIGN.md describes and the only one the maintainer kept. The
  // classic live renderer — the state strip, the two panes, the classic comp
  // tiles and pick panel, the classic tribe picker — was deleted with the
  // toggle, so there is no second page for a payload shape to reach. A payload
  // with no board (live.py never sends one: `_advise` builds it from the parsed
  // board) reaches the Tavern panel's own waiting state rather than a special
  // case here, which is what the `lvWaiting` sentence is for.
  renderLiveTavern(a);
}
// The in-play picker's POST (2026-09-19; the taps are the IN-TAVERN five since
// 2026-10-13). The route and its name are unchanged — the page and the server
// ship together, and the per-run token already makes a stale tab's POST
// impossible.
//: The client no longer keeps a copy of the tapped set (2026-10-13). It existed
//: for the classic picker, which drew from a local Set that had to survive a
//: re-render and outrun a poll; the Tavern row (`lvTribes`) reads
//: `tribes_available` from the payload every time, so the server is the single
//: owner and a stale set cannot be held across a game boundary.
function postInPlay(list) {
  fetch(auth('/bans'), {method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  // The body key says what the list IS (2026-10-13): the five
                  // tribes the tavern offers.
                  body: JSON.stringify({in_play: list})});
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
  renderTavernGame(j.rep || j);
}
// THE REVIEW IS THE TAVERN LAYOUT (2026-10-13). `renderSettleGame` was the
// classic one — every timeline turn as its own card under a sticky header, the
// final duel's phases attached to the last card, the model's plan and its
// grading in a folded row per phase. It, its `_viewer` dispatcher and the
// `bl-settle-viewer` key are gone; `renderTavernGame` below is what the saved
// game dropdown reaches.
//
// The plan did NOT go with it. The review is where the model's verdict is
// allowed to ship (PIVOT.md), and `tavernRail` carries every phase of the turn
// — the plan text AND its grading — so the ledger's whole point (the model's
// line beside what the player did) is still on screen.
let _settleRep = null;
let _tavernTurn = null;
// Summary (rail + card) or Step through (design §4.6). The choice persists; a
// rep without steps forces Summary and the toggle says why.
// _tavernStep/_tavernPlayTimer are the step-through's position and autoplay
// handle.
let _tavernMode = 'summary';
let _tavernStep = 0;
let _tavernPlayTimer = null;
try { _tavernMode = localStorage.getItem('bl-settle-mode') || 'summary'; }
catch (e) { /* private mode */ }
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
// The minions a turn bought AND sold (design §4.4's "passed through" tray), ONE
// ENTRY PER EVENT (round-3 item 1's audit of the same dedupe): the old version
// walked an id-keyed map, so buying and selling the same minion twice in one
// phase drew ONE ghost. The tray's job is to show what the phase moved, and the
// log moved two.
function passedThrough(bought, sold) {
  const boughtIds = new Set((bought || []).map(x => x.card || x));
  const pool = (bought || []).concat(sold || []);
  const named = id => {
    const src = pool.find(x => (x.card || x) === id);
    return typeof src === 'string' || src == null
      ? {card: id, name: id} : src;
  };
  const out = [];
  for (const s of sold || []) {
    const id = s.card || s;
    if (boughtIds.has(id)) out.push(named(id));
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
// The review (REPLAY_VIEWER_DESIGN.md): the warm palette, a turn strip with the
// result markers, ONE turn on screen at a time, the Summary rail and the
// Step-through. The turn itself is `settleTurnCard` — the shared card the
// classic reviewer also used, which is why it kept its tabs, its notes and its
// honesty; the classic reviewer is gone (2026-10-13) and this is the only
// renderer the saved-game dropdown reaches.
function renderTavernGame(rep) {
  // The rep is remembered so the mode toggle and the keyboard can re-render
  // without a refetch. (This was `renderSettleGame`'s job while a `_viewer`
  // dispatcher sat in front of the two reviewers; the dispatcher is gone and
  // this is the entry point every caller reaches.)
  _settleRep = rep;
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
      renderTavernGame(rep);
    };
    strip.appendChild(b);
  }
  root.appendChild(strip);
  const row = turns.find(r => r.turn === _tavernTurn);
  let card = null;
  if (row && effMode === 'step') {
    root.appendChild(renderTavernSteps(row));
  } else if (row) {
    // Design §3: rail 330px left, the turn's card right. The face-off's HP line
    // needs the NEXT turn's effective-HP reading, which only the caller has.
    //
    // The model's plan rides the RAIL (2026-10-09, player call), folded under a
    // neutral label with its grading on that label (2026-10-13). The card gets
    // no phase rows: every phase this turn — plus any final-duel phase with no
    // shop of its own, which the classic reviewer used to attach to the last
    // card — lands in the rail's Plan section, once.
    const idx = turns.indexOf(row);
    const nextEff = idx >= 0 && turns[idx + 1] ? turns[idx + 1].eff : null;
    const seen = new Set(turns.map(r => r.turn));
    const isLast = row === turns[turns.length - 1];
    const railPhases = phases.filter(p => p.turn === row.turn
        || (isLast && !seen.has(p.turn)));
    const wrap = document.createElement('div');
    wrap.className = 'twrap';
    wrap.appendChild(tavernRail(row, railPhases));
    card = settleTurnCard(row, {hero: rep.hero, nextEff: nextEff});
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
    // STATS, NOT VALUE (2026-10-17). The chip said "value" and printed the
    // board's stat growth, and the two are different questions — `stats()` in
    // turn_review says so itself, and the review carries no value figure at all.
    // MEASURED: "it says that the value went up 19061. But the amount that the
    // stats of the minions went up is a verry different number." It was one
    // number pretending to be another. Split into attack/health, the same pair
    // and the same order the tiles show, so a player can check it.
    const signed = n => (n >= 0 ? '+' : '') + n;
    const ga = stats.growth_atk, gh = stats.growth_hp;
    chip(ga != null && gh != null
      ? 'stats ' + signed(ga) + '/' + signed(gh)
      : 'stats ' + signed(stats.growth));
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
  // The model's plan, folded, under a neutral label — and its GRADING beside
  // it on the summary line (2026-10-13). The grading used to ride the classic
  // reviewer's phase row ("coaching — taken"), which the classic reviewer took
  // with it; the review is where the model's verdict ships (PIVOT.md), so the
  // label stays the neutral noun the rail has always used and the verdict is
  // the fact appended to it. Without this the tab would show what the model
  // wanted and never whether it was done, which is the ledger's whole point.
  for (const p of phases || []) {
    const det = document.createElement('details');
    det.className = 'rplan';
    det.appendChild(el('summary', null,
                       p.verdict ? 'Plan — ' + p.verdict : 'Plan'));
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
  renderTavernGame(_settleRep);
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
      renderTavernGame(_settleRep);
    }, 900);
  }
  renderTavernGame(_settleRep);
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
      renderTavernGame(_settleRep);
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
  // THE TAVERN ABOVE AND THE HAND BELOW (2026-10-17, the maintainer's ask): the
  // board alone cannot say what you were working with, or whether a roll went
  // past something you may have wanted. Both rows are mini tiles so the BOARD
  // stays the subject, and the tavern is dimmed for the same reason. Data is per
  // step; a replay written before this change simply has neither and the rows
  // do not appear.
  const miniRow = (label, cards, note, dim) => {
    const wrap = el('div', 'stepmini' + (dim ? ' dim' : ''));
    wrap.appendChild(el('span', 'minilbl', label));
    const row = el('div', 'minitiles');
    for (const c of cards) {
      const cid = (c && c.card) || c;
      const meta = cardMeta(cid);
      row.appendChild(tile(cid, (meta && meta.name) || cid,
                           c && c.atk != null ? statSub(c) : '',
                           {cls: 'mini'}));
    }
    wrap.appendChild(row);
    if (note) wrap.appendChild(el('span', 'mininote', note));
    return wrap;
  };
  if (st && st.tavern && st.tavern.length) {
    col.appendChild(miniRow('TAVERN', st.tavern.map(c => ({card: c})),
                            'what the shop offered at this step', true));
  }
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
  if (st && st.hand && st.hand.length) {
    col.appendChild(miniRow('HAND', st.hand, 'what you held at this step', false));
  }
  return col;
}
// One board row of a turn card: card tiles when the stored board is
// structured (the server joins display names at serve time), the text the
// standalone page uses when it is not. Art rides /img like everywhere else,
// so tiles hover to the full card render for free.
function boardTiles(list, tags) {
  const wrap = document.createElement('span');
  wrap.className = 'brow-tiles';
  for (const m of list || []) {
    // The two-color stat line (attack gold, health red) — the classic
    // renderer's plain "?/?-when-unknown" string went with the classic
    // renderer (2026-10-13), and a value nobody read is a dash here instead.
    const t = tile(m.card, m.name || m.card, statSub(m), {golden: m.golden});
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
function boardRow(lbl, list, text, tags) {
  // The label is ABOVE the row (2026-10-09, player call), so `stacked` is not a
  // choice any more; the classic side-by-side form with a colour class for the
  // opponent's row went with the classic reviewer (2026-10-13).
  const d = document.createElement('div');
  d.className = 'brow stacked';
  d.innerHTML = '<span class="blbl">' + lbl + '</span>';
  if (list && list.length) d.appendChild(boardTiles(list, tags));
  else {
    const s = document.createElement('span');
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
// (The classic reviewer's phase row lived here — "You: bought… — next fight:
// −N HP" with the model's line folded under it, headed "coaching — taken".
// 2026-10-13: it went with the classic reviewer, because the rail already
// carries the actions as groups, the cost as chips, and the plan with its
// grading on the Plan summary.)
// One turn of a saved game, in the Tavern layout. It was the SHARED card of the
// two reviewers — `opts.tavern` switched the tavern-only extras on for one of
// them — and with the classic reviewer deleted (2026-10-13) there is one caller
// and no flag: the extras ARE this card now. The model's plan is not here; the
// rail carries it with its grading.
function settleTurnCard(r, opts) {
  const c = r.commitment || {};
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
  // The header is the turn and the comp target ONLY (2026-10-09, player call):
  // its gold / board / growth / spent numbers are the rail's chips, and a fact
  // printed twice on one card is the duplication the rail exists to remove.
  head.innerHTML = '<span class="caret">▾</span>'
    + '<span class="tturn">Turn ' + (r.turn ?? '?') + '</span>'
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
  // BATTLE — the fight after beginning-of-combat effects, both sides from
  // the same (peak) burst so the rows are honest relative to each other.
  // Opponent on top, mirroring the in-game combat view (2026-10-07).
  // Design §4.5: the face-off — their board top, VS, yours below (your side
  // tinted warm, theirs cool), the result panel at right. Both boards are the
  // same peak burst the rows use; the panel carries the outcome wording the
  // Result view carries. The classic reviewer's two stacked "brought" rows went
  // with it (2026-10-13).
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
  for (const n of r.notes || []) {
    const d = document.createElement('div');
    d.className = 'note';
    d.textContent = n;
    bodies.battle.appendChild(d);
  }
  // SHOP — open to close, with the turn's events and the action list. The board
  // labels sit ABOVE their rows: a board is a full-width row of cards, and a
  // label beside it only took width from them (2026-10-09).
  bodies.shop.appendChild(r.turn === 1
    ? boardRow('Opened with', null, 'New game — nothing came before')
    : noSnapshot
      ? boardRow('Opened with', null,
                 'No opening board recorded for this turn.')
      : boardRow('Opened with', r.buy_start,
                 '(no shop snapshot — a skipped turn?)'));
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
      boardDelta(r.buy_start, r.buy_end)));
  }
  // Passed through (design §4.4): minions bought AND sold this phase — they
  // never touch either board, so this tray is the only place their card art
  // appears. Ghost styling, hidden when there are none. ONE GHOST PER EVENT
  // (round-3 item 1's audit of the same dedupe): this used to walk an id-keyed
  // map, so a phase that bought and sold the same minion twice drew one ghost.
  const flipped = passedThrough((r.took || {}).bought, (r.took || {}).sold);
  if (flipped.length) {
    const tray = document.createElement('div');
    tray.className = 'brow stacked';
    tray.innerHTML = '<span class="blbl">Passed through</span>';
    const wrap = document.createElement('span');
    wrap.className = 'brow-tiles';
    for (const m of flipped) {
      // A passed-through minion carries no stats in the took lists, so statSub
      // answers null and the ghost draws its name alone — the "?/?" this tray
      // used to print was a question, not a stat (2026-10-09, player call).
      wrap.appendChild(tile(m.card, m.name || m.card, statSub(m),
                            {cls: 'ghost'}));
    }
    tray.appendChild(wrap);
    bodies.shop.appendChild(tray);
  }
  // (THE TURN line and the worth-a-look flags were here. The line's numbers are
  // the rail's chips, and the rail carries the flags — printing them twice, in
  // two vocabularies, is the duplication the rail exists to remove. The classic
  // reviewer was the second printer and it is gone, 2026-10-13.)
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
    w === 'them' ? '— none' : r.battle_end_text));
  bodies.aftermath.appendChild(boardRow('They survived with',
    w === 'them' ? r.theirs_survivors : [],
    w === 'them' ? '' : (w === 'tie' ? '— none — a tie' : '— none')));
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
// NO VIEWER SWITCHES (2026-10-13). The Settle Up header carried a
// `Classic | Tavern` segment and the live nav row carried its own; each wrote a
// key (`bl-settle-viewer`, `bl-live-viewer`) and redrew from the payload on
// screen. Tavern is the only style, so both, their keys, `setSettleViewer`,
// `setLiveViewer` and the `_viewer`/`_liveViewer` variables are gone. Nothing
// reads either key, so a player who had chosen Classic simply sees the one
// renderer that exists.
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
document.querySelectorAll('#settle-mode button').forEach(b => {
  b.onclick = () => {
    if (b.disabled) return;
    stopTavernPlay();
    _tavernMode = b.dataset.m === 'step' ? 'step' : 'summary';
    try { localStorage.setItem('bl-settle-mode', _tavernMode); }
    catch (e) { /* private mode */ }
    if (_settleRep) renderTavernGame(_settleRep);
  };
});
// Keyboard (design §5): Left and Right walk turns (Summary) or steps
// (Step-through); Shift+Left/Right walks turns while stepping; Space
// plays/pauses; Home and End jump to the ends. Ignored while typing, and only
// on the Settle Up tab.
document.addEventListener('keydown', e => {
  if (document.getElementById('settle').className !== 'on') return;
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
      renderTavernGame(_settleRep);
    } else {
      const ni = Math.min(turns.length - 1, Math.max(0, idx + d));
      if (ni !== idx) {
        stopTavernPlay();
        _tavernStep = 0;
        _tavernTurn = turns[ni].turn;
        renderTavernGame(_settleRep);
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
    renderTavernGame(_settleRep);
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
        # The player's hand-picked IN-TAVERN tribes (POST /bans, body key
        # `in_play`), or None when not set. The tribe panel is on screen at t0
        # and the pool inference needs minutes to converge, so a 5-tap override
        # at hero pick is the precise path (2026-09-19; the list itself is not in
        # any log). The five tapped ARE the tribes the tavern offers — `banned`
        # is the derived complement, never this list (2026-10-13).
        self.manual_in_play = None
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


#: Set when HEARTHSTONE'S OWN size cap ends the recording mid-game. The page has
#: no other way to say "the coach can no longer see this game": without it the
#: last shop frame simply stayed up — measured 2026-10-15, a turn-7 board sat
#: there for 24 minutes with nothing but an ageing "read Ns ago" line, and the
#: game's ending (with its review, replay and placement) was gone.
#:
#: A PAGE value, added in `welcome_payload` and never in an analysis, so it
#: cannot reach `decision_log` and therefore cannot reach
#: `session_report.SPEC` — the same rule `share_state` follows, for the same
#: reason.
_LOG_CAP_NOTICE = None


def set_log_cap_notice(limit_kb=None):
    """Put the cap on the card, in the player's words rather than ours."""
    global _LOG_CAP_NOTICE
    where = f"{limit_kb}KB" if limit_kb else "its size limit"
    _LOG_CAP_NOTICE = (
        f"Hearthstone capped its log file at {where} and stopped writing, so "
        f"the rest of this game cannot be read — including how it ended. Run "
        f"the launcher again and say yes and it will remove that cap for you, "
        f"or put Log.FileSizeLimit.Int=-1 in client.config beside the game "
        f"yourself, then restart Hearthstone.")


def clear_log_cap_notice():
    """A new session's log is not capped, so the card goes back to normal."""
    global _LOG_CAP_NOTICE
    _LOG_CAP_NOTICE = None


def log_cap_notice():
    return _LOG_CAP_NOTICE


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
    # `root_score` is what tells the two causes apart, and it has to be the
    # score rather than "is there a Logs folder": a root holding the GAME
    # (score 1) has simply never written a log, so the cause is file logging,
    # not a game installed elsewhere. Measured on the first macOS install
    # (2026-10-15): `/Applications/Hearthstone` holds `Hearthstone.app` and no
    # `Logs/` until the game has been played once, so the very first thing a
    # new Mac player read was the wrong cause — "the game is probably installed
    # somewhere else", about a game sitting in the usual place.
    if config.root_score(config.HS_DIR) >= 1:
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
    if _LOG_CAP_NOTICE:
        # Hearthstone's own size cap ended the recording. Say so on the card
        # instead of leaving the last shop frame up: measured 2026-10-15, the
        # page sat on a turn-7 board for 24 minutes with nothing but an ageing
        # "read Ns ago" line, and the player had no way to tell that the game
        # they were watching had already been cut off mid-fight.
        payload["title"] = "The log stopped"
        payload["status"] = _LOG_CAP_NOTICE
        payload["hint"] = _LOG_CAP_NOTICE
    return json.dumps(payload).encode()


_state = _State()


def clear_analysis(keep_bans=False):
    """Reset the overlay to the welcome state.

    Fired on a new game's CREATE_GAME — the previous game's panel must
    never survive into the next one, and the hand-set in-tavern tribes wipe
    with it (the 5/5 tribe set differs per game). The page's Clear button
    passes keep_bans=True: mid-game, a wipe should blank the screen, not
    throw away a deliberate 5-tap set.
    """
    with _state.lock:
        _state.analysis = None
        _state.payload = welcome_payload()
        _state.etag = hashlib.sha1(_state.payload).hexdigest()
        if not keep_bans:
            _state.manual_in_play = None


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
        # The game's own 5/5 tribe set dies with the game (fix list round 4 item
        # 2). It used to survive until the NEXT game's CREATE_GAME cleared it,
        # which is long enough for the waiting state to be showing a set that
        # belongs to a game that is over — and the tribe set differs per game,
        # so between games there is no correct set to show. The welcome payload
        # carries no tribe field at all, so this is the state agreeing with what
        # is on screen rather than a fix for a visible chip.
        _state.manual_in_play = None


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


def store_manual_in_play(tribes):
    """Set the player's hand-picked IN-TAVERN tribes; an empty list clears it.

    RENAMED 2026-10-13 (was store_manual_bans). The value is the five tribes the
    player tapped on the reveal screen — the tribes the tavern offers, and what
    `banned` is DERIVED from — so the old name described the opposite set, which
    is how the inverted reading survived this long. Only canonical display names
    (tribes.DISPLAY_TRIBES) are accepted; everything else is dropped. Returns the
    list that stuck (sorted).
    """
    from tribes import DISPLAY_TRIBES
    roster = set(DISPLAY_TRIBES)
    clean = sorted({t for t in (tribes or [])
                    if isinstance(t, str) and t in roster})
    with _state.lock:
        _state.manual_in_play = clean if clean else None
    return clean


def latest_manual_in_play():
    """The player's hand-picked in-tavern tribes, or None when unset."""
    with _state.lock:
        return list(_state.manual_in_play) if _state.manual_in_play is not None \
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


def _tribe_mix(mrows, srows, cards):
    """Counts per tribe over a list of card ids (fix list round 4 items 3(b)
    and 4), biggest first.

    Built here rather than in the page because the card -> tribe map is the
    meta DB's, and the payload already has the DB rows in hand (`_meta_rows`);
    shipping a second copy of 339 minions to the browser to count five cards
    would be the same data twice.

    A compound tribe ("Demon/Naga") keeps the DB's own string — it is a fact
    about that minion, and picking one half would be a guess. A tribe-less
    minion (23 of the shipped 339) counts as "No tribe", not as nothing: the
    counts then add up to the number of cards on screen, which is what makes
    the row readable. A tavern SPELL counts as "Spell" for the same reason. A
    card neither DB carries contributes nothing at all — `?` is not a tribe.

    Biggest-first is a COUNT order and not a value ranking: §4.3/§4.4 ban the
    page from ranking for the player, and a composition whose largest slice is
    buried is a table nobody can read.
    """
    counts = {}
    for cid in cards:
        base = cid[:-2] if isinstance(cid, str) and cid.endswith("_G") else cid
        rec = mrows.get(base)
        if rec is not None:
            name = _canon_tribe(rec.get("tribe")) or "No tribe"
        elif base in srows:
            name = "Spell"
        else:
            continue
        counts[name] = counts.get(name, 0) + 1
    return [{"tribe": t, "n": n}
            for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


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

    It is ALSO where the keys no page reads stop (2026-10-14, see
    LIVE_UNREAD_KEYS): those are dropped at the END rather than here, because
    this function's own derivations read some of them.
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
        # shared string `test_hand_engine` pins and the review reads.
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
    # beside it. live_coach hands us the offers in the order the log lists them,
    # so each tile keeps every FACT — its price, its pool count, whether it is a
    # comp piece, its value score — and loses the ordering that made one of them
    # "the" buy. `buy_this` (the named headline) is in LIVE_VERDICT_KEYS, so the
    # page cannot name one either.
    #
    # ONE ROW PER OFFER, NOT PER CARD (2026-10-09, round-3 fix list item 1).
    # `shop_rank` is a card-keyed ranking — one entry per distinct card — so a
    # tavern offering the SAME minion twice drew ONE card: the row was built by
    # keying offers onto the ranking, and `setdefault` quietly dropped the
    # second copy. The offers themselves are entities (`shop_entities`, one
    # entry per offer with the log's own eid), so the row is built from those
    # and each copy gets the card's facts — its score is a property of the CARD,
    # which is why one lookup serves both copies and the POOL chip is the same
    # number twice rather than a halved or doubled one.
    _facts = {c: v for c, v in analysis.get("shop_rank", [])}
    _entities = analysis.get("shop_entities") or []
    if _entities:
        _offers = [(e.get("card"), e.get("eid")) for e in _entities
                   if isinstance(e, dict)]
    else:
        # No entity list: an analysis recorded before this field existed (the
        # review renders old records) or a caller that built its own payload.
        # The offer ORDER is still the log's; only the entity ids are missing.
        _offers = [(c, None) for c in (analysis.get("shop_offers") or [])]
    if not _offers:
        # No offer list at all: no shop parsed. Sort by card id rather than
        # leaving value.shop_ranking's order in place — arbitrary is fine,
        # best-first is the one thing this row must never silently become again.
        _offers = [(c, None)
                   for c, _v in sorted(analysis.get("shop_rank", []),
                                       key=lambda cv: str(cv[0]))]
    a["shop_rank"] = [dict(card=c, eid=e, name=names.get(c, c),
                           score=round(_facts.get(c, 0.0)),
                           price=prices.get(c),
                           pool=(pool.chip(c, held)
                                 if held is not None else None),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else
                                "deploys hand" if c.rstrip("_G") in deployers
                                else None))
                      for c, e in _offers]
    # THE OFFERS THAT LEFT THE SHOP THIS TURN (fix list round 4 item 3(c)):
    # `live_coach.shop_passed` is the per-GAME record — one entry per OFFER
    # ENTITY in the order they left, each stamped with the buy phase it left in
    # — and the panel is per TURN, so the payload carries this turn's rows and
    # the analysis keeps the rest for the record. One row per ENTITY again: two
    # copies of one minion that were both rolled past are two rows (measured on
    # the 2026-10-10 21:04 game: 14 turns in it rolled past two copies of one
    # card, and turn 11 three copies of BG36_730).
    #
    # No `price`: the card can no longer be bought, and printing what it would
    # have cost invites reading the row as buyable. The POOL chip stays — it is
    # a property of the CARD, and "is another copy still out there" is the
    # question this row exists to answer.
    _turn_now = analysis.get("turn")
    a["shop_passed"] = [
        dict(r, name=names.get(r.get("card"), r.get("card")),
             pool=(pool.chip(r.get("card"), held) if held is not None else None),
             tag=("spell" if r.get("card") in spells else
                  "core" if r.get("card") in core else
                  "addon" if r.get("card") in addons else None))
        for r in (analysis.get("shop_passed") or [])
        # A record without a turn (a hand-built fixture, or one written before
        # this field existed) filters NOTHING: the rows are still the rows.
        if _turn_now is None or r.get("turn") == _turn_now]
    # THE BOARD AS ENTITIES TOO (round-3 item 1). `sell_rank` is grouped BY CARD
    # for the payload's grouped Sell row ("Fauna Whisperer ×2", one row, the
    # instance you would sell first — the classic box that drew it is gone, and
    # the grouping stays because `board_cards` below is derived from it and
    # `test_live_view` pins it) — and the Tavern's board row drew from it, so two
    # identical minions on the board rendered one card. This is one row per
    # minion, in board order, carrying the same per-card facts.
    _why = {g["card"]: g for g in sell}
    a["board_cards"] = []
    for _m in analysis.get("board", []):
        _cid = _m.get("card")
        _g = _why.get(_cid) or {}
        a["board_cards"].append({
            "card": _cid, "eid": _m.get("eid"), "name": names.get(_cid, _cid),
            "atk": _m.get("atk"), "health": _m.get("health"),
            "golden": bool(_m.get("golden")),
            "score": _g.get("score"), "why": _g.get("why"),
            "tribe": _g.get("tribe"), "off_play": bool(_g.get("off_play")),
            "fuel": bool(_g.get("fuel")),
        })
    # Next-opponent composition (phase 2): the seat's last-known board as
    # named tiles, golden-flagged, biggest first. Age rides along — the box
    # says "as of round N" so a stale preview never reads current.
    oc = analysis.get("opp_comp")
    if oc:
        cards = [{"card": c, "name": names.get(c, c), "n": n,
                  "golden": c in (oc.get("goldens") or [])}
                 for c, n in sorted(oc["cards"].items(),
                                    key=lambda kv: (-kv[1], kv[0]))]
        # The seat's tribe MIX rides the composition (fix list round 4 item 4):
        # the same helper the tavern's own shop uses, over the board's cards
        # repeated by their count, so "2 Beasts" means two minions rather than
        # two distinct cards.
        _occards = [c for c, n in oc["cards"].items() for _ in range(n)]
        _omrows, _osrows, _ = _meta_rows()
        a["opp_comp"] = dict(oc, cards=cards,
                             tribes=_tribe_mix(_omrows, _osrows, _occards))
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
            # Can this game still build this comp? (round 4 item 1.) True from
            # `game_comps`' own mark; a fixture or an older record without the
            # mark reads True, because "no information" must not render as
            # "unavailable".
            "tribe_available": comp.get("_tribe_available", True),
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
    # The rolled-past row and the next-opponent panel draw cards too, and a card
    # absent from `cards` gets no tier badge and no card text on hover (round 4
    # items 3(c)/4). Golden ids resolve to their base like every other reader.
    ids.update(r["card"] for r in a["shop_passed"] if r.get("card"))
    ids.update(c["card"] for c in ((a.get("opp_comp") or {}).get("cards") or [])
               if c.get("card"))
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
    # TAVERN MIX (fix list round 4 item 3(b)): the tribe composition of the
    # shop the player is looking at. Counted over the OFFERS, one per offer, so
    # two copies of one minion count twice — that IS the shop's composition.
    # A shop nobody has parsed yet yields an empty list, and the page says
    # nothing rather than drawing a row of zeroes.
    a["shop_mix"] = _tribe_mix(mrows, srows,
                               [r["card"] for r in a["shop_rank"]])
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
    # THE SECOND DROP, AND IT GOES LAST (2026-10-14). LIVE_UNREAD_KEYS is its own
    # list — not the pivot's, see it at the top of this file — and it is applied
    # HERE, after every derivation above rather than beside the verdict drop. The
    # reason is that this function reads back its own work: `a["comp_progress"]`
    # is walked by the tooltip collector just above, `a["shop_rank"]` by the
    # pre-commit "leads" tag, `a["sell_rank"]` by `board_cards`. Dropped at the
    # top, the next derivation added here would silently read a key that is
    # already gone — the failure shape `_canon_tribe` and the comp-meter crash
    # both were.
    for _k in LIVE_UNREAD_KEYS:
        a.pop(_k, None)
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
        m = re.match(r"^/img/([A-Za-z0-9_]+)\.png$",
                     self.path.split("?", 1)[0])
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
        m = re.match(r"^/card/([A-Za-z0-9_]+)\.png$",
                     self.path.split("?", 1)[0])
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
            # The body key is `in_play` (RENAMED 2026-10-13, was `banned`): the
            # list is the five tribes the tavern OFFERS, and the server derives
            # the banned set from it. The echo key follows the body, so the two
            # cannot drift apart again.
            in_play = store_manual_in_play(payload.get("in_play"))
            self._send(200, "application/json",
                       json.dumps({"ok": True, "in_play": in_play}).encode())
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
            # player's hand-set in-tavern tribes (mid-game, a wipe should not
            # throw away a deliberate 5-tap set).
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
    return (_HTML.replace("__BL_TOKEN__", server_token())
            .replace("__ART_EPOCH__", art_epoch()))


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
