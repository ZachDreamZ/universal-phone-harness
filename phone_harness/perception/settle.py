"""
Perceptual Settle Detection.
Calculates visual frame differences to detect when animations have stabilized,
eliminating arbitrary sleeps in agent interaction loops.
"""

import time
from typing import Tuple, Optional
from PIL import Image, ImageChops, ImageStat

from phone_harness.core.device import BasePhoneDevice


class PerceptualSettleDetector:
    """Detects when screen visual state has settled using perceptual frame differencing."""

    @staticmethod
    def calculate_frame_difference(image_a: Image.Image, image_b: Image.Image) -> float:
        """
        Calculates normalized perceptual difference between two frames.
        Returns a float between 0.0 (identical) and 1.0 (completely distinct).
        """
        if image_a is None or image_b is None:
            return 1.0

        # Downsample directly to a standardized low-resolution grayscale thumbnail for fast perceptual diffing
        thumbnail_size = (64, 64)
        gray_a = image_a.convert("L").resize(thumbnail_size, Image.Resampling.BILINEAR)
        gray_b = image_b.convert("L").resize(thumbnail_size, Image.Resampling.BILINEAR)

        diff_image = ImageChops.difference(gray_a, gray_b)
        stats = ImageStat.Stat(diff_image)
        mean_delta = stats.mean[0]  # Average pixel difference in range [0, 255]

        normalized_difference = mean_delta / 255.0
        return normalized_difference

    @classmethod
    def wait_for_settle(
        cls,
        device: BasePhoneDevice,
        max_wait_seconds: float = 2.0,
        poll_interval_seconds: float = 0.1,
        settle_threshold: float = 0.01,
        consecutive_stable_frames: int = 1,
    ) -> Tuple[bool, Image.Image, int, float]:
        """
        Polls frames until the screen visually stabilizes or timeout is reached.

        Returns:
            Tuple of (is_settled: bool, latest_frame: Image, frames_checked: int, final_difference: float)
        """
        start_time = time.monotonic()
        previous_frame = device.capture_frame()
        frames_checked = 1
        latest_difference = 1.0
        stable_count = 0

        time.sleep(poll_interval_seconds)

        while (time.monotonic() - start_time) < max_wait_seconds:
            current_frame = device.capture_frame()
            frames_checked += 1
            latest_difference = cls.calculate_frame_difference(previous_frame, current_frame)

            if latest_difference <= settle_threshold:
                stable_count += 1
                if stable_count >= consecutive_stable_frames:
                    return True, current_frame, frames_checked, latest_difference
            else:
                stable_count = 0

            previous_frame = current_frame
            time.sleep(poll_interval_seconds)

        # Timeout reached without dropping below threshold
        final_frame = device.capture_frame()
        return False, final_frame, frames_checked, latest_difference
