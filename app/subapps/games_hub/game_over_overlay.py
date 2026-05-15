from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.subapps.games_hub.base_game import GameResult
from app.subapps.games_hub.palette import GamePalette
from app.subapps.games_hub.score_store import ScoreEntry


class GameOverOverlay(QWidget):
    retry_clicked = Signal()
    hub_clicked   = Signal()

    def __init__(
        self,
        game_name: str,
        result:    GameResult,
        best:      ScoreEntry | None,
        parent:    QWidget,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("GameOverOverlay")
        self.setGeometry(parent.rect())

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(0)

        card = QWidget()
        card.setObjectName("GameOverCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(12)

        title = QLabel("GAME OVER")
        title.setObjectName("GameOverTitle")
        title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title)

        name_lbl = QLabel(game_name)
        name_lbl.setObjectName("GameOverGameName")
        name_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(name_lbl)

        card_layout.addSpacing(8)

        # Result line — game decides winner, we just display it
        if result.message:
            result_lbl = QLabel(result.message)
        elif result.winner is not None:
            result_lbl = QLabel(f"Player {result.winner + 1} wins!")
        elif result.scores:
            top_score = max(result.scores.values())
            result_lbl = QLabel(f"{top_score:,}")
        else:
            result_lbl = QLabel("—")

        result_lbl.setObjectName("GameOverScore")
        result_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(result_lbl)

        # Per-player scores (when more than one player)
        if len(result.scores) > 1:
            for player_idx, score in sorted(result.scores.items()):
                sub = QLabel(f"P{player_idx + 1}: {score:,}")
                sub.setObjectName("GameOverScoreSub")
                sub.setAlignment(Qt.AlignCenter)
                card_layout.addWidget(sub)

        # Best score
        p0_score = result.scores.get(0)
        if best is not None:
            sep = QWidget()
            sep.setObjectName("GameOverSep")
            sep.setFixedHeight(1)
            card_layout.addSpacing(4)
            card_layout.addWidget(sep)
            card_layout.addSpacing(4)

            best_lbl = QLabel(f"Best  {best.score:,}   {best.player}")
            best_lbl.setObjectName("GameOverBest")
            best_lbl.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(best_lbl)

            if p0_score is not None and p0_score > best.score:
                new_best = QLabel("New best!")
                new_best.setObjectName("GameOverNewBest")
                new_best.setAlignment(Qt.AlignCenter)
                card_layout.addWidget(new_best)

        card_layout.addSpacing(16)

        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(10)

        hub_btn = QPushButton("← Hub")
        hub_btn.setObjectName("GameOverHubBtn")
        hub_btn.clicked.connect(self.hub_clicked)

        retry_btn = QPushButton("Play Again")
        retry_btn.setObjectName("GameOverRetryBtn")
        retry_btn.setDefault(True)
        retry_btn.clicked.connect(self.retry_clicked)

        btn_layout.addWidget(hub_btn)
        btn_layout.addWidget(retry_btn)
        card_layout.addWidget(btn_row)

        layout.addWidget(card)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.retry_clicked.emit()
        elif event.key() == Qt.Key_Escape:
            self.hub_clicked.emit()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.setFocus()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = GamePalette.get()
        p = QPainter(self)
        bg = pal.board_bg
        from PySide6.QtGui import QColor
        scrim = QColor(bg.red(), bg.green(), bg.blue(), 200)
        p.fillRect(self.rect(), scrim)

    def resizeEvent(self, event) -> None:  # noqa: N802
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
