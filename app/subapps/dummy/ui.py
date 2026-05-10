import logging
import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.notification_bus import notification_bus

_logger = logging.getLogger("dummy.test")

_LOG_SAMPLES = [
    (logging.DEBUG,    "Processing batch job #{n}"),
    (logging.INFO,     "User session started (id={n})"),
    (logging.INFO,     "Loaded {n} records from cache"),
    (logging.INFO,     "Sub-app activated successfully"),
    (logging.WARNING,  "Response time high: {n}ms"),
    (logging.WARNING,  "Retry attempt {n}/3"),
    (logging.ERROR,    "Connection refused on port {n}"),
    (logging.ERROR,    "Failed to parse response (attempt {n})"),
    (logging.CRITICAL, "Unhandled exception in worker #{n}"),
]


def _section(title: str) -> tuple[QWidget, QVBoxLayout]:
    """Returns a card widget and its content layout."""
    card = QFrame()
    card.setObjectName("TestCard")
    card.setFixedWidth(480)
    vl = QVBoxLayout(card)
    vl.setContentsMargins(16, 12, 16, 14)
    vl.setSpacing(10)

    heading = QLabel(title)
    heading.setObjectName("TestCardTitle")
    vl.addWidget(heading)

    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setObjectName("TestCardSep")
    vl.addWidget(sep)

    return card, vl


class TestSuitePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Toasts ────────────────────────────────────────────
        toast_card, tl = _section("Toast notifications")

        self._msg_input = QLineEdit()
        self._msg_input.setPlaceholderText("Message text (leave blank for default)")
        tl.addWidget(self._msg_input)

        toast_row = QWidget()
        trl = QHBoxLayout(toast_row)
        trl.setContentsMargins(0, 0, 0, 0)
        trl.setSpacing(8)

        self._level_combo = QComboBox()
        self._level_combo.addItems(["info", "warning", "error"])
        self._level_combo.setFixedWidth(110)
        trl.addWidget(self._level_combo)

        send_btn = QPushButton("Send toast")
        send_btn.clicked.connect(self._send_toast)
        trl.addWidget(send_btn)

        tl.addWidget(toast_row)
        layout.addWidget(toast_card)

        # ── Logs ──────────────────────────────────────────────
        log_card, ll = _section("Log entries")

        log_row = QWidget()
        lrl = QHBoxLayout(log_row)
        lrl.setContentsMargins(0, 0, 0, 0)
        lrl.setSpacing(8)

        lrl.addWidget(QLabel("Count:"))

        self._log_count = QComboBox()
        self._log_count.addItems(["1", "5", "10", "25"])
        self._log_count.setFixedWidth(70)
        lrl.addWidget(self._log_count)

        lrl.addStretch()

        log_btn = QPushButton("Generate random logs")
        log_btn.clicked.connect(self._generate_logs)
        lrl.addWidget(log_btn)

        ll.addWidget(log_row)
        layout.addWidget(log_card)

    def _send_toast(self) -> None:
        msg = self._msg_input.text().strip() or "Test notification"
        level = self._level_combo.currentText()
        notification_bus.notify.emit(level, level.capitalize(), msg)

    def _generate_logs(self) -> None:
        count = int(self._log_count.currentText())
        for _ in range(count):
            level, template = random.choice(_LOG_SAMPLES)
            _logger.log(level, template.format(n=random.randint(1, 999)))
