"""
Standard Model Context Protocol (MCP) Server for Phone Harness.
Exposes mobile phone control tools over JSON-RPC 2.0 stdio transport.
Compatible with Claude Code, Codex, Antigravity, OpenCode, Cursor, and custom agent runtimes.
"""

import sys
import json
import traceback
from typing import Dict, Any, List, Optional

from phone_harness.harness import PhoneHarness
from phone_harness.core.models import (
    ActionRequest,
    ActionType,
    KeyCode,
    SwipeDirection,
    VerificationSpec,
)
from phone_harness.core.exceptions import PhoneHarnessError
from phone_harness.perception.tree_simplifier import TreeSimplifier


class PhoneHarnessMCPServer:
    """MCP Server exposing mobile automation tools to LLM agents."""

    def __init__(self, harness: Optional[PhoneHarness] = None):
        self._harness = harness

    @property
    def harness(self) -> PhoneHarness:
        if self._harness is None:
            self._harness = PhoneHarness()
        return self._harness

    @harness.setter
    def harness(self, h: PhoneHarness) -> None:
        self._harness = h

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Returns MCP tool definitions matching the official MCP specification."""
        return [
            {
                "name": "phone_observe",
                "description": "Observes the current phone screen state. Returns a token-compacted indexed DOM ([1], [2], ...) and optional Set-of-Marks image.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_som_image": {
                            "type": "boolean",
                            "description": "If true, generates Set-of-Marks visual overlay with numbered badges for multimodal vision models.",
                            "default": False,
                        },
                        "include_raw_image": {
                            "type": "boolean",
                            "description": "If true, returns raw JPEG screenshot in base64 format.",
                            "default": False,
                        },
                        "filter_interactive_only": {
                            "type": "boolean",
                            "description": "If true, prunes non-interactive layout noise to minimize token consumption (<500 tokens).",
                            "default": True,
                        },
                    },
                },
            },
            {
                "name": "phone_tap",
                "description": "Taps an on-screen element by its badge index [ID], text label, or coordinates with zero-mistake pre/post verification.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Element badge index from phone_observe (e.g., 3 for [3] Button 'Submit'). Required with observation_generation when used.",
                        },
                        "text": {
                            "type": "string",
                            "description": "Fuzzy text match query if index is not known (e.g., 'Settings', 'Sign In'). Compatible without observation_generation.",
                        },
                        "x": {
                            "type": "integer",
                            "description": "Exact physical X coordinate in screen pixels.",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Exact physical Y coordinate in screen pixels.",
                        },
                        "confirm_destructive": {
                            "type": "boolean",
                            "description": "Set to true if clicking a potentially destructive button (Delete, Format, Purchase).",
                            "default": False,
                        },
                        "observation_generation": {
                            "type": "integer",
                            "description": "observation_generation returned by phone_observe. Required when 'index' is used to ground the tap against the exact observed screen.",
                        },
                        "verify": {
                            "type": "object",
                            "description": "Optional post-condition assertions to guarantee zero mistakes.",
                            "properties": {
                                "assert_text_present": {"type": "array", "items": {"type": "string"}},
                                "assert_text_absent": {"type": "array", "items": {"type": "string"}},
                                "assert_app_package": {"type": "string"},
                            },
                        },
                    },
                },
            },
            {
                "name": "phone_type",
                "description": "Types text into a focused input field or element identified by index.",
                "inputSchema": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to enter into the input field.",
                        },
                        "index": {
                            "type": "integer",
                            "description": "Optional EditText badge index to focus before typing. Requires observation_generation when used.",
                        },
                        "observation_generation": {
                            "type": "integer",
                            "description": "observation_generation returned by phone_observe. Required when 'index' is used to ground typing against the exact observed input field.",
                        },
                        "clear_existing": {
                            "type": "boolean",
                            "description": "If true, clears existing text before typing.",
                            "default": True,
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "If true, sends Enter / Submit action key after typing.",
                            "default": False,
                        },
                    },
                },
            },
            {
                "name": "phone_swipe",
                "description": "Performs directional scrolling ('up', 'down', 'left', 'right') or precision coordinate drag.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                            "description": "Standard scroll direction.",
                        },
                        "distance": {
                            "type": "string",
                            "enum": ["short", "medium", "long"],
                            "default": "medium",
                        },
                        "start_x": {"type": "integer"},
                        "start_y": {"type": "integer"},
                        "end_x": {"type": "integer"},
                        "end_y": {"type": "integer"},
                        "duration_ms": {"type": "integer", "default": 250},
                    },
                },
            },
            {
                "name": "phone_press_key",
                "description": "Triggers hardware or system navigation keys (HOME, BACK, APP_SWITCH, ENTER, POWER).",
                "inputSchema": {
                    "type": "object",
                    "required": ["key"],
                    "properties": {
                        "key": {
                            "type": "string",
                            "enum": ["HOME", "BACK", "APP_SWITCH", "ENTER", "VOLUME_UP", "VOLUME_DOWN", "POWER", "DELETE", "TAB"],
                            "description": "System navigation key to press.",
                        },
                    },
                },
            },
            {
                "name": "phone_open_app",
                "description": "Launches an Android application by package identifier.",
                "inputSchema": {
                    "type": "object",
                    "required": ["app_name"],
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Android package identifier such as 'com.android.settings'.",
                        },
                        "stop_existing": {
                            "type": "boolean",
                            "description": "If true, force-stops the app first for a clean launch.",
                            "default": False,
                        },
                    },
                },
            },
            {
                "name": "phone_assert_state",
                "description": "Deterministically checks that expected conditions hold on screen.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "assert_text_present": {"type": "array", "items": {"type": "string"}},
                        "assert_text_absent": {"type": "array", "items": {"type": "string"}},
                        "assert_app_package": {"type": "string"},
                    },
                },
            },
            {
                "name": "phone_wait_for",
                "description": "Locally polls the screen until expected text or app package appears without consuming LLM turn tokens.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text_present": {"type": "array", "items": {"type": "string"}},
                        "text_absent": {"type": "array", "items": {"type": "string"}},
                        "app_package": {"type": "string"},
                        "timeout_ms": {"type": "integer", "default": 5000},
                        "poll_interval_ms": {"type": "integer", "default": 150},
                    },
                },
            },
            {
                "name": "phone_open_url",
                "description": "Opens an HTTP or HTTPS URL in the default browser.",
                "inputSchema": {
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "description": "The URL to navigate to."},
                    },
                },
            },
            {
                "name": "phone_open_settings",
                "description": "Directly opens a specific settings section ('wifi', 'bluetooth', 'apps', 'display', 'battery', etc.).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "default": "settings"},
                    },
                },
            },
            {
                "name": "phone_set_clipboard",
                "description": "Sets device clipboard for fast instant pasting of long strings, URLs, or unicode text.",
                "inputSchema": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string"},
                    },
                },
            },
            {
                "name": "phone_get_clipboard",
                "description": "Reads text from the device system clipboard (useful for retrieving OTP codes, tokens, or copied links).",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "phone_save_screenshot",
                "description": "Captures and saves a phone screenshot directly to a local filesystem path (e.g. ./screen.png).",
                "inputSchema": {
                    "type": "object",
                    "required": ["output_path"],
                    "properties": {
                        "output_path": {
                            "type": "string",
                            "description": "Local file path where the screenshot will be saved (.png or .jpg).",
                        },
                        "include_som": {
                            "type": "boolean",
                            "description": "If true, saves the Set-of-Marks annotated image with element badges instead of raw screenshot.",
                            "default": False,
                        },
                    },
                },
            },
            {
                "name": "phone_dismiss_dialog",
                "description": "Auto-detects and responds to system permission or alert dialogs ('allow' | 'deny' | 'dismiss').",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["allow", "deny", "dismiss"],
                            "default": "deny",
                        },
                    },
                },
            },
            {
                "name": "phone_long_press",
                "description": "Long-presses an on-screen element by badge index, text, or coordinates. Useful for context menus and drag-start gestures.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Element badge index. Requires observation_generation when used."},
                        "text": {"type": "string", "description": "Fuzzy text match query. Compatible without observation_generation."},
                        "x": {"type": "integer", "description": "Physical X coordinate. Compatible without observation_generation."},
                        "y": {"type": "integer", "description": "Physical Y coordinate. Compatible without observation_generation."},
                        "observation_generation": {
                            "type": "integer",
                            "description": "observation_generation returned by phone_observe. Required when 'index' is used to ground the long-press against the exact observed element.",
                        },
                        "duration_ms": {"type": "integer", "default": 800, "description": "Hold duration in milliseconds."},
                    },
                },
            },
            {
                "name": "phone_double_tap",
                "description": "Double-taps an on-screen element by badge index, text, or coordinates. Useful for text selection and zoom gestures.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Element badge index. Requires observation_generation when used."},
                        "text": {"type": "string", "description": "Fuzzy text match query. Compatible without observation_generation."},
                        "x": {"type": "integer", "description": "Physical X coordinate. Compatible without observation_generation."},
                        "y": {"type": "integer", "description": "Physical Y coordinate. Compatible without observation_generation."},
                        "observation_generation": {
                            "type": "integer",
                            "description": "observation_generation returned by phone_observe. Required when 'index' is used to ground the double-tap against the exact observed element.",
                        },
                    },
                },
            },
            {
                "name": "phone_efficiency_report",
                "description": "Returns step budget usage, remaining budget, average latency, and task efficiency score for the current session.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "optimal_steps": {"type": "integer", "default": 5, "description": "Expected optimal number of steps for efficiency scoring."},
                    },
                },
            },
            {
                "name": "phone_health_check",
                "description": "Returns connection status, hardware metadata, and diagnostic metrics.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def _compact_json(self, payload: Any, **_ignored_options: Any) -> str:
        """Serialize MCP text content without formatting whitespace."""
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _compact_action_dom(self, state: Any) -> str:
        """Return a smaller post-action DOM while preserving complete element lines."""
        if state is None:
            return ""
        return TreeSimplifier.generate_compact_dom(
            state.elements,
            max_tokens=self.harness.config.max_tokens_action_dom,
        )

    def _reject_missing_generation(self, action: str) -> Dict[str, Any]:
        """Returns a structured MCP error when an indexed action omits observation_generation.

        The MCP contract requires indexed actions (tap/type/long_press/double_tap) to be
        grounded on the exact observed screen, so an index without a generation is rejected
        without actuating the device. Text and coordinate selectors remain compatible.
        """
        payload = {
            "error": "MissingObservationGeneration",
            "message": (
                f"Indexed {action} requires 'observation_generation'. Call phone_observe first and "
                f"pass its returned observation_generation alongside 'index'."
            ),
        }
        return {
            "isError": True,
            "content": [{"type": "text", "text": self._compact_json(payload, indent=2)}],
        }

    def handle_tool_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an incoming MCP tool call to the PhoneHarness."""
        try:
            if name == "phone_observe":
                state = self.harness.observe(
                    include_som_image=args.get("include_som_image", False),
                    include_raw_image=args.get("include_raw_image", False),
                    filter_interactive_only=args.get("filter_interactive_only", True),
                )
                res: Dict[str, Any] = {
                    "foreground_app": state.current_app_package,
                    "screen_size": f"{state.screen_width}x{state.screen_height}",
                    "keyboard_visible": state.keyboard_visible,
                    "element_count": len(state.elements),
                    "compact_dom": state.compact_dom,
                }
                res["observation_generation"] = state.generation
                content: List[Dict[str, Any]] = [
                    {"type": "text", "text": self._compact_json(res)}
                ]
                if state.som_screenshot_base64:
                    content.append(
                        {
                            "type": "image",
                            "data": state.som_screenshot_base64,
                            "mimeType": "image/jpeg",
                        }
                    )
                if state.screenshot_base64:
                    content.append(
                        {
                            "type": "image",
                            "data": state.screenshot_base64,
                            "mimeType": "image/jpeg",
                        }
                    )
                return {"content": content}

            elif name == "phone_tap":
                verify_data = args.get("verify")
                verify_spec = VerificationSpec(**verify_data) if verify_data else None

                if args.get("index") is not None and args.get("observation_generation") is None:
                    return self._reject_missing_generation("phone_tap")

                req = ActionRequest(
                    action=ActionType.TAP,
                    target_index=args.get("index"),
                    target_text=args.get("text"),
                    x=args.get("x"),
                    y=args.get("y"),
                    confirm_destructive=args.get("confirm_destructive", False),
                    verify=verify_spec,
                    observation_generation=args.get("observation_generation"),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "tap",
                                    "target": action_res.target_info,
                                    "latency_ms": action_res.latency_ms,
                                    "foreground_app": action_res.new_state.current_app_package if action_res.new_state else "",
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                    "observation_generation": action_res.new_state.generation if action_res.new_state else 0,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_type":
                if args.get("index") is not None and args.get("observation_generation") is None:
                    return self._reject_missing_generation("phone_type")

                req = ActionRequest(
                    action=ActionType.TYPE,
                    target_index=args.get("index"),
                    text_to_type=args.get("text"),
                    clear_existing=args.get("clear_existing", True),
                    press_enter=args.get("press_enter", False),
                    observation_generation=args.get("observation_generation"),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "type",
                                    "latency_ms": action_res.latency_ms,
                                    "observation_generation": action_res.new_state.generation if action_res.new_state else 0,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_swipe":
                dir_val = args.get("direction")
                direction = SwipeDirection(dir_val) if dir_val else None
                req = ActionRequest(
                    action=ActionType.SWIPE,
                    direction=direction,
                    swipe_distance=args.get("distance", "medium"),
                    start_x=args.get("start_x"),
                    start_y=args.get("start_y"),
                    end_x=args.get("end_x"),
                    end_y=args.get("end_y"),
                    duration_ms=args.get("duration_ms", 250),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "swipe",
                                    "latency_ms": action_res.latency_ms,
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_press_key":
                key = KeyCode(args["key"])
                req = ActionRequest(action=ActionType.PRESS_KEY, key=key)
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": f"press_key({key.value})",
                                    "latency_ms": action_res.latency_ms,
                                    "foreground_app": action_res.new_state.current_app_package if action_res.new_state else "",
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_open_app":
                req = ActionRequest(
                    action=ActionType.OPEN_APP,
                    package_name=args["app_name"],
                    stop_existing=args.get("stop_existing", False),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": f"open_app({args['app_name']})",
                                    "foreground_app": action_res.new_state.current_app_package if action_res.new_state else "",
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_assert_state":
                spec = VerificationSpec(
                    assert_text_present=args.get("assert_text_present"),
                    assert_text_absent=args.get("assert_text_absent"),
                    assert_app_package=args.get("assert_app_package"),
                )
                req = ActionRequest(action=ActionType.WAIT, duration_ms=50, verify=spec)
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "assertion_passed",
                                    "verification": "ok",
                                    "foreground_app": action_res.new_state.current_app_package if action_res.new_state else "",
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_wait_for":
                passed, state = self.harness.wait_for_condition(
                    text_present=args.get("text_present"),
                    text_absent=args.get("text_absent"),
                    app_package=args.get("app_package"),
                    timeout_ms=args.get("timeout_ms", 5000),
                    poll_interval_ms=args.get("poll_interval_ms", 150),
                )
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "condition_met" if passed else "timeout_reached",
                                    "passed": passed,
                                    "foreground_app": state.current_app_package,
                                    "updated_compact_dom": self._compact_action_dom(state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_open_url":
                state = self.harness.open_url(args["url"])
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "open_url",
                                    "foreground_app": state.current_app_package,
                                    "updated_compact_dom": self._compact_action_dom(state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_open_settings":
                section = args.get("section", "settings")
                state = self.harness.open_settings(section)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": f"open_settings({section})",
                                    "foreground_app": state.current_app_package,
                                    "updated_compact_dom": self._compact_action_dom(state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_set_clipboard":
                self.harness.set_clipboard(args["text"])
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json({"status": "success", "clipboard_set": True}, indent=2),
                        }
                    ]
                }

            elif name == "phone_get_clipboard":
                clip_text = self.harness.get_clipboard()
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json({"status": "success", "clipboard_text": clip_text}, indent=2),
                        }
                    ]
                }

            elif name == "phone_save_screenshot":
                output_path = args.get("output_path")
                if not output_path:
                    return {
                        "isError": True,
                        "content": [{"type": "text", "text": "Missing required argument 'output_path'"}],
                    }
                include_som = bool(args.get("include_som", False))
                w, h = self.harness.save_screenshot(output_path, include_som=include_som)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "saved_path": output_path,
                                    "width": w,
                                    "height": h,
                                    "som_annotated": include_som,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_dismiss_dialog":
                action = args.get("action", "deny")
                action_res = self.harness.dismiss_dialog(action=action)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": f"dismiss_dialog({action})",
                                    "target": action_res.target_info,
                                    "foreground_app": action_res.new_state.current_app_package if action_res.new_state else "",
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_long_press":
                if args.get("index") is not None and args.get("observation_generation") is None:
                    return self._reject_missing_generation("phone_long_press")

                req = ActionRequest(
                    action=ActionType.LONG_PRESS,
                    target_index=args.get("index"),
                    target_text=args.get("text"),
                    x=args.get("x"),
                    y=args.get("y"),
                    duration_ms=args.get("duration_ms", 800),
                    observation_generation=args.get("observation_generation"),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "long_press",
                                    "target": action_res.target_info,
                                    "latency_ms": action_res.latency_ms,
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                    "observation_generation": action_res.new_state.generation if action_res.new_state else 0,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_double_tap":
                if args.get("index") is not None and args.get("observation_generation") is None:
                    return self._reject_missing_generation("phone_double_tap")

                req = ActionRequest(
                    action=ActionType.DOUBLE_TAP,
                    target_index=args.get("index"),
                    target_text=args.get("text"),
                    x=args.get("x"),
                    y=args.get("y"),
                    observation_generation=args.get("observation_generation"),
                )
                action_res = self.harness.execute_action(req)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(
                                {
                                    "status": "success",
                                    "action": "double_tap",
                                    "target": action_res.target_info,
                                    "latency_ms": action_res.latency_ms,
                                    "updated_compact_dom": self._compact_action_dom(action_res.new_state),
                                    "observation_generation": action_res.new_state.generation if action_res.new_state else 0,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }

            elif name == "phone_efficiency_report":
                report = self.harness.get_efficiency_report(
                    optimal_steps=args.get("optimal_steps", 5),
                )
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(report, indent=2),
                        }
                    ]
                }

            elif name == "phone_health_check":
                summary = self.harness.device.get_device_summary()
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self._compact_json(summary.model_dump()),
                        }
                    ]
                }

            else:
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                }

        except PhoneHarnessError as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": self._compact_json(e.to_dict(), indent=2)}],
            }
        except Exception as e:
            # Server-side diagnostic on stderr: exception class and stack frame
            # locations (file:line:function) only. We never emit the exception
            # message, tool args, or runtime values, so typed text, clipboard,
            # secrets, or DOM data carried in exception args cannot leak here.
            # The client payload below remains limited to stable 'error'/'message'
            # keys per the MCP contract.
            print(f"[MCP Internal Error] {type(e).__name__}", file=sys.stderr)
            for frame in traceback.extract_tb(e.__traceback__):
                print(f"  at {frame.filename}:{frame.lineno} in {frame.name}", file=sys.stderr)
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": self._compact_json(
                            {
                                "error": "InternalHarnessError",
                                "message": "Internal phone harness error.",
                            },
                            indent=2,
                        ),
                    }
                ],
            }

    def get_resource_definitions(self) -> List[Dict[str, Any]]:
        """Returns MCP resource definitions matching the official MCP specification."""
        return [
            {
                "uri": "phone://device/status",
                "name": "Phone Device Status",
                "description": "Current device telemetry, OS version, active app package, resolution, and connection status.",
                "mimeType": "application/json",
            },
            {
                "uri": "phone://screen/dom",
                "name": "Current Screen Compact DOM",
                "description": "Token-compacted indexed DOM of the active phone screen without executing a mutating action.",
                "mimeType": "text/plain",
            },
            {
                "uri": "phone://diagnostics/efficiency",
                "name": "Phone Harness Efficiency & Latency Telemetry",
                "description": "Aggregated execution telemetry, step budget utilization, and latency metrics.",
                "mimeType": "application/json",
            },
        ]

    def handle_resource_read(self, uri: str) -> Dict[str, Any]:
        """Reads and returns the content of an MCP resource by URI."""
        if uri == "phone://device/status":
            summary = self.harness.device.get_device_summary()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": self._compact_json(summary.model_dump(), indent=2),
                    }
                ]
            }
        elif uri == "phone://screen/dom":
            state = self.harness.last_state or self.harness.observe()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": state.compact_dom,
                    }
                ]
            }
        elif uri == "phone://diagnostics/efficiency":
            report = self.harness.get_efficiency_report()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": self._compact_json(report, indent=2),
                    }
                ]
            }
        else:
            raise PhoneHarnessError(f"Resource not found: {uri}")

    def get_prompt_definitions(self) -> List[Dict[str, Any]]:
        """Returns MCP prompt definitions matching the official MCP specification."""
        return [
            {
                "name": "mobile_flow_qa",
                "description": "Automate end-to-end mobile flow testing with assertion checks and step budget tracking.",
                "arguments": [
                    {
                        "name": "target_flow",
                        "description": "The mobile user flow to test (e.g. 'Settings Wi-Fi toggle', 'Checkout flow').",
                        "required": True,
                    },
                    {
                        "name": "expected_outcome",
                        "description": "What state or message confirms the flow succeeded.",
                        "required": True,
                    },
                ],
            },
            {
                "name": "extract_screen_data",
                "description": "Extract structured data from the active phone screen according to a target schema.",
                "arguments": [
                    {
                        "name": "data_schema",
                        "description": "Description of the data fields to extract into JSON.",
                        "required": True,
                    },
                ],
            },
            {
                "name": "troubleshoot_screen",
                "description": "Inspect and diagnose why an expected element is missing, dialog is blocking, or app crashed.",
                "arguments": [],
            },
        ]

    def handle_prompt_get(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Generates prompt template messages for agent task execution."""
        if name == "mobile_flow_qa":
            flow = arguments.get("target_flow", "Target mobile workflow")
            outcome = arguments.get("expected_outcome", "Expected success state")
            return {
                "description": f"Automated Mobile QA Flow: {flow}",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"You are executing mobile QA for flow: '{flow}'.\n"
                                f"Expected outcome: '{outcome}'.\n\n"
                                "Guidelines:\n"
                                "1. Call `phone_observe` first to inspect the indexed screen DOM.\n"
                                "2. Tap, type, or swipe using indexed elements [ID] and the current observation_generation.\n"
                                "3. If unexpected permission dialogs appear, call `phone_dismiss_dialog`.\n"
                                "4. Finally, call `phone_assert_state` to verify the expected outcome.\n"
                                "5. Report the final efficiency metrics via `phone_efficiency_report`."
                            ),
                        },
                    }
                ],
            }
        elif name == "extract_screen_data":
            schema = arguments.get("data_schema", "All key-value fields")
            return {
                "description": "Extract Structured Screen Data",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Extract structured data from the current mobile screen matching: '{schema}'.\n\n"
                                "1. Call `phone_observe` with `filter_interactive_only=False` to inspect all text elements.\n"
                                "2. Extract the values into a clean JSON object according to the schema.\n"
                                "3. If data is scrolled out of view, use `phone_swipe` (direction='up') and observe again."
                            ),
                        },
                    }
                ],
            }
        elif name == "troubleshoot_screen":
            return {
                "description": "Troubleshoot Mobile Screen State",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                "The mobile screen appears stuck, unresponsive, or in an unexpected state.\n\n"
                                "1. Call `phone_health_check` to verify ADB/WDA backend status.\n"
                                "2. Call `phone_observe` with `include_raw_image=True` to inspect visual state.\n"
                                "3. Check if a system dialog or keyboard is obscuring the view.\n"
                                "4. If an alert dialog is detected, call `phone_dismiss_dialog`.\n"
                                "5. If the app has crashed, call `phone_open_app` to restart it."
                            ),
                        },
                    }
                ],
            }
        else:
            raise PhoneHarnessError(f"Prompt not found: {name}")

    def run_stdio_server(self) -> None:
        """Standard JSON-RPC 2.0 stdio server loop for MCP."""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except Exception:
                continue

            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "phone-harness-mcp", "version": "1.1.0"},
                        "capabilities": {
                            "tools": {},
                            "resources": {},
                            "prompts": {},
                        },
                    },
                }
                print(self._compact_json(response), flush=True)

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": self.get_tool_definitions()},
                }
                print(self._compact_json(response), flush=True)

            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                tool_res = self.handle_tool_call(tool_name, tool_args)
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": tool_res,
                }
                print(self._compact_json(response), flush=True)

            elif method == "resources/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"resources": self.get_resource_definitions()},
                }
                print(self._compact_json(response), flush=True)

            elif method == "resources/read":
                uri = params.get("uri", "")
                try:
                    res = self.handle_resource_read(uri)
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": res,
                    }
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32002, "message": str(exc)},
                    }
                print(self._compact_json(response), flush=True)

            elif method == "prompts/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"prompts": self.get_prompt_definitions()},
                }
                print(self._compact_json(response), flush=True)

            elif method == "prompts/get":
                prompt_name = params.get("name", "")
                prompt_args = params.get("arguments", {})
                try:
                    res = self.handle_prompt_get(prompt_name, prompt_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": res,
                    }
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": str(exc)},
                    }
                print(self._compact_json(response), flush=True)

            elif method == "ping":
                print(self._compact_json({"jsonrpc": "2.0", "id": msg_id, "result": {}}), flush=True)

            else:
                if msg_id is not None:
                    print(
                        self._compact_json(
                            {
                                "jsonrpc": "2.0",
                                "id": msg_id,
                                "error": {"code": -32601, "message": f"Method not found: {method}"},
                            }
                        ),
                        flush=True,
                    )


def main():
    server = PhoneHarnessMCPServer()
    server.run_stdio_server()


if __name__ == "__main__":
    main()

