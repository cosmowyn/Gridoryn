from help_ui import _build_help_html


def test_help_includes_qss_styling_chapter_and_selectors():
    html = _build_help_html()
    assert 'id="qss-styling"' in html
    assert "Custom QSS override" in html
    assert "QPushButton#RowDeleteButton" in html
    assert "QDockWidget#ProjectCockpitDock::title" in html
    assert "QToolBar#MainToolBar QToolButton" in html
