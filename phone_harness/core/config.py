"""
Configuration settings for Phone Harness.
"""

from typing import Tuple
from pydantic import BaseModel, Field


class HarnessConfig(BaseModel):
    # Device defaults
    # Fail-closed default: target connected Android and raise on failure
    # rather than silently falling back to the offline Mock backend.
    default_platform: str = "android"  # "android", "ios", "mock"
    allow_mock_fallback: bool = False  # only when explicitly enabled
    default_device_id: str = "auto"
    screen_resolution: Tuple[int, int] = (1080, 2400)

    # Timing & Delays
    default_settle_ms: int = 100
    default_timeout_ms: int = 3000
    swipe_duration_ms: int = 250
    typing_delay_ms: int = 15

    # Perception & Token Optimization
    filter_interactive_only: bool = True
    max_tokens_compact_dom: int = 600
    max_tokens_action_dom: int = 200
    som_badge_font_size: int = 20
    som_badge_color: Tuple[int, int, int] = (230, 40, 40)
    som_text_color: Tuple[int, int, int] = (255, 255, 255)
    som_box_thickness: int = 3

    # Zero-Mistake & Safety
    enable_zero_mistake_verification: bool = True
    enable_destructive_safety_gate: bool = True
    enable_loop_detection: bool = True
    max_loop_threshold: int = 3
    max_step_budget: int = 15
    enable_pii_masking: bool = True

    # Image Quality
    jpeg_quality: int = 80
    max_image_dimension: int = 1280


DEFAULT_CONFIG = HarnessConfig()
