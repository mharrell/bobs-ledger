"""Parse a Hearthstone Power.log into per-game Battlegrounds summaries using hslog.

Usage:
    python parse_bg.py <path-to-Power.log> [--games N]

Smoke test: confirm hslog can parse real Battlegrounds logs and that
per-player data (hero card, placement) is recoverable.

Note: hslog's LogParser shares one PlayerManager across all games, but in
Battlegrounds the same player name gets a different player_id per lobby, which
raises InconsistentPlayerIdError. We split the log into games first and parse
each with a fresh LogParser to avoid that.
"""
import sys

from hslog.export import EntityTreeExporter
from hslog.parser import LogParser
from hearthstone.enums import GameTag, GameType, PlayState


def _enum_name(enum_cls, value):
    try:
        return enum_cls(value).name if value is not None else "?"
    except Exception:
        return str(value)


def split_game_chunks(lines):
    """Yield (start, end) line-index ranges, one per game.

    Game boundaries are CREATE_GAME lines from GameState.DebugPrintPower()
    (the duplicate PowerTaskList entries are ignored).
    """
    boundaries = [
        i for i, line in enumerate(lines)
        if "CREATE_GAME" in line and "GameState.DebugPrintPower" in line
    ]
    if not boundaries:
        return
    ends = boundaries[1:] + [len(lines)]
    for start, end in zip(boundaries, ends):
        yield start, end


def player_final_playstate(game, player):
    """Find the final PLAYSTATE tag across entities controlled by this player."""
    for ent in game.entities:
        if ent.tags.get(GameTag.CONTROLLER, -1) == player.player_id:
            ps = ent.tags.get(GameTag.PLAYSTATE, None)
            if ps is not None:
                return _enum_name(PlayState, ps)
    return "?"


def summarize(game, game_type=None):
    lines = []
    gtype = _enum_name(GameType, game_type)
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
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    chunks = list(split_game_chunks(lines))
    print(f"Games found: {len(chunks)}", file=sys.stderr)
    if limit:
        chunks = chunks[:limit]

    for idx, (start, end) in enumerate(chunks, 1):
        parser = LogParser()
        parser.read(lines[start:end])
        if not parser.games:
            print(f"\n=== Game {idx} === NO GAME PARSED")
            continue
        tree = parser.games[0]
        exporter = EntityTreeExporter(tree, parser.player_manager)
        try:
            exporter.export()
            game = exporter.game
        except Exception as e:
            print(f"\n=== Game {idx} === EXPORT FAILED: {e!r}")
            continue
        print(f"\n=== Game {idx} ===")
        print(summarize(game, parser.game_meta.get("GameType")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
