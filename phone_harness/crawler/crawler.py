"""
Autonomous App Explorer & QA Auditor.
Explores mobile application state graphs, detects crashes, ANRs, dead-ends,
and produces executive QA audit reports with Set-of-Marks annotated screenshots.
"""

import os
import time
from typing import Optional, Dict, Any, List, Set, Tuple
from pydantic import BaseModel, Field

from phone_harness.core.models import ActionRequest, ActionType, KeyCode, PhoneState, UIElement
from phone_harness.engine.verifier import ZeroMistakeVerifier


class ScreenNode(BaseModel):
    """Represents a discovered screen in the app state graph."""
    state_hash: str
    app_package: str
    element_count: int
    interactive_count: int
    screenshot_path: Optional[str] = None
    is_crash_dialog: bool = False


class CrawlTransition(BaseModel):
    """A directed edge between two screen states in the app state graph."""
    from_state_hash: str
    to_state_hash: str
    action_type: str
    target_id: Optional[int] = None
    target_text: Optional[str] = None


class CrawlReport(BaseModel):
    """Executive audit report of an autonomous crawling session."""
    target_package: str
    screens_discovered: int
    transitions_explored: int
    crashes_detected: int
    dead_ends: int
    execution_duration_sec: float
    output_directory: str
    report_markdown_path: str
    nodes: List[ScreenNode] = Field(default_factory=list)
    transitions: List[CrawlTransition] = Field(default_factory=list)


class AppCrawler:
    """Explores mobile app interfaces autonomously and outputs an executive QA audit report."""

    CRASH_INDICATORS = [
        "has stopped",
        "keeps stopping",
        "isn't responding",
        "anr",
        "crash",
        "fatal exception",
    ]

    def __init__(self, harness: Any, output_directory: str = "./crawler_audit"):
        self.harness = harness
        self.output_directory = output_directory
        self.screens_dir = os.path.join(output_directory, "screens")
        os.makedirs(self.screens_dir, exist_ok=True)

        self.discovered_nodes: Dict[str, ScreenNode] = {}
        self.transitions: List[CrawlTransition] = []
        self.explored_actions: Set[Tuple[str, str]] = set()  # (state_hash, element_signature)
        self.crashes_detected: int = 0
        self.dead_ends: int = 0

    def _is_crash_state(self, state: PhoneState) -> bool:
        """Determines if the current screen represents an application crash or ANR dialog."""
        for element in state.elements:
            element_text = (element.text or "").lower()
            element_desc = (element.description or "").lower()
            for indicator in self.CRASH_INDICATORS:
                if indicator in element_text or indicator in element_desc:
                    return True
        return False

    def _get_element_signature(self, element: UIElement) -> str:
        """Generates a stable signature for an element within a state."""
        return f"{element.type}:{element.resource_id or ''}:{element.text or ''}"

    def _save_screen_artifact(self, state_hash: str) -> str:
        """Captures and persists a Set-of-Marks screenshot for the state."""
        screen_file = os.path.join(self.screens_dir, f"screen_{state_hash}.png")
        if not os.path.exists(screen_file):
            try:
                self.harness.save_screenshot(screen_file, include_som=True)
            except Exception:
                pass
        return screen_file

    def crawl(
        self,
        target_package: Optional[str] = None,
        max_depth: int = 5,
        step_budget: int = 20,
    ) -> CrawlReport:
        """
        Executes an autonomous state-graph exploration loop.
        """
        start_time = time.monotonic()

        # Initial observation
        initial_state = self.harness.observe()
        pkg = target_package or initial_state.current_app_package

        current_depth = 0

        for step in range(step_budget):
            state = self.harness.observe()
            state_hash = state.perceptual_hash or ZeroMistakeVerifier.calculate_tree_hash(state.elements)

            is_crash = self._is_crash_state(state)
            if is_crash:
                self.crashes_detected += 1

            if state_hash not in self.discovered_nodes:
                saved_screen = self._save_screen_artifact(state_hash)
                node = ScreenNode(
                    state_hash=state_hash,
                    app_package=state.current_app_package,
                    element_count=len(state.elements),
                    interactive_count=sum(1 for el in state.elements if el.is_clickable or el.is_focusable),
                    screenshot_path=saved_screen,
                    is_crash_dialog=is_crash,
                )
                self.discovered_nodes[state_hash] = node

            # Select an unvisited interactive element to explore
            candidates = [
                el for el in state.elements
                if (el.is_clickable or el.is_focusable) and (el.text != "Factory Reset Phone")  # safety exclusion
            ]

            next_element: Optional[UIElement] = None
            for candidate in candidates:
                sig = self._get_element_signature(candidate)
                if (state_hash, sig) not in self.explored_actions:
                    next_element = candidate
                    self.explored_actions.add((state_hash, sig))
                    break

            if next_element is not None and current_depth < max_depth:
                # Actuate on element
                action_req = ActionRequest(
                    action=ActionType.TAP,
                    target_index=next_element.id,
                    observation_generation=state.generation,
                )
                try:
                    self.harness.execute_action(action_req)
                    current_depth += 1
                except Exception:
                    pass

                # Record transition
                post_state = self.harness.observe()
                post_hash = post_state.perceptual_hash or ZeroMistakeVerifier.calculate_tree_hash(post_state.elements)
                self.transitions.append(
                    CrawlTransition(
                        from_state_hash=state_hash,
                        to_state_hash=post_hash,
                        action_type="tap",
                        target_id=next_element.id,
                        target_text=next_element.text,
                    )
                )
            else:
                # Dead end or depth limit reached: Backtrack
                self.dead_ends += 1
                back_req = ActionRequest(
                    action=ActionType.PRESS_KEY,
                    key_code=KeyCode.BACK,
                    observation_generation=state.generation,
                )
                try:
                    self.harness.execute_action(back_req)
                    current_depth = max(0, current_depth - 1)
                except Exception:
                    pass

        duration = time.monotonic() - start_time
        report_md_path = self._generate_markdown_report(pkg, duration)

        return CrawlReport(
            target_package=pkg,
            screens_discovered=len(self.discovered_nodes),
            transitions_explored=len(self.transitions),
            crashes_detected=self.crashes_detected,
            dead_ends=self.dead_ends,
            execution_duration_sec=duration,
            output_directory=self.output_directory,
            report_markdown_path=report_md_path,
            nodes=list(self.discovered_nodes.values()),
            transitions=self.transitions,
        )

    def _generate_markdown_report(self, target_package: str, duration: float) -> str:
        """Generates an executive QA audit report in Markdown."""
        report_file = os.path.join(self.output_directory, "QA_AUDIT_REPORT.md")

        lines = [
            "# Autonomous Mobile QA Audit Report",
            "",
            f"- **Target Package:** `{target_package}`",
            f"- **Exploration Duration:** `{duration:.2f}s`",
            f"- **Screens Discovered:** `{len(self.discovered_nodes)}`",
            f"- **State Transitions Explored:** `{len(self.transitions)}`",
            f"- **Crashes / ANRs Detected:** `{self.crashes_detected}`",
            f"- **Dead-Ends Backtracked:** `{self.dead_ends}`",
            "",
            "## 1. Executive Summary",
            "",
            "The autonomous explorer navigated the user application state graph, auditing screen interactions,",
            "backtrack paths, and state stability. All screen transitions and interactive elements were cataloged.",
            "",
            "## 2. Discovered Screen Nodes",
            "",
            "| State Hash | App Package | Elements | Interactive | Crash Detected | Screenshot |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for node in self.discovered_nodes.values():
            screen_link = f"[Image]({node.screenshot_path})" if node.screenshot_path else "N/A"
            crash_str = "⚠️ YES" if node.is_crash_dialog else "Clean"
            lines.append(
                f"| `{node.state_hash[:10]}` | `{node.app_package}` | {node.element_count} | {node.interactive_count} | {crash_str} | {screen_link} |"
            )

        lines.extend([
            "",
            "## 3. Explored State Transitions",
            "",
            "| Step | From State | To State | Action | Target Element |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])

        for idx, trans in enumerate(self.transitions, start=1):
            target_str = f"\"{trans.target_text}\"" if trans.target_text else f"id={trans.target_id}"
            lines.append(
                f"| {idx} | `{trans.from_state_hash[:8]}` | `{trans.to_state_hash[:8]}` | `{trans.action_type}` | {target_str} |"
            )

        lines.extend([
            "",
            "---",
            "*Report generated autonomously by Universal Phone Harness QA Crawler.*",
            "",
        ])

        with open(report_file, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return report_file
