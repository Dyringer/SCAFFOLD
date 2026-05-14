from app.subapps.games_hub.games.bomberman import game  # noqa: F401

from app.subapps.games_hub.base_game import GameComposite
from app.subapps.games_hub.ui import register_composite
from app.subapps.games_hub.games.bomberman.game import BombermanSingleGame, BombermanPvPGame

register_composite(GameComposite(
    display_name="Bomberman",
    icon_char="💣",
    variants=[BombermanSingleGame, BombermanPvPGame],
))
