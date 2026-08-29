"""
Tests for Tree Simplifier & Token Compaction.
"""

from phone_harness.core.models import UIElement
from phone_harness.perception.tree_simplifier import TreeSimplifier


def test_tree_simplifier_pruning():
    raw_elements = [
        # Layout container with no text or clicks (should be pruned)
        UIElement.create(99, "FrameLayout", (0, 0, 1080, 2400), is_clickable=False),
        # Interactive Button (should be kept)
        UIElement.create(101, "Button", (100, 300, 500, 400), text="Sign In", is_clickable=True),
        # Offscreen element (should be pruned)
        UIElement.create(102, "Button", (100, 3000, 500, 3100), text="Offscreen", is_clickable=True),
        # Zero dimension element (should be pruned)
        UIElement.create(103, "TextView", (100, 100, 100, 100), text="Zero"),
        # Informative TextView (should be kept)
        UIElement.create(104, "TextView", (100, 150, 900, 250), text="Account Details"),
    ]

    indexed = TreeSimplifier.filter_and_index_elements(raw_elements, screen_size=(1080, 2400), interactive_only=True)

    assert len(indexed) == 2
    assert indexed[0].id == 1
    assert indexed[0].text == "Account Details"  # Spatial sort (y=150 is above y=300)
    assert indexed[1].id == 2
    assert indexed[1].text == "Sign In"

    compact_dom = TreeSimplifier.generate_compact_dom(indexed)
    assert "[1] TextView \"Account Details\"" in compact_dom
    assert "[2] Button \"Sign In\"" in compact_dom


def test_compact_dom_respects_character_budget():
    elements = [
        UIElement.create(
            index,
            "Button",
            (0, index * 10, 100, index * 10 + 9),
            text=f"Button {index} with a long descriptive label",
        )
        for index in range(1, 101)
    ]
    compact_dom = TreeSimplifier.generate_compact_dom(elements, max_tokens=40)
    assert len(compact_dom) <= 160
    assert compact_dom.endswith("[truncated]")


def test_non_positive_compact_budget_returns_empty_output():
    element = UIElement.create(1, "Button", (0, 0, 100, 100), text="Button")
    assert TreeSimplifier.generate_compact_dom([element], max_tokens=0) == ""


def test_tiny_positive_budget_marker_cannot_fit_returns_empty():
    element = UIElement.create(1, "Button", (0, 0, 100, 100), text="Button")
    for max_tokens in (1, 2):
        out = TreeSimplifier.generate_compact_dom([element], max_tokens=max_tokens)
        hard_cap = max_tokens * TreeSimplifier.CHARS_PER_TOKEN
        assert len(out) <= hard_cap
        # The 11-char marker cannot fit in 4 or 8 chars, so the only
        # complete output is an empty string (never a partial marker).
        assert out == ""


def test_tiny_positive_budget_marker_fits_returns_complete_marker():
    # Element line is far longer than the tiny budget, so no element fits,
    # but the truncation marker fits on its own.
    element = UIElement.create(
        1,
        "Button",
        (0, 0, 100, 100),
        text="A label that is intentionally far too long for a tiny budget",
    )
    out = TreeSimplifier.generate_compact_dom([element], max_tokens=3)
    hard_cap = 3 * TreeSimplifier.CHARS_PER_TOKEN
    assert len(out) <= hard_cap
    # The only valid complete output is the full marker; never a truncated one.
    assert out == TreeSimplifier.TRUNCATION_MARKER
    assert out == "[truncated]"
