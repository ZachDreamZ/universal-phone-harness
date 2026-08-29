"""
Tests for MockPhoneDevice State Transitions & Navigation.
"""

from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.models import KeyCode


def test_mock_device_screen_transitions():
    dev = MockPhoneDevice()
    assert dev.is_connected() is True
    assert dev.current_screen == "home"

    # Tap on Settings icon
    elems = dev.dump_hierarchy()
    settings_btn = next(e for e in elems if e.text == "Settings")
    dev.tap(settings_btn.center[0], settings_btn.center[1])

    assert dev.current_screen == "settings"
    assert dev.get_foreground_app() == "com.android.settings"

    # Press BACK key
    dev.press_key(KeyCode.BACK)
    assert dev.current_screen == "home"


def test_mock_device_settings_toggles():
    dev = MockPhoneDevice()
    dev.launch_app("settings")
    assert dev.current_screen == "settings"
    assert dev.settings_wifi_enabled is True

    # Tap on Wi-Fi checkbox
    elems = dev.dump_hierarchy()
    wifi_elem = next(e for e in elems if "Wi-Fi" in (e.text or ""))
    dev.tap(wifi_elem.center[0], wifi_elem.center[1])

    assert dev.settings_wifi_enabled is False


def test_mock_device_login_flow():
    dev = MockPhoneDevice()
    dev.launch_app("login")
    assert dev.current_screen == "login"

    dev.type_text("alice@example.com")
    assert dev.login_email == "alice@example.com"
