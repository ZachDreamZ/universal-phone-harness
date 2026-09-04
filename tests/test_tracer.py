"""Unit tests for SessionTracer and TraceReplayer."""

import os
import tempfile
import pytest

from phone_harness.harness import PhoneHarness
from phone_harness.backends.mock import MockPhoneDevice
from phone_harness.core.models import ActionRequest, ActionType, UIElement, BoundingBox
from phone_harness.recording.tracer import SessionTracer, TraceReplayer


def test_session_tracer_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = os.path.join(tmpdir, "test_session.trace.jsonl")
        tracer = SessionTracer(trace_path)
        assert tracer.is_recording is True

        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)
        state = harness.observe()

        req = ActionRequest(
            action=ActionType.TAP,
            target_index=1,
            observation_generation=state.generation,
        )
        res = harness.execute_action(req)
        post_state = harness.observe()

        step = tracer.record_step(req, res, state, post_state)
        assert step.step_number == 1
        assert step.action_type == "tap"
        assert step.target_id == 1
        assert step.success is True

        stopped_path = tracer.stop_recording()
        assert stopped_path == trace_path
        assert tracer.is_recording is False

        # Verify trace file exists and parses
        steps = TraceReplayer.load_trace(trace_path)
        assert len(steps) == 1
        assert steps[0].step_number == 1
        assert steps[0].action_type == "tap"


def test_trace_replay_deterministic():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = os.path.join(tmpdir, "replay.trace.jsonl")
        tracer = SessionTracer(trace_path)

        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)
        state = harness.observe()

        # Step 1: Tap Settings (transitions to settings screen)
        settings_el = next(el for el in state.elements if el.text == "Settings")
        req1 = ActionRequest(action=ActionType.TAP, target_index=settings_el.id, observation_generation=state.generation)
        res1 = harness.execute_action(req1)
        post_state1 = harness.observe()
        tracer.record_step(req1, res1, state, post_state1)

        # Step 2: Tap Wi-Fi in settings
        wifi_el = next(el for el in post_state1.elements if el.text == "Wi-Fi")
        req2 = ActionRequest(action=ActionType.TAP, target_index=wifi_el.id, observation_generation=post_state1.generation)
        res2 = harness.execute_action(req2)
        post_state2 = harness.observe()
        tracer.record_step(req2, res2, post_state1, post_state2)
        tracer.stop_recording()

        # Fresh harness & device to replay
        replay_device = MockPhoneDevice()
        replay_harness = PhoneHarness(device=replay_device)

        summary = TraceReplayer.replay_trace(replay_harness, trace_path, enable_self_healing=True)
        assert summary.is_success is True
        assert summary.total_steps == 2
        assert summary.executed_steps == 2
        assert summary.failed_steps == 0


def test_trace_replay_self_healing():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = os.path.join(tmpdir, "self_heal.trace.jsonl")
        tracer = SessionTracer(trace_path)

        device = MockPhoneDevice()
        harness = PhoneHarness(device=device)
        state = harness.observe()

        # Record action targeting Settings element on home screen
        settings_el = next(el for el in state.elements if el.text == "Settings")
        req = ActionRequest(action=ActionType.TAP, target_index=settings_el.id, observation_generation=state.generation)
        res = harness.execute_action(req)
        tracer.record_step(req, res, state, harness.observe())
        tracer.stop_recording()

        # Create a mock device where element order has shifted due to a new top banner
        class ShiftedMockDevice(MockPhoneDevice):
            def dump_hierarchy(self):
                original = super().dump_hierarchy()
                banner = UIElement.create(999, "Button", (100, 50, 980, 150), text="System Banner", is_clickable=True)
                return [banner] + original

        shifted_device = ShiftedMockDevice()
        shifted_harness = PhoneHarness(device=shifted_device)

        # Replay should self-heal using text match "Settings"
        summary = TraceReplayer.replay_trace(shifted_harness, trace_path, enable_self_healing=True)
        assert summary.is_success is True
        assert summary.total_steps == 1
        assert summary.executed_steps == 1
        assert summary.healed_steps == 1
