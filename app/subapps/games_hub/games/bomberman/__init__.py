from app.subapps.games_hub.games.bomberman import game_solo  # noqa: F401
from app.subapps.games_hub.games.bomberman import game_pvp   # noqa: F401

from app.subapps.games_hub.base_game import GameComposite
from app.subapps.games_hub.ui import register_composite
from app.subapps.games_hub.games.bomberman.game_solo import BombermanSingleGame
from app.subapps.games_hub.games.bomberman.game_pvp import BombermanPvPGame

register_composite(GameComposite(
    display_name="Bomberman",
    icon_char="💣",
    variants=[BombermanSingleGame, BombermanPvPGame],
))
