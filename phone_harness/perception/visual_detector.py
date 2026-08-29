"""
Vision & OCR Fallback Detector.
Extracts interactive UI elements from raw pixel frames when accessibility trees are empty or blocked (Flutter, Unity, Canvas, WebViews).
"""

from typing import List, Tuple, Optional
from PIL import Image

from phone_harness.core.models import UIElement

try:
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    _HAS_RAPID_OCR = True
    _ocr_engine = RapidOCR()
except Exception:
    np = None
    _HAS_RAPID_OCR = False
    _ocr_engine = None


class VisualElementDetector:
    """Detects text and clickable regions directly from image pixels using local fast OCR."""

    @classmethod
    def is_available(cls) -> bool:
        return _HAS_RAPID_OCR and _ocr_engine is not None

    @classmethod
    def detect_elements_from_image(
        cls,
        image: Image.Image,
        min_box_size: int = 15,
    ) -> List[UIElement]:
        """
        Runs fast local OCR to detect text bounding boxes and constructs UIElement list.
        """
        if not cls.is_available():
            return []

        img_np = np.array(image)
        try:
            result, _ = _ocr_engine(img_np)
        except Exception:
            return []

        if not result:
            return []

        elements: List[UIElement] = []
        for idx, item in enumerate(result, start=1):
            box, text, score = item
            if score < 0.45 or not text.strip():
                continue

            # box is [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            xmin = int(min(xs))
            ymin = int(min(ys))
            xmax = int(max(xs))
            ymax = int(max(ys))

            w = xmax - xmin
            h = ymax - ymin
            if w < min_box_size or h < min_box_size:
                continue

            elem = UIElement.create(
                id=idx,
                type="VisionText",
                bounds=(xmin, ymin, xmax, ymax),
                text=text.strip(),
                description=f"OCR Visual Element (conf: {score:.2f})",
                is_clickable=True,
                is_focusable=True,
                is_enabled=True,
            )
            elements.append(elem)

        return elements
