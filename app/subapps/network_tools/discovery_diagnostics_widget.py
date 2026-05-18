from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.discovery import AUTO, classify


class DiscoveryDiagnosticsWidget(QFrame):
    """Live view of DiscoveryAgent telemetry + bound interfaces."""

    def __init__(self, service=network_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setFrameShape(QFrame.NoFrame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        title = QLabel("Discovery diagnostics")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)

        # --- interface selector ---
        sel_row = QHBoxLayout()
        sel_row.setContentsMargins(0, 0, 0, 0)
        sel_label = QLabel("Interface:")
        sel_label.setStyleSheet("color: #888;")
        self._iface_combo = QComboBox()
        self._iface_combo.setMinimumWidth(220)
        self._iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        self._show_all_chk = QCheckBox("show non-RFC1918")
        self._show_all_chk.setToolTip(
            "By default only 192.168.x.x, 10.x.x.x, and 172.16-31.x.x interfaces "
            "are listed. Enable to also show Tailscale/VPN/public addresses."
        )
        self._show_all_chk.toggled.connect(self._populate_interfaces)
        sel_row.addWidget(sel_label)
        sel_row.addWidget(self._iface_combo, 1)
        sel_row.addWidget(self._show_all_chk)
        root.addLayout(sel_row)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(2)

        self._labels: dict[str, QLabel] = {}
        for row, key in enumerate([
            "Multicast", "Bound iface", "Advertised",
            "Beacons", "Last sent", "Last seen",
        ]):
            k = QLabel(key + ":")
            k.setStyleSheet("color: #888;")
            v = QLabel("—")
            v.setStyleSheet("font-family: 'Consolas','Menlo',monospace;")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._grid.addWidget(k, row, 0, alignment=Qt.AlignRight | Qt.AlignTop)
            self._grid.addWidget(v, row, 1)
            self._labels[key] = v
        root.addLayout(self._grid)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #d4a017; font-style: italic;")
        root.addWidget(self._hint)

        iface_title = QLabel("Interfaces")
        iface_title.setStyleSheet("font-weight: 600; margin-top: 6px;")
        root.addWidget(iface_title)

        self._iface_box = QVBoxLayout()
        self._iface_box.setContentsMargins(0, 0, 0, 0)
        self._iface_box.setSpacing(2)
        root.addLayout(self._iface_box)
        root.addStretch(1)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()

        self._service.restarted.connect(self._populate_interfaces)
        self._populate_interfaces()
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        disc = self._service.discovery
        if disc is None:
            return
        t = disc.telemetry
        self._labels["Multicast"].setText(f"{t.multicast_group}:{t.multicast_port}")
        self._labels["Bound iface"].setText(self._format_bound_iface())
        self._labels["Advertised"].setText(
            f"{t.advertised_host}:{t.control_port}" if t.control_port else f"{t.advertised_host}  (no control port yet)"
        )
        self._labels["Beacons"].setText(
            f"sent {t.beacons_sent}   received {t.beacons_received}   self-loop {t.beacons_received_from_self}"
        )
        self._labels["Last sent"].setText(self._ago(t.last_beacon_sent_at))
        self._labels["Last seen"].setText(self._ago(t.last_beacon_received_at))

        # diagnostic hint
        if t.bind_error:
            self._hint.setText(f"Bind error: {t.bind_error}")
        elif t.beacons_sent > 5 and t.beacons_received == 0:
            self._hint.setText(
                "Beacons going out but none received. Likely causes: "
                "firewall blocking inbound UDP, multicast disabled on switch/AP, "
                "or wrong interface bound."
            )
        elif t.beacons_received > 0 and t.beacons_received == t.beacons_received_from_self:
            self._hint.setText(
                "Only seeing self-beacons — no other SCAFFOLD peer on this network."
            )
        else:
            self._hint.setText("")

        self._rebuild_interfaces()

    def _format_bound_iface(self) -> str:
        # show which interface holds the advertised address
        adv = self._service.discovery.telemetry.advertised_host
        for iface in self._service.discovery.network_interfaces():
            if adv in iface.addresses:
                return f"{iface.name}  ({adv})"
        return adv

    def _rebuild_interfaces(self) -> None:
        while self._iface_box.count():
            item = self._iface_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        adv = self._service.discovery.telemetry.advertised_host
        for iface in self._service.discovery.network_interfaces():
            active = adv in iface.addresses
            dot = "●" if active else "○"
            color = "#3ba55c" if active else "#666"
            addrs = ", ".join(iface.addresses) or "(no IPv4)"
            row = QLabel(f"{dot}  {iface.name:<24} {addrs}")
            row.setStyleSheet(
                f"font-family: 'Consolas','Menlo',monospace; color: {color};"
            )
            self._iface_box.addWidget(row)

    @staticmethod
    def _ago(ts: float) -> str:
        if not ts:
            return "never"
        delta = time.time() - ts
        if delta < 1:
            return "just now"
        if delta < 60:
            return f"{int(delta)}s ago"
        return f"{int(delta // 60)}m ago"

    # ------------------------------------------------------------------
    # interface selector

    def _populate_interfaces(self) -> None:
        """Rebuild the combo. Preserves current pref selection."""
        disc = self._service.discovery
        if disc is None:
            return
        current_pref = self._service.interface_pref
        strict = not self._show_all_chk.isChecked()
        candidates = disc.candidate_addresses(strict=strict)

        # If user's saved pref isn't in the filtered list (e.g. they
        # toggled show_all off but had a CGNAT selected), force show_all on
        # so they still see it.
        addrs_in_list = {addr for addr, _, _ in candidates}
        if current_pref != AUTO and current_pref not in addrs_in_list and strict:
            self._show_all_chk.blockSignals(True)
            self._show_all_chk.setChecked(True)
            self._show_all_chk.blockSignals(False)
            candidates = disc.candidate_addresses(strict=False)

        self._iface_combo.blockSignals(True)
        self._iface_combo.clear()
        self._iface_combo.addItem("Auto (prefer RFC1918)", AUTO)
        for addr, iface_name, cls in candidates:
            label = f"{addr}   [{iface_name}]   {cls.name.lower()}"
            self._iface_combo.addItem(label, addr)
        # restore selection
        idx = self._iface_combo.findData(current_pref)
        self._iface_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._iface_combo.blockSignals(False)

    def _on_iface_changed(self, _index: int) -> None:
        pref = self._iface_combo.currentData()
        if pref is None:
            return
        if pref != self._service.interface_pref:
            self._service.set_interface(pref)
