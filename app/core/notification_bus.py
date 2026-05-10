from PySide6.QtCore import QObject, Signal


class NotificationBus(QObject):
    # level: "info" | "warning" | "error"
    notify = Signal(str, str, str)


notification_bus = NotificationBus()
