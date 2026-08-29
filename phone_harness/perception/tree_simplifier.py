"""
Tree Simplifier & Token Compactor.
Transforms bloated accessibility trees into token-efficient, LLM-ready representations.
"""

from typing import List, Tuple
from phone_harness.core.models import UIElement


class TreeSimplifier:
    """Prunes noise from accessibility trees and formats compact token-efficient representations."""

    TRUNCATION_MARKER = "[truncated]"

    # Heuristic tokens->characters ratio used to bound the emitted compact DOM.
    CHARS_PER_TOKEN = 4

    IGNORED_TYPES = {
        "FrameLayout",
        "LinearLayout",
        "RelativeLayout",
        "CoordinatorLayout",
        "ConstraintLayout",
        "ViewGroup",
        "ViewStub",
        "CardView",
        "UIStackView",
        "UIView",
    }

    @classmethod
    def filter_and_index_elements(
        cls,
        raw_elements: List[UIElement],
        screen_size: Tuple[int, int] = (1080, 2400),
        interactive_only: bool = True,
    ) -> List[UIElement]:
        """
        Filters out non-interactive layout containers, off-screen nodes,
        and assigns sequential 1-based integer badge IDs.
        """
        screen_w, screen_h = screen_size
        filtered: List[UIElement] = []

        for elem in raw_elements:
            xmin, ymin, xmax, ymax = elem.bounds
            w = xmax - xmin
            h = ymax - ymin

            # 1. Ignore zero/negative dimension elements
            if w <= 0 or h <= 0:
                continue

            # 2. Ignore completely off-screen elements
            if xmax < 0 or ymax < 0 or xmin >= screen_w or ymin >= screen_h:
                continue

            # 3. Filter layout containers if interactive_only is True
            if interactive_only:
                is_interactive = (
                    elem.is_clickable
                    or elem.is_focusable
                    or elem.is_scrollable
                    or elem.is_editable
                    or (elem.text is not None and len(elem.text.strip()) > 0)
                    or (elem.description is not None and len(elem.description.strip()) > 0)
                )
                if not is_interactive:
                    continue

                # If it's a generic layout container with no direct text or clickability, skip it
                if elem.type in cls.IGNORED_TYPES and not elem.is_clickable and not elem.text:
                    continue

            filtered.append(elem)

        # Sort elements spatially (top-to-bottom, left-to-right) for deterministic, intuitive numbering
        filtered.sort(key=lambda e: (e.bounds[1] // 50, e.bounds[0]))

        # Re-index elements monotonically: 1, 2, 3, ...
        indexed_elements: List[UIElement] = []
        for idx, elem in enumerate(filtered, start=1):
            elem.id = idx
            # Recompute center
            xmin, ymin, xmax, ymax = elem.bounds
            elem.center = (xmin + (xmax - xmin) // 2, ymin + (ymax - ymin) // 2)
            indexed_elements.append(elem)

        return indexed_elements

    @classmethod
    def generate_compact_dom(
        cls,
        elements: List[UIElement],
        max_tokens: int = 600,
    ) -> str:
        """
        Generates a token-compacted multiline string representation of the UI elements.
        Format: [ID] TYPE "LABEL / TEXT" {x, y, w, h} [FLAGS]

        The output is bounded to ``max_tokens * CHARS_PER_TOKEN`` characters. Lines are
        emitted whole: a candidate line that would overflow the budget is dropped rather
        than truncated mid-element, and a ``[truncated]`` marker is appended when not all
        elements fit. A non-positive budget returns an empty string.
        """
        if max_tokens <= 0:
            return ""

        if not elements:
            return "No interactive elements detected on screen."

        budget = max_tokens * cls.CHARS_PER_TOKEN
        marker = cls.TRUNCATION_MARKER
        total = len(elements)

        lines: List[str] = []
        joined_len = 0
        for idx, elem in enumerate(elements):
            line = elem.to_compact_line()
            more_remaining = idx < total - 1

            # Project length if we append this whole line, plus the marker when the
            # following elements still cannot fit. This guarantees we never emit a
            # partial element line and always leave room for the marker.
            add_len = len(line) + (1 if lines else 0)
            projected = joined_len + add_len
            if more_remaining:
                projected += len(marker) + 1

            if projected > budget:
                break

            lines.append(line)
            joined_len += add_len

        if len(lines) < total:
            if lines:
                return "\n".join(lines) + "\n" + marker
            # No element line fit. Emit the marker only if it fits within budget;
            # otherwise return an empty string so we never emit a partial marker.
            if len(marker) <= budget:
                return marker
            return ""

        return "\n".join(lines)
