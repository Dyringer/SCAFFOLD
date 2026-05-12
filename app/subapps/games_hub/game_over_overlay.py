from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.subapps.games_hub.score_store import ScoreEntry


class GameOverOverlay(QWidget):
    retry_clicked = Signal()
    hub_clicked = Signal()

    def __init__(
        self,
        game_name: str,
        scores: dict,           # {"p1": int, "p2": int | None}
        best: ScoreEntry | None,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("GameOverOverlay")

        # Fill parent
        self.setGeometry(parent.rect())

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(0)

        # Card
        card = QWidget()
        card.setObjectName("GameOverCard")
        card.setFixedWidth(320)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(12)

        # Title
        title = QLabel("GAME OVER")
        title.setObjectName("GameOverTitle")
        title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title)

        # Game name
        name_lbl = QLabel(game_name)
        name_lbl.setObjectName("GameOverGameName")
        name_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(name_lbl)

        card_layout.addSpacing(8)

        # Scores — detect win/loss format (values are 0 or 1) vs point format
        p1_score = scores.get("p1", 0) or 0
        p2_score = scores.get("p2")

        is_win_loss = (p2_score is not None and set(scores.values()) <= {0, 1})

        if is_win_loss:
            winner_text = "P1 WINS!" if p1_score > (p2_score or 0) else "P2 WINS!"
            score_lbl = QLabel(winner_text)
        else:
            score_lbl = QLabel(f"{p1_score:,}")
        score_lbl.setObjectName("GameOverScore")
        score_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(score_lbl)

        if p2_score is not None and not is_win_loss:
            p2_lbl = QLabel(f"P2: {p2_score:,}")
            p2_lbl.setObjectName("GameOverScoreSub")
            p2_lbl.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(p2_lbl)

        # Top score
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

            if p1_score > best.score:
                new_best = QLabel("New best!")
                new_best.setObjectName("GameOverNewBest")
                new_best.setAlignment(Qt.AlignCenter)
                card_layout.addWidget(new_best)

        card_layout.addSpacing(16)

        # Buttons
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

    def paintEvent(self, event) -> None:  # noqa: N802
        # Semi-transparent scrim using theme background color
        p = QPainter(self)
        bg = self.palette().color(QPalette.Window)
        bg.setAlpha(200)
        p.fillRect(self.rect(), bg)

    def resizeEvent(self, event) -> None:  # noqa: N802
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
