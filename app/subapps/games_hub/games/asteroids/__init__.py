from app.subapps.games_hub.games.asteroids import game_solo  # noqa: F401
from app.subapps.games_hub.games.asteroids import game_bot   # noqa: F401

from app.subapps.games_hub.base_game import GameComposite
from app.subapps.games_hub.ui import register_composite
from app.subapps.games_hub.games.asteroids.game_solo import AsteroidsGame
from app.subapps.games_hub.games.asteroids.game_bot import AsteroidsBotGame

register_composite(GameComposite(
    display_name="Asteroids",
    icon_char="☄️",
    variants=[AsteroidsGame, AsteroidsBotGame],
))
