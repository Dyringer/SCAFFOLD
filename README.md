# S.C.A.F.F.O.L.D.

**S**ome **C**ross-platform **A**pp **F**ramework **O**f **L**oosely **D**efined decisions

A PySide6 / Python 3.14 desktop shell that acts as a host for pluggable sub-apps.
Custom chrome, extensible registry, aggregated settings, toast notifications,
typed message bus, command palette, system tray, and in-app log panel.

## Requirements

- Python 3.14
- PySide6 6.7+

## Setup

```powershell
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r requirements-dev.txt
```

## Run

```powershell
.venv\Scripts\python main.py
```

## Lint / Format

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
```

## Test

```powershell
.venv\Scripts\python -m pytest
```
