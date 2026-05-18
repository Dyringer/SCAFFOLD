from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class Service(Protocol):
    """Minimal lifecycle contract for app-level services.

    Services start before subapps are activated and stop before subapps
    are torn down. Order of start = order of registration; order of stop
    = reverse.
    """

    def start(self) -> None: ...
    def stop(self) -> None: ...


class ServiceRegistry:
    """Tracks app-level services so application.py doesn't grow a fresh
    inline start/stop pair every time we add one.
    """

    def __init__(self) -> None:
        self._services: list[tuple[str, Service]] = []
        self._started: list[str] = []

    def register(self, name: str, service: Service) -> None:
        self._services.append((name, service))

    def start_all(self) -> None:
        for name, svc in self._services:
            try:
                svc.start()
                self._started.append(name)
                log.info("service started: %s", name)
            except Exception:
                log.exception("service %s failed to start", name)

    def stop_all(self) -> None:
        for name, svc in reversed(self._services):
            try:
                svc.stop()
                log.info("service stopped: %s", name)
            except Exception:
                log.exception("service %s failed to stop", name)
        self._started.clear()


service_registry = ServiceRegistry()
