"""
Abstract base class for all phone device drivers (Android, iOS, Mock).
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from PIL import Image

from phone_harness.core.models import (
    UIElement,
    DeviceSummary,
    KeyCode,
    SwipeDirection,
)


class BasePhoneDevice(ABC):
    """Abstract interface for mobile device hardware/protocol abstraction."""

    # Stable platform identity. Concrete backends override this class constant
    # (e.g. "android", "ios", "mock") so selection logic can reason about the
    # active device without probing hardware.
    platform: str = "unknown"

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the target device."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and clean up resources."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if device is currently online and responsive."""
        pass

    @abstractmethod
    def get_device_summary(self) -> DeviceSummary:
        """Return high-level metadata, battery, OS version, and resolution."""
        pass

    @abstractmethod
    def capture_frame(self) -> Image.Image:
        """Capture the current screen framebuffer as a PIL Image."""
        pass

    @abstractmethod
    def dump_hierarchy(self) -> List[UIElement]:
        """Extract the accessibility node hierarchy as structured UIElement objects."""
        pass

    @abstractmethod
    def tap(self, x: int, y: int) -> None:
        """Inject a single tap at the given physical screen coordinates."""
        pass

    @abstractmethod
    def double_tap(self, x: int, y: int) -> None:
        """Inject a double tap at physical screen coordinates."""
        pass

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Inject a long press gesture."""
        pass

    @abstractmethod
    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 250,
    ) -> None:
        """Inject a drag/swipe gesture from start to end coordinates."""
        pass

    @abstractmethod
    def swipe_directional(
        self,
        direction: SwipeDirection,
        distance: str = "medium",
        duration_ms: int = 250,
    ) -> None:
        """Helper to perform standard directional swipes (up, down, left, right)."""
        pass

    @abstractmethod
    def type_text(self, text: str, clear_existing: bool = False, press_enter: bool = False, fast_paste: bool = False) -> None:
        """Type text into currently focused input field."""
        pass

    @abstractmethod
    def clear_text(self) -> None:
        """Clear text from the active input field."""
        pass

    @abstractmethod
    def press_key(self, key: KeyCode) -> None:
        """Trigger a physical or software navigation key."""
        pass

    @abstractmethod
    def launch_app(self, package_or_name: str, stop_existing: bool = False) -> None:
        """Launch an application by platform package or bundle identifier."""
        pass

    @abstractmethod
    def open_url(self, url: str) -> None:
        """Open a validated HTTP or HTTPS URL in the default browser."""
        pass

    @abstractmethod
    def open_settings_section(self, section: str) -> None:
        """Opens a specific system settings page (wifi, bluetooth, apps, display, battery, etc.)."""
        pass

    @abstractmethod
    def set_clipboard(self, text: str) -> None:
        """Copies text directly to device system clipboard."""
        pass

    @abstractmethod
    def get_clipboard(self) -> str:
        """Reads text from device system clipboard."""
        pass

    @abstractmethod
    def get_foreground_app(self) -> str:
        """Get the package name of the currently active app."""
        pass

    @abstractmethod
    def is_keyboard_visible(self) -> bool:
        """Check if the soft keyboard (IME) is displayed on screen."""
        pass

