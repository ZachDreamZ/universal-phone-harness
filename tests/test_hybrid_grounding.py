"""
Tests for Hybrid Grounding Engine & Fuzzy Text Resolution.
"""

import pytest
from phone_harness.core.models import UIElement, ActionRequest, ActionType
from phone_harness.core.exceptions import ElementNotFoundError, AmbiguousTargetError
from phone_harness.perception.hybrid_grounding import HybridGroundingEngine


def test_resolve_by_index():
    elements = [
        UIElement.create(1, "Button", (100, 100, 300, 200), text="Home"),
        UIElement.create(2, "Button", (100, 300, 500, 400), text="Settings"),
    ]
    req = ActionRequest(action=ActionType.TAP, target_index=2)
    x, y, elem = HybridGroundingEngine.resolve_target_element(req, elements)

    assert x == 300
    assert y == 350
    assert elem is not None
    assert elem.id == 2


def test_resolve_by_fuzzy_text():
    elements = [
        UIElement.create(1, "Button", (100, 100, 300, 200), text="Wi-Fi Connections"),
        UIElement.create(2, "Button", (100, 300, 500, 400), text="Bluetooth Audio"),
    ]
    req = ActionRequest(action=ActionType.TAP, target_text="wifi")
    x, y, elem = HybridGroundingEngine.resolve_target_element(req, elements)

    assert elem is not None
    assert elem.id == 1
    assert x == 200
    assert y == 150


def test_resolve_missing_element_raises():
    elements = [UIElement.create(1, "Button", (100, 100, 300, 200), text="Home")]
    req = ActionRequest(action=ActionType.TAP, target_index=99)
    with pytest.raises(ElementNotFoundError):
        HybridGroundingEngine.resolve_target_element(req, elements)
