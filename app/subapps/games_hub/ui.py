from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.subapps.games_hub.base_game import BaseGame, GameMode, PlayerSlot
from app.subapps.games_hub.input_router import input_router
from app.subapps.games_hub.score_store import score_store

if TYPE_CHECKING:
    pass

# Registry of all available game classes — populated by each game's module at import time.
_GAME_REGISTRY: list[type[BaseGame]] = []


def register_game(cls: type[BaseGame]) -> type[BaseGame]:
    """Decorator used by each game module to register itself with the hub."""
    _GAME_REGISTRY.append(cls)
    return cls


# ------------------------------------------------------------------
# Mode selector dialog

class _ModeSelectorDialog(QDialog):
    def __init__(self, game_cls: type[BaseGame], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Start {game_cls.display_name}")
        self.setMinimumWidth(280)
        self._selected_mode = GameMode.SINGLE

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel(f"<b>{game_cls.display_name}</b>"))

        self._single_btn = QRadioButton("Single player")
        self._single_btn.setChecked(True)
        layout.addWidget(self._single_btn)

        self._pvp_btn: QRadioButton | None = None
        if game_cls.max_players >= 2:
            self._pvp_btn = QRadioButton("2 Players (same keyboard)")
            layout.addWidget(self._pvp_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if self._pvp_btn and self._pvp_btn.isChecked():
            self._selected_mode = GameMode.LOCAL_PVP
        else:
            self._selected_mode = GameMode.SINGLE
        self.accept()

    @property
    def mode(self) -> GameMode:
        return self._selected_mode


# ------------------------------------------------------------------
# Game card

class _GameCard(QFrame):
    def __init__(self, game_cls: type[BaseGame], hub: "HubPanel", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_cls = game_cls
        self._hub = hub
        self.setObjectName("GameCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(160, 180)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        icon_lbl = QLabel(getattr(game_cls, "icon_char", "🎮"))
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_lbl)

        # Game name
        name_lbl = QLabel(game_cls.display_name)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        layout.addWidget(name_lbl)

        # 2P badge
        if game_cls.max_players >= 2:
            badge = QLabel("2P")
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                "background: #3b82f6; color: #fff; border-radius: 4px;"
                "padding: 1px 6px; font-size: 10px; font-weight: 700;"
            )
            layout.addWidget(badge)

        # Top score
        self._score_lbl = QLabel()
        self._score_lbl.setAlignment(Qt.AlignCenter)
        self._score_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._score_lbl)

        self.refresh_score()

    def refresh_score(self) -> None:
        best = score_store.best(self._game_cls.game_id)
        if best:
            self._score_lbl.setText(f"Best: {best.score:,}  ({best.player})")
        else:
            self._score_lbl.setText("No scores yet")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._launch()

    def _launch(self) -> None:
        mode = GameMode.SINGLE
        if self._game_cls.max_players >= 2:
            dlg = _ModeSelectorDialog(self._game_cls, self)
            if dlg.exec() != QDialog.Accepted:
                return
            mode = dlg.mode

        players: dict[PlayerSlot, str] = {PlayerSlot.P1: "P1"}
        if mode == GameMode.LOCAL_PVP:
            players[PlayerSlot.P2] = "P2"

        self._hub.launch_game(self._game_cls, mode, players)


# ------------------------------------------------------------------
# In-game container (wraps the game widget with a top bar)

class _GameContainer(QWidget):
    def __init__(self, game: BaseGame, hub: "HubPanel", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game = game
        self._hub = hub
        self._overlay = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setObjectName("GameTopBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 0, 8, 0)

        back_btn = QPushButton("← Hub")
        back_btn.setFixedWidth(72)
        back_btn.clicked.connect(self._on_back)
        bar_layout.addWidget(back_btn)

        bar_layout.addStretch()

        self._name_lbl = QLabel(game.display_name)
        self._name_lbl.setStyleSheet("font-weight: 700;")
        bar_layout.addWidget(self._name_lbl)

        bar_layout.addStretch()

        self._score_lbl = QLabel("")
        bar_layout.addWidget(self._score_lbl)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFixedWidth(60)
        self._pause_btn.clicked.connect(self._on_pause)
        bar_layout.addWidget(self._pause_btn)

        layout.addWidget(bar)

        # Game canvas — wrap in a container so overlay can sit on top of it
        self._canvas_wrap = QWidget()
        wrap_layout = QVBoxLayout(self._canvas_wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        canvas = game.create_widget()
        canvas.setFocusPolicy(Qt.StrongFocus)
        wrap_layout.addWidget(canvas)
        layout.addWidget(self._canvas_wrap, stretch=1)

        game.score_tick.connect(self._on_score_tick)
        game.game_over.connect(self._on_game_over)

        self.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not input_router.handle_key_press(Qt.Key(event.key())):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if not input_router.handle_key_release(Qt.Key(event.key())):
            super().keyReleaseEvent(event)

    def _on_back(self) -> None:
        self._hub.stop_active_game()

    def _on_pause(self) -> None:
        if self._game.current_state.value == "running":
            self._game.pause()
            self._pause_btn.setText("Resume")
        else:
            self._game.resume()
            self._pause_btn.setText("Pause")

    def _on_score_tick(self, scores: dict) -> None:
        parts = [f"P1: {scores.get('p1', 0):,}"]
        if "p2" in scores and scores["p2"] is not None:
            parts.append(f"P2: {scores.get('p2', 0):,}")
        self._score_lbl.setText("  ".join(parts))

    def _on_game_over(self, scores: dict) -> None:
        from app.subapps.games_hub.game_over_overlay import GameOverOverlay

        # Submit scores first so best score is current when overlay shows
        self._hub.submit_scores(self._game, scores)

        best = score_store.best(self._game.game_id)
        overlay = GameOverOverlay(self._game.display_name, scores, best, self._canvas_wrap)
        overlay.hub_clicked.connect(self._hub.stop_active_game)
        overlay.retry_clicked.connect(self._on_retry)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _on_retry(self) -> None:
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
        self._pause_btn.setText("Pause")
        self._score_lbl.setText("")
        self._game.start(self._game._mode, self._game._players)
        self.setFocus()


# ------------------------------------------------------------------
# Hub panel — top-level widget returned by GamesHubSubApp.create_body()

class HubPanel(QWidget):
    _GRID_COLS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_game: BaseGame | None = None

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        # Page 0: hub grid
        self._hub_page = self._build_hub_page()
        self._stack.addWidget(self._hub_page)

        # Page 1: game container (created dynamically)
        self._game_page_index = -1

        from app.core.theme_manager import theme_manager
        theme_manager.theme_changed.connect(self._on_theme_changed)

    def _build_hub_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Games")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        grid_widget = QWidget()
        self._grid = QGridLayout(grid_widget)
        self._grid.setSpacing(16)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(grid_widget)
        outer.addWidget(scroll, stretch=1)

        self._cards: list[_GameCard] = []
        self._populate_grid()
        return page

    def _populate_grid(self) -> None:
        for i, game_cls in enumerate(_GAME_REGISTRY):
            card = _GameCard(game_cls, hub=self)
            self._cards.append(card)
            row, col = divmod(i, self._GRID_COLS)
            self._grid.addWidget(card, row, col)

    def refresh(self) -> None:
        for card in self._cards:
            card.refresh_score()

    def _on_theme_changed(self, _theme: str) -> None:
        # Re-polish the whole subtree so QSS rules (GameCard borders etc.) reapply,
        # then repaint custom-drawn widgets (renderers use QPainter, not QSS).
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            self._repaint_tree(self)

    def _repaint_tree(self, widget: QWidget) -> None:
        from PySide6.QtWidgets import QApplication, QStyle
        style = QApplication.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
        for child in widget.findChildren(QWidget):
            child.update()

    def launch_game(
        self,
        game_cls: type[BaseGame],
        mode: GameMode,
        players: dict[PlayerSlot, str],
    ) -> None:
        self.stop_active_game()

        game = game_cls()
        self._active_game = game
        input_router.attach(game)

        container = _GameContainer(game, hub=self)
        self._game_page_index = self._stack.addWidget(container)
        self._stack.setCurrentIndex(self._game_page_index)

        game.start(mode, players)
        container.setFocus()

    def stop_active_game(self) -> None:
        if self._active_game is None:
            return
        self._active_game.stop()
        input_router.detach()
        self._remove_game_page()
        self._active_game = None
        self._stack.setCurrentIndex(0)
        self.refresh()

    def submit_scores(self, game: BaseGame, scores: dict) -> None:
        # Skip win/loss format (values are 0 or 1) — not meaningful as a score
        if set(scores.values()) <= {0, 1}:
            return
        p1_name = game._players.get(PlayerSlot.P1, "P1")
        p2_name = game._players.get(PlayerSlot.P2, "P2")
        if scores.get("p1") is not None:
            score_store.submit(game.game_id, p1_name, scores["p1"])
        if scores.get("p2") is not None:
            score_store.submit(game.game_id, p2_name, scores["p2"])

    def _remove_game_page(self) -> None:
        if self._game_page_index < 0:
            return
        widget = self._stack.widget(self._game_page_index)
        self._stack.removeWidget(widget)
        # Disconnect game signals before destroying the container so no
        # in-flight timer callbacks can reach the deleted widget.
        if self._active_game is not None:
            try:
                self._active_game.score_tick.disconnect()
                self._active_game.game_over.disconnect()
            except RuntimeError:
                pass
        widget.deleteLater()
        self._game_page_index = -1
