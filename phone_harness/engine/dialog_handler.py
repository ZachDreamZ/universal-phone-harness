"""
System Dialog & Permission Interceptor.
Detects and auto-resolves permission dialogs, alert modals, and system popups.
"""

import re
from typing import List, Optional, Tuple
from phone_harness.core.models import UIElement


class SystemDialogHandler:
    """Detects and interacts with system permission and alert dialogs."""

    PERMISSION_PACKAGES = {
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.packageinstaller",
    }

    ALLOW_PATTERNS = re.compile(
        r"(?i)(while\s+using\s+the\s+app|only\s+this\s+time|allow|agree|accept|ok|continue|got\s+it|grant)"
    )

    DENY_PATTERNS = re.compile(
        r"(?i)(don'?t\s+allow|deny|cancel|dismiss|decline|reject|not\s+now|later)"
    )

    @classmethod
    def is_permission_or_alert_dialog(cls, current_package: str, elements: List[UIElement]) -> bool:
        """Checks if current foreground is a system permission or alert prompt."""
        if current_package in cls.PERMISSION_PACKAGES:
            return True

        # Check for typical dialog button combinations (Allow / Deny or OK / Cancel)
        has_allow = False
        has_deny = False
        for elem in elements:
            label = f"{elem.text or ''} {elem.description or ''}"
            if cls.ALLOW_PATTERNS.search(label):
                has_allow = True
            if cls.DENY_PATTERNS.search(label):
                has_deny = True

        return has_allow and has_deny

    @classmethod
    def find_action_button(
        cls,
        action: str,  # "allow", "deny", "dismiss"
        elements: List[UIElement],
    ) -> Optional[UIElement]:
        """Finds target button element for permission or dialog response."""
        pattern = cls.ALLOW_PATTERNS if action.lower() in ("allow", "accept", "ok") else cls.DENY_PATTERNS
        for elem in elements:
            label = (elem.text or elem.description or "").strip()
            # Ignore long prompt titles / descriptions
            if len(label) > 35:
                continue
            if pattern.search(label) and elem.is_clickable:
                return elem
        return None
