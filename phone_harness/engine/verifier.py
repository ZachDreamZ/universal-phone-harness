"""
Zero-Mistake Closed-Loop State Verification Engine.
Performs pre-condition checks, animation settle detection, perceptual hash diffing, and post-action assertions.
"""

import time
import hashlib
from typing import List, Optional, Tuple
from PIL import Image

from phone_harness.core.models import (
    UIElement,
    PhoneState,
    VerificationSpec,
    ActionRequest,
)
from phone_harness.core.exceptions import AssertionFailedError, PhoneHarnessError
from phone_harness.perception.tree_simplifier import TreeSimplifier


class ZeroMistakeVerifier:
    """Verifies that actions produce the expected state transitions without hallucination."""

    @classmethod
    def calculate_perceptual_hash(cls, image: Image.Image) -> str:
        """Computes a fast 64-bit perceptual image hash for change/settle detection."""
        resized = image.resize((8, 8), Image.Resampling.LANCZOS).convert("L")
        pixels = list(resized.tobytes())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p > avg else "0" for p in pixels)
        return hex(int(bits, 2))[2:].zfill(16)

    @classmethod
    def calculate_tree_hash(cls, elements: List[UIElement]) -> str:
        """Computes SHA256 digest of interactive element labels and positions."""
        content = "|".join(f"{e.id}:{e.text}:{e.bounds}" for e in elements)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def verify_pre_conditions(
        cls,
        action_req: ActionRequest,
        target_elem: Optional[UIElement],
    ) -> None:
        """Ensures the target element is enabled and interactable before firing input."""
        if target_elem:
            if not target_elem.is_enabled:
                raise PhoneHarnessError(
                    f"Target element [{target_elem.id}] '{target_elem.text or target_elem.type}' is currently disabled."
                )

    @classmethod
    def evaluate_post_assertions(
        cls,
        spec: VerificationSpec,
        new_state: PhoneState,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates explicit assertions against the new post-action state.
        Returns: (passed: bool, failure_reason: Optional[str])
        """
        compact_dom_lower = new_state.compact_dom.lower()

        # 1. Assert text presence
        if spec.assert_text_present:
            for text in spec.assert_text_present:
                if text.lower() not in compact_dom_lower:
                    return (
                        False,
                        f"Expected text '{text}' was NOT found on screen after action.",
                    )

        # 2. Assert text absence
        if spec.assert_text_absent:
            for text in spec.assert_text_absent:
                if text.lower() in compact_dom_lower:
                    return (
                        False,
                        f"Prohibited text '{text}' was still present on screen after action.",
                    )

        # 3. Assert foreground package
        if spec.assert_app_package:
            if spec.assert_app_package.lower() not in new_state.current_app_package.lower():
                return (
                    False,
                    f"Expected foreground app '{spec.assert_app_package}', but got '{new_state.current_app_package}'.",
                )

        # 4. Assert element exists with specific criteria
        if spec.assert_element_exists:
            matched = False
            for elem in new_state.elements:
                match_all = True
                for k, v in spec.assert_element_exists.items():
                    elem_val = getattr(elem, k, None)
                    if elem_val != v and str(v).lower() not in str(elem_val).lower():
                        match_all = False
                        break
                if match_all:
                    matched = True
                    break
            if not matched:
                return (
                    False,
                    f"Element matching criteria {spec.assert_element_exists} was not found.",
                )

        return (True, None)
