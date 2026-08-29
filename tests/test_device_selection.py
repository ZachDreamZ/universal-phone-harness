"""
Task 1: Device identity and fail-closed selection.

Verifies that each backend exposes a stable platform identity and that
PhoneHarness selects devices according to HarnessConfig.default_platform
with a fail-closed policy (real backend failures raise rather than silently
falling back to mock unless allow_mock_fallback is explicitly enabled).
"""

import pytest

from phone_harness.backends.android import AndroidPhoneDevice
from phone_harness.backends.ios import IOSPhoneDevice
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.config import HarnessConfig
from phone_harness.core.exceptions import DeviceDisconnectedError
from phone_harness.harness import PhoneHarness


def test_backends_expose_platform_identity():
    assert AndroidPhoneDevice().platform == "android"
    assert IOSPhoneDevice().platform == "ios"
    assert MockPhoneDevice().platform == "mock"


def test_mock_platform_selects_mock_without_probe():
    harness = PhoneHarness(config=HarnessConfig(default_platform="mock"))
    assert harness.device.platform == "mock"


def test_real_backend_failure_does_not_silently_use_mock(monkeypatch):
    monkeypatch.setattr(AndroidPhoneDevice, "connect", lambda self: False)
    harness = PhoneHarness(config=HarnessConfig(default_platform="android"))
    with pytest.raises(DeviceDisconnectedError):
        _ = harness.device


def test_explicit_mock_fallback_allows_offline_execution(monkeypatch):
    monkeypatch.setattr(AndroidPhoneDevice, "connect", lambda self: False)
    harness = PhoneHarness(
        config=HarnessConfig(default_platform="android", allow_mock_fallback=True)
    )
    assert harness.device.platform == "mock"


def test_ios_happy_path_returns_ios_platform(monkeypatch):
    monkeypatch.setattr(IOSPhoneDevice, "connect", lambda self: True)
    harness = PhoneHarness(config=HarnessConfig(default_platform="ios"))
    assert harness.device.platform == "ios"


def test_unknown_platform_raises_disconnected_error():
    harness = PhoneHarness(config=HarnessConfig(default_platform="beos"))
    with pytest.raises(DeviceDisconnectedError):
        _ = harness.device
