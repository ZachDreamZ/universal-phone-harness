"""
Task 5: Android text correctness regression tests (fix round 1).

These tests validate real ADB command construction through a recording
subclass that overrides ``AndroidPhoneDevice._run_adb``. They do NOT patch
subprocess or any implementation internals; they only observe the commands the
device would send and the outputs it would receive.

Required regression tests:

C2  ``clear_text`` primary path must be ONE host ADB shell call issuing, in
    exact order, ``KEYCODE_MOVE_END`` then a single ``--longpress KEYCODE_DEL``
    (``input keyevent KEYCODE_MOVE_END && input keyevent --longpress KEYCODE_DEL``).
    On a primary-command exception ONLY, a bounded 64-delete fallback (also a
    single constant-only shell call) runs; if the fallback also fails its error
    propagates. No user content is interpolated.

C1  ``type_text`` must not trust a broadcast merely because it reports
    ``result=0``. Before sending ``ADB_INPUT_B64`` it must gather evidence that
    ``com.android.adbkeyboard`` is installed and is the current default IME. If
    the receiver is absent/inactive the broadcast is skipped and the call falls
    through to standard input. When the receiver is active AND ``result=0`` is
    observed, the broadcast is accepted.

I1  ``type_text`` must not report a successful clipboard paste after
    ``set_clipboard`` silently failed. A failed clipboard setup must fall
    through to the final input command, and a failing final command must
    propagate its error.
"""

import base64
import shlex

import pytest

from phone_harness.backends.android import AndroidPhoneDevice


class RecordingAndroidDevice(AndroidPhoneDevice):
    """Override ``_run_adb`` to record command construction and return scripted
    output without touching subprocess or real hardware."""

    def __init__(self, serial=None):
        super().__init__(serial)
        self.calls = []          # list of args lists passed to _run_adb
        self.responses = {}      # substring -> response string
        self.raises = {}         # substring -> exception to raise

    def script(self, responses=None, raises=None):
        self.responses = responses or {}
        self.raises = raises or {}

    def _run_adb(self, args, timeout=5.0):
        self.calls.append(list(args))
        joined = " ".join(args)
        for substr, exc in self.raises.items():
            if substr in joined:
                raise exc
        for substr, resp in self.responses.items():
            if substr in joined:
                return resp
        return ""


def _calls_joined(dev):
    return [" ".join(c) for c in dev.calls]


ADBKEYBOARD_ENABLED = (
    "com.android.adbkeyboard/.AdbKeyboard\n"
    "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
)
ADBKEYBOARD_DEFAULT = "com.android.adbkeyboard/.AdbKeyboard"
GBOARD_ENABLED = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
GBOARD_DEFAULT = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"


def test_clear_text_primary_single_call_exact_order():
    """Task 6 (C2): clear_text primary path must be a SINGLE host ADB shell call
    issuing, in exact order, ``KEYCODE_MOVE_END`` then a single
    ``--longpress KEYCODE_DEL``:
        input keyevent KEYCODE_MOVE_END && input keyevent --longpress KEYCODE_DEL
    No select-all chord (keycombination) is used; no user content is interpolated;
    the command string must be exactly the constant composition.
    """
    dev = RecordingAndroidDevice()
    dev.clear_text()

    assert dev.calls, "clear_text sent no commands"

    # SINGLE host ADB call (one shell roundtrip).
    assert len(dev.calls) == 1, (
        f"clear_text must be a single ADB call: {_calls_joined(dev)}"
    )
    full = " ".join(dev.calls[0])
    assert dev.calls[0][0] == "shell", f"expected a shell call: {full}"

    # No select-all chord in the fast path.
    assert "keycombination" not in full, full

    # Exact composition (constant-only; no user input interpolated).
    expected = (
        "shell input keyevent KEYCODE_MOVE_END"
        " && input keyevent --longpress KEYCODE_DEL"
    )
    assert full == expected, f"{full}\n!=\n{expected}"

    # Exact order: MOVE_END strictly before the long-press DELETE.
    move_i = full.find("KEYCODE_MOVE_END")
    del_i = full.find("--longpress KEYCODE_DEL")
    assert move_i != -1 and del_i != -1, full
    assert move_i < del_i, (
        "clear_text order wrong (expected MOVE_END then --longpress DEL): "
        f"{full}"
    )
    # Exactly one DELETE token in the primary path (single long-press, not a burst).
    assert full.count("KEYCODE_DEL") == 1, full


def test_clear_text_successful_path_skips_fallback():
    """Task 6 (C2): when the primary command succeeds, clear_text does NOT run
    the bounded 64-delete fallback — only the single primary call is issued."""
    dev = RecordingAndroidDevice()
    dev.clear_text()

    # Single call only; the fallback 64-delete burst is NOT invoked.
    assert len(dev.calls) == 1, _calls_joined(dev)
    # Only the single long-press DELETE is present (no bounded burst).
    assert " ".join(dev.calls[0]).count("KEYCODE_DEL") == 1, _calls_joined(dev)


def test_clear_text_exception_invokes_bounded_fallback_and_propagates():
    """Task 6 (C2): on a primary-command exception, clear_text must run the
    bounded (>20) 64-delete fallback as a constant-only shell call, and if that
    fallback also fails the exception must propagate to the caller."""
    dev = RecordingAndroidDevice()
    # Make BOTH the primary and the fallback shell calls raise.
    dev.script(raises={"shell": RuntimeError("adb shell failed")})

    with pytest.raises(RuntimeError):
        dev.clear_text()

    # Primary attempted, then fallback attempted => two shell calls.
    assert len(dev.calls) == 2, _calls_joined(dev)
    # The fallback must be the bounded 64-delete burst (>20 deletes).
    fallback = " ".join(dev.calls[1])
    assert "input keyevent" in fallback, fallback
    n = fallback.count("KEYCODE_DEL")
    assert n > 20, f"fallback delete count ({n}) not >20: {fallback}"
    assert n == dev._CLEAR_FALLBACK_DELETES, fallback


def test_set_clipboard_raises_on_readback_mismatch():
    """I1 (Fix Round 2): set_clipboard must raise RuntimeError when the
    read-back content differs from the input (silent-success paste prevented)."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            # set command reports success
            "cmd clipboard set": "Set succeeded",
            # read-back returns something other than the input
            "cmd clipboard get": "DIFFERENT-CONTENT",
        }
    )
    with pytest.raises(RuntimeError):
        dev.set_clipboard("secret text")


def test_set_clipboard_raises_when_readback_unavailable():
    """I1 (Fix Round 2): set_clipboard must raise RuntimeError when the read-back
    cannot be performed (cannot confirm)."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={"cmd clipboard set": "Set succeeded"},
        raises={"cmd clipboard get": RuntimeError("readback unavailable")},
    )
    with pytest.raises(RuntimeError):
        dev.set_clipboard("secret text")


def test_type_text_propagates_failure_after_clipboard_mismatch():
    """I1 (Fix Round 2): when set_clipboard raises on a read-back mismatch,
    type_text must fall through to the final input command, and a failing final
    command must propagate its error (not be reported as success)."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            # adbkeyboard inactive -> broadcast path skipped
            "ime list": GBOARD_ENABLED,
            "default_input_method": GBOARD_DEFAULT,
            # set command reports success but read-back mismatches
            "cmd clipboard set": "Set succeeded",
            "cmd clipboard get": "WRONG",
        },
        raises={"input text": RuntimeError("ADB error code 1")},
    )
    # Long enough (>12 chars) to reach the clipboard fallback path.
    with pytest.raises(RuntimeError):
        dev.type_text("this is a long clipboard test")


def test_type_text_skips_broadcast_when_adbkeyboard_inactive():
    """C1 (inactive evidence): when com.android.adbkeyboard is NOT installed or
    not the default IME, no ADB_INPUT_B64 broadcast may be attempted and the call
    must fall through to standard input text."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            "ime list": GBOARD_ENABLED,
            "default_input_method": GBOARD_DEFAULT,
        }
    )
    dev.type_text("hello")  # short ASCII -> clipboard fallback skipped

    broadcast_calls = [c for c in _calls_joined(dev) if "ADB_INPUT_B64" in c]
    input_text_calls = [c for c in _calls_joined(dev) if "input text" in c]

    assert not broadcast_calls, (
        "ADB_INPUT_B64 broadcast attempted without receiver evidence: "
        f"{_calls_joined(dev)}"
    )
    assert input_text_calls, (
        "type_text did not fall through to standard input text when adbkeyboard "
        f"is inactive: {_calls_joined(dev)}"
    )


def test_type_text_uses_broadcast_when_adbkeyboard_active_and_result0():
    """C1 (active evidence): when adbkeyboard is installed AND the default IME,
    and the broadcast confirms delivery (result=0), the broadcast is accepted and
    the call does NOT fall through to standard input text."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            "ime list": ADBKEYBOARD_ENABLED,
            "default_input_method": ADBKEYBOARD_DEFAULT,
            "am broadcast": (
                "Broadcasting: Intent { act=ADB_INPUT_B64 ... }\n"
                "Broadcast completed: result=0\n"
            ),
        }
    )
    dev.type_text("hello")

    broadcast_calls = [c for c in _calls_joined(dev) if "ADB_INPUT_B64" in c]
    input_text_calls = [c for c in _calls_joined(dev) if "input text" in c]

    assert broadcast_calls, "ADB_INPUT_B64 broadcast was not attempted"
    assert not input_text_calls, (
        "confirmed broadcast should not fall through to input text: "
        f"{_calls_joined(dev)}"
    )


def test_broadcast_without_confirmation_falls_through_to_input_text():
    """C1: even with adbkeyboard active, a broadcast whose output lacks delivery
    confirmation (no result=0) must NOT be treated as success; type_text must
    fall through to standard input text."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            "ime list": ADBKEYBOARD_ENABLED,
            "default_input_method": ADBKEYBOARD_DEFAULT,
            "am broadcast": (
                "Broadcasting: Intent { act=ADB_INPUT_B64 ... }\n"
                "Broadcast completed\n"  # no result=0 -> not confirmed
            ),
        }
    )
    dev.type_text("hello")

    broadcast_calls = [c for c in _calls_joined(dev) if "ADB_INPUT_B64" in c]
    input_text_calls = [c for c in _calls_joined(dev) if "input text" in c]

    assert broadcast_calls, "ADB_INPUT_B64 broadcast was not attempted"
    assert input_text_calls, (
        "type_text did not fall through to standard input text for an "
        f"unconfirmed broadcast: {_calls_joined(dev)}"
    )


def test_clipboard_set_failure_falls_through_to_input_text():
    """I1: a silently-failed set_clipboard must not report a successful paste.
    type_text must fall through to the final input command instead."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            # adbkeyboard inactive -> broadcast path skipped
            "ime list": GBOARD_ENABLED,
            "default_input_method": GBOARD_DEFAULT,
            # clipboard service set reports failure
            "cmd clipboard set": RuntimeError("ADB error code 1"),
            "cmd clipboard get": "",
        }
    )
    # Long enough (>12 chars) to reach the clipboard fallback path.
    dev.type_text("this is a long clipboard test")

    input_text_calls = [c for c in _calls_joined(dev) if "input text" in c]
    paste_calls = [c for c in _calls_joined(dev) if "279" in c or "KEYCODE_PASTE" in c]

    assert not paste_calls, (
        "type_text reported a paste despite set_clipboard failing: "
        f"{_calls_joined(dev)}"
    )
    assert input_text_calls, (
        "type_text did not fall through to input text after clipboard failure: "
        f"{_calls_joined(dev)}"
    )


def test_nonzero_adb_command_propagates_failure():
    """I1: when the clipboard setup fails AND the final input command fails, the
    failure must propagate (raise) rather than be reported as success."""
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            "ime list": GBOARD_ENABLED,
            "default_input_method": GBOARD_DEFAULT,
            "cmd clipboard set": RuntimeError("ADB error code 1"),
            "cmd clipboard get": "",
        },
        raises={"input text": RuntimeError("ADB error code 1")},
    )
    with pytest.raises(RuntimeError):
        dev.type_text("this is a long clipboard test")


# --- Finding #1 (final review): set_clipboard error messages must never leak
# clipboard text, read-back, the underlying exception string, base64, or command
# values. They must be stable generic messages. ---


class LeakFreeClipboardDevice(RecordingAndroidDevice):
    """Controls set / read-back outcomes without real ADB so we can assert that
    set_clipboard error messages never leak sensitive material."""

    def __init__(self, mode):
        super().__init__()
        self.mode = mode  # "setter_failure" | "readback_failure" | "mismatch"
        # Read-back value used for the mismatch scenario; deliberately differs from
        # any input so it must never appear verbatim in an error message.
        self.readback = "UNRELATED-READBACK-VALUE-z9x3"

    def script_for_mode(self):
        if self.mode == "setter_failure":
            # Primary cmd clipboard set raises; the broadcast call is swallowed.
            self.script(
                raises={
                    "cmd clipboard set": RuntimeError(
                        "underlying adb failure: exit=13 permission denied"
                    )
                }
            )
        else:
            self.script(responses={"cmd clipboard set": "Set succeeded"})

    def get_clipboard(self):
        if self.mode == "readback_failure":
            raise RuntimeError("underlying readback failure: clipboard service died")
        if self.mode == "mismatch":
            return self.readback
        return ""


SECRET_TEXT = "TEST_SECRET_VALUE_9F2a8Bc1D3e7 TopSecretValue 🔒"
GENERIC_MESSAGES = {
    "setter_failure": "clipboard set operation failed",
    "readback_failure": "clipboard readback could not be confirmed",
    "mismatch": "clipboard content mismatch after set",
}


def test_android_shell_quotes_typed_text():
    dev = RecordingAndroidDevice()
    dev.script(
        responses={
            "ime list": GBOARD_ENABLED,
            "default_input_method": GBOARD_DEFAULT,
        }
    )
    text = "hello;reboot|whoami"

    dev.type_text(text, fast_paste=False)

    input_call = next(call for call in dev.calls if call[1:3] == ["input", "text"])
    assert input_call[-1] == shlex.quote(text)


def test_android_clipboard_quotes_shell_metacharacters():
    dev = RecordingAndroidDevice()
    text = "secret;reboot|whoami"
    dev.script(
        responses={
            "cmd clipboard set": "Set succeeded",
            "cmd clipboard get": text,
        }
    )

    dev.set_clipboard(text)

    set_call = next(call for call in dev.calls if "cmd clipboard set" in " ".join(call))
    assert set_call[-1] == shlex.quote(text)


def test_android_open_url_allows_https_and_quotes_shell_metacharacters():
    dev = RecordingAndroidDevice()
    url = "https://example.com/path?x=1&y=2"

    dev.open_url(url)

    assert dev.calls[-1][-1] == shlex.quote(url)


@pytest.mark.parametrize("url", ["file:///data/local/tmp/private", "javascript:alert(1)", "intent://settings"])
def test_android_open_url_rejects_unsafe_schemes(url):
    dev = RecordingAndroidDevice()

    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        dev.open_url(url)

    assert dev.calls == []


def test_android_launch_app_rejects_shell_metacharacters():
    dev = RecordingAndroidDevice()

    with pytest.raises(ValueError, match="package identifier"):
        dev.launch_app("com.example.safe;reboot")

    assert dev.calls == []


@pytest.mark.parametrize("mode", ["setter_failure", "readback_failure", "mismatch"])
def test_set_clipboard_raises_generic_message_without_secret(mode):
    """set_clipboard must raise a stable generic message for every failure mode
    and must NOT include clipboard text, read-back, base64, command values, or
    the underlying exception string."""
    dev = LeakFreeClipboardDevice(mode)
    dev.script_for_mode()
    secret_b64 = base64.b64encode(SECRET_TEXT.encode("utf-8")).decode("utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        dev.set_clipboard(SECRET_TEXT)

    msg = str(excinfo.value)
    # Stable generic message (one of the three allowed strings only).
    assert GENERIC_MESSAGES[mode] in msg
    # Never leaks clipboard text, read-back, base64, command values, or the
    # underlying exception string.
    assert SECRET_TEXT not in msg
    assert secret_b64 not in msg
    assert dev.readback not in msg
    assert "cmd clipboard" not in msg
    assert "am broadcast" not in msg
    assert "permission denied" not in msg
    assert "service died" not in msg
    assert "TEST_SECRET_VALUE" not in msg
    assert "🔒" not in msg
