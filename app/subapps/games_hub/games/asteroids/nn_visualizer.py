from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.palette import GamePalette

_LAYERS     = [22, 24, 16, 4]
_IN_LABELS  = ["sVel", "cVel", "spd", "rdy",
               "r0", "r30", "r60", "r90", "r120", "r150",
               "r180", "r210", "r240", "r270", "r300", "r330",
               "tDst", "tSz", "tApp", "thSin", "thCos", "bOnT"]
_OUT_LABELS = ["L", "R", "thr", "fire"]

_WEIGHT_CLIP = 3.0
_NODE_R      = 6
_MARGIN_X    = 52
_MARGIN_Y    = 14


class NNVisualizerWidget(QWidget):
    """Live visualisation of the current bot's neural network."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._activations: list[list[float]] = [[] for _ in _LAYERS]
        self._weights: list[list[list[float]]] = []
        self._edge_cache: QPixmap | None = None   # redrawn only when weights change
        self._cache_size  = (0, 0)
        self.setMinimumHeight(160)
        self.setMaximumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def update_net(self, net, activations: list[list[float]]) -> None:
        weights_changed = net.w1 is not (self._weights[0] if self._weights else None)
        self._activations = activations
        if weights_changed:
            self._weights     = [net.w1, net.w2, net.w3]
            self._edge_cache  = None   # invalidate — will be rebuilt in paintEvent
        self.update()

    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._edge_cache = None
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._weights:
            p = QPainter(self)
            pal = GamePalette.get()
            p.fillRect(self.rect(), pal.board_bg)
            p.setPen(pal.text_muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for bot…")
            return

        w, h  = self.width(), self.height()
        positions = _node_positions(w, h)
        pal   = GamePalette.get()

        # Rebuild edge pixmap only when weights changed or widget resized
        if self._edge_cache is None or self._cache_size != (w, h):
            self._edge_cache = _render_edges(self._weights, positions, pal, w, h)
            self._cache_size = (w, h)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), pal.board_bg)
        p.drawPixmap(0, 0, self._edge_cache)

        # Nodes — drawn live (activations change every tick)
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        last_layer = len(_LAYERS) - 1

        for li, pts in enumerate(positions):
            acts = self._activations[li] if li < len(self._activations) else []
            for ni, pt in enumerate(pts):
                act = acts[ni] if ni < len(acts) else 0.0

                if li == last_layer:
                    active = act > 0.5
                    fill   = pal.piece(3) if active else (
                        QColor(40, 40, 40) if pal.dark else QColor(180, 180, 180)
                    )
                    border = pal.piece(3) if active else pal.text_muted
                    r, pen_w = _NODE_R + 2, 2.0
                else:
                    brightness = int(60 + act * 180)
                    fill   = QColor(brightness, brightness, brightness)
                    border = pal.text_muted
                    r, pen_w = _NODE_R, 1.0

                pen = QPen(border)
                pen.setWidthF(pen_w)
                p.setPen(pen)
                p.setBrush(fill)
                p.drawEllipse(pt, r, r)

                p.setPen(pal.text_muted)
                if li == 0 and ni < len(_IN_LABELS):
                    p.drawText(int(pt.x()) - _MARGIN_X + 2, int(pt.y()) + 4, _IN_LABELS[ni])
                elif li == last_layer and ni < len(_OUT_LABELS):
                    p.drawText(int(pt.x()) + r + 3, int(pt.y()) + 4, _OUT_LABELS[ni])


# ---------------------------------------------------------------------------
# Helpers — pure functions so they are easy to reason about

def _node_positions(w: int, h: int) -> list[list[QPointF]]:
    n = len(_LAYERS)
    layer_x = [_MARGIN_X + i * (w - 2 * _MARGIN_X) / (n - 1) for i in range(n)]
    return [
        [QPointF(layer_x[li], _MARGIN_Y + (ni + 0.5) * (h - 2 * _MARGIN_Y) / count)
         for ni in range(count)]
        for li, count in enumerate(_LAYERS)
    ]


def _render_edges(
    weights: list[list[list[float]]],
    positions: list[list[QPointF]],
    pal,
    w: int,
    h: int,
) -> QPixmap:
    """Draw all edges onto an off-screen pixmap. Called only when weights change."""
    px = QPixmap(w, h)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    for li, weight_matrix in enumerate(weights):
        src_pts = positions[li]
        dst_pts = positions[li + 1]
        for oi, row in enumerate(weight_matrix):
            if oi >= len(dst_pts):
                break
            for ii, w_val in enumerate(row):
                if ii >= len(src_pts):
                    break
                # Thin out hidden→hidden connections to reduce clutter
                if li == 1 and (oi * len(row) + ii) % 3 != 0:
                    continue
                norm  = max(-1.0, min(1.0, w_val / _WEIGHT_CLIP))
                alpha = int(30 + abs(norm) * 100)
                col   = QColor(100, 200, 120, alpha) if norm > 0 else QColor(220, 100, 100, alpha)
                pen   = QPen(col)
                pen.setWidthF(0.8 + abs(norm) * 1.2)
                p.setPen(pen)
                p.drawLine(src_pts[ii], dst_pts[oi])

    p.end()
    return px
