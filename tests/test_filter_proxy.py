from __future__ import annotations

from PySide6.QtCore import QModelIndex

from db import Database
from demo_data import populate_demo_database
from filter_proxy import TaskFilterProxyModel
from model import TaskTreeModel


def _visible_descriptions(proxy: TaskFilterProxyModel, parent: QModelIndex = QModelIndex()) -> list[str]:
    out: list[str] = []
    for row in range(proxy.rowCount(parent)):
        idx = proxy.index(row, 0, parent)
        text = str(proxy.data(idx) or "").strip()
        if text:
            out.append(text)
        out.extend(_visible_descriptions(proxy, idx))
    return out


def test_filter_proxy_search_tags_and_perspectives(tmp_path, qapp):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    populate_demo_database(db)
    model = TaskTreeModel(db)
    proxy = TaskFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_search_text("tag:finance due<today")
    finance_overdue = _visible_descriptions(proxy)
    assert "Demo: Vendor invoice follow-up" in finance_overdue
    assert "Demo: Inbox - clarify travel reimbursement" not in finance_overdue

    proxy.set_search_text("is:waiting")
    waiting_rows = _visible_descriptions(proxy)
    assert any("Await sponsor response" in row for row in waiting_rows)
    assert any("Get legal sign-off" in row for row in waiting_rows)

    proxy.set_search_text("")
    proxy.set_perspective("inbox")
    inbox_rows = _visible_descriptions(proxy)
    assert inbox_rows == ["Demo: Inbox - clarify travel reimbursement"]

    proxy.set_perspective("all")
    proxy.set_tag_filter({"demo", "marketing"})
    tagged_rows = _visible_descriptions(proxy)
    assert any("Finalize landing page copy" in row for row in tagged_rows)
    assert all("Demo: Someday - redesign office storage" not in row for row in tagged_rows)

    proxy.set_tag_filter(set())
    proxy.set_search_text("phase:approval")
    approval_rows = _visible_descriptions(proxy)
    assert any("Get legal sign-off" in row for row in approval_rows)
    assert all("Await sponsor response" not in row for row in approval_rows)
