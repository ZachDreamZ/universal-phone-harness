"""
Android Device Backend using ADB and Scrcpy/UIAutomator.
Provides low-latency frame extraction and input actuation for real Android hardware and emulators.
"""

import subprocess
import xml.etree.ElementTree as ET
import re
import io
import time
import shutil
import shlex
from urllib.parse import urlparse
from typing import List, Tuple, Optional
from PIL import Image

try:
    import adbutils
    _HAS_ADBUTILS = True
except ImportError:
    _HAS_ADBUTILS = False

from phone_harness.core.device import BasePhoneDevice
from phone_harness.core.models import (
    UIElement,
    DeviceSummary,
    KeyCode,
    SwipeDirection,
)
from phone_harness.core.exceptions import DeviceDisconnectedError


class AndroidPhoneDevice(BasePhoneDevice):
    """Real Android device driver interfacing via ADB."""

    platform = "android"

    KEY_MAP = {
        KeyCode.HOME: "KEYCODE_HOME",
        KeyCode.BACK: "KEYCODE_BACK",
        KeyCode.APP_SWITCH: "KEYCODE_APP_SWITCH",
        KeyCode.ENTER: "KEYCODE_ENTER",
        KeyCode.VOLUME_UP: "KEYCODE_VOLUME_UP",
        KeyCode.VOLUME_DOWN: "KEYCODE_VOLUME_DOWN",
        KeyCode.POWER: "KEYCODE_POWER",
        KeyCode.DELETE: "KEYCODE_DEL",
        KeyCode.TAB: "KEYCODE_TAB",
    }

    # Bounded fallback delete count used only when select-all is unsupported.
    _CLEAR_FALLBACK_DELETES = 64
    _PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
    _ALLOWED_URL_SCHEMES = {"http", "https"}

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._adb_bin = self._find_adb_binary()
        self._is_connected = False
        self.screen_width = 1080
        self.screen_height = 2400
        self._adb_device = None

    def _find_adb_binary(self) -> str:
        """Locates the ADB binary on the host system."""
        if _HAS_ADBUTILS:
            try:
                return adbutils.adb_path()
            except Exception:
                pass
        which_adb = shutil.which("adb")
        if which_adb:
            return which_adb
        return "adb"

    @property
    def adb_cmd(self) -> List[str]:
        cmd = [self._adb_bin]
        if self.serial:
            cmd.extend(["-s", self.serial])
        return cmd

    def _run_adb(self, args: List[str], timeout: float = 5.0) -> str:
        cmd = self.adb_cmd + args
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"ADB command failed with code {res.returncode}.")
            return res.stdout
        except subprocess.TimeoutExpired:
            raise TimeoutError("ADB command timed out.")
        except FileNotFoundError:
            raise DeviceDisconnectedError("auto", f"ADB binary '{self._adb_bin}' not found.")

    def _run_adb_bytes(self, args: List[str], timeout: float = 5.0) -> bytes:
        cmd = self.adb_cmd + args
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"ADB bytes command failed with code {res.returncode}.")
            return res.stdout
        except Exception:
            raise RuntimeError("ADB bytes command failed.")

    def connect(self) -> bool:
        try:
            # If serial not set, auto-discover first connected device
            if not self.serial and _HAS_ADBUTILS:
                try:
                    devices = adbutils.adb.device_list()
                    if devices:
                        self.serial = devices[0].serial
                        self._adb_device = devices[0]
                except Exception:
                    pass

            out = self._run_adb(["get-state"])
            self._is_connected = "device" in out.strip()
            if self._is_connected:
                # Fetch display size
                size_out = self._run_adb(["shell", "wm", "size"])
                match = re.search(r"Physical size:\s*(\d+)x(\d+)", size_out)
                if match:
                    self.screen_width = int(match.group(1))
                    self.screen_height = int(match.group(2))
            return self._is_connected
        except Exception:
            self._is_connected = False
            return False

    def disconnect(self) -> None:
        self._is_connected = False

    def is_connected(self) -> bool:
        return self._is_connected

    def get_device_summary(self) -> DeviceSummary:
        model = "Android Device"
        version = "Unknown"
        try:
            model = self._run_adb(["shell", "getprop", "ro.product.model"]).strip()
            version = self._run_adb(["shell", "getprop", "ro.build.version.release"]).strip()
        except Exception:
            pass
        active_pkg = self.get_foreground_app()
        return DeviceSummary(
            device_id=self.serial or "default-adb",
            platform="android",
            model=model or "Android Device",
            os_version=f"Android {version}",
            screen_resolution=(self.screen_width, self.screen_height),
            is_connected=self._is_connected,
            battery_level=100,
            active_package=active_pkg,
            capabilities=["fast_screencap", "uiautomator_dump", "adb_input"],
        )

    def capture_frame(self) -> Image.Image:
        """Fast ADB screen capture with fallback."""
        if _HAS_ADBUTILS and self._adb_device:
            try:
                # Direct PIL image from adbutils socket
                pil_img = self._adb_device.screenshot()
                if pil_img:
                    return pil_img.convert("RGB")
            except Exception:
                pass

        raw_bytes = self._run_adb_bytes(["exec-out", "screencap", "-p"])
        image = Image.open(io.BytesIO(raw_bytes))
        return image.convert("RGB")

    def dump_hierarchy(self) -> List[UIElement]:
        """Extracts and parses UIAutomator hierarchy XML."""
        if _HAS_ADBUTILS and self._adb_device:
            try:
                self._adb_device.shell("uiautomator dump /data/local/tmp/harness_dump.xml")
                xml_str = self._adb_device.shell("cat /data/local/tmp/harness_dump.xml")
                if xml_str and "<hierarchy" in xml_str:
                    return self._parse_uiautomator_xml(xml_str)
            except Exception:
                pass

        # Fallback via subprocess adb
        try:
            self._run_adb(["shell", "uiautomator", "dump", "/data/local/tmp/harness_dump.xml"])
            xml_str = self._run_adb(["shell", "cat", "/data/local/tmp/harness_dump.xml"])
            return self._parse_uiautomator_xml(xml_str)
        except Exception:
            return []

    def _parse_uiautomator_xml(self, xml_content: str) -> List[UIElement]:
        elements: List[UIElement] = []
        try:
            # Clean possible header noise
            idx_start = xml_content.find("<?xml")
            if idx_start == -1:
                idx_start = xml_content.find("<hierarchy")
            if idx_start != -1:
                xml_content = xml_content[idx_start:]

            root = ET.fromstring(xml_content)
            idx = 1
            for node in root.iter("node"):
                bounds_str = node.attrib.get("bounds", "")
                bounds_match = re.findall(r"\[(\d+),(\d+)\]", bounds_str)
                if len(bounds_match) != 2:
                    continue

                xmin = int(bounds_match[0][0])
                ymin = int(bounds_match[0][1])
                xmax = int(bounds_match[1][0])
                ymax = int(bounds_match[1][1])

                clazz = node.attrib.get("class", "View").split(".")[-1]
                text = node.attrib.get("text", "")
                desc = node.attrib.get("content-desc", "")
                res_id = node.attrib.get("resource-id", "")
                clickable = node.attrib.get("clickable", "false").lower() == "true"
                focusable = node.attrib.get("focusable", "false").lower() == "true"
                scrollable = node.attrib.get("scrollable", "false").lower() == "true"
                password = node.attrib.get("password", "false").lower() == "true"
                enabled = node.attrib.get("enabled", "true").lower() == "true"
                checked = None
                if "checked" in node.attrib:
                    checked = node.attrib.get("checked").lower() == "true"

                is_editable = "EditText" in clazz or (focusable and clickable)

                elem = UIElement.create(
                    id=idx,
                    type=clazz,
                    bounds=(xmin, ymin, xmax, ymax),
                    text=text if text else None,
                    description=desc if desc else None,
                    resource_id=res_id if res_id else None,
                    is_clickable=clickable,
                    is_focusable=focusable,
                    is_scrollable=scrollable,
                    is_editable=is_editable,
                    is_checked=checked,
                    is_enabled=enabled,
                    is_password=password,
                )
                elements.append(elem)
                idx += 1
        except Exception:
            pass

        return elements

    def tap(self, x: int, y: int) -> None:
        self._run_adb(["shell", "input", "tap", str(x), str(y)])

    def double_tap(self, x: int, y: int) -> None:
        self.tap(x, y)
        time.sleep(0.08)
        self.tap(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._run_adb(["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)])

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 250) -> None:
        self._run_adb([
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration_ms),
        ])

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

    def _adbkeyboard_ready(self) -> bool:
        """Return True only when ``com.android.adbkeyboard`` is installed (an
        enabled IME) AND is the current default input method, queried via ADB.

        This evidence is required before an ``ADB_INPUT_B64`` broadcast may be
        trusted as delivered. A bare ``result=0`` is not receiver proof: on stock
        Android a broadcast with no registered receiver can still report
        ``result=0``. Without this evidence we must not send the broadcast and
        instead fall through to clipboard / input text.
        """
        try:
            enabled = self._run_adb(["shell", "ime", "list", "-s"]).lower()
            if "adbkeyboard" not in enabled:
                return False
            default = self._run_adb(
                ["shell", "settings", "get", "secure", "default_input_method"]
            ).lower()
            return "adbkeyboard" in default
        except Exception:
            return False

    def _broadcast_delivered(self, output: str) -> bool:
        """A broadcast is treated as handled only when ADB reports a success
        result code. The generic 'Broadcast completed' line is emitted even when
        no receiver is registered, so it does not prove the input was delivered.
        """
        return "result=0" in output

    def type_text(self, text: str, clear_existing: bool = False, press_enter: bool = False, fast_paste: bool = True) -> None:
        if clear_existing:
            self.clear_text()

        # If text contains unicode or special characters, try ADBKeyboard base64
        # broadcast -- but ONLY when its receiver (com.android.adbkeyboard) is
        # installed and is the active default IME. Without that evidence we must
        # not send the broadcast and instead fall through to clipboard / input.
        has_unicode = any(ord(c) > 127 or c in "\"'$`\\#&|;<>~" for c in text)
        if has_unicode or fast_paste:
            if self._adbkeyboard_ready():
                try:
                    import base64
                    b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
                    res = self._run_adb(["shell", "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64])
                    if self._broadcast_delivered(res):
                        if press_enter:
                            self.press_key(KeyCode.ENTER)
                        return
                except Exception:
                    pass

        # Fast clipboard paste fallback
        if fast_paste and (has_unicode or len(text) > 12):
            try:
                self.set_clipboard(text)
                self.press_key(KeyCode.PASTE) if hasattr(KeyCode, "PASTE") else self._run_adb(["shell", "input", "keyevent", "279"])
                if press_enter:
                    self.press_key(KeyCode.ENTER)
                return
            except Exception:
                pass

        # Standard keystroke fallback
        escaped_text = text.replace(" ", "%s")
        self._run_adb(["shell", "input", "text", shlex.quote(escaped_text)])
        if press_enter:
            self.press_key(KeyCode.ENTER)

    def set_clipboard(self, text: str) -> None:
        """Set the Android clipboard.

        Raises ``RuntimeError`` if the clipboard could not be set OR if the set
        could not be confirmed by read-back (readback differs from the input, or
        the read-back could not be performed). Callers such as ``type_text`` catch
        this and fall through to another input path instead of reporting a
        successful paste after a silently-failed or unconfirmed set.
        """
        import base64
        b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")

        # ADBKeyboard broadcast (requires the receiver to be active). A missing
        # receiver here is non-fatal: the primary setter below is authoritative.
        try:
            self._run_adb(["shell", "am", "broadcast", "-a", "ADB_SET_CLIPBOARD_B64", "--es", "msg", b64])
        except Exception:  # noqa: BLE001
            pass

        # Primary setter via the Android clipboard service. A failed set is an
        # immediate, propagated error (no silent success).
        try:
            res = self._run_adb(["shell", "cmd", "clipboard", "set", shlex.quote(text)])
        except Exception:  # noqa: BLE001
            # Leak-free failure: the underlying exception, the clipboard text, the
            # command, and any base64 are intentionally NOT included in the message
            # so secret content can never surface through error strings.
            raise RuntimeError("clipboard set operation failed")
        if "No shell command" in res:
            # Command output is never echoed into the message.
            raise RuntimeError("clipboard service unavailable")

        # Confirm by read-back. If the clipboard content differs from the input,
        # or the read-back cannot be performed, raise so callers fall through
        # rather than reporting a successful paste.
        try:
            actual = self.get_clipboard()
        except Exception:  # noqa: BLE001
            raise RuntimeError("clipboard readback could not be confirmed")
        if actual != text:
            # Generic mismatch: do NOT echo the requested text or the read-back
            # value, which may both be secret.
            raise RuntimeError("clipboard content mismatch after set")

    def get_clipboard(self) -> str:
        """Gets clipboard from Android device."""
        if _HAS_ADBUTILS and self._adb_device:
            try:
                res = self._adb_device.shell("cmd clipboard get").strip()
                if "No shell command" not in res:
                    return res
            except Exception:
                pass
        return self._run_adb(["shell", "cmd", "clipboard", "get"]).strip()

    def open_url(self, url: str) -> None:
        """Open an HTTP or HTTPS URL through Android's View intent."""
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() not in self._ALLOWED_URL_SCHEMES or not parsed_url.netloc:
            raise ValueError("URL must use HTTP or HTTPS and include a host.")
        self._run_adb(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                shlex.quote(url),
            ]
        )

    def open_settings_section(self, section: str) -> None:
        """Opens specific Android settings section."""
        sec_map = {
            "wifi": "android.settings.WIFI_SETTINGS",
            "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
            "display": "android.settings.DISPLAY_SETTINGS",
            "battery": "android.intent.action.POWER_USAGE_SUMMARY",
            "apps": "android.settings.APPLICATION_SETTINGS",
            "sound": "android.settings.SOUND_SETTINGS",
            "date": "android.settings.DATE_SETTINGS",
            "accessibility": "android.settings.ACCESSIBILITY_SETTINGS",
        }
        action = sec_map.get(section.lower(), "android.settings.SETTINGS")
        self._run_adb(["shell", "am", "start", "-a", action])

    def clear_text(self) -> None:
        """Clear text from the focused input using the fast, hardware-validated
        single-call path (Task 6).

        Primary path — ONE constant-only host ADB ``shell`` call:
            input keyevent KEYCODE_MOVE_END && input keyevent --longpress KEYCODE_DEL
        Observed on a connected Huawei Android 12 Settings search field: this
        clears the entire field in a single keystroke (caret-to-start long-press
        delete), ~79 ms vs ~1.1 s for the prior 64-delete baseline.

        Fallback — ONLY when the primary command raises (e.g. unsupported flags
        or a transient ADB error), run a bounded 64-delete burst as a SINGLE
        constant-only host ADB ``shell`` call. If the fallback also fails, its
        exception propagates to the caller.

        No user-supplied content is interpolated; every token is a compile-time
        constant, so this method is safe for arbitrary field contents.
        """
        primary = (
            "input keyevent KEYCODE_MOVE_END && input keyevent --longpress KEYCODE_DEL"
        )
        try:
            # Primary fast path: a single host ADB shell call.
            self._run_adb(["shell", primary])
        except Exception:
            # Bounded 64-delete fallback (also a single constant-only shell call).
            # If the fallback itself fails, its exception propagates to the caller.
            deletes = " ".join(["KEYCODE_DEL"] * self._CLEAR_FALLBACK_DELETES)
            self._run_adb(["shell", f"input keyevent {deletes}"])

    def press_key(self, key: KeyCode) -> None:
        key_code = self.KEY_MAP.get(key, "KEYCODE_UNKNOWN")
        self._run_adb(["shell", "input", "keyevent", key_code])

    def launch_app(self, package_or_name: str, stop_existing: bool = False) -> None:
        if self._PACKAGE_PATTERN.fullmatch(package_or_name) is None:
            raise ValueError("Android app launch requires a valid package identifier.")
        safe_package = shlex.quote(package_or_name)
        if stop_existing:
            self._run_adb(["shell", "am", "force-stop", safe_package])
        self._run_adb(["shell", "monkey", "-p", safe_package, "-c", "android.intent.category.LAUNCHER", "1"])

    def get_foreground_app(self) -> str:
        try:
            if _HAS_ADBUTILS and self._adb_device:
                out = self._adb_device.shell("dumpsys window | grep mCurrentFocus")
                match = re.search(r"mCurrentFocus=Window\{[^\}]*\s+([^\/\}\s]+)", out)
                if match and match.group(1) != "null":
                    return match.group(1)

                # Fallback to activity top
                out_act = self._adb_device.shell("dumpsys activity top | grep ACTIVITY")
                match_act = re.search(r"ACTIVITY\s+([^\/\s]+)", out_act)
                if match_act:
                    return match_act.group(1)
        except Exception:
            pass

        try:
            out = self._run_adb(["shell", "dumpsys", "window", "windows"])
            match = re.search(r"mCurrentFocus=Window\{[^\}]*\s+([^\/\}\s]+)", out)
            if match:
                return match.group(1)
        except Exception:
            pass
        return "unknown"

    def is_keyboard_visible(self) -> bool:
        try:
            out = self._run_adb(["shell", "dumpsys", "input_method"])
            return "mInputShown=true" in out or "mIsInputViewShown=true" in out
        except Exception:
            return False
