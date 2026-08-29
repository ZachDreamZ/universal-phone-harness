"""
Set-of-Marks (SoM) Visual Overlay Generator.
Renders high-contrast bounding boxes and numbered index badges on phone screenshots for Multimodal LLMs.
"""

import io
import base64
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from phone_harness.core.models import UIElement


class VisualSoMAnnotator:
    """Generates Set-of-Marks annotated images for multimodal reasoning."""

    DEFAULT_PALETTE = [
        (230, 40, 40),    # Red
        (40, 120, 230),   # Blue
        (30, 180, 80),    # Green
        (230, 140, 20),   # Orange
        (160, 40, 200),   # Purple
        (0, 180, 200),    # Cyan
    ]

    @classmethod
    def annotate(
        cls,
        image: Image.Image,
        elements: List[UIElement],
        mask_passwords: bool = True,
        badge_scale: float = 1.0,
    ) -> Image.Image:
        """
        Draws numbered badges and bounding boxes onto a copy of the screen image.
        """
        annotated = image.copy().convert("RGBA")
        draw = ImageDraw.Draw(annotated)

        # Font setup (uses default fallback if truetype is unavailable)
        try:
            font_size = max(14, int(20 * badge_scale))
            font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        for elem in elements:
            color = cls.DEFAULT_PALETTE[elem.id % len(cls.DEFAULT_PALETTE)]
            xmin, ymin, xmax, ymax = elem.bounds

            # 1. Mask sensitive / password fields
            if mask_passwords and elem.is_password:
                try:
                    cropped = annotated.crop((xmin, ymin, xmax, ymax))
                    blurred = cropped.filter(ImageFilter.GaussianBlur(radius=15))
                    annotated.paste(blurred, (xmin, ymin))
                except Exception:
                    pass

            # 2. Draw subtle bounding box outline
            draw.rectangle(
                [xmin, ymin, xmax, ymax],
                outline=(color[0], color[1], color[2], 220),
                width=2,
            )

            # 3. Draw numbered badge pill
            badge_text = str(elem.id)
            # Estimate badge dimensions
            text_w = len(badge_text) * 10 + 8
            text_h = 18

            # Position badge at top-left inside element or just above
            badge_x1 = max(0, xmin + 2)
            badge_y1 = max(0, ymin + 2)
            badge_x2 = badge_x1 + text_w
            badge_y2 = badge_y1 + text_h

            # Draw badge background
            draw.rectangle(
                [badge_x1, badge_y1, badge_x2, badge_y2],
                fill=(color[0], color[1], color[2], 240),
            )

            # Draw white text
            draw.text(
                (badge_x1 + 4, badge_y1 + 1),
                badge_text,
                fill=(255, 255, 255, 255),
                font=font,
            )

        return annotated.convert("RGB")

    @classmethod
    def to_base64_jpeg(cls, image: Image.Image, quality: int = 80) -> str:
        """Encodes PIL Image to Base64 JPEG string."""
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
