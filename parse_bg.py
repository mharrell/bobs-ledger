"""Parse a Hearthstone Power.log into per-game Battlegrounds summaries using hslog.

Usage:
    python parse_bg.py <path-to-Power.log> [--games N]

Smoke test: confirm hslog can parse real Battlegrounds logs and that
per-player data (hero card, placement) is recoverable.
"""
import argparse
import sys

from hslog.export import EntityTreeExporter
from hslog.parser import LogParser
from hearthstone.enums import GameTag, GameType, PlayState


def _enum_name(enum_cls, value):
    try:
        return enum_cls(value).name if value is not None else "?"
    except Exception:
        return str(value)


def player_final_playstate(game, player):
    """Find the final PLAYSTATE tag across entities controlled by this player."""
    for ent in game.entities:
        if ent.tags.get(GameTag.CONTROLLER, -1) == player.player_id:
            ps = ent.tags.get(GameTag.PLAYSTATE, None)
            if ps is not None:
                return _enum_name(PlayState, ps)
    return "?"


def summarize(game):
    lines = []
    gtype = _enum_name(GameType, game.tags.get(GameTag.GAMETYPE))
    lines.append(f"  game_type={gtype}")
    for player in game.players:
        hero_id = "?"
        hero_ent = player.initial_hero_entity_id
        if hero_ent:
            ent = game.find_entity_by_id(hero_ent)
            if ent:
                hero_id = ent.card_id
        name = getattr(player, "name", None) or "?"
        lines.append(
            f"  player id={player.player_id} name={name!r} hero={hero_id} "
            f"placement/playstate={player_final_playstate(game, player)}"
        )
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("usage: python parse_bg.py <Power.log> [--games N]")
        return 1
    log_path = sys.argv[1]
    limit = None
    if "--games" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--games") + 1])

    print(f"Parsing {log_path} ...", file=sys.stderr)
    parser = LogParser()
    with open(log_path, encoding="utf-8", errors="replace") as f:
        parser.read(f)

    trees = parser.games
    print(f"Total games parsed: {len(trees)}", file=sys.stderr)
    if limit:
        trees = trees[:limit]

    for idx, tree in enumerate(trees, 1):
        exporter = EntityTreeExporter(tree, parser.player_manager)
        try:
            exporter.export()
            game = exporter.game
        except Exception as e:
            print(f"\n=== Game {idx} === EXPORT FAILED: {e!r}")
            continue
        print(f"\n=== Game {idx} ===")
        print(summarize(game))
    return 0


if __name__ == "__main__":
    sys.exit(main())
