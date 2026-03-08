# Changelog

All notable changes to this project should be documented in this file.

The format is inspired by Keep a Changelog and uses straightforward dated entries.

## [Unreleased]

### Added

- A production-oriented personal project management layer with project charters, phases, milestones, deliverables, structured risk/issue/assumption/decision registers, baselines, dependency validation, and a project cockpit dock
- Lightweight timeline / Gantt-style planning data and workload summaries for local single-user project planning
- Automated tests covering project-management schema migration, CRUD, validation, dashboard summaries, backup round-trips, search integration, and demo data
- A dedicated project-health tree column so project health is visible directly in the main task list
- PM-specific review categories for overdue milestones, deliverables due soon, and high-severity open risks

### Changed

- Demo/sample data now showcases project-management records and timeline-friendly task metadata
- Embedded help and README were updated to document the project cockpit, phase search, milestones, deliverables, baselines, and workload planning
- Project timeline bars can now be dragged horizontally to reschedule task, milestone, and deliverable dates from the cockpit
- Milestone and deliverable timeline drags now participate in undo/redo, and project-cockpit dock defaults were tightened so action buttons stay visible sooner on smaller monitors
- The main workspace layout was refactored so the project cockpit, details panel, relationship inspector, focus mode, analytics, and supporting docks use a more consistent section-based desktop layout with local action rows, bounded data regions, better default dock sizing, and contextual empty states
- Settings, custom-column management, and template-variable dialogs now follow the same section-based layout doctrine so configuration and editor surfaces feel consistent with the main workspace
- Active-task synchronization now keeps the relationship inspector, details panel, focus mode, project cockpit context, and status bar aligned to the same current task, and wheel-sensitive controls no longer change values accidentally while the user is scrolling through the UI

## [1.0.0] - 2026-03-08

### Added

- Production hardening features including crash logging, diagnostics, integrity checks, migration validation, restore-point reporting, centralized app version metadata, and an in-app application log viewer
- Workflow assistance features including a weekly review assistant, focus mode, onboarding/welcome flow, modular demo dataset generation, floating-table support, and expanded embedded help
- Project intelligence features including next-action analysis, stalled/blocked reasoning, workload warnings, scheduling hints, relationship inspection, and stronger project summaries
- Capture and interaction improvements including quick capture, tray integration, richer inline quick-add parsing, platform-aware shortcuts, and reusable capture command routing
- Advanced workspace and history tooling including portable workspace profiles, snapshot history browsing, safe restore-to-copy flows, safe removal flows for templates, workspaces, and snapshots, and workspace-aware backups
- Additional UI modules, a higher-resolution application icon asset for high-DPI packaging, and automated tests covering core database, model, backup/import, diagnostics, filtering, demo generation, workspace behavior, and project logic

### Changed

- Main application workflows, side panels, command/help surfaces, and filtering logic were expanded to expose the new review, focus, diagnostics, relationship, and workspace capabilities
- Repository hygiene, documentation, legal, and CI scaffolding were prepared for public GitHub use and updated to reflect the current app scope
- Pytest-based automated coverage was extended, CI runtime issues were corrected, and local signing artifacts are ignored in Git on the stable branch
- Style-only PEP 8 cleanup applied to selected UI/helper modules with no intended functional changes

## [0.1.0] - 2026-03-07

### Added

- Initial public repository baseline for the current desktop application
- README, contribution guide, security policy, changelog, issue templates, and CI workflow
- Explicit non-commercial license file and repository disclaimer

### Included Application Capabilities

- Hierarchical task management with custom columns, undo/redo, themes, backups, archive/restore, reminders, review workflow, templates, analytics, and calendar tools
