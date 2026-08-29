"""
Fuzzy Text & Semantic Matcher.
Enables reliable resolution of user-specified strings ("Settings", "Submit", "Sign In") to target elements.
"""

import re
import difflib
from typing import List, Optional, Tuple
from phone_harness.core.models import UIElement


class TextMatcher:
    """Matches text queries against UIElement text, description, and resource IDs."""

    @classmethod
    def _normalize(cls, s: str) -> str:
        if not s:
            return ""
        # Remove non-alphanumeric characters for normalized comparison
        return re.sub(r"[^a-zA-Z0-9\s]", "", s).strip().lower()

    @classmethod
    def similarity(cls, s1: str, s2: str) -> float:
        """Calculates normalized sequence and token-overlap ratio between two strings."""
        if not s1 or not s2:
            return 0.0

        s1_raw = s1.strip().lower()
        s2_raw = s2.strip().lower()

        if s1_raw == s2_raw:
            return 1.0

        # Substring exact check
        if s1_raw in s2_raw or s2_raw in s1_raw:
            return 0.95

        # Normalized alphanumeric check (e.g. "wifi" vs "wi-fi")
        norm1 = cls._normalize(s1_raw)
        norm2 = cls._normalize(s2_raw)
        norm1_no_space = norm1.replace(" ", "")
        norm2_no_space = norm2.replace(" ", "")

        if norm1 == norm2:
            return 1.0
        if norm1_no_space and norm2_no_space:
            if norm1_no_space in norm2_no_space or norm2_no_space in norm1_no_space:
                return 0.90

        # Token set overlap
        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())
        if tokens1 and tokens2:
            intersection = tokens1.intersection(tokens2)
            if intersection:
                overlap_ratio = len(intersection) / min(len(tokens1), len(tokens2))
                if overlap_ratio >= 1.0:
                    return 0.85 + 0.1 * (len(intersection) / max(len(tokens1), len(tokens2)))

        return max(
            difflib.SequenceMatcher(None, s1_raw, s2_raw).ratio(),
            difflib.SequenceMatcher(None, norm1, norm2).ratio(),
        )

    @classmethod
    def find_best_match(
        cls,
        query: str,
        elements: List[UIElement],
        threshold: float = 0.60,
    ) -> Optional[Tuple[UIElement, float]]:
        """
        Finds the element with the highest fuzzy match score for the given query string.
        """
        if not query or not elements:
            return None

        best_elem: Optional[UIElement] = None
        best_score = 0.0

        for elem in elements:
            # Check text
            score_text = cls.similarity(query, elem.text or "")
            # Check description
            score_desc = cls.similarity(query, elem.description or "")
            # Check resource_id (short name)
            score_res = 0.0
            if elem.resource_id:
                res_short = elem.resource_id.split("/")[-1]
                score_res = cls.similarity(query, res_short)

            max_elem_score = max(score_text, score_desc, score_res)
            if max_elem_score > best_score:
                best_score = max_elem_score
                best_elem = elem

        if best_elem and best_score >= threshold:
            return (best_elem, best_score)
        return None

    @classmethod
    def find_all_matches(
        cls,
        query: str,
        elements: List[UIElement],
        threshold: float = 0.70,
    ) -> List[Tuple[UIElement, float]]:
        """Finds all candidate elements matching the text query above the threshold."""
        matches = []
        for elem in elements:
            score_text = cls.similarity(query, elem.text or "")
            score_desc = cls.similarity(query, elem.description or "")
            score = max(score_text, score_desc)
            if score >= threshold:
                matches.append((elem, score))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

