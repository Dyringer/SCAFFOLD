"""Shared pastel color palette for all game renderers."""
from __future__ import annotations

from PySide6.QtGui import QColor


def is_dark() -> bool:
    from app.core.theme_manager import theme_manager
    return theme_manager.current == "dark"


class GamePalette:
    """
    Call GamePalette.get() inside paintEvent — reads current theme each time.

    Dark theme:  near-black board, soft pastel objects, very subtle grid.
    Light theme: light-gray board, slightly deeper pastels, same layout.
    """

    # Pastel piece / object colors — same hue set for both themes,
    # slightly more saturated in dark, slightly muted in light.
    PASTEL_DARK = [
        QColor(255, 179, 186),  # pink-red
        QColor(255, 223, 163),  # peach
        QColor(255, 255, 186),  # lemon
        QColor(186, 255, 201),  # mint
        QColor(186, 225, 255),  # sky
        QColor(204, 186, 255),  # lavender
        QColor(255, 200, 221),  # rose
    ]
    PASTEL_LIGHT = [
        QColor(220, 120, 130),  # deeper pink-red
        QColor(210, 160,  90),  # deeper peach
        QColor(180, 170,  60),  # deeper lemon
        QColor(80,  170, 110),  # deeper mint
        QColor(80,  140, 200),  # deeper sky
        QColor(130,  90, 200),  # deeper lavender
        QColor(200, 110, 150),  # deeper rose
    ]

    @staticmethod
    def get() -> "_Palette":
        return _Palette(is_dark())


class _Palette:
    def __init__(self, dark: bool) -> None:
        self.dark = dark
        if dark:
            self.board_bg  = QColor(18,  18,  18)
            self.grid      = QColor(30,  30,  30)
            self.border    = QColor(50,  50,  50)
            self.text      = QColor(210, 210, 210)
            self.text_muted= QColor(120, 120, 120)
            self.surface   = QColor(28,  28,  28)
            self.accent    = QColor(150, 200, 255)   # sky blue
            self.danger    = QColor(255, 150, 150)   # soft red
            self.success   = QColor(150, 230, 160)   # mint green
            self.pieces    = GamePalette.PASTEL_DARK
        else:
            self.board_bg  = QColor(215, 215, 215)
            self.grid      = QColor(198, 198, 198)
            self.border    = QColor(180, 180, 180)
            self.text      = QColor(40,  40,  40)
            self.text_muted= QColor(130, 130, 130)
            self.surface   = QColor(228, 228, 228)
            self.accent    = QColor(80,  120, 200)
            self.danger    = QColor(200,  70,  80)
            self.success   = QColor(60,  160,  90)
            self.pieces    = GamePalette.PASTEL_LIGHT

    def piece(self, index: int) -> QColor:
        return self.pieces[index % len(self.pieces)]
