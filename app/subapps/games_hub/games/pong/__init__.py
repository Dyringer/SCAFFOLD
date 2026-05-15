from app.subapps.games_hub.games.pong import game_solo  # noqa: F401

from app.subapps.games_hub.base_game import GameComposite
from app.subapps.games_hub.ui import register_composite
from app.subapps.games_hub.games.pong.game_solo import PongSingleGame, PongPvPGame

register_composite(GameComposite(
    display_name="Pong",
    icon_char="🏓",
    variants=[PongSingleGame, PongPvPGame],
))
