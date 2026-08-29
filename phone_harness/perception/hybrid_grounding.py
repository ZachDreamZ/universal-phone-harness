"""
Hybrid Grounding Engine.
Resolves agent intent (Index, Text, Coordinates, or Semantic descriptor) into verified physical targets.
"""

from typing import List, Optional, Tuple
from phone_harness.core.models import UIElement, ActionRequest
from phone_harness.core.exceptions import ElementNotFoundError, AmbiguousTargetError
from phone_harness.perception.ocr_matcher import TextMatcher
from phone_harness.perception.tree_simplifier import TreeSimplifier


class HybridGroundingEngine:
    """Fuses structured accessibility index and fuzzy textual recognition to resolve action targets."""

    @classmethod
    def resolve_target_element(
        cls,
        action_req: ActionRequest,
        elements: List[UIElement],
        screen_size: Tuple[int, int] = (1080, 2400),
    ) -> Tuple[int, int, Optional[UIElement]]:
        """
        Resolves the exact (x, y) physical screen coordinates and matching UIElement.
        Returns: (x, y, matched_element)
        """
        # 1. Exact integer badge index (Highest precedence & most deterministic)
        if action_req.target_index is not None:
            for elem in elements:
                if elem.id == action_req.target_index:
                    return (elem.center[0], elem.center[1], elem)

            # Element not found by index
            compact_summary = TreeSimplifier.generate_compact_dom(elements[:8])
            raise ElementNotFoundError(
                target=f"Badge Index [{action_req.target_index}]",
                available_elements_summary=compact_summary,
            )

        # 2. Text query matching
        if action_req.target_text is not None:
            matches = TextMatcher.find_all_matches(action_req.target_text, elements, threshold=0.75)
            if not matches:
                # Try lower threshold fallback
                fallback_match = TextMatcher.find_best_match(action_req.target_text, elements, threshold=0.55)
                if fallback_match:
                    elem, _ = fallback_match
                    return (elem.center[0], elem.center[1], elem)

                compact_summary = TreeSimplifier.generate_compact_dom(elements[:8])
                raise ElementNotFoundError(
                    target=f"Text '{action_req.target_text}'",
                    available_elements_summary=compact_summary,
                )

            if len(matches) > 1 and matches[0][1] == matches[1][1]:
                # Ambiguous ties (e.g. multiple identical "Next" buttons)
                matched_ids = [m[0].id for m in matches]
                raise AmbiguousTargetError(
                    query=action_req.target_text,
                    match_count=len(matches),
                    matched_indexes=matched_ids,
                )

            best_elem = matches[0][0]
            return (best_elem.center[0], best_elem.center[1], best_elem)

        # 3. Direct physical or normalized coordinate
        if action_req.x is not None and action_req.y is not None:
            target_x = action_req.x
            target_y = action_req.y

            # If normalized 0.0 - 1.0 coords passed by mistake, convert to physical pixels
            if 0.0 <= target_x <= 1.0 and 0.0 <= target_y <= 1.0:
                target_x = int(target_x * screen_size[0])
                target_y = int(target_y * screen_size[1])

            # Prefer the smallest interactive element containing the point. Large
            # parent containers often overlap their actionable children.
            containing_elements = [
                element
                for element in elements
                if element.bounds[0] <= target_x <= element.bounds[2]
                and element.bounds[1] <= target_y <= element.bounds[3]
            ]
            interactive_elements = [
                element
                for element in containing_elements
                if element.is_clickable or element.is_editable or element.is_focusable
            ]
            candidates = interactive_elements if interactive_elements else containing_elements
            matched_elem = min(
                candidates,
                key=lambda element: (element.bounds[2] - element.bounds[0])
                * (element.bounds[3] - element.bounds[1]),
                default=None,
            )

            return (target_x, target_y, matched_elem)

        raise ElementNotFoundError(target="None (No index, text, or coordinates provided)")
