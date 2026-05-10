# Scaffold App — Work Plan

## Overview

A PySide6 / Python 3.14 multi-platform desktop shell that acts as a host for
pluggable sub-apps. Custom chrome (no OS titlebar), extensible sub-app registry,
aggregated settings, toast notification bus, typed inter-sub-app message bus,
command palette, system tray, sub-app lifecycle states, and async task support.

---

## App Identity

| Constant | Value |
|---|---|
| Name | S.C.A.F.F.O.L.D. |
| Full name | Some Cross-platform App Framework Of Loosely Defined decisions |
| Default window size | 1024 × 768 |
| Minimum window size | 800 × 600 |
| Icons | Qt built-in standard icons (`QStyle.StandardPixmap`) |
| Settings file | `settings.json` beside executable |
| Log file | `app.log` beside executable |

---

## UI Layout

### Main window

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ☰   [Universal Widget]             🔔   ◑   ⚙   ─   ✕              │  ← Header
├────┬────────────────────────────────────────────────────────────────────┤
│    │                                                                     │
│ ⊞  │                                                                     │
│    │                                                                     │
│ ⊟  │                    Body  (active sub-app panel)                    │
│    │                                                                     │
│ ⊠  │                                                                     │
│    │                                                                     │
│    ├── Logs  ● ─────────────────────────────── [All][ℹ][▲][✕] [≡] [✕]│  ← Log panel
│    │  12:01  INFO   app.registry  registered counter                    │  ← (expanded)
│    │  12:01  WARN   app.network   timeout, retrying…                   │
│    │  12:02  ERROR  counter.core  fetch failed                          │
├────┴────────────────────────────────────────────────────────────────────┤
│  Panel status text …                                              ◢     │  ← Footer
└─────────────────────────────────────────────────────────────────────────┘
   ↑
  Sidebar
 (collapsed)
```

### Sidebar — collapsed vs expanded

```
Collapsed          Expanded
┌────┐             ┌──────────────┐
│ ⊞  │             │ ⊞  Counter   │
│    │             │              │
│ ⊟  │             │ ⊟  Dummy     │
│    │             │              │
│ ⊠  │             │ ⊠  Settings  │
└────┘             └──────────────┘
icon only          icon + name
```

### Header — detail

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ☰  │  [────── Universal Widget ──────]  ··spacer··  │  🔔  │  ◑  │  ⚙  │  ─  │  ✕ │
└──────────────────────────────────────────────────────────────────────────────┘
  ↑                        ↑                              ↑      ↑     ↑     ↑    ↑
menu toggle         sub-app-specific             notifs  theme  settings  min  exit
(sidebar)         (swapped on activation)        history toggle
```

Ctrl+K anywhere opens the command palette overlay.

### Toast overlay (top-right, over body)

```
                             ┌──────────────────────────────┐
                             │▏ ℹ  Title                    │  ← info (blue border)
                             │   Message text here           │
                             └──────────────────────────────┘
                             ┌──────────────────────────────┐
                             │▏ ▲  Title                    │  ← warning (amber)
                             │   Message text here           │
                             └──────────────────────────────┘
                             ┌──────────────────────────────┐
                             │▏ ✕  Title                    │  ← error (red)
                             │   Message text here           │
                             └──────────────────────────────┘
```

### Log panel — collapsed vs expanded

```
Collapsed (just header strip):
├── Logs  ●  ──────────────────────────────────────────── [▲] [✕] ─┤

Expanded (Ctrl+` or click ▲):
├── Logs  ●  ── [All] [ℹ Info] [▲ Warn] [✕ Err] ── [⏎ auto] [🗑] [▼] [✕]
│  12:01:04  INFO   app.registry   registered "counter"
│  12:01:05  WARN   app.network    connection timeout, retrying (1/3)
│  12:01:07  ERROR  counter.core   fetch failed: HTTPError 503
│  12:01:09  INFO   counter.core   retry succeeded
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← drag handle (resizes)
```

Level badge colours: INFO=default, WARN=amber text, ERROR=red text + subtle row tint.
Unread error/warning count shown as badge (●) on header strip when collapsed.

### Command palette overlay (Ctrl+K, floats over body)

```
┌──────────────────────────────────────────────────────┐
│  🔍  Search commands and sub-apps…                   │
├──────────────────────────────────────────────────────┤
│  ▶  Counter                          sub-app         │
│  ▶  Dummy                            sub-app         │
│  ▶  Increment counter                counter  Ctrl+↑ │
│  ▶  Reset counter                    counter         │
└──────────────────────────────────────────────────────┘
```

### Notification history panel (🔔 click, drops below header)

```
                     ┌──────────────────────────────────┐
                     │ Notifications               Clear │
                     ├──────────────────────────────────┤
                     │ ℹ  Data loaded       12:04        │
                     │ ▲  Connection slow   11:58        │
                     │ ✕  Fetch failed      11:45        │
                     └──────────────────────────────────┘
```

### Sub-app body — lifecycle states

```
  LOADING                READY                  ERROR
┌──────────┐         ┌──────────┐           ┌──────────┐
│          │         │          │           │          │
│    ⟳     │         │  <panel  │           │    ✕     │
│ Loading… │         │ content> │           │  <msg>   │
│          │         │          │           │ [Retry]  │
└──────────┘         └──────────┘           └──────────┘
```

### Settings sub-app (body panel)

```
┌──────────────────────────────────────────────────────┐
│  Application                                         │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    Window size on start    [ last | default ]        │
│    …                                                 │
│                                                      │
│  Counter                                             │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    Increment step          [ 1 | 5 | 10 ]           │
│                                                      │
│  Dummy                                               │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    (no settings)                                     │
└──────────────────────────────────────────────────────┘
```

---

## Architecture

```
scaffold/
├── main.py                         # Entry point
├── app/
│   ├── __init__.py
│   ├── application.py              # QApplication bootstrap, lifecycle
│   ├── window.py                   # MainWindow (frameless, resize, save state)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── registry.py             # SubApp registry (register / lookup / iterate)
│   │   ├── settings_store.py       # JSON-backed key-value settings
│   │   ├── notification_bus.py     # Signal bus: emit(level, title, message)
│   │   ├── message_bus.py          # Typed pub/sub bus for inter-sub-app messaging
│   │   ├── theme_manager.py        # Load/apply QSS stylesheets, persist selection
│   │   ├── resource_manager.py     # Resolve asset paths (dev vs PyInstaller frozen)
│   │   ├── async_runner.py         # Thread-pool worker → main-thread callback bridge
│   │   ├── log_handler.py          # logging.Handler → Qt signal relay
│   │   └── base_subapp.py          # Abstract BaseSubApp contract
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── header.py               # HeaderBar widget
│   │   ├── sidebar.py              # SidePanel widget (collapsed / expanded + easter egg)
│   │   ├── body.py                 # BodyStack (QStackedWidget wrapper)
│   │   ├── footer.py               # FooterBar widget
│   │   ├── toast.py                # ToastManager + ToastWidget
│   │   ├── notification_history.py # NotificationHistory dropdown panel
│   │   ├── command_palette.py      # CommandPalette overlay (Ctrl+K)
│   │   ├── log_panel.py            # LogPanel collapsible bottom widget
│   │   └── tray.py                 # SystemTrayIcon + tray menu
│   │
│   ├── resources/
│   │   └── themes/
│   │       ├── light.qss
│   │       └── dark.qss
│   │
│   └── subapps/
│       ├── settings/
│       │   ├── __init__.py
│       │   ├── core.py             # SettingsSubApp(BaseSubApp)
│       │   └── ui.py               # SettingsPanel — aggregates all registered settings
│       ├── counter/
│       │   ├── __init__.py
│       │   ├── core.py             # CounterSubApp(BaseSubApp)
│       │   └── ui.py               # CounterPanel, CounterHeaderWidget
│       ├── dummy/
│       │   ├── __init__.py
│       │   ├── core.py             # DummySubApp(BaseSubApp)
│       │   └── ui.py               # HelloWorldPanel
│       └── secret/
│           ├── __init__.py
│           ├── core.py             # SecretSubApp(BaseSubApp, hidden=True)
│           └── ui.py               # SecretPanel
│
├── requirements.txt
├── requirements-dev.txt
└── workplan.md
```

---

## Key Contracts

### BaseSubApp (app/core/base_subapp.py)

`BaseSubApp` inherits `QObject` so it can own signals. Combining `QObject` with
`ABCMeta` requires a merged metaclass:

```python
from abc import ABCMeta, abstractmethod
from PySide6.QtCore import QObject, Signal

class _Meta(type(QObject), ABCMeta):
    pass

class BaseSubApp(QObject, metaclass=_Meta):
    status_changed = Signal(str)        # emit to update footer live
    state_changed  = Signal(SubAppState)# emit to update body lifecycle view

    id: str                             # unique slug, e.g. "counter"
    name: str                           # display name
    icon: QIcon                         # sidebar icon
    hidden: bool = False                # easter-egg flag

    @abstractmethod
    def create_body(self) -> QWidget: ...
    def create_header_widget(self) -> QWidget | None: ...   # None = clear slot
    def get_settings(self) -> list[SettingDef]: ...         # [] = no settings
    def get_commands(self) -> list[CommandDef]: ...         # [] = no commands
    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    # convenience — delegates to async_runner singleton
    def run_async(self, fn: Callable, on_done: Callable, on_error: Callable | None = None) -> None: ...
```

- `status_changed` → footer subscribes on activation, disconnects on deactivation
- `state_changed` → `BodyStack` subscribes; shows spinner (LOADING), panel (READY),
  or error view with Retry button (ERROR)
- `run_async` is a thin wrapper — sub-apps never touch threads directly

### SettingDef (app/core/settings_store.py)

```python
@dataclass
class SettingDef:
    key: str
    label: str
    type: Literal["int", "str", "bool", "choice"]
    default: Any
    choices: list | None = None     # for type="choice"
```

### SubAppState (app/core/base_subapp.py)

```python
class SubAppState(Enum):
    LOADING = "loading"
    READY   = "ready"
    ERROR   = "error"
```

### CommandDef (app/core/base_subapp.py)

```python
@dataclass
class CommandDef:
    id: str
    label: str
    callback: Callable[[], None]
    shortcut: str | None = None     # e.g. "Ctrl+Up"
    icon: QIcon | None = None
```

Sub-apps return these from `get_commands()`. The command palette and global
shortcut manager consume this list — sub-apps never register shortcuts directly.

### LogHandler (app/core/log_handler.py)

Bridges Python's `logging` system to Qt without metaclass conflicts by using a
separate relay object:

```python
class _LogRelay(QObject):
    record_emitted = Signal(object)     # carries logging.LogRecord

_relay = _LogRelay()

class LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _relay.record_emitted.emit(record)

log_handler = LogHandler()             # added to root logger in application.py
log_relay   = _relay                   # LogPanel connects to log_relay.record_emitted
```

- Thread-safe: Qt queues the signal automatically when emitted from a worker thread
- `LogPanel` connects to `log_relay.record_emitted`; all Python log output flows through
- Error/warning records also forwarded to `NotificationBus` (optional, configurable)

### AsyncRunner (app/core/async_runner.py)

```python
class AsyncRunner(QObject):
    def run(
        self,
        fn: Callable[[], T],                    # executed in QThreadPool
        on_done: Callable[[T], None],            # called on main thread
        on_error: Callable[[Exception], None] | None = None,
    ) -> None: ...

async_runner = AsyncRunner()
```

Uses `QThreadPool` + a private `QObject` signal to marshal the result back to the
main thread. Sub-apps call `self.run_async(...)` which delegates here.

### SettingsStore (app/core/settings_store.py)

```python
class SettingsStore:
    # Resolves path as: directory of sys.executable / "settings.json"
    # Falls back to CWD when running from source (non-frozen)
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...        # writes to disk immediately
    def all_for_prefix(self, prefix: str) -> dict: ...
```

- Storage: flat JSON object, dot-separated keys (`"app.theme"`, `"window.geometry"`)
- Written on every `set()` call — no explicit save/flush needed
- `sys.frozen` check: if running as a PyInstaller bundle, `sys.executable` points to
  the exe; otherwise fall back to `Path.cwd()` so dev runs work without elevation

### NotificationBus (app/core/notification_bus.py)

```python
class NotificationBus(QObject):
    notify = Signal(str, str, str)  # level, title, message
    # level: "info" | "warning" | "error"
```

### ThemeManager (app/core/theme_manager.py)

```python
class ThemeManager(QObject):
    theme_changed = Signal(str)     # "light" | "dark"

    def apply(self, theme: str) -> None: ...   # loads QSS, calls qApp.setStyleSheet
    def toggle(self) -> None: ...
    @property
    def current(self) -> str: ...
```

- QSS files live in `app/resources/themes/light.qss` and `dark.qss`
- `apply()` resolves path via `resource_path()`, reads the file, calls `QApplication.instance().setStyleSheet(qss)`
- Current theme persisted to `SettingsStore` key `app.theme` (default `"light"`)
- `theme_changed` signal lets widgets react if they need runtime icon swaps

### Singleton Access Pattern

All core services are module-level instances — no service locator, no DI framework.

```python
# app/core/settings_store.py
settings_store = SettingsStore()

# app/core/message_bus.py
message_bus = MessageBus()

# app/core/notification_bus.py
notification_bus = NotificationBus()

# app/core/theme_manager.py
theme_manager = ThemeManager()

# app/core/registry.py
registry = Registry()

# app/core/async_runner.py
async_runner = AsyncRunner()

# app/core/log_handler.py
log_handler = LogHandler()    # added to root logger
log_relay   = _relay          # UI connects here
```

Usage anywhere in the codebase:

```python
from app.core.message_bus import message_bus
from app.core.notification_bus import notification_bus
```

Singletons are initialised on first import; `application.py` imports them all
early so order is deterministic.

### ResourceManager (app/core/resource_manager.py)

Resolves paths to bundled assets in both dev and PyInstaller-frozen contexts.

```python
def resource_path(relative: str) -> Path:
    # When frozen: Path(sys._MEIPASS) / relative
    # When dev:    Path(__file__).parent.parent / "resources" / relative
    ...
```

All code that loads QSS, icons, or other assets calls `resource_path()` —
never constructs paths manually.

### Logging

Standard `logging` module; configured once in `application.py`:

- `RotatingFileHandler` writing to `app.log` in the same directory as `settings.json`
- Max 1 MB per file, 3 backups
- `StreamHandler` for console output in dev (omitted when frozen)
- Every module uses `logging.getLogger(__name__)` — no shared logger object

### MessageBus (app/core/message_bus.py)

Typed publish/subscribe channel for sub-app-to-sub-app communication.
Sub-apps never import each other; they share only message type definitions.

```python
@dataclass
class Message:
    sender_id: str                  # id of the publishing sub-app

class MessageBus(QObject):
    _signal = Signal(object)        # internal Qt signal carrying Message instances

    def publish(self, message: Message) -> None: ...
    def subscribe(self, msg_type: type[T], handler: Callable[[T], None]) -> None: ...
    def unsubscribe(self, msg_type: type[T], handler: Callable[[T], None]) -> None: ...
```

**Dispatch rules:**
- `publish()` emits `_signal`; the bus checks the runtime type of the message and
  calls only handlers registered for that exact type (no inheritance walk for now).
- All handlers are called on the Qt main thread (signal is queued if published from
  a worker thread).
- Subscription map is `dict[type, list[Callable]]`; `unsubscribe` removes by identity.

**Ownership of message types:**
Each sub-app defines its own message classes inside `core.py`.  
Other sub-apps import *only* the message type, never the whole sub-app module.

```python
# counter/core.py
@dataclass
class CountChanged(Message):
    value: int
    step: int

# some_other_subapp/core.py
from app.subapps.counter.core import CountChanged

bus.subscribe(CountChanged, self._on_count_changed)
```

**Lifecycle convention:**
Subscribe in `on_activated()`, unsubscribe in `on_deactivated()` to avoid
stale handlers firing for inactive sub-apps.

---

## Phase 1 — UI Shell

### Milestone 1.1 — Project scaffold
- [ ] `requirements.txt`: `PySide6>=6.7`
- [ ] `requirements-dev.txt`: `pytest`, `pytest-qt`
- [ ] `app/application.py`: bootstrap `QApplication`, configure logging, load settings, apply theme, build window
- [ ] `main.py`: call `application.run()`
- [ ] `app/core/resource_manager.py`: `resource_path(relative)` with `sys._MEIPASS` / dev fallback
- [ ] Logging: `RotatingFileHandler` → `app.log` beside `settings.json`; `StreamHandler` in dev; `LogHandler` always added to root logger

### Milestone 1.2 — Frameless window + resize
- [ ] `app/window.py`: `Qt.FramelessWindowHint`, custom mouse-press/move for drag
- [ ] Resize grip in footer corner (8-direction resize via `QSizeGrip` or custom)
- [ ] Default size 1024 × 768; minimum size 800 × 600
- [ ] Save/restore geometry and position via `SettingsStore`

### Milestone 1.3 — Header bar
- [ ] Menu icon (hamburger) — toggles sidebar
- [ ] Universal widget slot (`QStackedWidget`, swapped on sub-app activation)
- [ ] Spacer
- [ ] Notification history bell icon — opens `NotificationHistory` dropdown panel
- [ ] Theme toggle button — switches light/dark, persists to `app.theme` in `SettingsStore`
- [ ] Settings icon — activates settings sub-app
- [ ] Minimize button — `window.showMinimized()`
- [ ] Exit button — `QApplication.quit()`

### Milestone 1.4 — Sidebar
- [ ] Collapsed state: icon-only, fixed narrow width
- [ ] Expanded state: icon + name, wider width, animated with `QPropertyAnimation`
- [ ] Click item → activate sub-app
- [ ] Easter egg: track toggle timestamps; 5 toggles within 2 s → reveal hidden apps
  - Hidden apps initially absent from sidebar; added/removed dynamically

### Milestone 1.5 — Body stack
- [ ] `QStackedWidget` managed by `BodyStack`
- [ ] Empty/placeholder page shown on startup
- [ ] `switch_to(subapp_id)` creates body widget on first use, caches thereafter
- [ ] Subscribes to `subapp.state_changed`; overlays spinner (LOADING) or error view (ERROR) on top of body widget

### Milestone 1.6 — Footer bar
- [ ] Status label (left) — connects to `subapp.status_changed` on activation, disconnects on deactivation
- [ ] `QSizeGrip` (right corner) for window resize

### Milestone 1.7 — Registry & activation flow
- [ ] `Registry.register(subapp: BaseSubApp)` — validates, stores, populates sidebar
- [ ] `Registry.activate(subapp_id)` — orchestrates:
  1. Swap header widget (or clear)
  2. Swap body page
  3. Update footer status signal connection
  4. Register sub-app commands in command palette + shortcut manager
  5. Call `on_deactivated` / `on_activated`
- [ ] Persist last active sub-app id to `app.last_subapp`; restore on startup

### Milestone 1.8 — Settings store
- [ ] JSON file stored next to the executable (`settings.json`)
  - Path resolved via `Path(sys.executable).parent / "settings.json"` when frozen
  - Falls back to `Path.cwd() / "settings.json"` when running from source
- [ ] `get(key, default)` / `set(key, value)` / `all_for_prefix(prefix)`
- [ ] Flat dict, dot-separated keys; written to disk on every `set()` call
- [ ] Window geometry keys: `window.geometry`, `window.pos`
- [ ] Theme key: `app.theme` (default `"light"`)

### Milestone 1.8a — Theme manager
- [ ] `app/core/theme_manager.py`: `ThemeManager` singleton
- [ ] `app/resources/themes/light.qss` and `dark.qss` — base stylesheets
- [ ] `apply(theme)` loads QSS and calls `QApplication.setStyleSheet`
- [ ] `toggle()` flips between light/dark, persists via `SettingsStore`
- [ ] Theme restored from `SettingsStore` on startup (before window is shown)
- [ ] Header toggle button wired to `ThemeManager.toggle()`

### Milestone 1.9 — Message bus
- [ ] `MessageBus` singleton in `app/core/message_bus.py`
  - Internal `Signal(object)` connected to a dispatch method
  - `subscribe(msg_type, handler)` — stores in `dict[type, list[Callable]]`
  - `unsubscribe(msg_type, handler)` — removes handler by identity
  - `publish(message)` — emits signal (thread-safe via Qt queued connection if needed)
- [ ] `Message` base dataclass with `sender_id: str`
- [ ] Unit-testable without a running `QApplication` (pure dispatch logic extractable)

### Milestone 1.10 — Toast notifications + history
- [ ] `NotificationBus` singleton — `Signal(level, title, message)`
- [ ] `ToastManager` overlay widget (parent = MainWindow, always on top)
  - Anchored top-right, stacks downward
  - Each `ToastWidget`: coloured left border (info=blue, warning=amber, error=red)
  - Auto-dismiss after 4 s with fade-out animation
  - Max 5 visible; oldest removed when limit exceeded
- [ ] `NotificationHistory` — in-memory list of all notifications (capped at 100)
  - Dropdown panel anchored below 🔔 header button
  - Each row: icon + title + timestamp; click to dismiss
  - "Clear all" button
  - Bell icon shows unread badge count; resets on panel open
- [ ] Any sub-app accesses bus via `notification_bus.notify.emit(...)`

### Milestone 1.11 — Settings sub-app
- [ ] Registered like any other sub-app (id=`"settings"`)
- [ ] Opened via header settings icon (bypasses sidebar click)
- [ ] `SettingsPanel` queries `Registry` for all sub-apps, calls `get_settings()`
- [ ] Renders sections: App → SubApp1 → SubApp2 …
- [ ] Widget per `SettingDef.type`: `QSpinBox`, `QLineEdit`, `QCheckBox`, `QComboBox`
- [ ] Changes written to `SettingsStore` immediately (no apply button needed)
- [ ] Export button — file dialog → copy `settings.json` to chosen path
- [ ] Import button — file dialog → load JSON, merge into `SettingsStore`, reload UI

### Milestone 1.12 — Sub-app lifecycle states
- [ ] `SubAppState` enum (`LOADING | READY | ERROR`) in `base_subapp.py`
- [ ] `BodyStack` listens to `state_changed`; overlays:
  - LOADING → centred spinner (`QMovie` or animated SVG)
  - ERROR → centred error message + "Retry" button (calls `on_activated` again)
  - READY → show normal body widget
- [ ] Sub-apps emit `state_changed(LOADING)` at start of async work, `READY` on completion, `ERROR` on failure

### Milestone 1.13 — Command palette & shortcuts
- [ ] `CommandPalette` overlay widget in `app/ui/command_palette.py`
  - Floats centred over body; dismissed by Escape or clicking outside
  - `QLineEdit` fuzzy-filters combined list: all registered sub-apps + active sub-app's `get_commands()`
  - Arrow keys navigate; Enter activates
  - Right-aligned shortcut hint per item
- [ ] Global `QShortcut` for Ctrl+K registered on `MainWindow`
- [ ] On sub-app activation: active sub-app's commands registered; previous sub-app's commands removed
- [ ] Global shortcuts from `CommandDef.shortcut` registered/unregistered with activation

### Milestone 1.14 — System tray
- [ ] `SystemTrayIcon` in `app/ui/tray.py`
  - Icon in OS tray; single-click → restore/raise window
  - Right-click menu: Restore, separator, Exit
- [ ] Closing window via ✕ minimises to tray (does not quit); `QApplication.quit()` exits fully
- [ ] When window is hidden: error-level notifications surfaced as OS `showMessage()` tray balloon
- [ ] Tray icon reflects unread notification count (badge overlay on icon) when window hidden

### Milestone 1.15 — Async task helper
- [ ] `AsyncRunner` in `app/core/async_runner.py`
  - `QThreadPool`-based; wraps callable in a `QRunnable`
  - Private `Signal` marshals result/exception back to main thread
  - `run(fn, on_done, on_error)` — non-blocking, returns immediately
- [ ] `BaseSubApp.run_async(fn, on_done, on_error)` delegates to `async_runner`
- [ ] Typical pattern in a sub-app:
  ```python
  def on_activated(self):
      self.state_changed.emit(SubAppState.LOADING)
      self.run_async(self._fetch, self._on_fetched, self._on_error)

  def _on_fetched(self, data):
      self._data = data
      self.state_changed.emit(SubAppState.READY)
  ```

### Milestone 1.16 — Log panel
- [ ] `LogPanel` widget in `app/ui/log_panel.py`
  - Lives in a `QSplitter` (vertical) between the body/sidebar area and the footer
  - Collapsed state: 24 px header strip only — shows label "Logs", unread badge, expand button
  - Expanded state: header strip + scrollable log view; default height 200 px, user-resizable via splitter
  - Toggle: Ctrl+` shortcut on `MainWindow` + click header strip or expand button
  - Splitter position persisted to `app.log_panel_height` in `SettingsStore`
- [ ] Header strip controls: level filter buttons (All / ℹ / ▲ / ✕), auto-scroll toggle, clear button, collapse button
- [ ] Log row format: `HH:MM:SS  LEVEL  logger.name  message`
  - Row colours: INFO=default, WARN=amber text, ERROR=red text + subtle row tint
- [ ] Connects to `log_relay.record_emitted`; applies level filter before appending
- [ ] Unread badge on header strip counts error+warning records received while collapsed; clears on expand
- [ ] Error/warning records optionally forwarded to `notification_bus` (setting: `app.log_notify`, default `False`)
- [ ] Cap display at 1000 rows; oldest trimmed when exceeded (file log is the full record)

---

## Phase 2 — Demo Sub-Apps

### Milestone 2.1 — Counter sub-app
- [ ] `core.py`: `CounterSubApp`
  - State: `count`, `step` (loaded from settings)
  - Methods: `increment()`, `decrement()`, `reset()`
  - Emits `status_changed` with `f"Step: {self.step}"` on step change
  - Settings: `counter.step` with choices `[1, 5, 10]`
- [ ] `ui.py`: `CounterPanel` (− / count label / +), `CounterHeaderWidget` (count badge)
- [ ] Counter value updates header widget and panel in sync

### Milestone 2.2 — Dummy sub-app
- [ ] `core.py`: `DummySubApp` — no settings, no header widget, no status
- [ ] `ui.py`: `DummyPanel` — centred "Hello, World!" label

### Milestone 2.3 — Secret sub-app
- [ ] `core.py`: `SecretSubApp(hidden=True)` — revealed only after easter egg
- [ ] `ui.py`: minimal panel with thematic content

---

## Implementation Order

```
── Foundation ──────────────────────────────────────────────────────
1.1  scaffold + resource_manager + logging
1.8  settings store
1.8a theme manager
1.9  message bus
1.15 async runner          ← needed before any sub-app does real work

── Shell UI ────────────────────────────────────────────────────────
1.2  frameless window + resize
1.3  header bar            ← bell icon wired after 1.10
1.4  sidebar + easter egg
1.12 sub-app lifecycle states (SubAppState + BodyStack overlays)
1.5  body stack + lifecycle overlay
1.6  footer (status_changed signal)
1.16 log panel             ← log_handler ready from 1.1
1.7  registry + activation flow (restore last active, register commands)

── Features ────────────────────────────────────────────────────────
1.10 toasts + notification history
1.13 command palette + shortcuts
1.14 system tray
1.11 settings sub-app (export/import last)

── Demo sub-apps ───────────────────────────────────────────────────
2.2  dummy      — simplest path through registry + lifecycle
2.1  counter    — status_changed, MessageBus, run_async, commands
2.3  secret     — validates easter egg reveal
```

Foundation layer must be complete before any UI milestone starts. Within Shell UI,
1.12 must precede 1.5 (BodyStack depends on SubAppState). Everything else within
a layer can proceed in order.

---

## Non-Goals (out of scope for this plan)

- Packaging / PyInstaller config
- Network or IPC between processes
- Sub-app hot-reloading
