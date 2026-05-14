from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.palette import GamePalette

_LAYERS     = [12, 16, 16, 4]
_IN_LABELS  = ["vx", "vy", "sin", "cos", "r0", "r45", "r90", "r135", "r180", "r225", "r270", "r315"]
_OUT_LABELS = ["L", "R", "thr", "fire"]

_WEIGHT_CLIP = 3.0
_NODE_R      = 6


class NNVisualizerWidget(QWidget):
    """Live visualisation of the current bot's neural network."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._activations: list[list[float]] = [[] for _ in _LAYERS]
        self._weights: list[list[list[float]]] = []
        self.setMinimumHeight(160)
        self.setMaximumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def update_net(self, net, activations: list[list[float]]) -> None:
        self._activations = activations
        self._weights = [net.w1, net.w2, net.w3]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()
        p.fillRect(self.rect(), pal.board_bg)

        if not self._weights:
            p.setPen(pal.text_muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for bot…")
            return

        w, h = self.width(), self.height()
        margin_x = 52
        margin_y = 14
        n_layers  = len(_LAYERS)
        layer_x   = [margin_x + i * (w - 2 * margin_x) / (n_layers - 1) for i in range(n_layers)]

        # Node positions
        positions: list[list[QPointF]] = []
        for li, count in enumerate(_LAYERS):
            xs  = layer_x[li]
            pts = [QPointF(xs, margin_y + (ni + 0.5) * (h - 2 * margin_y) / count)
                   for ni in range(count)]
            positions.append(pts)

        # Edges
        for li, weight_matrix in enumerate(self._weights):
            src_pts = positions[li]
            dst_pts = positions[li + 1]
            out_act = self._activations[li + 1] if li + 1 < len(self._activations) else []
            for oi, row in enumerate(weight_matrix):
                if oi >= len(dst_pts):
                    break
                for ii, w_val in enumerate(row):
                    if ii >= len(src_pts):
                        break
                    # Thin out hidden→hidden to reduce clutter
                    if li == 1 and (oi * len(row) + ii) % 3 != 0:
                        continue
                    norm  = max(-1.0, min(1.0, w_val / _WEIGHT_CLIP))
                    alpha = int(30 + abs(norm) * 100)
                    col   = QColor(100, 200, 120, alpha) if norm > 0 else QColor(220, 100, 100, alpha)
                    pen   = QPen(col)
                    pen.setWidthF(0.8 + abs(norm) * 1.2)
                    p.setPen(pen)
                    p.drawLine(src_pts[ii], dst_pts[oi])

        # Nodes
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)

        is_output_layer = len(_LAYERS) - 1
        for li, pts in enumerate(positions):
            acts = self._activations[li] if li < len(self._activations) else []
            for ni, pt in enumerate(pts):
                act = acts[ni] if ni < len(acts) else 0.0

                if li == is_output_layer:
                    active = act > 0.5
                    fill   = pal.piece(3) if active else (
                        QColor(40, 40, 40) if pal.dark else QColor(180, 180, 180)
                    )
                    border = pal.piece(3) if active else pal.text_muted
                    r      = _NODE_R + 2
                    pen_w  = 2.0
                else:
                    brightness = int(60 + act * 180)
                    fill   = QColor(brightness, brightness, brightness)
                    border = pal.text_muted
                    r      = _NODE_R
                    pen_w  = 1.0

                pen = QPen(border)
                pen.setWidthF(pen_w)
                p.setPen(pen)
                p.setBrush(fill)
                p.drawEllipse(pt, r, r)

                # Labels
                p.setPen(pal.text_muted)
                if li == 0 and ni < len(_IN_LABELS):
                    p.drawText(int(pt.x()) - margin_x + 2, int(pt.y()) + 4, _IN_LABELS[ni])
                elif li == is_output_layer and ni < len(_OUT_LABELS):
                    p.drawText(int(pt.x()) + r + 3, int(pt.y()) + 4, _OUT_LABELS[ni])
