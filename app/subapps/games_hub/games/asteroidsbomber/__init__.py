from app.subapps.games_hub.games.asteroidsbomber import game  # noqa: F401

from app.subapps.games_hub.base_game import GameComposite
from app.subapps.games_hub.ui import register_composite
from app.subapps.games_hub.games.asteroidsbomber.game import (
    AsteroidsBomberSingleGame, AsteroidsBomberPvPGame,
)

register_composite(GameComposite(
    display_name="Asteroid Bomber",
    icon_char="💣",
    variants=[AsteroidsBomberSingleGame, AsteroidsBomberPvPGame],
))
