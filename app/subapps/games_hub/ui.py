from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
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

from app.subapps.games_hub.base_game import BaseGame, GameComposite, GameMode, GameResult
from app.subapps.games_hub.score_store import score_store

if TYPE_CHECKING:
    from app.core.settings_store import SettingDef

_GAME_REGISTRY: list[type[BaseGame] | GameComposite] = []


def register_game(cls: type[BaseGame]) -> type[BaseGame]:
    _GAME_REGISTRY.append(cls)
    return cls


def register_composite(composite: GameComposite) -> None:
    _GAME_REGISTRY.append(composite)


def aggregate_settings() -> list["SettingDef"]:
    seen: set[str] = set()
    result = []
    for entry in _GAME_REGISTRY:
        variants = entry.variants if isinstance(entry, GameComposite) else [entry]
        for cls in variants:
            for defn in cls.get_settings():
                if defn.key not in seen:
                    seen.add(defn.key)
                    result.append(defn)
    return result


# ---------------------------------------------------------------------------
# Mode selector dialog

class _ModeSelectorDialog(QDialog):
    def __init__(
        self,
        entry: "type[BaseGame] | GameComposite",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumWidth(280)
        self._drag_pos = None

        self.selected_cls:  type[BaseGame] = (
            entry.variants[0] if isinstance(entry, GameComposite) else entry
        )
        self.selected_mode: GameMode = GameMode.SINGLE

        self.setStyleSheet(
            "QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px;"
            "  border: 2px solid #888; background: transparent; }"
            "QRadioButton::indicator:checked { background: #4a9eff; border-color: #4a9eff; }"
            "QRadioButton::indicator:hover   { border-color: #4a9eff; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setObjectName("DialogTitleBar")
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(12, 0, 6, 0)
        tb.addWidget(QLabel(f"<b>{entry.display_name}</b>"))
        tb.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 4px; font-size: 14px; }"
            "QPushButton:hover { background: #c0392b; color: #fff; }"
        )
        close_btn.clicked.connect(self.reject)
        tb.addWidget(close_btn)
        layout.addWidget(title_bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 0)
        body_layout.setSpacing(10)

        self._radios: list[tuple[QRadioButton, type[BaseGame], GameMode]] = []
        variants = entry.variants if isinstance(entry, GameComposite) else [entry]
        for i, variant_cls in enumerate(variants):
            btn = QRadioButton(variant_cls.display_name)
            if i == 0:
                btn.setChecked(True)
            body_layout.addWidget(btn)
            self._radios.append((btn, variant_cls, GameMode.SINGLE))

        body_layout.addSpacing(8)
        ok_btn = QPushButton("Start")
        ok_btn.clicked.connect(self._on_accept)
        body_layout.addWidget(ok_btn)
        layout.addWidget(body)

    def _on_accept(self) -> None:
        for radio, cls, mode in self._radios:
            if radio.isChecked():
                self.selected_cls  = cls
                self.selected_mode = mode
                break
        self.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None


# ---------------------------------------------------------------------------
# Game card

class _GameCard(QFrame):
    def __init__(
        self,
        entry: "type[BaseGame] | GameComposite",
        hub:   "HubPanel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry        = entry
        self._hub          = hub
        self._is_composite = isinstance(entry, GameComposite)
        self.setObjectName("GameCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(160, 180)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        icon_lbl = QLabel(entry.icon_char)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(entry.display_name)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        layout.addWidget(name_lbl)

        n_modes = len(entry.variants) if self._is_composite else 1
        badge = QLabel(f"{n_modes} mode{'s' if n_modes != 1 else ''}")
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "background: #3b82f6; color: #fff; border-radius: 4px;"
            "padding: 1px 6px; font-size: 10px; font-weight: 700;"
        )
        layout.addWidget(badge)

        self._game_id   = entry.game_id
        self._score_lbl = QLabel()
        self._score_lbl.setAlignment(Qt.AlignCenter)
        self._score_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._score_lbl)
        self.refresh_score()

    def refresh_score(self) -> None:
        best = score_store.best(self._game_id)
        self._score_lbl.setText(
            f"Best: {best.score:,}  ({best.player})" if best else "No scores yet"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._launch()

    def _launch(self) -> None:
        needs_dialog = self._is_composite

        if needs_dialog:
            dlg = _ModeSelectorDialog(self._entry, self)
            if dlg.exec() != QDialog.Accepted:
                return
            game_cls = dlg.selected_cls
            mode     = dlg.selected_mode
        else:
            game_cls = self._entry  # type: ignore[assignment]
            mode     = GameMode.SINGLE

        self._hub.launch_game(game_cls, mode, {0: "P1"})


# ---------------------------------------------------------------------------
# In-game container

class _GameContainer(QWidget):
    def __init__(self, game: BaseGame, hub: "HubPanel",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game    = game
        self._hub     = hub
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

        name_lbl = QLabel(game.display_name)
        name_lbl.setStyleSheet("font-weight: 700;")
        bar_layout.addWidget(name_lbl)

        bar_layout.addStretch()

        self._score_lbl = QLabel("")
        bar_layout.addWidget(self._score_lbl)

        self._pause_btn: QPushButton | None = None
        if game.can_pause():
            self._pause_btn = QPushButton("Pause")
            self._pause_btn.setFixedWidth(60)
            self._pause_btn.clicked.connect(self._on_pause)
            bar_layout.addWidget(self._pause_btn)

        for label, callback in game.toolbar_actions():
            btn = QPushButton(label)
            btn.setFixedWidth(max(52, len(label) * 8))
            btn.clicked.connect(lambda _checked=False, cb=callback: cb())
            bar_layout.addWidget(btn)

        layout.addWidget(bar)

        self._canvas_wrap = QWidget()
        wrap_layout = QVBoxLayout(self._canvas_wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        canvas = game.create_widget()
        canvas.setFocusPolicy(Qt.StrongFocus)
        wrap_layout.addWidget(canvas)
        layout.addWidget(self._canvas_wrap, stretch=1)
        self._canvas = canvas

        game.score_tick.connect(self._score_lbl.setText)
        game.game_over.connect(self._on_game_over)

        canvas.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Escape, Qt.Key_P):
            self._on_pause()
        else:
            super().keyPressEvent(event)

    def _on_back(self) -> None:
        self._hub.stop_active_game()

    def _on_pause(self) -> None:
        if not self._game.can_pause():
            return
        if self._game.current_state.value == "running":
            self._game.pause()
            if self._pause_btn:
                self._pause_btn.setText("Resume")
        else:
            self._game.resume()
            if self._pause_btn:
                self._pause_btn.setText("Pause")

    def _on_game_over(self, result: GameResult) -> None:
        from app.subapps.games_hub.game_over_overlay import GameOverOverlay
        self._submit_scores(result)
        best = score_store.best(self._game.game_id)
        overlay = GameOverOverlay(self._game.display_name, result, best, self._canvas_wrap)
        overlay.hub_clicked.connect(self._hub.stop_active_game)
        overlay.retry_clicked.connect(self._on_retry)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _submit_scores(self, result: GameResult) -> None:
        if not result.scores:
            return
        for player_idx, score in result.scores.items():
            name = self._game._players.get(player_idx, f"P{player_idx + 1}")
            score_store.submit(self._game.game_id, name, score)

    def _on_retry(self) -> None:
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
        if self._pause_btn is not None:
            self._pause_btn.setText("Pause")
        self._score_lbl.setText("")
        self._game.start(self._game._mode, self._game._players)
        self._canvas.setFocus()


# ---------------------------------------------------------------------------
# Hub panel

class HubPanel(QWidget):
    _GRID_COLS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_game: BaseGame | None = None

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._hub_page = self._build_hub_page()
        self._stack.addWidget(self._hub_page)
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
        composite_variants: set[type[BaseGame]] = set()
        for entry in _GAME_REGISTRY:
            if isinstance(entry, GameComposite):
                composite_variants.update(entry.variants)

        visible = [
            entry for entry in _GAME_REGISTRY
            if isinstance(entry, GameComposite) or entry not in composite_variants
        ]

        for i, entry in enumerate(visible):
            card = _GameCard(entry, hub=self)
            self._cards.append(card)
            row, col = divmod(i, self._GRID_COLS)
            self._grid.addWidget(card, row, col)

    def refresh(self) -> None:
        for card in self._cards:
            card.refresh_score()

    def _on_theme_changed(self, _theme: str) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance():
            self._repaint_tree(self)

    def _repaint_tree(self, widget: QWidget) -> None:
        from PySide6.QtWidgets import QApplication
        style = QApplication.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
        for child in widget.findChildren(QWidget):
            child.update()

    def launch_game(
        self,
        game_cls: type[BaseGame],
        mode:     GameMode,
        players:  dict[int, str],
    ) -> None:
        self.stop_active_game()
        game = game_cls()
        self._active_game = game
        container = _GameContainer(game, hub=self)
        self._game_page_index = self._stack.addWidget(container)
        self._stack.setCurrentIndex(self._game_page_index)
        game.start(mode, players)
        container._canvas.setFocus()

    def stop_active_game(self) -> None:
        if self._active_game is None:
            return
        self._active_game.stop()
        self._remove_game_page()
        self._active_game = None
        self._stack.setCurrentIndex(0)
        self.refresh()

    def _remove_game_page(self) -> None:
        if self._game_page_index < 0:
            return
        widget = self._stack.widget(self._game_page_index)
        self._stack.removeWidget(widget)
        if self._active_game is not None:
            try:
                self._active_game.score_tick.disconnect()
                self._active_game.game_over.disconnect()
            except RuntimeError:
                pass
        widget.deleteLater()
        self._game_page_index = -1
