"""Unit tests for RobotManager connection lifecycle, status, and manual control."""

from unittest.mock import MagicMock, patch

import pytest

import robot_manager as rm_module
from robot_manager import RobotManager


@pytest.fixture
def manager():
    return RobotManager()


def _make_conn(state: str = "connected") -> MagicMock:
    conn = MagicMock()
    conn.ping.return_value = {"ok": True, "serial": "TEST123"}
    conn.connection_info.return_value = {
        "target": "1.2.3.4:26400",
        "state": state,
        "monitoring": True,
        "monitor_interval": 5.0,
        "state_changed_ago_s": 1.5,
        "last_ok_ping_ago_s": 0.5 if state == "connected" else None,
    }
    return conn


@pytest.fixture
def connected_manager(manager, monkeypatch):
    """Manager wired to a mocked KachakaConnection via connect()."""
    conn = _make_conn()
    monkeypatch.setattr(rm_module.settings_service, "save", lambda *_a, **_k: None)
    with patch.object(rm_module.KachakaConnection, "get", return_value=conn), \
         patch.object(rm_module.KachakaConnection, "remove") as remove, \
         patch.object(rm_module, "RobotController"), \
         patch.object(rm_module, "KachakaQueries"), \
         patch.object(rm_module, "CameraStreamer"):
        result = manager.connect("1.2.3.4")
        assert result["ok"] is True
        yield manager, conn, remove


# ── Fix 2: monitor-thread leak — remove() on every teardown path ──────


class TestConnectionRemove:
    def test_ping_failure_calls_remove(self, manager, monkeypatch):
        conn = _make_conn()
        conn.ping.return_value = {"ok": False, "error": "unreachable"}
        with patch.object(rm_module.KachakaConnection, "get", return_value=conn), \
             patch.object(rm_module.KachakaConnection, "remove") as remove:
            result = manager.connect("1.2.3.4")
        assert result["ok"] is False
        remove.assert_called_once_with("1.2.3.4")
        assert manager._conn is None

    def test_connect_exception_calls_remove(self, manager):
        conn = _make_conn()
        conn.ping.side_effect = RuntimeError("boom")
        with patch.object(rm_module.KachakaConnection, "get", return_value=conn), \
             patch.object(rm_module.KachakaConnection, "remove") as remove:
            result = manager.connect("1.2.3.4")
        assert result["ok"] is False
        remove.assert_called_once_with("1.2.3.4")
        assert manager._conn is None

    def test_disconnect_calls_remove(self, connected_manager):
        manager, _conn, remove = connected_manager
        result = manager.disconnect()
        assert result["ok"] is True
        remove.assert_called_once_with("1.2.3.4")
        assert manager._conn is None

    def test_reconnect_removes_previous_connection(self, connected_manager):
        manager, _conn, remove = connected_manager
        manager.connect("5.6.7.8")
        # _shutdown_components must remove the old IP before connecting anew
        assert remove.call_args_list[0].args == ("1.2.3.4",)


# ── Fix 4: health-aware get_connection_status ─────────────────────────


class TestConnectionStatus:
    def test_status_when_never_connected(self, manager):
        status = manager.get_connection_status()
        assert status["connected"] is False
        assert status["state"] == "disconnected"
        assert status["state_changed_ago_s"] is None
        assert status["last_ok_ping_ago_s"] is None

    def test_status_connected(self, connected_manager):
        manager, _conn, _remove = connected_manager
        status = manager.get_connection_status()
        assert status["connected"] is True
        assert status["state"] == "connected"
        assert status["ip"] == "1.2.3.4"
        assert status["serial"] == "TEST123"
        assert status["state_changed_ago_s"] == 1.5
        assert status["last_ok_ping_ago_s"] == 0.5

    def test_status_disconnected_state_overrides_conn_presence(self, connected_manager):
        manager, conn, _remove = connected_manager
        conn.connection_info.return_value["state"] = "disconnected"
        status = manager.get_connection_status()
        assert status["connected"] is False
        assert status["state"] == "disconnected"

    def test_status_unknown_state_is_not_connected_but_exposed(self, connected_manager):
        manager, conn, _remove = connected_manager
        conn.connection_info.return_value["state"] = "unknown"
        status = manager.get_connection_status()
        assert status["connected"] is False
        assert status["state"] == "unknown"


# ── Fix 3: raw SDK manual control must not block ──────────────────────


class TestManualControl:
    def test_move_forward_no_wait(self, connected_manager):
        manager, conn, _remove = connected_manager
        manager.move_forward(0.1)
        conn.client.move_forward.assert_called_once_with(
            distance_meter=0.1, speed=0.1, wait_for_completion=False)

    def test_rotate_no_wait(self, connected_manager):
        manager, conn, _remove = connected_manager
        manager.rotate(0.5)
        conn.client.rotate_in_place.assert_called_once_with(
            angle_radian=0.5, wait_for_completion=False)

    def test_fc_rotate_message_acknowledges_issuance(self, connected_manager):
        manager, _conn, _remove = connected_manager
        result = manager.execute_function_call("rotate", {"angle": 30})
        assert result["ok"] is True
        assert "issued" in result["message"]
        assert "Rotated" not in result["message"]


# ── Fix 5 support: camera frame age accessor ──────────────────────────


class TestCameraFrameAge:
    def test_age_none_without_camera(self, manager):
        assert manager.get_camera_frame_age_s() is None

    def test_age_proxies_streamer(self, connected_manager):
        manager, _conn, _remove = connected_manager
        manager._camera.latest_frame_age_s = 1.25
        assert manager.get_camera_frame_age_s() == 1.25
