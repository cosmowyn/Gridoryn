from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from app_metadata import APP_NAME
from platform_utils import shortcut_display_text
from ui_layout import polish_button_layouts


def _sc(value: str | QKeySequence.StandardKey) -> str:
    return f"<code>{shortcut_display_text(value)}</code>"


def _help_body_font_css() -> str:
    app = QApplication.instance()
    if app is None:
        return "sans-serif"
    family = str(app.font().family() or "").strip().replace("'", "\\'")
    return f"'{family}'" if family else "sans-serif"


@dataclass
class HelpChapter:
    anchor: str
    title: str
    keywords: list[str]
    body_html: str


HELP_CHAPTERS: list[HelpChapter] = [
    HelpChapter(
        anchor="overview",
        title="Overview",
        keywords=[
            "overview",
            "workflow",
            "tree",
            "details",
            "calendar",
            "review",
            "analytics",
            "command palette",
        ],
        body_html=f"""
        <p><strong>{APP_NAME}</strong> is a hierarchical task manager focused on fast daily execution and clear review workflows.</p>
        <ul>
            <li>The <strong>task tree</strong> remains the central workspace for planning, editing, and reordering work.</li>
            <li><strong>Quick add</strong> captures tasks quickly with natural date and priority parsing.</li>
            <li><strong>Quick capture</strong> provides a lightweight capture window and tray/menu-bar entry for fast inbox capture without working directly in the main tree.</li>
            <li><strong>Search, filters, saved views, and perspectives</strong> let you move between planning contexts quickly.</li>
            <li><strong>Perspective buttons</strong> keep All, Today, Upcoming, Inbox, Someday, and Completed / Archive visible as first-class navigation targets.</li>
            <li><strong>Capture and navigation controls</strong> live in their own dock, so quick add, search, perspective, and sort controls can be shown, hidden, floated, and rearranged separately from the main tree.</li>
            <li><strong>Details, calendar, review, undo history, and analytics docks</strong> add depth without replacing the main tree workflow.</li>
            <li><strong>The task table can be hidden or floated</strong> from the View menu when you want to work only from the side panels or move the table to another monitor.</li>
            <li><strong>Focus mode</strong> provides a low-noise shortlist of overdue, today, and next-action work for the current session.</li>
            <li><strong>Quick Start</strong> offers first-run onboarding, sample data, and fast links into the guide and review workflow.</li>
            <li><strong>Calendar double-click entry</strong> lets you create a dated task directly from the calendar and jump straight into editing.</li>
            <li><strong>Relationship inspector</strong> surfaces dependencies, dependents, same-tag tasks, same-project context, and project health in one place.</li>
            <li><strong>Active task selection stays synchronized</strong> across the main tree, details, relationship inspector, focus mode, project cockpit, and status bar so the current record is always clear.</li>
            <li><strong>Project cockpit</strong> turns top-level work into a local-first project workspace with charters, phases, milestones, deliverables, baselines, workload, and structured risk/issue/assumption/decision registers.</li>
            <li><strong>Major docks now share a consistent workspace layout</strong> with top-aligned sections, local action rows, bounded data regions, and contextual empty states instead of long stacks of detached controls.</li>
            <li><strong>Major panels and dialogs now expose a small contextual help button</strong> in their header area, so you can jump straight to the matching guide chapter without searching manually.</li>
            <li><strong>Section headers stay compact</strong> so current records, controls, and data appear sooner, while longer explanation text lives in tooltips and the embedded guide instead of prime screen space.</li>
            <li><strong>Mouse-wheel protection on editor controls</strong> prevents accidental changes while you are simply scrolling through docks and forms.</li>
            <li><strong>Project health is also visible in the main tree</strong> through a dedicated Health column, so you can scan project status without opening the cockpit.</li>
            <li><strong>Workspace profiles</strong> keep multiple databases explicit and let each workspace restore its own layout and view state.</li>
            <li><strong>Snapshot history</strong> shows restore points with metadata and restores them safely into a new database copy or workspace.</li>
            <li><strong>Template, workspace, and snapshot removal</strong> always asks for explicit confirmation before anything is permanently deleted.</li>
            <li><strong>Templates, recurrence, reminders, tags, attachments, backups, themes, and archive restore</strong> are integrated into the same database-backed workflow.</li>
        </ul>
        <p>Use the tree for immediate work, the details panel for deeper metadata, the command palette for fast keyboard actions, the review workflow for weekly cleanup, and analytics for lightweight trust-building metrics.</p>
        """,
    ),
    HelpChapter(
        anchor="task-tree",
        title="Task Tree Basics",
        keywords=[
            "tree",
            "parent",
            "child",
            "gutter",
            "manual order",
            "progress",
            "multi-select",
            "nesting",
        ],
        body_html="""
        <p>The tree is the main task editor.</p>
        <ul>
            <li><strong>Add task</strong> creates a top-level task.</li>
            <li><strong>Add child task</strong> creates a nested task under the selected row.</li>
            <li><strong>Category folders</strong> let you group top-level tasks and projects without turning the group itself into a task.</li>
            <li><strong>Subcategories</strong> can be nested up to <strong>10 levels</strong>, with their own color, icon, and identifier set from the context menu.</li>
            <li><strong>Right-click empty tree space or a folder row</strong> to add or customize category folders. Right-click a top-level task to move it into a category or clear its category assignment.</li>
            <li><strong>Row gutter buttons</strong> stay visible to the left of the tree:
                <ul>
                    <li><code>+</code> adds a child to the focused row</li>
                    <li><code>-</code> archives the focused row</li>
                </ul>
            </li>
            <li><strong>Manual order mode</strong> supports drag/drop reordering while preserving hierarchy.</li>
            <li><strong>Alternative sort modes</strong> show due-date, priority, or status order without destroying the saved manual order.</li>
            <li><strong>Multi-selection</strong> supports bulk changes, archive, and delete workflows.</li>
            <li><strong>Parent progress</strong> rolls child completion up as done/total and percentage.</li>
            <li>When a parent reaches <strong>100% child completion</strong>, it is automatically marked <strong>Done</strong>.</li>
            <li>Nested hierarchy depth is limited to <strong>10 levels</strong> per task chain to prevent runaway indentation.</li>
            <li>The <strong>View &gt; Task table</strong> toggle hides the center tree while keeping the rest of the app active.</li>
            <li>The <strong>View &gt; Capture/navigation panel</strong> toggle controls the dock that contains quick add, search, perspective, and sort controls.</li>
            <li>The <strong>Details panel task browser</strong> lets you move to the previous/next parent, walk tasks inside the current parent, and jump directly to any visible top-level parent from a dropdown.</li>
            <li><strong>View &gt; Float task table</strong> detaches the tree into a separate window and keeps the rest of the docks in the main workspace.</li>
        </ul>
        <p>If drag/drop or manual movement is unavailable, check whether a filter or non-manual sort mode is active.</p>
        """,
    ),
    HelpChapter(
        anchor="quick-add",
        title="Quick Add Syntax",
        keywords=[
            "quick add",
            "quick capture",
            "natural language",
            "@work",
            "#urgent",
            "!p1",
            "/today",
            "/inbox",
            "+child",
            ">parent",
            "move this",
            "postpone overdue",
            "show blocked",
            "create weekly review",
            "today",
            "tomorrow",
            "tonight",
            "day after tomorrow",
            "next monday",
            "this monday",
            "next week",
            "next month",
            "next year",
            "in 3 days",
            "weekday",
            "p1",
            "high",
            "medium",
            "low",
        ],
        body_html="""
        <p>The Quick add bar is designed for rapid capture. Type one line, press Enter, and keep going.</p>
        <p><strong>Recognized due-date patterns</strong>:</p>
        <ul>
            <li>Natural words: <code>today</code>, <code>tonight</code>, <code>tomorrow</code>, <code>day after tomorrow</code></li>
            <li>Relative weekdays: <code>monday</code>, <code>friday</code>, <code>this monday</code>, <code>next monday</code></li>
            <li>Relative periods: <code>next week</code>, <code>next month</code>, <code>next year</code></li>
            <li>Offsets: <code>in 3 days</code>, <code>in 2 weeks</code>, <code>in 1 month</code>, <code>in 1 year</code></li>
            <li>Explicit dates: <code>2026-03-12</code> and <code>12-Mar-2026</code></li>
        </ul>
        <p><strong>Recognized priority patterns</strong>:</p>
        <ul>
            <li><code>p1</code> to <code>p5</code></li>
            <li><code>!p1</code> to <code>!p5</code></li>
            <li><code>high</code>, <code>medium</code>, <code>low</code></li>
        </ul>
        <p><strong>Inline capture directives</strong>:</p>
        <ul>
            <li><code>@work</code> and <code>#urgent</code> add tags</li>
            <li><code>/inbox</code>, <code>/today</code>, <code>/upcoming</code>, <code>/someday</code> set the planning bucket</li>
            <li><code>+child</code> creates the task as a child of the current selection when one exists</li>
            <li><code>&gt;parent</code>, <code>&gt;selected</code>, or <code>&gt;123</code> route capture under a matching parent task when possible</li>
        </ul>
        <p><strong>Command-style planning phrases</strong>:</p>
        <ul>
            <li><code>move this to next friday</code></li>
            <li><code>postpone all overdue work tasks by 2 days</code></li>
            <li><code>create weekly review every friday at 16:00</code></li>
            <li><code>show blocked tasks</code></li>
        </ul>
        <p><strong>Examples</strong>:</p>
        <ul>
            <li><code>Call supplier tomorrow p1</code></li>
            <li><code>Weekly sync @ops !p2 /today</code></li>
            <li><code>Draft proposal +child next week</code></li>
            <li><code>Finish report 12-Mar-2026 high</code></li>
            <li><code>Review budget next monday</code></li>
            <li><code>Book venue in 2 weeks low</code></li>
            <li><code>Draft roadmap next month medium</code></li>
        </ul>
        <p>If parsing fails, the raw text still becomes the task description so capture never blocks on syntax.</p>
        """,
    ),
    HelpChapter(
        anchor="search",
        title="Search and Filter Syntax",
        keywords=[
            "search",
            "filter",
            "saved views",
            "status",
            "priority",
            "due",
            "tag",
            "bucket",
            "due:none",
            "has:children",
            "blocked",
            "waiting",
            "recurring",
        ],
        body_html="""
        <p>The search bar supports free text and structured operators in the same query.</p>
        <p><strong>Supported operators</strong>:</p>
        <ul>
            <li><code>status:todo</code>, <code>status:in progress</code>, <code>status:blocked</code>, <code>status:done</code></li>
            <li><code>priority:1</code></li>
            <li><code>due&lt;today</code>, <code>due&lt;=2026-03-12</code>, <code>due&gt;=12-Mar-2026</code></li>
            <li><code>due:none</code></li>
            <li><code>tag:work</code></li>
            <li><code>bucket:inbox</code>, <code>bucket:today</code>, <code>bucket:upcoming</code>, <code>bucket:someday</code></li>
            <li><code>phase:planning</code>, <code>phase:approval</code></li>
            <li><code>has:children</code>, <code>has:nochildren</code></li>
            <li><code>blocked:true</code> or <code>is:blocked</code></li>
            <li><code>waiting:true</code> or <code>is:waiting</code></li>
            <li><code>recurring:true</code> or <code>is:recurring</code></li>
        </ul>
        <p>Free text remains active and is combined with the operators above. The Filters dock can then narrow results further by status, priority range, due-date filters, tags, hide-done, overdue-only, blocked-only, and waiting-only settings.</p>
        <p>Saved filter views store the current filter/search state so you can return to frequently used working contexts with one action or one command-palette search.</p>
        """,
    ),
    HelpChapter(
        anchor="command-palette",
        title="Command Palette",
        keywords=[
            "command palette",
            "ctrl+shift+p",
            "cmd+shift+p",
            "command+shift+p",
            "commands",
            "keyboard-first",
            "saved view",
            "template",
            "backup",
            "theme",
            "workspace",
            "snapshot",
            "relationships",
        ],
        body_html=f"""
        <p>Open the command palette with {_sc("Ctrl+Shift+P")} to run actions without leaving the keyboard.</p>
        <ul>
            <li>Type part of a command title, alias, or keyword to filter the list.</li>
            <li>Press <strong>Enter</strong> to run the selected command.</li>
            <li>Commands include quick capture, add task, add child, duplicate, archive, delete, open details, open focus mode, open diagnostics, open the relationship inspector, change status, change priority, apply saved views, go to perspectives such as <strong>Go to Inbox</strong>, insert templates, open workspace profiles, open snapshot history, open quick-start help, focus search or quick add, and open backup/theme import-export actions.</li>
            <li>The command list is extensible and includes dynamic entries such as saved views and saved templates.</li>
        </ul>
        <p>Use the palette when you know what you want to do but do not want to hunt through menus.</p>
        """,
    ),
    HelpChapter(
        anchor="views",
        title="Perspectives, Saved Views, and Sort Modes",
        keywords=[
            "today",
            "upcoming",
            "inbox",
            "someday",
            "completed",
            "archive",
            "saved view",
            "sort",
        ],
        body_html="""
        <p><strong>Built-in perspectives</strong> change the planning lens without changing the underlying data:</p>
        <ul>
            <li><strong>All</strong>: active non-archived tasks.</li>
            <li><strong>Today</strong>: tasks due today or bucketed into Today.</li>
            <li><strong>Upcoming</strong>: future-due tasks and Upcoming-bucket items.</li>
            <li><strong>Inbox</strong>: unprocessed tasks not yet planned.</li>
            <li><strong>Someday</strong>: deferred or non-active planned items.</li>
            <li><strong>Completed / Archive</strong>: done and archived content for cleanup or restoration.</li>
        </ul>
        <p>The top navigation area includes a dedicated <strong>perspective button bar</strong> so the active perspective is always visible and highlighted.</p>
        <p>Major view headers include a contextual <strong>?</strong> button that jumps directly to the matching help chapter for the current surface.</p>
        <p><strong>Saved views</strong> persist the current search text and filter state so you can reload a named working context later.</p>
        <p><strong>Sort modes</strong>:</p>
        <ul>
            <li><strong>Manual order</strong> keeps drag/drop ordering persistent.</li>
            <li><strong>Due date</strong>, <strong>Priority</strong>, and <strong>Status</strong> provide temporary analytical sorting without overwriting the manual order data.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="details",
        title="Details Panel",
        keywords=[
            "details",
            "notes",
            "tags",
            "bucket",
            "dependencies",
            "waiting",
            "recurrence",
            "effort",
            "timer",
            "reminder",
            "attachments",
            "project summary",
        ],
        body_html="""
        <p>The Details panel follows the current selection and is the main place to edit task metadata beyond the visible tree columns.</p>
        <ul>
            <li><strong>Notes</strong>: long-form text with scrollbars for larger content.</li>
            <li><strong>Tags</strong>: lightweight labels stored in normalized tables for filtering and search.</li>
            <li><strong>Bucket</strong>: Inbox, Today, Upcoming, or Someday planning classification.</li>
            <li><strong>Waiting</strong>: free-form waiting context such as a person, handoff, or external dependency note.</li>
            <li><strong>Blocked by IDs</strong>: task IDs that must complete before this task becomes actionable.</li>
            <li><strong>Recurrence</strong>: frequency plus "create next occurrence when done".</li>
            <li><strong>Estimated and actual minutes</strong>: lightweight effort planning and time tracking.</li>
            <li><strong>Reminder controls</strong>: direct reminder timestamp, due-date-based reminder, or clear reminder.</li>
            <li><strong>Attachments</strong>: attach files or folders, open them, and remove links.</li>
        </ul>
        <p>The summary label at the top also shows status, priority, child progress, recurrence state, and project intelligence such as next action, blocked state, or stalled state when relevant.</p>
        """,
    ),
    HelpChapter(
        anchor="custom-columns",
        title="Custom Columns and Cell Editors",
        keywords=[
            "custom column",
            "columns",
            "date column",
            "list column",
            "calendar picker",
            "radial time picker",
            "clock dial",
            "clear date",
            "list values",
        ],
        body_html="""
        <p>Use the <strong>Columns</strong> menu to add, remove, show, or hide task columns.</p>
        <p><strong>Supported custom column types</strong>:</p>
        <ul>
            <li><strong>text</strong>: free-form text</li>
            <li><strong>int</strong>: numeric editor</li>
            <li><strong>date</strong>: calendar date picker with clear button</li>
            <li><strong>bool</strong>: Yes/No selector</li>
            <li><strong>list</strong>: editable combo list with reusable values</li>
        </ul>
        <p><strong>Date and datetime editors</strong>:</p>
        <ul>
            <li>If a cell already has a value, the popup opens on that stored date.</li>
            <li>If a cell is empty, the popup defaults to <strong>today</strong> instead of a legacy zero date.</li>
            <li>The clear button removes the stored value completely.</li>
            <li>The default <strong>Reminder</strong> datetime column uses a calendar for the date and a reusable <strong>radial clock dial</strong> for the time.</li>
            <li>The radial dial supports click-to-jump, continuous wraparound, and alternating hour/minute selection for quick time entry.</li>
        </ul>
        <p><strong>List columns</strong>:</p>
        <ul>
            <li>Seed values can be defined when the column is created.</li>
            <li>Cells show a dropdown but remain editable.</li>
            <li>If you type a new value that is not already in the list, it is accepted and appended to that column's reusable values.</li>
        </ul>
        <p>The default task table also includes an optional <strong>Reminder</strong> datetime column for direct scheduling from the tree.</p>
        """,
    ),
    HelpChapter(
        anchor="review",
        title="Review Workflow",
        keywords=[
            "review",
            "weekly review",
            "overdue",
            "stalled",
            "waiting older",
            "archive roots",
            "cleanup",
        ],
        body_html="""
        <p>The Review Workflow dock is a guided maintenance workspace rather than just another filter.</p>
        <p><strong>Built-in review categories</strong>:</p>
        <ul>
            <li>Overdue</li>
            <li>Overdue Milestones</li>
            <li>Deliverables Due Soon</li>
            <li>High-Severity Risks</li>
            <li>No Due Date</li>
            <li>Inbox Unprocessed</li>
            <li>Stalled Projects</li>
            <li>Projects: No Next Action</li>
            <li>Projects: Blocked</li>
            <li>Waiting Older</li>
            <li>Recurring Attention</li>
            <li>Recent Done/Archived</li>
            <li>Archive Roots</li>
        </ul>
        <p><strong>Workflow controls</strong>:</p>
        <ul>
            <li>Adjust thresholds for waiting age, stalled threshold, and recent window.</li>
            <li>Double-click a row to focus it in the main tree.</li>
            <li>Use the action buttons to focus, use the category in the main tree, acknowledge handled items, mark done, archive, or restore directly from the review dock.</li>
            <li>PM-specific categories such as milestones, deliverables, and risks still support focus and acknowledgement, but destructive task actions are disabled when they would be misleading.</li>
            <li>Acknowledged items are hidden from the current review category until you clear the handled state, which keeps repeat review sessions shorter and less noisy.</li>
        </ul>
        <p>This dock is intended for weekly review, daily cleanup, and restoring trust in the system when your task list gets noisy.</p>
        """,
    ),
    HelpChapter(
        anchor="focus-mode",
        title="Focus Mode",
        keywords=["focus", "focus mode", "today", "next action", "overdue", "blocked", "waiting"],
        body_html="""
        <p>Focus mode is a lightweight shortlist for doing work, not a replacement for the main tree.</p>
        <ul>
            <li>It surfaces <strong>overdue</strong> work, <strong>today</strong> work, and <strong>next actionable tasks</strong> from active projects.</li>
            <li>The top summary mirrors the current selection so you can keep context while scanning the focus shortlist.</li>
            <li>The action row is attached directly to the focus list, so refresh, focus, detail access, and exit controls remain visible beside the data they affect.</li>
            <li>Enable <strong>Include blocked/waiting context</strong> when you want due-today dependencies or waiting items visible during planning.</li>
            <li>Double-click a focus item to jump back to it in the main tree.</li>
            <li>Use <strong>Open details</strong> when you need notes, reminders, dependencies, or attachments while staying in a focused session.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="onboarding",
        title="Quick Start and Onboarding",
        keywords=["welcome", "quick start", "onboarding", "sample data", "first run"],
        body_html="""
        <p>The Quick Start dialog appears automatically for a new empty task list and is always available from the Help menu.</p>
        <ul>
            <li>It highlights the quickest ways to start: Quick add, Search, Command palette, and Review Workflow.</li>
            <li>You can <strong>start empty</strong>, <strong>load a full showcase demo</strong>, <strong>open help</strong>, or <strong>jump straight into review mode</strong>.</li>
            <li>The demo workspace now includes dense project timelines, milestones, deliverables, risk registers, reminders, recurrence, custom columns, attachments, templates, archive data, and saved views so you can tour the whole app immediately.</li>
            <li>The automatic first-run display is skipped for existing users with real task data, so upgrades do not become intrusive.</li>
            <li>You can disable automatic onboarding and reopen it later manually whenever needed.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="projects",
        title="Projects and Next Actions",
        keywords=[
            "project",
            "project cockpit",
            "charter",
            "milestone",
            "deliverable",
            "baseline",
            "phase",
            "risk",
            "issue",
            "assumption",
            "decision",
            "timeline",
            "gantt",
            "next action",
            "blocked",
            "stalled",
            "child progress",
            "parent",
        ],
        body_html=f"""
        <p>The <strong>Project cockpit</strong> dock turns a selected top-level task into a structured personal project workspace without leaving the local task database.</p>
        <ul>
            <li>The cockpit is laid out as a compact desktop workspace: <strong>project selection</strong> at the top, a persistent <strong>project summary header</strong> below it, then tab-local work surfaces underneath.</li>
            <li>Each cockpit tab keeps <strong>actions attached to its own table or view</strong>, so milestone, deliverable, register, timeline, and workload actions do not get pushed to the bottom of the whole panel.</li>
            <li>Empty tabs now show <strong>contextual empty states</strong> instead of leaving large blank areas.</li>
            <li><strong>Project definition</strong> stores objective, scope, out-of-scope items, owner, stakeholders, target date, success criteria, summary/background, category, and health override.</li>
            <li><strong>Category folders also appear in the cockpit</strong> so you can filter the project list by folder and manage folders from the category selector's context menu.</li>
            <li><strong>Phases</strong> provide a default project lifecycle and can be extended or renamed per project.</li>
            <li><strong>Tasks can be assigned to phases</strong> from the details panel, which improves filtering and timeline clarity.</li>
            <li><strong>Milestones</strong> are first-class records with title, description, target date, baseline date, completion state, linked task, phase, and dependency handling.</li>
            <li><strong>Deliverables</strong> stay distinct from generic tasks and track due date, acceptance criteria, linked work, and version/reference text.</li>
            <li><strong>Structured registers</strong> store risks, issues, assumptions, and decisions as separate records instead of free-form notes.</li>
            <li><strong>Baseline tracking</strong> compares current target dates and effort against the saved baseline so slippage is visible.</li>
            <li><strong>Timeline</strong> now behaves like a serious interactive planner with a hierarchy tree on the left and a zoomable time canvas on the right.</li>
            <li><strong>Tasks, milestones, and deliverables can be dragged horizontally</strong> to move scheduled work directly from the chart.</li>
            <li><strong>Task bars can be resized from the left and right edges</strong> to adjust start and due dates with day-based snapping.</li>
            <li><strong>Double-click empty timeline space to add a new task at that date</strong>. The new bar is selected immediately so you can drag or resize it without leaving the chart.</li>
            <li><strong>Milestones use a dedicated diamond marker</strong>, while summary rows roll up child spans and use a distinct parent-bar style so hierarchy stays legible without relying on large inline bar labels.</li>
            <li><strong>The timeline includes Today, Selected, Fit project, and Fit selection controls</strong>, along with Day, Week, and Month zoom levels.</li>
            <li><strong>{_sc("Ctrl")} + mouse wheel zooms the chart</strong> and supported trackpad pinch gestures use the same zoom state. The left/right arrow keys nudge the selected item by day. Use <code>Alt+Left/Right</code> to resize task starts and <code>Shift+Left/Right</code> to resize task ends.</li>
            <li><strong>Right-click the chart for contextual planning actions</strong> such as adding tasks, child tasks, milestones, deliverables, dependency editing, row movement, per-item color overrides, archive, permanent delete, and view navigation.</li>
            <li><strong>Timeline selection stays synchronized</strong> with the project cockpit tables, task tree, details panel, and relationship inspector.</li>
            <li><strong>Task and project rows can be archived or permanently deleted from the cockpit</strong>, so items created from the planner can also be cleaned up there without returning to the main task tree.</li>
            <li><strong>Timeline rescheduling participates in undo/redo</strong>, including milestone and deliverable date moves.</li>
            <li><strong>Settings &amp; Themes includes dedicated Gantt bar colors</strong> for ordinary task bars and parent/summary bars, and you can override individual chart items locally from the timeline context menu for project-specific visual planning.</li>
            <li><strong>Workload</strong> summarizes planned effort by day and week to highlight overcommitment for a single local user.</li>
            <li><strong>Health</strong> can be overridden manually, but the app also infers risk from overdue work, blockers, inactivity, and scope-related register entries.</li>
            <li><strong>The main task tree now includes a compact Health column</strong> so project risk is visible even when the cockpit is closed.</li>
            <li>The app evaluates active children to find the <strong>next actionable child</strong>.</li>
            <li>A project can be marked as <strong>blocked</strong> when the remaining open children are waiting or dependency-blocked.</li>
            <li>A project can be marked as <strong>stalled</strong> when it has gone too long without useful forward movement.</li>
            <li>A project can be flagged as having <strong>no next action</strong> when it still has open work but nothing clearly actionable.</li>
            <li>Child completion rolls up to the parent progress column and summary metadata.</li>
        </ul>
        <p>These signals are surfaced in the details summary, the relationship inspector, the review workflow, and the project cockpit, but they do not remove manual control over task structure or status.</p>
        """,
    ),
    HelpChapter(
        anchor="relationships",
        title="Relationships and Project Context",
        keywords=[
            "relationships",
            "dependency",
            "dependents",
            "same tag",
            "same project",
            "inspector",
            "blocked",
            "project path",
        ],
        body_html="""
        <p>The <strong>Relationship inspector</strong> dock adds context around the selected task without replacing the main tree.</p>
        <ul>
            <li>Relationships are grouped into <strong>Dependencies</strong>, <strong>Structure</strong>, and <strong>Context</strong> tabs so the inspector stays readable on normal desktop sizes.</li>
            <li>The inspector updates immediately when the active task changes in the main tree, details browser, focus mode, or project cockpit.</li>
            <li><strong>Depends on</strong> shows the tasks that currently block the selected task.</li>
            <li><strong>Blocking</strong> shows tasks that depend on the current task.</li>
            <li><strong>Children</strong>, <strong>Siblings</strong>, and <strong>Same project</strong> reveal nearby work inside the same project structure.</li>
            <li><strong>Same tags</strong> and <strong>Same waiting context</strong> help you cluster similar work or follow up on external dependencies.</li>
            <li>The summary area highlights project state, next action, stalled reason, and same-day workload pressure when relevant.</li>
        </ul>
        <p>Double-click any related task in the inspector, or use the Focus button, to move the global selection back to that task in the main tree and refresh the rest of the UI around it.</p>
        """,
    ),
    HelpChapter(
        anchor="workspaces",
        title="Workspace Profiles and Snapshot History",
        keywords=[
            "workspace",
            "profile",
            "database",
            "snapshot",
            "history",
            "restore point",
            "restore",
            "switch workspace",
        ],
        body_html="""
        <p><strong>Workspace profiles</strong> let you keep separate databases explicit, for example Work, Personal, or project-specific task sets.</p>
        <ul>
            <li>Open <strong>File &gt; Workspace profiles</strong> or the command palette to create a workspace, register an existing database, and switch safely.</li>
            <li>Each workspace keeps its own current layout, perspective, column visibility, and related UI state.</li>
            <li>The current workspace name and database path are visible in the main window status bar.</li>
            <li>Removing a workspace always requires confirmation. The active workspace cannot be removed, and the app keeps at least one workspace database available at all times.</li>
            <li>Database-file deletion is only offered when that SQLite file is not shared by another workspace and is not currently in use.</li>
        </ul>
        <p><strong>Snapshot history</strong> builds on the existing restore-point system.</p>
        <ul>
            <li>It lists snapshot timestamp, reason, task counts, archived counts, size, and file name.</li>
            <li>Restores are always safe-copy restores: either into a new database file or into a newly created workspace.</li>
            <li>The current live database is not overwritten in place from the snapshot-history dialog.</li>
            <li>Snapshots can also be permanently removed from the history dialog after a confirmation prompt.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="recurrence",
        title="Recurring Tasks",
        keywords=["recurrence", "daily", "weekly", "monthly", "yearly", "next occurrence"],
        body_html="""
        <p>Recurrence is rule-based and stored separately from generated task instances.</p>
        <ul>
            <li>Frequencies: <strong>daily</strong>, <strong>weekly</strong>, <strong>monthly</strong>, and <strong>yearly</strong>.</li>
            <li>Enable <strong>create next occurrence when done</strong> to generate the next task after completion.</li>
            <li>Generated tasks remain editable without corrupting the source recurrence rule.</li>
            <li>Review mode includes a recurring-attention category for recurrence items that deserve inspection.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="templates",
        title="Templates and Placeholders",
        keywords=[
            "template",
            "placeholders",
            "parameterized templates",
            "project_name",
            "due_date",
            "insert template",
        ],
        body_html="""
        <p>Templates let you save a selected task subtree and recreate it later.</p>
        <ul>
            <li><strong>Save selected as template</strong> stores the current task plus its descendants.</li>
            <li><strong>Create from template</strong> inserts the saved structure under the current selection or at top level.</li>
            <li><strong>Delete template</strong> asks for confirmation before the saved template is permanently removed.</li>
            <li>Templates preserve hierarchy, notes, tags, custom-column values, attachments, and dependency structure where possible.</li>
            <li>If the selected task is a project root, the saved template also includes its project profile, phases, milestones, deliverables, register entries, baseline, and internal task-to-project links.</li>
            <li>If you save a subtree inside a project rather than the project root, it remains a normal task template and does not pull unrelated project state into the template.</li>
        </ul>
        <p><strong>Parameterized templates</strong> support placeholders such as <code>{project_name}</code>, <code>{due_date}</code>, <code>{owner}</code>, and <code>{location}</code>.</p>
        <ul>
            <li>When placeholders are detected, the app opens a value-entry dialog before insertion.</li>
            <li>Placeholder replacement is applied throughout the saved payload so the inserted tasks are ordinary editable tasks after creation.</li>
            <li>Fields containing <code>date</code> in the placeholder name are prefilled with today's ISO date to speed up template instantiation.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="reminders",
        title="Reminders and Notifications",
        keywords=[
            "reminder",
            "notification",
            "snooze",
            "mute",
            "priority 1",
            "reminder column",
            "grouped popup",
            "clock dial",
            "time picker",
        ],
        body_html="""
        <p>Reminders are local, persistent, and optional.</p>
        <ul>
            <li>Set a reminder directly from the Details panel or by editing the <strong>Reminder</strong> datetime column in the tree.</li>
            <li>Create reminders at an exact date/time or derive them from the due date using a minutes-before offset.</li>
            <li>The tree reminder editor uses a <strong>radial clock-style time picker</strong> with a 24-hour display label and accept/cancel workflow.</li>
            <li>Reminder popups are <strong>grouped and sorted</strong> so multiple due items appear in a single dialog rather than separate spammy windows.</li>
            <li>Accepted reminders are marked as fired and do not come back unless rescheduled.</li>
            <li>Snoozing lets you choose a new date/time for the whole shown batch.</li>
        </ul>
        <p><strong>Reminder modes</strong> are available from the View menu:</p>
        <ul>
            <li><strong>Reminders on</strong>: show all due reminders</li>
            <li><strong>Mute all reminders</strong>: suppress all reminder popups</li>
            <li><strong>Only priority 1 reminders</strong>: show only the most urgent reminder items</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="archive",
        title="Archive, Restore, Delete",
        keywords=["archive", "restore", "archive browser", "delete", "completed", "safety"],
        body_html="""
        <p>The app treats <strong>archive</strong> as the safe default instead of hard delete.</p>
        <ul>
            <li>Archiving removes tasks from normal active views while preserving the full subtree.</li>
            <li><strong>Restore from archive</strong> restores archived selections when they are already visible.</li>
            <li><strong>Browse archive</strong> opens a dedicated archive browser where you can search archived roots and choose exactly what to restore.</li>
            <li>The review workflow and Completed / Archive perspective make historical cleanup easier.</li>
            <li><strong>Delete permanently</strong> is explicit and remains a separate destructive action.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="bulk",
        title="Bulk Edit",
        keywords=["bulk", "multi-select", "status", "priority", "due", "tags", "archive", "delete"],
        body_html="""
        <p>Select multiple rows in the tree and run <strong>Bulk edit</strong> for one-step batch changes.</p>
        <p>Available operations include:</p>
        <ul>
            <li>Set status</li>
            <li>Set priority</li>
            <li>Shift due dates by day offset</li>
            <li>Set or clear due date</li>
            <li>Add or remove tags</li>
            <li>Archive selected tasks</li>
            <li>Permanently delete selected tasks</li>
        </ul>
        <p>Bulk edit is useful for triage, cleanup, and review sessions without manually opening each task.</p>
        """,
    ),
    HelpChapter(
        anchor="calendar",
        title="Calendar / Agenda",
        keywords=[
            "calendar",
            "agenda",
            "week numbers",
            "markers",
            "due date",
            "day list",
            "double click date",
            "add task from calendar",
        ],
        body_html="""
        <p>The Calendar / Agenda dock provides a date-oriented view of scheduled work.</p>
        <ul>
            <li>The monthly calendar shows <strong>ISO week numbers</strong>.</li>
            <li>Dates with tasks receive a <strong>completion-colored background</strong> so scheduled work is visible before you click a day.</li>
            <li>Marker color follows completion state:
                <ul>
                    <li>red for low completion</li>
                    <li>orange for mid completion</li>
                    <li>green for high or completed work</li>
                </ul>
            </li>
            <li>Select a date to populate the agenda list with tasks due on that day.</li>
            <li><strong>Double-click a date</strong> in the calendar to create a new top-level task with that due date and immediately start editing its description in the tree.</li>
            <li>Activate an agenda item to jump focus back to the corresponding task in the tree.</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="analytics",
        title="Analytics Dashboard",
        keywords=[
            "analytics",
            "dashboard",
            "completed today",
            "trend",
            "top tags",
            "active vs archived",
        ],
        body_html="""
        <p>The Analytics dock gives a lightweight summary of system health and execution trends.</p>
        <ul>
            <li>The layout uses a <strong>compact summary strip plus split list panels</strong>, so metrics, trends, warnings, and hints stay visible without wasting large areas of dock space.</li>
            <li><strong>Completed today</strong> and <strong>completed this week</strong> summarize throughput.</li>
            <li><strong>Overdue open</strong>, <strong>open with no due date</strong>, and <strong>Inbox unprocessed</strong> highlight planning debt.</li>
            <li><strong>Active open / Archived</strong> helps estimate whether the system is being trimmed or allowed to bloat.</li>
            <li><strong>Projects stalled/blocked/no-next</strong> shows the project-health counts used by review workflows.</li>
            <li>The trend list shows recent daily completion counts.</li>
            <li>The tags list shows the most active tags among recent completed tasks.</li>
        </ul>
        <p>The dashboard is intended to be quick to read, not a heavy BI tool.</p>
        """,
    ),
    HelpChapter(
        anchor="backup",
        title="Backup, Import/Export, and Safety",
        keywords=[
            "backup",
            "import",
            "export",
            "snapshot",
            "rotation",
            "theme",
            "integrity",
            "workspace",
            "history",
        ],
        body_html="""
        <p>Backup features are designed for safety and portability.</p>
        <ul>
            <li>Manual data export and import are available from <strong>File &gt; Backup</strong>.</li>
            <li>Theme export and import are stored separately so UI styling can travel without forcing data replacement.</li>
            <li>Automatic versioned snapshots support retention rotation and can also be triggered manually with <strong>Create snapshot now</strong>.</li>
            <li>Snapshots are stored per workspace/database location so restore points stay aligned with the data they belong to.</li>
            <li><strong>Snapshot history</strong> exposes restore points as a readable timeline and restores them only into new copies or new workspaces.</li>
            <li>Import validates stored integrity data and warns if the backup appears inconsistent.</li>
            <li>Schema migrations are additive and versioned to preserve existing user data.</li>
        </ul>
        <p>Most of these actions are also reachable through the command palette.</p>
        """,
    ),
    HelpChapter(
        anchor="shortcuts",
        title="Keyboard Shortcuts",
        keywords=["shortcuts", "keyboard", "hotkeys", "enter", "space", "ctrl", "cmd", "command", "option", "f1"],
        body_html=f"""
        <p><strong>General</strong></p>
        <ul>
            <li>{_sc("Ctrl+N")} Add task</li>
            <li>{_sc("Ctrl+Shift+N")} Add child task</li>
            <li>{_sc("Ctrl+F")} Focus search</li>
            <li>{_sc("Ctrl+L")} Focus quick add</li>
            <li>{_sc("Ctrl+Alt+Space")} Open quick capture</li>
            <li>{_sc("Ctrl+Shift+P")} Open command palette</li>
            <li><code>F1</code> Open the embedded help guide</li>
            <li>{_sc(QKeySequence.StandardKey.Undo)} Undo (platform standard)</li>
            <li>{_sc(QKeySequence.StandardKey.Redo)} Redo (platform standard)</li>
        </ul>
        <p><strong>View focus</strong></p>
        <ul>
            <li>{_sc("Ctrl+1")} Focus task workspace</li>
            <li>{_sc("Ctrl+2")} Focus details panel</li>
            <li>{_sc("Ctrl+3")} Focus filters panel</li>
            <li>{_sc("Ctrl+4")} Focus project cockpit</li>
            <li>{_sc("Ctrl+5")} Focus relationship inspector</li>
            <li>{_sc("Ctrl+6")} Focus focus mode</li>
            <li>{_sc("Ctrl+7")} Focus review workflow</li>
            <li>{_sc("Ctrl+8")} Focus calendar / agenda</li>
            <li>{_sc("Ctrl+9")} Focus analytics</li>
            <li>{_sc("Ctrl+0")} Focus undo history</li>
        </ul>
        <p><strong>View toggles and tools</strong></p>
        <ul>
            <li>{_sc("Ctrl+Alt+C")} Toggle capture/navigation panel</li>
            <li>{_sc("Ctrl+Alt+1")} Toggle task table</li>
            <li>{_sc("Ctrl+Alt+2")} Toggle details panel</li>
            <li>{_sc("Ctrl+Alt+3")} Toggle filters panel</li>
            <li>{_sc("Ctrl+Alt+4")} Toggle project cockpit</li>
            <li>{_sc("Ctrl+Alt+5")} Toggle relationship inspector</li>
            <li>{_sc("Ctrl+Alt+6")} Toggle focus mode</li>
            <li>{_sc("Ctrl+Alt+7")} Toggle review workflow</li>
            <li>{_sc("Ctrl+Alt+8")} Toggle calendar / agenda</li>
            <li>{_sc("Ctrl+Alt+9")} Toggle analytics</li>
            <li>{_sc("Ctrl+Alt+0")} Toggle undo history</li>
            <li>{_sc("Ctrl+Alt+W")} Open workspace profiles</li>
            <li>{_sc("Ctrl+Alt+H")} Open snapshot history</li>
            <li>{_sc("Ctrl+Alt+D")} Open diagnostics</li>
            <li>{_sc("Ctrl+Alt+L")} Open application log</li>
        </ul>
        <p><strong>Tree actions</strong></p>
        <ul>
            <li><code>Delete</code> Archive selected task(s)</li>
            <li><code>Shift+Delete</code> Permanently delete selected task(s)</li>
            <li>{_sc("Ctrl+D")} Duplicate selected task</li>
            <li>{_sc("Ctrl+Shift+D")} Duplicate selected subtree</li>
            <li>{_sc("Ctrl+Shift+B")} Open bulk edit</li>
            <li>{_sc("Ctrl+Shift+Up")} Move selected task up</li>
            <li>{_sc("Ctrl+Shift+Down")} Move selected task down</li>
            <li>{_sc("Ctrl+Shift+R")} Open archive browser</li>
            <li>{_sc("Ctrl+Alt+Up")} Collapse all</li>
            <li>{_sc("Ctrl+Alt+Down")} Expand all</li>
            <li><code>Enter</code> Edit current cell when the tree has focus</li>
            <li><code>Space</code> Toggle collapse/expand on the current row</li>
        </ul>
        <p><strong>Quick symbols</strong></p>
        <ul>
            <li><code>+</code> Add task</li>
            <li><code>-</code> Archive selected</li>
            <li><code>Shift++</code> Add child to selected</li>
            <li><code>Shift+-</code> Archive sibling near selected row</li>
        </ul>
        """,
    ),
    HelpChapter(
        anchor="tips",
        title="Tips and Troubleshooting",
        keywords=[
            "troubleshooting",
            "filters",
            "tips",
            "tooltips",
            "missing task",
            "drag drop",
            "reminders",
        ],
        body_html="""
        <ul>
            <li>If a new task appears missing, switch perspective to <strong>All</strong> and clear search and filters.</li>
            <li>If drag/drop is unavailable, check for active filters or a non-manual sort mode.</li>
            <li>If restore seems to do nothing, use <strong>Browse archive</strong> and restore from the archive browser directly.</li>
            <li>If reminder popups are too noisy for the current session, switch the View menu reminder mode to mute all or priority-1-only.</li>
            <li>Use saved views, the command palette, and review categories together to avoid manual re-filtering during repetitive workflows.</li>
            <li>Tooltips can be enabled or disabled from the Help menu.</li>
            <li>The embedded help dialog itself has a search box, indexed chapters, internal links, and Home navigation for fast lookup.</li>
        </ul>
        """,
    ),
]


def _build_help_html() -> str:
    toc = []
    sections = []

    for idx, ch in enumerate(HELP_CHAPTERS, start=1):
        toc.append(f'<li><a href="#{ch.anchor}">{idx}. {ch.title}</a></li>')
        sections.append(
            f"""
            <hr/>
            <h2 id="{ch.anchor}">{idx}. {ch.title}</h2>
            <p><a href="#home">Back to Help Home</a></p>
            {ch.body_html}
            """
        )

    return f"""
    <html>
      <head>
        <style>
          body {{ font-family: {_help_body_font_css()}; line-height: 1.5; }}
          code {{ background: #f2f2f2; padding: 2px 4px; border-radius: 3px; }}
          h1, h2 {{ margin-bottom: 0.25em; }}
          hr {{ margin: 18px 0; }}
        </style>
      </head>
      <body>
        <a id="home"></a>
        <h1>{APP_NAME} Help</h1>
        <p>This embedded guide explains workflows, features, shortcuts, and syntax in detail.</p>
        <h2>Index</h2>
        <ol>
          {"".join(toc)}
        </ol>
        {"".join(sections)}
      </body>
    </html>
    """


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(1080, 760)

        self._chapter_search_blob: dict[str, str] = {}
        for ch in HELP_CHAPTERS:
            self._chapter_search_blob[ch.anchor] = " ".join(
                [ch.title, " ".join(ch.keywords), ch.body_html]
            ).lower()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top = QHBoxLayout()
        lbl = QLabel("Search help")
        lbl.setToolTip("Type keywords to filter the chapter index and search guide content.")
        top.addWidget(lbl)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find topic or keyword...")
        self.search.setToolTip("Search chapters and find text inside the guide.")
        self.search.textChanged.connect(self._filter_index)
        self.search.returnPressed.connect(self._find_next)
        top.addWidget(self.search, 1)

        self.btn_find_next = QPushButton("Find Next")
        self.btn_find_next.setToolTip("Find next occurrence of current search text in guide content.")
        self.btn_find_next.clicked.connect(self._find_next)
        self.btn_find_prev = QPushButton("Find Prev")
        self.btn_find_prev.setToolTip("Find previous occurrence of current search text in guide content.")
        self.btn_find_prev.clicked.connect(self._find_prev)
        self.btn_home = QPushButton("Home")
        self.btn_home.setToolTip("Jump to Help home/index section.")
        self.btn_home.clicked.connect(lambda: self.browser.scrollToAnchor("home"))
        top.addWidget(self.btn_find_next)
        top.addWidget(self.btn_find_prev)
        top.addWidget(self.btn_home)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        self.index = QListWidget()
        self.index.setToolTip("Indexed chapters. Click a chapter to jump.")
        self.index.itemClicked.connect(self._jump_from_index)
        splitter.addWidget(self.index)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.browser.setHtml(_build_help_html())
        self.browser.setToolTip("Help content. Use internal links to jump between chapters.")
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760])

        polish_button_layouts(self)
        self._populate_index()
        self.browser.scrollToAnchor("home")

    def open_anchor(self, anchor: str):
        target = str(anchor or "").strip().lstrip("#")
        if not target:
            target = "home"
        self.browser.scrollToAnchor(target)

    def _populate_index(self):
        self.index.clear()
        for i, ch in enumerate(HELP_CHAPTERS, start=1):
            item = QListWidgetItem(f"{i}. {ch.title}")
            item.setData(Qt.ItemDataRole.UserRole, ch.anchor)
            item.setToolTip(f"Keywords: {', '.join(ch.keywords)}")
            self.index.addItem(item)

    def _jump_from_index(self, item: QListWidgetItem):
        if not item:
            return
        anchor = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if anchor:
            self.browser.scrollToAnchor(anchor)

    def _on_anchor_clicked(self, url: QUrl):
        s = url.toString()
        if s.startswith("#"):
            self.browser.scrollToAnchor(s[1:])
            return
        # Safety fallback for internal relative anchors.
        if not url.isRelative():
            self.browser.setSource(url)
            return
        self.browser.scrollToAnchor(s)

    def _filter_index(self):
        term = self.search.text().strip().lower()
        visible_anchors = []
        for i in range(self.index.count()):
            item = self.index.item(i)
            anchor = str(item.data(Qt.ItemDataRole.UserRole) or "")
            blob = self._chapter_search_blob.get(anchor, "")
            visible = (not term) or (term in blob)
            item.setHidden(not visible)
            if visible:
                visible_anchors.append(anchor)

        if term and visible_anchors:
            self.browser.scrollToAnchor(visible_anchors[0])

    def _find_next(self):
        term = self.search.text().strip()
        if not term:
            return
        if not self.browser.find(term):
            cursor = self.browser.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.browser.setTextCursor(cursor)
            self.browser.find(term)

    def _find_prev(self):
        term = self.search.text().strip()
        if not term:
            return
        if not self.browser.find(term, QTextDocument.FindFlag.FindBackward):
            cursor = self.browser.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.browser.setTextCursor(cursor)
            self.browser.find(term, QTextDocument.FindFlag.FindBackward)
