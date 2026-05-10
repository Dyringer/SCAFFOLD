from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core.base_subapp import BaseSubApp, SubAppState


class _LoadingOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("LoadingOverlay")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("⟳  Loading…")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 18px;")
        layout.addWidget(lbl)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.setGeometry(self.parent().rect())  # type: ignore[union-attr]


class _ErrorOverlay(QWidget):
    def __init__(self, message: str, retry_callback, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ErrorOverlay")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("✕")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 32px; color: #ef4444;")
        msg = QLabel(message)
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        retry_btn = QPushButton("Retry")
        retry_btn.setFixedWidth(80)
        retry_btn.clicked.connect(retry_callback)

        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(retry_btn, alignment=Qt.AlignCenter)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.setGeometry(self.parent().rect())  # type: ignore[union-attr]


class BodyStack(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # placeholder
        placeholder = QWidget()
        ph_lbl = QLabel("Select a sub-app from the sidebar")
        ph_lbl.setAlignment(Qt.AlignCenter)
        ph_lbl.setStyleSheet("color: #888; font-size: 16px;")
        ph_layout = QVBoxLayout(placeholder)
        ph_layout.addWidget(ph_lbl)
        self._stack.addWidget(placeholder)

        self._pages: dict[str, QWidget] = {}
        self._active_subapp: BaseSubApp | None = None
        self._overlay: QWidget | None = None

    def switch_to(self, subapp_id: str) -> None:
        from app.core.registry import registry
        subapp = registry.get(subapp_id)
        if subapp is None:
            return

        if self._active_subapp is not None:
            try:
                self._active_subapp.state_changed.disconnect(self._on_state_changed)
            except RuntimeError:
                pass

        self._active_subapp = subapp
        subapp.state_changed.connect(self._on_state_changed)

        if subapp_id not in self._pages:
            page = subapp.create_body()
            self._pages[subapp_id] = page
            self._stack.addWidget(page)

        self._stack.setCurrentWidget(self._pages[subapp_id])
        self._clear_overlay()

    def _on_state_changed(self, state: SubAppState) -> None:
        self._clear_overlay()
        current = self._stack.currentWidget()
        if current is None:
            return

        if state == SubAppState.LOADING:
            self._overlay = _LoadingOverlay(current)
            self._overlay.resize(current.size())
            self._overlay.show()
            self._overlay.raise_()
        elif state == SubAppState.ERROR:
            msg = "An error occurred."
            if self._active_subapp:
                retry = self._active_subapp.on_activated
            else:
                retry = lambda: None
            self._overlay = _ErrorOverlay(msg, retry, current)
            self._overlay.resize(current.size())
            self._overlay.show()
            self._overlay.raise_()
        # READY → no overlay

    def _clear_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
