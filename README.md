# S.C.A.F.F.O.L.D.

**S**ome **C**ross-platform **A**pp **F**ramework **F**or **O**rganising **L**oosely-coupled **D**evelopment

A PySide6 / Python 3.14 desktop shell that acts as a host for pluggable sub-apps.
Custom chrome, extensible registry, aggregated settings, toast notifications,
typed message bus, command palette, system tray, in-app log panel, and a Games Hub.

## Requirements

- Python 3.14
- pip (comes with Python)

## Quick start

### 1. Create a virtual environment

```powershell
python -m venv .venv
```

### 2. Activate it

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1

# CMD
.\.venv\Scripts\activate.bat
```

> If PowerShell blocks script execution, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

Dev tools (linter, formatter, test runner, packager) — optional:

```powershell
pip install -r requirements-dev.txt
```

### 4. Run

```powershell
python main.py
```

---

Alternatively, run the one-shot setup script which does steps 1–3 automatically:

```powershell
.\setup.ps1
```

Then activate the venv and run as above.

---

## Dependencies

| File                   | Package          | Purpose                        |
|------------------------|------------------|--------------------------------|
| `requirements.txt`     | PySide6 ≥ 6.7    | Qt bindings (UI framework)     |
| `requirements-dev.txt` | ruff ≥ 0.9       | Linter / formatter             |
|                        | pytest ≥ 8.0     | Test runner                    |
|                        | pytest-qt ≥ 4.4  | Qt widget testing helpers      |
|                        | pyinstaller ≥ 6  | Standalone executable packager |

## Lint / Format

```powershell
python -m ruff check .
python -m ruff format .
```

## Test

```powershell
python -m pytest
```

## Build standalone executable

```powershell
pyinstaller main.py --name scaffold --windowed --onefile
```

Output will be in `dist/`.
