from __future__ import annotations

import uuid

import main as main_module


def test_single_instance_guard_redirects_later_launches_to_existing_instance(qapp, tmp_path):
    app_uid = f"com.gridoryn.tests.{uuid.uuid4().hex}"
    lock_path = str(tmp_path / f"{uuid.uuid4().hex}.singleton.lock")
    activations: list[str] = []

    first_lock, first_name, first_server, first_running = main_module._acquire_single_instance_guard(
        lambda: activations.append("activate"),
        app_uid=app_uid,
        lock_path=lock_path,
    )
    assert first_name == main_module._single_instance_server_name(app_uid)
    assert first_running is False
    assert first_lock is not None
    assert first_server is not None

    try:
        second_lock, second_name, second_server, second_running = main_module._acquire_single_instance_guard(
            lambda: activations.append("unexpected"),
            app_uid=app_uid,
            lock_path=lock_path,
        )
        assert second_name == first_name
        assert second_running is True
        assert second_lock is None
        assert second_server is None

        qapp.processEvents()
        qapp.processEvents()

        assert activations == ["activate"]
    finally:
        main_module._release_single_instance_guard(first_lock, first_name, first_server)
