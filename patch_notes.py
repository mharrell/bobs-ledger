"""Apply official Hearthstone patch notes to the curated meta DB.

Fetches a Blizzard patch-notes page, isolates the Battlegrounds section, uses
the DeepSeek LLM to turn the prose into structured before/after changes, then
matches each change against the meta JSON files and (with --apply) writes them
back. Defaults to a dry-run report so a human reviews before anything is edited.

The meta DB is point-in-time (DESIGN.md section 6); this is the "refresh on
patches" mechanism. Patch notes give card/hero NAMES but not internal card IDs,
so brand-new cards are reported for manual entry rather than auto-inserted.

Usage:
    python patch_notes.py <url> [--apply] [--no-llm]

    --apply   write the matched changes into meta/ (default: dry-run report)
    --no-llm  skip LLM extraction; just print the Battlegrounds section

Reads DEEPSEEK_API_KEY from the environment (same as coach_llm.py). Without it,
or with --no-llm, the script only prints the section for manual review.
"""
import argparse
import html
import json
import os
import re
import sys

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(_HERE, "meta")

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com/chat/completions"

# entity_type -> (meta file, field-alias map). The alias map translates the
# LLM's field names to the actual JSON key in that file.
ENTITY_FILES = {
    "minion": ("minions.json", {
        "attack": "attack", "atk": "attack", "health": "health",
        "cost": "cost", "tier": "tier", "tribe": "tribe",
        "text": "text", "card text": "text",
    }),
    "hero": ("heroes.json", {
        "hero_power": "hero_power", "hero power": "hero_power",
        "pick_rate": "pick_rate", "pick rate": "pick_rate",
    }),
    "trinket": ("trinkets.json", {
        "description": "description", "text": "description",
        "pick_rate": "pick_rate", "avg_placement": "avg_placement",
    }),
    "tavern_spell": ("tavern_spells.json", {
        "cost": "cost", "tier": "tier", "text": "text",
    }),
    "dark_gift": ("dark_gifts.json", {
        "description": "description", "text": "description",
    }),
    "card": ("cards.json", {
        "attack": "atk", "atk": "atk", "health": "health",
        "tier": "tier", "tribe": "tribe",
    }),
    "comp": ("comps.json", {
        "meta_tier": "meta_tier", "tier": "meta_tier",
        "difficulty": "difficulty",
    }),
}


# ---------------------------------------------------------------------------
# Fetch + section extraction
# ---------------------------------------------------------------------------

def fetch_text(url):
    """GET the page and return it as plain text."""
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return html_to_text(r.text)


def html_to_text(t):
    """Crude HTML -> text: keep headings and list items as structure."""
    t = re.sub(r"<h[23][^>]*>", "\n\n## ", t, flags=re.I)
    t = re.sub(r"</h[23]>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def extract_bg_section(text):
    """Return the Battlegrounds section (until the next same-level heading)."""
    m = re.search(r"##\s*Battlegrounds\b", text, flags=re.I)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"\n##\s+", rest)
    end = nxt.start() if nxt else len(rest)
    return rest[:end].strip()


def _version_key(title):
    """Sort key for a patch title like '36.4 Patch Notes' -> (36, 4, 0)."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", title or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def discover_latest():
    """Find the newest 'Patch Notes' article from the Blizzard news page.

    The news page embeds a `stickyBlogList` JSON array of articles, each with
    {id, title, slug}. We keep the patch-notes articles and take the highest
    patch version parsed from the title (the article id is not a reliable
    recency indicator). Returns (url, article_dict).
    """
    r = requests.get("https://hearthstone.blizzard.com/en-us/news", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    m = re.search(r"var stickyBlogList = (\[.*?\]);", r.text, re.S)
    if not m:
        raise RuntimeError("Could not find the article list on the news page")
    articles = json.loads(m.group(1))
    patches = [a for a in articles
               if "patch notes" in (a.get("title") or "").lower()]
    if not patches:
        raise RuntimeError("No patch-notes article found on the news page")
    latest = max(patches, key=lambda a: _version_key(a.get("title")))
    url = (f"https://hearthstone.blizzard.com/en-us/news/"
           f"{latest['id']}/{latest['slug']}")
    return url, latest


# ---------------------------------------------------------------------------
# LLM extraction of structured changes
# ---------------------------------------------------------------------------

def extract_changes(bg_text):
    """Ask DeepSeek to turn the prose into a JSON array of changes."""
    system = (
        "You extract structured card/hero balance changes from Hearthstone "
        "Battlegrounds patch notes. Return ONLY a JSON array. Each element is an "
        "object with keys: entity_type, name, field, old, new, note. "
        "entity_type is one of: minion, hero, trinket, tavern_spell, dark_gift, "
        "card, comp. field is the thing that changed (attack, health, cost, tier, "
        "tribe, text, hero_power, description, meta_tier, or 'removed' for a card "
        "being removed from the pool). old/new are the before/after values as "
        "strings (use null when unknown). note is a short human explanation. "
        "Only include real data changes; ignore pure bug fixes that don't alter "
        "card data. If there are no data changes, return []."
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": bg_text},
        ],
        "temperature": 0,
        "max_tokens": 2000,
        "stream": False,
    }
    resp = requests.post(
        BASE_URL,
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                 "Content-Type": "application/json"},
        json=payload, timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return parse_json_array(content)


def parse_json_array(text):
    """Parse a JSON array from LLM output, tolerating prose around it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError("Could not parse JSON array from LLM output")


# ---------------------------------------------------------------------------
# Match + apply
# ---------------------------------------------------------------------------

def load_meta(filename):
    with open(os.path.join(META, filename), encoding="utf-8") as f:
        return json.load(f)


def save_meta(filename, container):
    with open(os.path.join(META, filename), "w", encoding="utf-8") as f:
        json.dump(container, f, ensure_ascii=False, indent=2)
        f.write("\n")


def iter_entities(container):
    """Yield (key, entity) for each entity in a list or dict container."""
    if isinstance(container, dict):
        for k, v in container.items():
            yield k, v
    else:
        for v in container:
            yield None, v


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def coerce(new, old):
    """Cast a string value to the type of the old value (int/float/str)."""
    if isinstance(old, bool) or new is None:
        return new
    if isinstance(old, int):
        try:
            return int(new)
        except (TypeError, ValueError):
            return new
    if isinstance(old, float):
        try:
            return float(new)
        except (TypeError, ValueError):
            return new
    return new


def apply_changes(changes, do_apply):
    """Match each change to the meta DB and (optionally) write it back.

    Returns a list of report dicts, one per change.
    """
    report = []
    for ch in changes:
        et = ch.get("entity_type")
        name = ch.get("name")
        field = ch.get("field")
        new = ch.get("new")
        if et not in ENTITY_FILES or not name:
            report.append({"status": "skip", "reason": "unknown type/name", **ch})
            continue

        filename, aliases = ENTITY_FILES[et]
        container = load_meta(filename)
        idx = {norm(e.get("name")): (k, e) for k, e in iter_entities(container)}
        hit = idx.get(norm(name))
        if not hit:
            report.append({
                "status": "unmatched",
                "reason": "no entity by that name (new card? needs manual entry)",
                **ch,
            })
            continue

        k, entity = hit
        if field == "removed":
            if isinstance(container, dict):
                del container[k]
            else:
                container.remove(entity)
            report.append({**ch, "status": "removed"})
        else:
            json_key = aliases.get(field, field)
            old = entity.get(json_key)
            entity[json_key] = coerce(new, old)
            # spread ch first so the computed old/new (from the DB) win
            report.append({
                **ch, "status": "applied",
                "old": old, "new": entity[json_key],
            })

        if do_apply:
            save_meta(filename, container)
    return report


def print_report(report, do_apply):
    mode = "APPLIED" if do_apply else "DRY-RUN (no files written)"
    print(f"=== Changes ({mode}) ===")
    for r in report:
        tag = r["status"].upper()
        if r["status"] == "applied":
            print(f"[{tag}] {r['entity_type']} {r['name']}: "
                  f"{r['field']} {r.get('old')!r} -> {r.get('new')!r}")
        elif r["status"] == "removed":
            print(f"[{tag}] {r['entity_type']} {r['name']}: removed from pool")
        elif r["status"] == "unmatched":
            print(f"[{tag}] {r['entity_type']} {r['name']}: {r['reason']}")
        else:
            print(f"[{tag}] {r.get('entity_type')} {r.get('name')}: {r['reason']}")
        if r.get("note"):
            print(f"        note: {r['note']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", nargs="?", default=None,
                    help="Blizzard patch-notes URL (default: discover the latest)")
    ap.add_argument("--apply", action="store_true",
                    help="write matched changes into meta/ (default: dry-run)")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip LLM extraction; just print the Battlegrounds section")
    args = ap.parse_args(argv)

    if args.url:
        url = args.url
    else:
        url, article = discover_latest()
        print(f"Discovered latest patch: {article['title']} ({url})")
        print()

    text = fetch_text(url)
    bg = extract_bg_section(text)
    if bg is None:
        print("No Battlegrounds section found on this page.")
        return 1
    print("=== Battlegrounds section ===")
    print(bg)
    print()

    if args.no_llm or not os.environ.get("DEEPSEEK_API_KEY"):
        print("(LLM extraction skipped: pass --no-llm or set DEEPSEEK_API_KEY)")
        return 0

    changes = extract_changes(bg)
    if not changes:
        print("No card/hero data changes detected (bug fixes only, or none).")
        return 0

    report = apply_changes(changes, args.apply)
    print_report(report, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
