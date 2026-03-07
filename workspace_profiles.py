from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSettings

from app_paths import app_data_dir, app_db_path
from db import now_iso


class WorkspaceProfileError(RuntimeError):
    pass


class WorkspaceProfileManager:
    STATE_PREFIX = "_workspace_state"
    GLOBAL_ONLY_KEYS = {"themes/list"}
    GLOBAL_ONLY_PREFIXES = ("themes/data/",)

    def __init__(self, settings: QSettings | None = None, base_dir: str | None = None):
        self.settings = settings or QSettings()
        self.base_dir = Path(base_dir or app_data_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.base_dir / "workspaces.json"
        self._registry = self._load_registry()
        self.ensure_default_workspace()

    def _load_registry(self) -> dict:
        if not self.registry_path.exists():
            return {"current": None, "workspaces": {}}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return {"current": None, "workspaces": {}}
        if not isinstance(data, dict):
            return {"current": None, "workspaces": {}}
        workspaces = data.get("workspaces")
        if not isinstance(workspaces, dict):
            workspaces = {}
        return {
            "current": data.get("current"),
            "workspaces": workspaces,
        }

    def _save_registry(self):
        payload = {
            "current": self._registry.get("current"),
            "workspaces": self._registry.get("workspaces", {}),
        }
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.registry_path)

    def _slugify(self, name: str) -> str:
        text = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
        return text or "workspace"

    def _unique_workspace_id(self, name: str) -> str:
        base = self._slugify(name)
        workspaces = self._registry.get("workspaces", {})
        if base not in workspaces:
            return base
        counter = 2
        while f"{base}-{counter}" in workspaces:
            counter += 1
        return f"{base}-{counter}"

    def _default_workspace_record(self) -> dict:
        current = now_iso()
        return {
            "id": "default",
            "name": "Default",
            "db_path": str(Path(app_db_path()).resolve()),
            "created_at": current,
            "last_opened_at": current,
        }

    def ensure_default_workspace(self):
        workspaces = self._registry.setdefault("workspaces", {})
        if "default" not in workspaces:
            workspaces["default"] = self._default_workspace_record()
        if not self._registry.get("current") or self._registry["current"] not in workspaces:
            self._registry["current"] = "default"
        self._save_registry()
        self.ensure_workspace_state(str(self._registry["current"]))

    def workspaces_dir(self) -> Path:
        path = self.base_dir / "workspaces"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def suggested_db_path(self, name: str) -> str:
        workspace_id = self._slugify(name)
        return str((self.workspaces_dir() / f"{workspace_id}.sqlite3").resolve())

    def _workspace_state_prefix(self, workspace_id: str) -> str:
        return f"{self.STATE_PREFIX}/{workspace_id}/"

    def _is_global_only_key(self, key: str) -> bool:
        if not key:
            return True
        if key.startswith(f"{self.STATE_PREFIX}/"):
            return True
        if key in self.GLOBAL_ONLY_KEYS:
            return True
        return any(key.startswith(prefix) for prefix in self.GLOBAL_ONLY_PREFIXES)

    def _active_setting_keys(self) -> list[str]:
        self.settings.sync()
        return [key for key in self.settings.allKeys() if not self._is_global_only_key(str(key))]

    def capture_current_state(self) -> dict[str, object]:
        return {key: self.settings.value(key) for key in self._active_setting_keys()}

    def _write_state(self, workspace_id: str, state: dict[str, object]):
        prefix = self._workspace_state_prefix(workspace_id)
        existing = [key for key in self.settings.allKeys() if str(key).startswith(prefix)]
        for key in existing:
            self.settings.remove(key)
        for key, value in (state or {}).items():
            self.settings.setValue(prefix + str(key), value)
        self.settings.sync()

    def copy_state(self, source_workspace_id: str, dest_workspace_id: str):
        prefix = self._workspace_state_prefix(source_workspace_id)
        state: dict[str, object] = {}
        for key in self.settings.allKeys():
            text = str(key)
            if not text.startswith(prefix):
                continue
            state[text[len(prefix):]] = self.settings.value(text)
        self._write_state(dest_workspace_id, state)

    def save_state_for(self, workspace_id: str):
        self._write_state(str(workspace_id), self.capture_current_state())

    def ensure_workspace_state(self, workspace_id: str):
        prefix = self._workspace_state_prefix(workspace_id)
        if any(str(key).startswith(prefix) for key in self.settings.allKeys()):
            return
        self.save_state_for(workspace_id)

    def restore_state_for(self, workspace_id: str):
        prefix = self._workspace_state_prefix(workspace_id)
        state_keys = [str(key) for key in self.settings.allKeys() if str(key).startswith(prefix)]
        current_keys = self._active_setting_keys()
        for key in current_keys:
            self.settings.remove(key)
        for state_key in state_keys:
            user_key = state_key[len(prefix):]
            self.settings.setValue(user_key, self.settings.value(state_key))
        self.settings.sync()

    def list_workspaces(self) -> list[dict]:
        current = str(self._registry.get("current") or "")
        rows = []
        for workspace_id, record in (self._registry.get("workspaces") or {}).items():
            row = deepcopy(record)
            row["id"] = workspace_id
            row["is_current"] = workspace_id == current
            rows.append(row)
        rows.sort(key=lambda row: (not bool(row.get("is_current")), str(row.get("name") or "").lower(), row["id"]))
        return rows

    def workspace_by_id(self, workspace_id: str) -> dict | None:
        record = (self._registry.get("workspaces") or {}).get(str(workspace_id))
        if not isinstance(record, dict):
            return None
        row = deepcopy(record)
        row["id"] = str(workspace_id)
        row["is_current"] = str(workspace_id) == str(self._registry.get("current") or "")
        return row

    def current_workspace(self) -> dict:
        current = str(self._registry.get("current") or "default")
        row = self.workspace_by_id(current)
        if row is None:
            row = self._default_workspace_record()
            self._registry.setdefault("workspaces", {})["default"] = row
            self._registry["current"] = "default"
            self._save_registry()
        return row

    def create_workspace(
        self,
        name: str,
        db_path: str | None = None,
        *,
        inherit_current_state: bool = True,
    ) -> dict:
        display_name = str(name or "").strip()
        if not display_name:
            raise WorkspaceProfileError("Workspace name is required.")
        workspace_id = self._unique_workspace_id(display_name)
        default_path = self.workspaces_dir() / f"{workspace_id}.sqlite3"
        target_path = str(Path(db_path or default_path).expanduser().resolve())
        current = now_iso()
        record = {
            "id": workspace_id,
            "name": display_name,
            "db_path": target_path,
            "created_at": current,
            "last_opened_at": current,
        }
        self._registry.setdefault("workspaces", {})[workspace_id] = record
        self._save_registry()
        if inherit_current_state:
            source = self.current_workspace().get("id")
            if source:
                self.copy_state(str(source), workspace_id)
            else:
                self.save_state_for(workspace_id)
        return self.workspace_by_id(workspace_id) or deepcopy(record)

    def set_current_workspace(self, workspace_id: str, apply_state: bool = True) -> dict:
        record = self.workspace_by_id(workspace_id)
        if record is None:
            raise WorkspaceProfileError(f"Workspace '{workspace_id}' does not exist.")
        record["last_opened_at"] = now_iso()
        self._registry.setdefault("workspaces", {})[str(workspace_id)] = record
        self._registry["current"] = str(workspace_id)
        self._save_registry()
        if apply_state:
            self.ensure_workspace_state(str(workspace_id))
            self.restore_state_for(str(workspace_id))
        return self.current_workspace()

    def remove_workspace(self, workspace_id: str):
        workspace_key = str(workspace_id)
        current = str(self._registry.get("current") or "")
        if workspace_key == current:
            raise WorkspaceProfileError("The active workspace cannot be removed.")
        workspaces = self._registry.setdefault("workspaces", {})
        workspaces.pop(workspace_key, None)
        prefix = self._workspace_state_prefix(workspace_key)
        for key in [str(k) for k in self.settings.allKeys() if str(k).startswith(prefix)]:
            self.settings.remove(key)
        self.settings.sync()
        self._save_registry()
