"""Unit tests for AppCrawler and autonomous QA audit reporting."""

import os
import tempfile
import pytest

from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.models import UIElement
from phone_harness.crawler.crawler import AppCrawler


def test_crawler_basic_exploration():
    with tempfile.TemporaryDirectory() as tmpdir:
        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)

        crawler = AppCrawler(harness=harness, output_directory=tmpdir)
        report = crawler.crawl(step_budget=8, max_depth=3)

        assert report.screens_discovered >= 2
        assert report.transitions_explored >= 2
        assert os.path.exists(report.report_markdown_path)

        with open(report.report_markdown_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# Autonomous Mobile QA Audit Report" in content
            assert "## 1. Executive Summary" in content
            assert "## 2. Discovered Screen Nodes" in content


def test_crawler_crash_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        class CrashingMockDevice(MockPhoneDevice):
            def dump_hierarchy(self):
                # Return crash dialog elements
                return [
                    UIElement.create(1, "TextView", (100, 400, 980, 600), text="Settings keeps stopping"),
                    UIElement.create(2, "Button", (100, 700, 500, 850), text="Close app", is_clickable=True),
                ]

        crash_device = CrashingMockDevice()
        harness = PhoneHarness(device=crash_device)

        crawler = AppCrawler(harness=harness, output_directory=tmpdir)
        report = crawler.crawl(step_budget=2, max_depth=1)

        assert report.crashes_detected >= 1
        assert any(node.is_crash_dialog for node in report.nodes)


def test_crawler_safety_exclusion():
    with tempfile.TemporaryDirectory() as tmpdir:
        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)

        # Transition directly to settings screen where "Factory Reset Phone" exists
        harness.device.current_screen = "settings"

        crawler = AppCrawler(harness=harness, output_directory=tmpdir)
        report = crawler.crawl(step_budget=6, max_depth=2)

        # Confirm Factory Reset was never targeted
        for trans in report.transitions:
            assert trans.target_text != "Factory Reset Phone"


def test_crawler_backtracking():
    with tempfile.TemporaryDirectory() as tmpdir:
        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)

        crawler = AppCrawler(harness=harness, output_directory=tmpdir)
        # Crawl with max_depth=1 so it explores an item and triggers backtracks
        report = crawler.crawl(step_budget=5, max_depth=1)

        assert report.dead_ends >= 1
        assert report.screens_discovered >= 2
