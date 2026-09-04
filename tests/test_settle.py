"""Unit tests for PerceptualSettleDetector."""

import pytest
from PIL import Image

from phone_harness.perception.settle import PerceptualSettleDetector
from phone_harness.backends.mock import MockPhoneDevice


def test_calculate_frame_difference_identical_images():
    img1 = Image.new("RGB", (100, 100), color=(128, 128, 128))
    img2 = Image.new("RGB", (100, 100), color=(128, 128, 128))

    diff = PerceptualSettleDetector.calculate_frame_difference(img1, img2)
    assert diff == pytest.approx(0.0, abs=1e-5)


def test_calculate_frame_difference_opposite_images():
    black_img = Image.new("RGB", (100, 100), color=(0, 0, 0))
    white_img = Image.new("RGB", (100, 100), color=(255, 255, 255))

    diff = PerceptualSettleDetector.calculate_frame_difference(black_img, white_img)
    assert diff == pytest.approx(1.0, abs=1e-3)


def test_calculate_frame_difference_different_sizes():
    img1 = Image.new("RGB", (200, 400), color=(50, 50, 50))
    img2 = Image.new("RGB", (100, 200), color=(50, 50, 50))

    diff = PerceptualSettleDetector.calculate_frame_difference(img1, img2)
    assert diff == pytest.approx(0.0, abs=1e-5)


def test_wait_for_settle_static_mock_device():
    device = MockPhoneDevice()
    is_settled, frame, count, diff = PerceptualSettleDetector.wait_for_settle(
        device=device,
        max_wait_seconds=1.0,
        poll_interval_seconds=0.05,
        settle_threshold=0.01,
    )
    assert is_settled is True
    assert diff <= 0.01
    assert count >= 2
    assert frame.size == (1080, 2400)


def test_wait_for_settle_animating_mock_device():
    class AnimatingMockDevice(MockPhoneDevice):
        def __init__(self):
            super().__init__()
            self.frame_index = 0

        def capture_frame(self) -> Image.Image:
            self.frame_index += 1
            # Frames 1 and 2 are animating, frame 3+ stabilizes
            color_val = min(self.frame_index * 80, 240) if self.frame_index <= 2 else 240
            return Image.new("RGB", (1080, 2400), color=(color_val, color_val, color_val))

    anim_device = AnimatingMockDevice()
    is_settled, frame, count, diff = PerceptualSettleDetector.wait_for_settle(
        device=anim_device,
        max_wait_seconds=2.0,
        poll_interval_seconds=0.05,
        settle_threshold=0.02,
    )
    assert is_settled is True
    assert count >= 3
