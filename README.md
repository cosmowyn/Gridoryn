# CustomTaskManager

CustomTaskManager is a desktop task manager built with Python 3, PySide6, and SQLite. It focuses on hierarchical task planning, fast capture, local-first data storage, and power-user workflows such as saved views, templates, reminders, and review dashboards.

## Key Features

- Hierarchical task tree with parent/child tasks, drag-and-drop ordering, and row action gutter buttons
- Quick-add input with natural parsing for due dates and priorities
- Advanced search, filter dock, saved views, and built-in perspectives such as Today, Upcoming, Inbox, Someday, and Completed / Archive
- Notes, tags, dependencies, waiting states, recurrence, time tracking, attachments, and reminders in the details panel
- Calendar / agenda view, review workflow, analytics dashboard, undo history, bulk edit, and archive restore browser
- Custom columns with typed editors, including date pickers and editable list values
- Theme editing plus theme import/export
- Backup import/export and automatic versioned snapshots
- PyInstaller packaging helper for Windows and macOS

## Platform Support

- Supported targets: macOS and Windows
- Linux development use should work in principle, but the current packaging helper is primarily tuned for Windows and macOS

## Screenshots

Screenshot documentation can be added here before public release.

## Quick Start

### Prerequisites

- Python 3.11 or newer
- `pip`
- A local virtual environment is recommended

### Clone and set up

```bash
git clone <your-repo-url>
cd CustomToDo
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell activation:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### Run the app

```bash
python main.py
```

The app stores its SQLite database in the per-user application data directory managed by Qt. It does not require admin privileges.

## Build / Package

The repository includes an interactive PyInstaller helper:

```bash
pip install -r requirements-dev.txt
python buildfile.py
```

Notes:

- The build helper expects the virtual environment directory to be named `.venv`
- On Windows, the build helper expects an optional `.ico` icon if you choose to supply one
- On macOS, the helper can convert common image formats into `.icns` using `sips` and `iconutil`
- Non-macOS builds can optionally use a splash image
- Build outputs are written to `dist/`

## Backup and Theme Portability

The app includes both data and theme portability features:

- `File > Backup` for data export/import
- Theme export/import for visual settings
- Automatic versioned snapshots for local safety

Backup exports, theme exports, and automatic snapshots are local user files and are not intended to be committed to the repository.

## Development Notes

- The codebase is intentionally local-first and desktop-first
- SQLite is used directly rather than through an ORM
- UI logic is split across focused `*_ui.py` modules instead of one large widget file
- The current structure favors maintainability over packaging to PyPI

## Testing

The repository includes an automated `pytest` test suite covering critical application logic such as:

- database creation, migrations, integrity checks, and backups
- model behavior, ordering, filtering, and project intelligence logic
- quick-add / capture parsing, templates, workspace profiles, and demo data
- crash logging and related production-hardening helpers

Install development dependencies first:

```bash
pip install -r requirements-dev.txt
```

Run the full suite:

```bash
python -m pytest -q
```

Additional validation steps:

```bash
python -m py_compile *.py
```

For a lightweight UI smoke check on a headless system:

```bash
QT_QPA_PLATFORM=offscreen python - <<'PY'
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from settings_ui import SettingsDialog

app = QApplication([])
dlg = SettingsDialog(QSettings("FocusTools", "CustomTaskManager"))
print("UI smoke ok")
PY
```

## Project Structure

```text
main.py              Main window, menus, docks, application startup
db.py                SQLite schema, migrations, and persistence layer
model.py             Tree model, business logic, and undo-aware operations
commands.py          Undo/redo command objects
*_ui.py              Focused PySide6 dialogs, panels, and docks
theme.py             Theme model and theme application
theme_io.py          Theme import/export
backup_io.py         Backup import/export and restore logic
buildfile.py         Interactive PyInstaller build helper
app_paths.py         Cross-platform resource and app-data path helpers
tests/               Pytest suite for core logic and regression coverage
```

## License and Disclaimer

This project is licensed under the PolyForm Noncommercial License 1.0.0 with copyright held by **Mervyn van de Kleut**. Commercial resale and other commercial use are not permitted under that license.

Important:

- This repository is **not** released under MIT
- MIT allows commercial use, which conflicts with the stated requirement for this project
- Because commercial use is restricted, this repository is source-available but not open source in the strict OSI-approved sense
- The software is provided at your own risk and without warranty

See [LICENSE.txt](LICENSE.txt) for the full license text and required notice.
