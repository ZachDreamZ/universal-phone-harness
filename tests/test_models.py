"""
Tests for Core Models & BoundingBox math.
"""

import pytest
from phone_harness.core.models import BoundingBox, UIElement, ActionRequest, ActionType, VerificationSpec


def test_bounding_box():
    box = BoundingBox(xmin=100, ymin=200, xmax=500, ymax=600)
    assert box.width == 400
    assert box.height == 400
    assert box.center == (300, 400)
    assert box.area == 160000
    assert box.contains(300, 400) is True
    assert box.contains(50, 50) is False


def test_ui_element_compact_line():
    elem = UIElement.create(
        id=3,
        type="Button",
        bounds=(100, 200, 500, 300),
        text="Submit Order",
        is_clickable=True,
        is_enabled=True,
    )
    assert elem.id == 3
    assert elem.center == (300, 250)
    compact_str = elem.to_compact_line()
    assert '[3] Button "Submit Order"' in compact_str
    assert "{100, 200, 400, 100}" in compact_str
    assert "[clickable]" in compact_str


def test_verification_spec():
    spec = VerificationSpec(
        assert_text_present=["Success", "Order #123"],
        assert_app_package="com.example.store",
        settle_ms=150,
    )
    assert len(spec.assert_text_present) == 2
    assert spec.settle_ms == 150
