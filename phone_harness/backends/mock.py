"""
High-Fidelity Mock Phone Device Driver.
Provides interactive simulated screens, dynamic state transitions, and real image rendering for offline development & CI/CD.
"""

from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from phone_harness.core.device import BasePhoneDevice
from phone_harness.core.models import (
    UIElement,
    DeviceSummary,
    KeyCode,
    SwipeDirection,
)


class MockPhoneDevice(BasePhoneDevice):
    """Simulates realistic Android/iOS screen states, inputs, and transitions."""

    platform = "mock"

    def __init__(self, device_id: str = "mock-phone-01"):
        self.device_id = device_id
        self._is_connected = True
        self.screen_width = 1080
        self.screen_height = 2400
        self.current_screen = "home"
        self.current_package = "com.google.android.apps.nexuslauncher"
        self.history: List[str] = ["home"]
        self.keyboard_shown = False

        # State memory for mock screens
        self.settings_wifi_enabled = True
        self.settings_bluetooth_enabled = False
        self.login_email = ""
        self.login_password = ""
        self.login_remember_me = False
        self.messages_list = [
            "Alice: Hey, are you joining the team sync?",
            "Bob: PR #42 has been approved!",
            "Delivery: Your package is out for delivery.",
        ]

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def disconnect(self) -> None:
        self._is_connected = False

    def is_connected(self) -> bool:
        return self._is_connected

    def get_device_summary(self) -> DeviceSummary:
        return DeviceSummary(
            device_id=self.device_id,
            platform="mock",
            model="Simulated Pixel 9 Pro",
            os_version="Android 15 (API 35)",
            screen_resolution=(self.screen_width, self.screen_height),
            is_connected=self._is_connected,
            battery_level=88,
            active_package=self.current_package,
            capabilities=["fast_scrcpy_stream", "binary_ax_tree", "uinput_touch", "zero_mistake_verifier"],
        )

    def dump_hierarchy(self) -> List[UIElement]:
        """Generates screen-specific UI elements."""
        if self.current_screen == "home":
            return self._build_home_elements()
        elif self.current_screen == "settings":
            return self._build_settings_elements()
        elif self.current_screen == "login":
            return self._build_login_elements()
        elif self.current_screen == "messages":
            return self._build_messages_elements()
        else:
            return self._build_home_elements()

    def _build_home_elements(self) -> List[UIElement]:
        return [
            UIElement.create(1, "TextView", (100, 200, 980, 320), text="12:45 PM - Friday, Aug 28"),
            UIElement.create(2, "EditText", (80, 380, 1000, 480), text="Search apps & web...", is_editable=True, is_clickable=True),
            UIElement.create(3, "Button", (100, 800, 300, 1000), text="Settings", description="Open Settings App", resource_id="com.android.settings/icon"),
            UIElement.create(4, "Button", (390, 800, 590, 1000), text="Messages", description="Open Messages App", resource_id="com.google.android.apps.messaging/icon"),
            UIElement.create(5, "Button", (680, 800, 880, 1000), text="Login Portal", description="Open Login Screen", resource_id="com.example.auth/icon"),
            UIElement.create(6, "Button", (100, 2100, 300, 2250), text="Phone", description="Phone dialer"),
            UIElement.create(7, "Button", (390, 2100, 590, 2250), text="Chrome", description="Web browser"),
            UIElement.create(8, "Button", (680, 2100, 880, 2250), text="Camera", description="Camera app"),
        ]

    def _build_settings_elements(self) -> List[UIElement]:
        wifi_status = "Connected" if self.settings_wifi_enabled else "Disconnected"
        bt_status = "On" if self.settings_bluetooth_enabled else "Off"
        return [
            UIElement.create(1, "ImageButton", (40, 120, 140, 220), text="Back", description="Navigate Up"),
            UIElement.create(2, "TextView", (160, 140, 900, 220), text="Settings"),
            UIElement.create(3, "CheckBox", (100, 300, 980, 450), text="Wi-Fi", description=f"Status: {wifi_status}", is_checked=self.settings_wifi_enabled),
            UIElement.create(4, "CheckBox", (100, 480, 980, 630), text="Bluetooth", description=f"Status: {bt_status}", is_checked=self.settings_bluetooth_enabled),
            UIElement.create(5, "TextView", (100, 660, 980, 780), text="Display & Brightness", is_clickable=True),
            UIElement.create(6, "TextView", (100, 810, 980, 930), text="Apps & Notifications", is_clickable=True),
            UIElement.create(7, "Button", (100, 1800, 980, 1950), text="Factory Reset Phone", description="Erase all user data", is_clickable=True),
        ]

    def _build_login_elements(self) -> List[UIElement]:
        return [
            UIElement.create(1, "ImageButton", (40, 120, 140, 220), text="Back", description="Navigate Up"),
            UIElement.create(2, "TextView", (100, 280, 980, 380), text="Welcome Back"),
            UIElement.create(3, "EditText", (100, 460, 980, 580), text=self.login_email or "Email address", is_editable=True, is_clickable=True, value=self.login_email),
            UIElement.create(4, "EditText", (100, 620, 980, 740), text="••••••••" if self.login_password else "Password", is_editable=True, is_clickable=True, is_password=True, value=self.login_password),
            UIElement.create(5, "CheckBox", (100, 780, 500, 860), text="Remember me", is_checked=self.login_remember_me),
            UIElement.create(6, "Button", (100, 920, 980, 1050), text="Sign In", description="Submit credentials"),
            UIElement.create(7, "TextView", (100, 1100, 980, 1180), text="Forgot password?", is_clickable=True),
        ]

    def _build_messages_elements(self) -> List[UIElement]:
        elements = [
            UIElement.create(1, "ImageButton", (40, 120, 140, 220), text="Back", description="Navigate Up"),
            UIElement.create(2, "TextView", (160, 140, 800, 220), text="Messages"),
            UIElement.create(3, "Button", (850, 140, 980, 220), text="New Chat", is_clickable=True),
        ]
        top = 280
        for i, msg in enumerate(self.messages_list, start=4):
            elements.append(
                UIElement.create(i, "TextView", (100, top, 980, top + 140), text=msg, is_clickable=True)
            )
            top += 160
        return elements

    def capture_frame(self) -> Image.Image:
        """Dynamically draws the simulated screen UI."""
        img = Image.new("RGB", (self.screen_width, self.screen_height), color=(245, 247, 250))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()

        # Draw top status bar
        draw.rectangle([0, 0, self.screen_width, 80], fill=(30, 35, 45))
        draw.text((40, 30), "12:45 | 5G | 88%", fill=(255, 255, 255), font=font)

        elements = self.dump_hierarchy()
        for elem in elements:
            xmin, ymin, xmax, ymax = elem.bounds
            if elem.type == "Button":
                draw.rectangle([xmin, ymin, xmax, ymax], fill=(45, 110, 230), outline=(20, 80, 180), width=2)
                draw.text((xmin + 20, ymin + (ymax - ymin) // 2 - 10), elem.text or elem.description or "Btn", fill=(255, 255, 255), font=font)
            elif elem.type == "EditText":
                draw.rectangle([xmin, ymin, xmax, ymax], fill=(255, 255, 255), outline=(180, 185, 195), width=2)
                draw.text((xmin + 20, ymin + (ymax - ymin) // 2 - 10), elem.text or "", fill=(80, 85, 95), font=font)
            elif elem.type == "CheckBox":
                check_char = "[X]" if elem.is_checked else "[ ]"
                draw.text((xmin, ymin + 10), f"{check_char} {elem.text}", fill=(30, 30, 30), font=font)
            else:
                draw.text((xmin, ymin + 10), elem.text or "", fill=(20, 20, 20), font=font)

        return img

    def tap(self, x: int, y: int) -> None:
        """Simulates physical tap and dispatches state transitions."""
        elements = self.dump_hierarchy()
        for elem in elements:
            if elem.bounds[0] <= x <= elem.bounds[2] and elem.bounds[1] <= y <= elem.bounds[3]:
                self._handle_element_tap(elem)
                return

    def _handle_element_tap(self, elem: UIElement) -> None:
        if self.current_screen == "home":
            if elem.text == "Settings":
                self.current_screen = "settings"
                self.current_package = "com.android.settings"
                self.history.append("settings")
            elif elem.text == "Messages":
                self.current_screen = "messages"
                self.current_package = "com.google.android.apps.messaging"
                self.history.append("messages")
            elif elem.text == "Login Portal":
                self.current_screen = "login"
                self.current_package = "com.example.auth"
                self.history.append("login")

        elif self.current_screen == "settings":
            if elem.text == "Back":
                self.press_key(KeyCode.BACK)
            elif "Wi-Fi" in (elem.text or ""):
                self.settings_wifi_enabled = not self.settings_wifi_enabled
            elif "Bluetooth" in (elem.text or ""):
                self.settings_bluetooth_enabled = not self.settings_bluetooth_enabled

        elif self.current_screen == "login":
            if elem.text == "Back":
                self.press_key(KeyCode.BACK)
            elif elem.text == "Sign In":
                # Simulated sign in transition
                self.current_screen = "home"
                self.current_package = "com.google.android.apps.nexuslauncher"
                self.history.append("home")
            elif "Remember" in (elem.text or ""):
                self.login_remember_me = not self.login_remember_me

        elif self.current_screen == "messages":
            if elem.text == "Back":
                self.press_key(KeyCode.BACK)

    def double_tap(self, x: int, y: int) -> None:
        self.tap(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self.tap(x, y)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 250) -> None:
        pass

    def swipe_directional(self, direction: SwipeDirection, distance: str = "medium", duration_ms: int = 250) -> None:
        pass

    def type_text(self, text: str, clear_existing: bool = False, press_enter: bool = False, fast_paste: bool = False) -> None:
        if self.current_screen == "login":
            if not self.login_email:
                self.login_email = text
            else:
                self.login_password = text

    def clear_text(self) -> None:
        if self.current_screen == "login":
            self.login_email = ""
            self.login_password = ""

    def press_key(self, key: KeyCode) -> None:
        if key == KeyCode.HOME:
            self.current_screen = "home"
            self.current_package = "com.google.android.apps.nexuslauncher"
            self.history = ["home"]
        elif key == KeyCode.BACK:
            if len(self.history) > 1:
                self.history.pop()
                self.current_screen = self.history[-1]
                if self.current_screen == "home":
                    self.current_package = "com.google.android.apps.nexuslauncher"

    def open_url(self, url: str) -> None:
        self.current_screen = "browser"
        self.current_package = "com.android.chrome"
        self.history.append("browser")

    def open_settings_section(self, section: str) -> None:
        self.current_screen = "settings"
        self.current_package = "com.android.settings"
        self.history.append("settings")

    def set_clipboard(self, text: str) -> None:
        self._clipboard = text

    def get_clipboard(self) -> str:
        return getattr(self, "_clipboard", "")

    def launch_app(self, package_or_name: str, stop_existing: bool = False) -> None:
        target = package_or_name.lower()
        if "setting" in target:
            self.current_screen = "settings"
            self.current_package = "com.android.settings"
            self.history.append("settings")
        elif "messag" in target or "chat" in target:
            self.current_screen = "messages"
            self.current_package = "com.google.android.apps.messaging"
            self.history.append("messages")
        elif "login" in target or "auth" in target:
            self.current_screen = "login"
            self.current_package = "com.example.auth"
            self.history.append("login")
        else:
            self.current_screen = "home"
            self.current_package = package_or_name
            self.history.append("home")

    def get_foreground_app(self) -> str:
        return self.current_package

    def is_keyboard_visible(self) -> bool:
        return self.keyboard_shown
