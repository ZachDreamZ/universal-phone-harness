"""
iOS Device Backend using WebDriverAgent (WDA) REST API.
Provides reliable gesture execution and accessibility tree parsing for physical iPhones and iOS Simulators.
"""

import io
import json
import base64
import requests
from typing import List, Optional
from urllib.parse import urlparse
from PIL import Image

from phone_harness.core.device import BasePhoneDevice
from phone_harness.core.models import (
    UIElement,
    DeviceSummary,
    KeyCode,
    SwipeDirection,
)
from phone_harness.core.exceptions import DeviceDisconnectedError


class IOSPhoneDevice(BasePhoneDevice):
    """iOS device driver communicating with WebDriverAgent server."""

    platform = "ios"

    def __init__(self, wda_url: str = "http://127.0.0.1:8100", device_id: str = "ios-device"):
        self.wda_url = wda_url.rstrip("/")
        self.device_id = device_id
        self._session_id: Optional[str] = None
        self._is_connected = False
        self.screen_width = 1170
        self.screen_height = 2532

    def _url(self, path: str) -> str:
        if self._session_id and not path.startswith("/status") and not path.startswith("/session"):
            return f"{self.wda_url}/session/{self._session_id}{path}"
        return f"{self.wda_url}{path}"

    def connect(self) -> bool:
        try:
            res = requests.get(f"{self.wda_url}/status", timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                self._session_id = data.get("sessionId")
                if not self._session_id:
                    # Create new session
                    sess_res = requests.post(f"{self.wda_url}/session", json={"capabilities": {}}, timeout=5.0)
                    if sess_res.status_code == 200:
                        self._session_id = sess_res.json().get("sessionId")
                self._is_connected = True

                # Fetch window size
                size_res = requests.get(self._url("/window/size"), timeout=3.0)
                if size_res.status_code == 200:
                    sz = size_res.json().get("value", {})
                    self.screen_width = int(sz.get("width", self.screen_width))
                    self.screen_height = int(sz.get("height", self.screen_height))
                return True
        except Exception:
            self._is_connected = False
            return False
        return False

    def disconnect(self) -> None:
        self._is_connected = False

    def is_connected(self) -> bool:
        return self._is_connected

    def get_device_summary(self) -> DeviceSummary:
        return DeviceSummary(
            device_id=self.device_id,
            platform="ios",
            model="iPhone 16 Pro",
            os_version="iOS 18.0",
            screen_resolution=(self.screen_width, self.screen_height),
            is_connected=self._is_connected,
            battery_level=95,
            active_package=self.get_foreground_app(),
            capabilities=["wda_screenshot", "wda_accessibility_tree", "wda_touch"],
        )

    def capture_frame(self) -> Image.Image:
        res = requests.get(self._url("/screenshot"), timeout=5.0)
        if res.status_code == 200:
            b64_data = res.json().get("value", "")
            raw_bytes = base64.b64decode(b64_data)
            return Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        raise RuntimeError("Failed to capture iOS screenshot via WDA.")

    def dump_hierarchy(self) -> List[UIElement]:
        res = requests.get(self._url("/source?format=json"), timeout=5.0)
        elements: List[UIElement] = []
        if res.status_code == 200:
            tree_data = res.json().get("value", {})
            self._flatten_ios_tree(tree_data, elements)
        return elements

    def _flatten_ios_tree(self, node: dict, elements: List[UIElement]) -> None:
        rect = node.get("rect", {})
        x = int(rect.get("x", 0))
        y = int(rect.get("y", 0))
        w = int(rect.get("width", 0))
        h = int(rect.get("height", 0))

        if w > 0 and h > 0:
            elem = UIElement.create(
                id=len(elements) + 1,
                type=node.get("type", "XCUIElementTypeOther").replace("XCUIElementType", ""),
                bounds=(x, y, x + w, y + h),
                text=node.get("label") or node.get("value"),
                description=node.get("name"),
                is_clickable=node.get("is_enabled", True),
                is_enabled=node.get("is_enabled", True),
            )
            elements.append(elem)

        for child in node.get("children", []):
            self._flatten_ios_tree(child, elements)

    def tap(self, x: int, y: int) -> None:
        requests.post(self._url("/wda/tap/0"), json={"x": x, "y": y}, timeout=3.0)

    def double_tap(self, x: int, y: int) -> None:
        requests.post(self._url("/wda/doubleTap"), json={"x": x, "y": y}, timeout=3.0)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        requests.post(self._url("/wda/touchAndHold"), json={"x": x, "y": y, "duration": duration_ms / 1000.0}, timeout=4.0)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 250) -> None:
        requests.post(
            self._url("/wda/dragfromtoforduration"),
            json={"fromX": start_x, "fromY": start_y, "toX": end_x, "toY": end_y, "duration": duration_ms / 1000.0},
            timeout=5.0,
        )

    def swipe_directional(self, direction: SwipeDirection, distance: str = "medium", duration_ms: int = 250) -> None:
        w, h = self.screen_width, self.screen_height
        cx, cy = w // 2, h // 2
        offset = int(h * 0.3) if distance == "medium" else (int(h * 0.15) if distance == "short" else int(h * 0.5))
        if direction == SwipeDirection.UP:
            self.swipe(cx, cy + offset // 2, cx, cy - offset // 2, duration_ms)
        elif direction == SwipeDirection.DOWN:
            self.swipe(cx, cy - offset // 2, cx, cy + offset // 2, duration_ms)
        elif direction == SwipeDirection.LEFT:
            self.swipe(cx + offset // 2, cy, cx - offset // 2, cy, duration_ms)
        elif direction == SwipeDirection.RIGHT:
            self.swipe(cx - offset // 2, cy, cx + offset // 2, cy, duration_ms)

    def type_text(self, text: str, clear_existing: bool = False, press_enter: bool = False, fast_paste: bool = False) -> None:
        if fast_paste:
            self.set_clipboard(text)
            # WDA paste not universally supported, fall back to keys
        payload = {"value": list(text)}
        requests.post(self._url("/wda/keys"), json=payload, timeout=3.0)
        if press_enter:
            requests.post(self._url("/wda/keys"), json={"value": ["\n"]}, timeout=3.0)

    def clear_text(self) -> None:
        """Select all + delete via WDA keys."""
        try:
            requests.post(self._url("/wda/keys"), json={"value": ["\u0001"]}, timeout=3.0)  # Ctrl+A
            requests.post(self._url("/wda/keys"), json={"value": ["\u007f"]}, timeout=3.0)  # Delete
        except Exception:
            pass

    def press_key(self, key: KeyCode) -> None:
        if key == KeyCode.HOME:
            requests.post(self._url("/wda/homescreen"), timeout=3.0)
        elif key == KeyCode.BACK:
            # iOS back gesture: swipe from left edge
            self.swipe(5, self.screen_height // 2, self.screen_width // 2, self.screen_height // 2, 300)
        elif key == KeyCode.ENTER:
            requests.post(self._url("/wda/keys"), json={"value": ["\n"]}, timeout=3.0)

    def open_url(self, url: str) -> None:
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("URL must use HTTP or HTTPS and include a host.")
        requests.post(self._url("/wda/apps/launch"), json={"bundleId": "com.apple.mobilesafari", "arguments": [url]}, timeout=5.0)

    def open_settings_section(self, section: str) -> None:
        requests.post(self._url("/wda/apps/launch"), json={"bundleId": "com.apple.Preferences"}, timeout=5.0)

    def set_clipboard(self, text: str) -> None:
        raw_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        requests.post(self._url("/wda/setPasteboard"), json={"content": raw_b64, "contentType": "plaintext"}, timeout=3.0)

    def get_clipboard(self) -> str:
        try:
            res = requests.post(self._url("/wda/getPasteboard"), json={"contentType": "plaintext"}, timeout=3.0)
            if res.status_code == 200:
                raw_b64 = res.json().get("value", "")
                return base64.b64decode(raw_b64).decode("utf-8")
        except Exception:
            pass
        return ""

    def launch_app(self, package_or_name: str, stop_existing: bool = False) -> None:
        requests.post(self._url("/wda/apps/launch"), json={"bundleId": package_or_name}, timeout=5.0)

    def get_foreground_app(self) -> str:
        try:
            res = requests.get(self._url("/wda/activeAppInfo"), timeout=3.0)
            if res.status_code == 200:
                return res.json().get("value", {}).get("bundleId", "unknown")
        except Exception:
            pass
        return "unknown"

    def is_keyboard_visible(self) -> bool:
        return False
