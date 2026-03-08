# CustomTaskManager

CustomTaskManager is a local-first desktop task manager built with Python 3, PySide6, and SQLite. It is designed around a hierarchical task tree, fast keyboard capture, explicit review workflows, and strong data safety features such as snapshots, diagnostics, logging, and migration validation.

Current app version: `v1.0.0`

## Highlights

### Core task management

- Hierarchical task tree with parent/child tasks, drag-and-drop ordering, row gutter action buttons, and persistent collapse state
- Manual ordering plus alternate due-date, priority, and status sort modes without destroying saved manual order
- Multi-selection, bulk edit, archive/restore, permanent delete, and undo/redo with visible history
- Parent progress rollups and automatic parent completion when child progress reaches 100%
- Project intelligence including next-action analysis, stalled/blocked reasoning, and workload summaries

### Fast capture and keyboard workflow

- Quick-add bar with natural parsing for dates and priorities
- Inline capture directives such as tags, buckets, and child/parent targeting
- Lightweight quick-capture dialog and tray/menu-bar capture entry
- Command palette for navigation and actions such as views, templates, backups, diagnostics, and workspace switching
- Platform-aware shortcut labels and behavior for macOS and Windows

### Planning, review, and visibility

- Built-in perspectives: All, Today, Upcoming, Inbox, Someday, and Completed / Archive
- Advanced search syntax and filter dock
- Saved filter views
- Project cockpit for charters, phases, milestones, deliverables, baselines, and structured project registers
- Lightweight project timeline / Gantt-style planning for dated tasks, milestones, and deliverables
- Guided review workflow for overdue, inbox, stalled, waiting, recurring, and archive review
- Focus mode for short actionable work lists
- Calendar / agenda view with due-date activity markers
- Analytics dashboard with completion trends, workload warnings, and scheduling hints
- Relationship inspector for dependencies, dependents, same-tag tasks, and same-project context

### Task details and metadata

- Notes, tags, waiting context, dependencies, recurrence, effort estimates, actual time, and timer support
- Start dates and project phases for timeline-friendly task planning
- Attachments to files and folders
- Local reminders with grouped reminder popups, snoozing, reminder modes, and reminder history flags
- Custom columns with typed editors, including date pickers and editable list values
- Reusable templates with placeholder variables

### Personal project management

- Project charter/definition fields for objective, scope, out-of-scope, owner, stakeholders, target date, success criteria, summary/background, category, and health override
- Default and per-project phases for intake, planning, execution, testing, approval, and closure
- First-class milestones with dependencies, progress, target dates, baseline dates, linked tasks, and completion state
- First-class deliverables with due date, acceptance criteria, version/reference, linked work, and lifecycle status
- Structured risk, issue, assumption, and decision registers
- Baseline target-date and effort tracking with current-versus-baseline variance
- Personal workload summaries by day/week with overcommitment warnings
- Hybrid project health logic combining manual override with inferred signals from blockers, overdue work, inactivity, and scope drift cues

### Safety, diagnostics, and portability

- SQLite schema versioning with migration validation and pre-migration backups
- Backup export/import plus automatic versioned restore-point snapshots
- Snapshot history viewer with safe restore-to-copy and restore-to-workspace flows
- Crash logging and labeled operation logging for troubleshooting
- In-app application log viewer
- Diagnostics panel with integrity checks and repair preview/repair tools
- Theme editor plus theme import/export
- Workspace profiles for multiple databases with separate UI state restoration

### Onboarding and discoverability

- Embedded help system with indexed chapters, search, internal links, and platform-aware shortcut text
- Quick Start / welcome flow
- Optional demo data in the current empty workspace
- Optional separate demo workspace for safe exploration

## Platform Support

- Primary supported desktop targets: macOS and Windows
- Linux development and headless test execution are supported in practice, but packaging is primarily tuned for macOS and Windows

## Screenshots

Screenshots can be added here later. Suggested captures:

- main task tree with details/review/calendar docks
- quick-capture dialog
- command palette
- diagnostics panel
- snapshot history and workspace manager

## Quick Start

### Requirements

- Python 3.11 or newer
- `pip`
- A local virtual environment is recommended

### Clone and install

```bash
git clone <your-repo-url>
cd CustomToDo
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell:

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

The application stores its SQLite database and supporting files in the per-user application data directory managed by Qt. No admin rights are required.

### First launch

On first launch, the app can show a Quick Start dialog that helps you:

- start with an empty database
- load demo data into an empty workspace
- open a separate demo workspace
- open the embedded help
- jump into the review workflow

## Daily Workflow Summary

Typical usage flow:

1. Capture tasks with Quick add, Quick capture, or the command palette
2. Organize tasks in the tree, details panel, and built-in perspectives
3. Review the system with Filters, Saved Views, Focus mode, and Review Workflow
4. Use the Project cockpit for charters, phases, milestones, deliverables, registers, timeline planning, and workload
5. Inspect project health through next-action, stalled, relationship, and analytics views
6. Protect data through snapshots, backups, diagnostics, and the application log

## Data, Safety, and Storage

The app is local-first. Important user data stays in the per-user Qt application data location, including:

- primary SQLite database
- workspace-specific backup snapshots
- migration backups
- crash and operation logs
- persistent settings and themes

Safety features currently included:

- schema validation on open
- migration error reporting
- pre-migration SQLite backup
- integrity diagnostics and repair preview
- automatic restore-point snapshots with rotation
- snapshot restore into a separate database copy or separate workspace
- in-app log viewing for failures and high-risk operations
- defensive validation for project phases, milestones, deliverables, register entries, and dependency references

## Backup and Theme Portability

The app includes both data and theme portability:

- `File > Backup > Export Data…`
- `File > Backup > Import Data…`
- `File > Backup > Export Themes…`
- `File > Backup > Import Themes…`
- `File > Backup > Create snapshot now`
- `View > Application log…`
- `Tools > Snapshot history…`

Exports, snapshots, logs, and restored copies are user files and should generally not be committed to source control.

## Build / Package

The repository includes an interactive PyInstaller helper and a spec file:

```bash
pip install -r requirements-dev.txt
python buildfile.py
```

Notes:

- The build helper expects the virtual environment directory to be named `.venv`
- `CustomTaskManager.spec` is included for PyInstaller-based packaging
- On Windows, the build helper can use an `.ico` app icon
- On macOS, the helper can generate `.icns` assets via `sips` and `iconutil`
- Build assets live under `build_assets/`
- Build outputs are written to `dist/`

## Testing

The repository includes an automated `pytest` suite covering critical application logic, including:

- database creation, migrations, recurrence persistence, integrity checks, and restore-point helpers
- project-management entities, dependency validation, baseline variance, timeline generation, and workload summaries
- tree model behavior, ordering, undo/redo behavior, filtering, and project intelligence logic
- backup import/export and theme import/export
- quick-add parsing, capture parsing, templates, workspace profiles, and demo data generation
- crash logging and diagnostics helpers

Install development dependencies first:

```bash
pip install -r requirements-dev.txt
```

Run the full suite:

```bash
python -m pytest -q
```

Optional validation:

```bash
python -m py_compile *.py tests/*.py
```

For a lightweight headless UI smoke check:

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

The project is larger than a single-window app now. The main groups are:

```text
main.py                   Main window, menus, dock orchestration, startup flow
db.py                     SQLite schema, migrations, diagnostics, and persistence
model.py                  Tree model, business logic, and undo-aware operations
commands.py               QUndoCommand implementations

app_metadata.py           App name/version/profile metadata
app_paths.py              Cross-platform app-data and resource paths
platform_utils.py         OS detection and platform-aware shortcut helpers
crash_logging.py          Crash logging and structured operation logging

backup_io.py              Backup export/import flows
auto_backup.py            Versioned restore-point snapshot creation and rotation
theme.py                  Theme definitions and application
theme_io.py               Theme import/export
diagnostics.py            Diagnostics report generation
demo_data.py              Demo dataset and demo workspace generation

query_parsing.py          Search and quick-add parsing helpers
capture_parsing.py        Capture intent parsing
capture_actions.py        Capture intent execution routing
filter_proxy.py           Tree filtering and perspectives
project_intelligence.py   Next-action, stalled, blocked, and workload analysis
project_management.py     Project-management logic helpers and summary/timeline calculations
workflow_assist.py        Review and workflow acknowledgement helpers
template_params.py        Template placeholder parsing and substitution

calendar_widgets.py       Calendar widgets and agenda helpers
delegates.py              Tree/editor delegates, typed editors, reminder editors
time_picker_ui.py         Reusable radial time picker
columns_ui.py             Custom column dialogs
settings_ui.py            Settings and theme editor
details_panel.py          Details editor dock
filters_ui.py             Filter dock
review_ui.py              Review workflow dock
focus_ui.py               Focus mode dock
analytics_ui.py           Analytics dashboard dock
project_cockpit_ui.py     Project cockpit dock for charters, phases, milestones, deliverables, registers, and timeline
relationships_ui.py       Relationship inspector dock
diagnostics_ui.py         Diagnostics dialog
log_viewer_ui.py          In-app application log viewer
command_palette.py        Command palette dialog
quick_capture_ui.py       Lightweight capture dialog
archive_ui.py             Archive browser / restore dialog
snapshot_history_ui.py    Snapshot history and restore dialog
workspace_profiles.py     Workspace registry and persistence
workspace_ui.py           Workspace manager dialog
welcome_ui.py             Quick Start / onboarding dialog
help_ui.py                Embedded help system
reminders_ui.py           Reminder batch dialog
template_vars_ui.py       Template placeholder prompt

buildfile.py              Interactive PyInstaller build helper
CustomTaskManager.spec    PyInstaller spec
build_assets/             Packaging and build assets
tests/                    Pytest suite
```

## Development Notes

- The codebase is intentionally desktop-first and local-first
- SQLite is used directly rather than through an ORM
- UI behavior is split into focused modules instead of one monolithic window file
- Diagnostics, logging, and snapshots are treated as first-class app features rather than afterthoughts
- Packaging is oriented toward standalone desktop distribution rather than PyPI library packaging
- Global quick-capture hotkey support is optional and depends on `qhotkey` being available in the runtime environment

## License and Disclaimer

This project is licensed under the PolyForm Noncommercial License 1.0.0 with copyright held by **Mervyn van de Kleut**. Commercial resale and other commercial use are not permitted under that license.

Important:

- This repository is **not** released under MIT
- MIT allows commercial use, which conflicts with the stated requirement for this project
- Because commercial use is restricted, this repository is source-available but not open source in the strict OSI-approved sense
- The software is provided at your own risk and without warranty

See [LICENSE.txt](LICENSE.txt) for the full license text and required notice.
