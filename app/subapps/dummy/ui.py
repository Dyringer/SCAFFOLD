import logging
import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.notification_bus import notification_bus
from app.ui.widgets import Card, field_label, mark_modern

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
    card = Card(title)
    card.setFixedWidth(480)
    card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    return card, card.body


def _row() -> tuple[QWidget, QHBoxLayout]:
    row = QWidget()
    row.setObjectName("Plain")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(8)
    return row, hl


class TestSuitePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TestSuite")
        mark_modern(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)

        inner = QWidget()
        inner.setObjectName("Plain")
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Toasts ────────────────────────────────────────────
        toast_card, tl = _section("Toast notifications")

        self._msg_input = QLineEdit()
        self._msg_input.setPlaceholderText("Message text (leave blank for default)")
        tl.addWidget(self._msg_input)

        toast_row, trl = _row()

        self._level_combo = QComboBox()
        self._level_combo.addItems(["info", "warning", "error"])
        self._level_combo.setFixedWidth(120)
        trl.addWidget(self._level_combo)
        trl.addStretch()

        send_btn = QPushButton("Send toast")
        send_btn.setObjectName("PrimaryBtn")
        send_btn.setProperty("compact", True)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.clicked.connect(self._send_toast)
        trl.addWidget(send_btn)

        tl.addWidget(toast_row)
        layout.addWidget(toast_card)

        # ── Logs ──────────────────────────────────────────────
        log_card, ll = _section("Log entries")

        log_row, lrl = _row()

        lrl.addWidget(field_label("COUNT"))

        self._log_count = QComboBox()
        self._log_count.addItems(["1", "5", "10", "25"])
        self._log_count.setFixedWidth(80)
        lrl.addWidget(self._log_count)

        lrl.addStretch()

        log_btn = QPushButton("Generate random logs")
        log_btn.setCursor(Qt.PointingHandCursor)
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
