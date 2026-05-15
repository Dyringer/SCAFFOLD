from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.pong.game_core import (
    BALL_SIZE, FIELD_H, FIELD_W, PADDLE_H, PADDLE_W, PongState, InputState,
)
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette


class PongRenderer(KeyHandler, QWidget):
    _TRACKED = {Qt.Key_W, Qt.Key_S, Qt.Key_Up, Qt.Key_Down}

    def __init__(
        self,
        state:       PongState,
        input_state: InputState | None = None,
        parent:      QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state   = state
        self._input  = input_state
        self.setMinimumSize(400, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        if self._input is None:
            return
        self._input.left_up    = Qt.Key_W    in self._held
        self._input.left_down  = Qt.Key_S    in self._held
        self._input.right_up   = Qt.Key_Up   in self._held
        self._input.right_down = Qt.Key_Down in self._held

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        sw, sh = self.width(), self.height()

        def fx(x: float) -> int: return round(x * sw / FIELD_W)
        def fy(y: float) -> int: return round(y * sh / FIELD_H)

        left_col  = pal.piece(4)   # sky blue
        right_col = pal.piece(0)   # pink-red

        p.fillRect(0, 0, sw, sh, pal.board_bg)

        # Net
        p.setPen(Qt.NoPen)
        seg_h = max(fy(18), 6)
        net_x = sw // 2 - 2
        y = 0
        while y < sh:
            p.fillRect(net_x, y, 4, seg_h, pal.grid)
            y += seg_h * 2

        s  = self.state
        pw = fx(PADDLE_W)
        ph = fy(PADDLE_H)

        p.setBrush(left_col)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(fx(0), fy(s.left.y), pw, ph, 4, 4)

        p.setBrush(right_col)
        p.drawRoundedRect(fx(FIELD_W - PADDLE_W), fy(s.right.y), pw, ph, 4, 4)

        if not s.serving:
            bs = max(fx(BALL_SIZE), 6)
            p.setBrush(pal.text)
            p.drawEllipse(fx(s.ball.x), fy(s.ball.y), bs, bs)
        else:
            font = QFont("Segoe UI", max(14, fy(24)))
            font.setBold(True)
            p.setFont(font)
            p.setPen(pal.text_muted)
            p.drawText(0, 0, sw, sh, Qt.AlignCenter, "READY")

        font = QFont("Segoe UI", max(18, fy(44)))
        font.setBold(True)
        p.setFont(font)

        p.setPen(left_col)
        p.drawText(0, fy(12), sw // 2 - 10, fy(52),
                   Qt.AlignRight | Qt.AlignVCenter, str(s.left.score))

        p.setPen(right_col)
        p.drawText(sw // 2 + 10, fy(12), sw // 2 - 10, fy(52),
                   Qt.AlignLeft | Qt.AlignVCenter, str(s.right.score))
