"""
Antigravity (AGY) Plugin & Skill Integration for Phone Harness.
Exposes specialized prompt templates, tool mappings, and workflow macros for Antigravity agents.
"""

from typing import Dict, Any

ANTIGRAVITY_PHONE_SKILL = {
    "name": "phone-harness",
    "description": "Token-efficient mobile automation harness for Android and iOS. Enables agents to observe compacted UI trees, use generation-bound indexes, type text, swipe, and assert state transitions.",
    "tools": [
        "phone_observe",
        "phone_tap",
        "phone_type",
        "phone_swipe",
        "phone_press_key",
        "phone_open_app",
        "phone_assert_state",
        "phone_health_check",
    ],
    "system_instructions": """
When controlling the mobile phone:
1. ALWAYS call `phone_observe()` first to retrieve the current indexed compact DOM tree and observation generation.
2. Refer to UI elements by integer badge index and pass the matching `observation_generation` instead of predicting coordinates.
3. For text entry, pass `index`, `observation_generation`, and `text` to `phone_type`.
4. If an action changes screens or submits forms, provide a `verify` spec with `assert_text_present` or `assert_app_package`.
5. Never pass `confirm_destructive=True` unless the user explicitly requested the destructive action.
""",
}
