"""Unit tests for FrameHub.wait_for_fresh_frame freshness handling."""

import pytest

import frame_hub as fh_module
from frame_hub import FrameHub

JPEG = b"\xff\xd8fakejpeg"


@pytest.fixture
def hub():
    return FrameHub()


def _patch_robot(monkeypatch, age, jpeg=JPEG):
    monkeypatch.setattr(fh_module.robot_manager, "get_camera_frame_age_s",
                        lambda: age, raising=False)
    monkeypatch.setattr(fh_module.robot_manager, "get_camera_jpeg_bytes",
                        lambda: jpeg, raising=False)


def test_fresh_frame_returned(hub, monkeypatch):
    _patch_robot(monkeypatch, age=0.5)
    assert hub.wait_for_fresh_frame(timeout=1.0) == JPEG


def test_stale_frame_times_out(hub, monkeypatch):
    _patch_robot(monkeypatch, age=10.0)
    assert hub.wait_for_fresh_frame(timeout=0.5) is None


def test_no_frame_times_out(hub, monkeypatch):
    _patch_robot(monkeypatch, age=None, jpeg=None)
    assert hub.wait_for_fresh_frame(timeout=0.5) is None


def test_frame_becoming_fresh_during_wait(hub, monkeypatch):
    ages = iter([5.0, 5.0, 0.3])
    monkeypatch.setattr(fh_module.robot_manager, "get_camera_frame_age_s",
                        lambda: next(ages, 0.3), raising=False)
    monkeypatch.setattr(fh_module.robot_manager, "get_camera_jpeg_bytes",
                        lambda: JPEG, raising=False)
    assert hub.wait_for_fresh_frame(timeout=2.0) == JPEG
