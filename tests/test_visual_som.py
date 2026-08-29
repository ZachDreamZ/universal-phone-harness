"""
Tests for Visual Set-of-Marks (SoM) Generator.
"""

from PIL import Image
from phone_harness.core.models import UIElement
from phone_harness.perception.visual_som import VisualSoMAnnotator


def test_visual_som_generation():
    img = Image.new("RGB", (400, 800), color=(255, 255, 255))
    elements = [
        UIElement.create(1, "Button", (50, 100, 350, 180), text="Click Me", is_clickable=True),
        UIElement.create(2, "EditText", (50, 220, 350, 300), text="Password", is_password=True),
    ]

    annotated = VisualSoMAnnotator.annotate(img, elements, mask_passwords=True)
    assert annotated.size == (400, 800)

    b64_str = VisualSoMAnnotator.to_base64_jpeg(annotated)
    assert len(b64_str) > 100
