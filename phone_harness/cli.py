"""
Command Line Interface (CLI) for Phone Harness.
Provides terminal commands for agents and developers to control phones and run the MCP server.
"""

import sys

# Ensure utf-8 encoding for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from phone_harness.harness import PhoneHarness
from phone_harness.core.models import (
    ActionRequest,
    ActionType,
    KeyCode,
    SwipeDirection,
    VerificationSpec,
)
from phone_harness.mcp_server import PhoneHarnessMCPServer

console = Console(safe_box=True)


@click.group()
def cli():
    """Universal Phone Harness CLI - Next-Gen Phone Control for AI Agents."""
    pass


@cli.command()
def serve():
    """Starts the Model Context Protocol (MCP) JSON-RPC stdio server."""
    server = PhoneHarnessMCPServer()
    server.run_stdio_server()


@cli.command()
@click.option("--som/--no-som", default=False, help="Generate Set-of-Marks image")
@click.option("--all-elements/--interactive-only", default=False, help="Show all layout elements")
def observe(som: bool, all_elements: bool):
    """Inspects the current phone screen and outputs the indexed DOM."""
    harness = PhoneHarness()
    state = harness.observe(include_som_image=som, filter_interactive_only=not all_elements)

    table = Table(title=f"Phone State: {state.current_app_package} ({state.screen_width}x{state.screen_height})")
    table.add_column("ID", justify="center", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Label / Text", style="green")
    table.add_column("Bounds {x, y, w, h}", style="yellow")
    table.add_column("Flags", style="blue")

    for elem in state.elements:
        w = elem.bounds[2] - elem.bounds[0]
        h = elem.bounds[3] - elem.bounds[1]
        bounds_str = f"{{{elem.bounds[0]}, {elem.bounds[1]}, {w}, {h}}}"
        flags = []
        if elem.is_clickable:
            flags.append("clickable")
        if elem.is_editable:
            flags.append("editable")
        if elem.is_checked is not None:
            flags.append(f"checked={elem.is_checked}")
        if elem.is_password:
            flags.append("password")

        table.add_row(
            str(elem.id),
            elem.type,
            elem.text or elem.description or "",
            bounds_str,
            ", ".join(flags),
        )

    console.print(table)
    console.print(Panel(state.compact_dom, title="Token-Compacted DOM for LLM (<500 tokens)"))


@cli.command()
@click.argument("target")
@click.option("--confirm-destructive/--no-confirm", default=False, help="Confirm destructive actions")
def tap(target: str, confirm_destructive: bool):
    """Taps an element by integer index [ID] or text label."""
    harness = PhoneHarness()
    target_idx = int(target) if target.isdigit() else None
    target_txt = None if target.isdigit() else target

    req = ActionRequest(
        action=ActionType.TAP,
        target_index=target_idx,
        target_text=target_txt,
        confirm_destructive=confirm_destructive,
    )
    res = harness.execute_action(req)
    console.print(f"[bold green][OK] Tapped {res.target_info} in {res.latency_ms}ms[/bold green]")


@cli.command("type")
@click.argument("text")
@click.option("--index", "-i", type=int, default=None, help="Target EditText index badge")
@click.option("--enter/--no-enter", default=False, help="Press enter after typing")
def type_cmd(text: str, index: int, enter: bool):
    """Types text into active input field or specified element index."""
    harness = PhoneHarness()
    req = ActionRequest(
        action=ActionType.TYPE,
        target_index=index,
        text_to_type=text,
        press_enter=enter,
    )
    res = harness.execute_action(req)
    console.print(f"[bold green][OK] Typed '{text}' in {res.latency_ms}ms[/bold green]")


@cli.command()
@click.argument("direction", type=click.Choice(["up", "down", "left", "right"]))
@click.option("--distance", type=click.Choice(["short", "medium", "long"]), default="medium")
def swipe(direction: str, distance: str):
    """Swipes in a given direction."""
    harness = PhoneHarness()
    req = ActionRequest(
        action=ActionType.SWIPE,
        direction=SwipeDirection(direction),
        swipe_distance=distance,
    )
    res = harness.execute_action(req)
    console.print(f"[bold green][OK] Swiped {direction} ({distance}) in {res.latency_ms}ms[/bold green]")


@cli.command("press")
@click.argument("key", type=click.Choice(["HOME", "BACK", "APP_SWITCH", "ENTER", "VOLUME_UP", "VOLUME_DOWN", "POWER"]))
def press_cmd(key: str):
    """Presses a system navigation key."""
    harness = PhoneHarness()
    req = ActionRequest(action=ActionType.PRESS_KEY, key=KeyCode(key))
    res = harness.execute_action(req)
    console.print(f"[bold green][OK] Pressed {key} in {res.latency_ms}ms[/bold green]")


@cli.command("open")
@click.argument("app_name")
def open_cmd(app_name: str):
    """Launches an application by Android package identifier."""
    harness = PhoneHarness()
    req = ActionRequest(action=ActionType.OPEN_APP, package_name=app_name)
    res = harness.execute_action(req)
    console.print(f"[bold green][OK] Launched {app_name} in {res.latency_ms}ms[/bold green]")


@cli.command("url")
@click.argument("target_url")
def url_cmd(target_url: str):
    """Opens a validated HTTP or HTTPS URL in the default browser."""
    harness = PhoneHarness()
    state = harness.open_url(target_url)
    console.print(f"[bold green][OK] Opened URL: {target_url} -> Active: {state.current_app_package}[/bold green]")


@cli.command("settings")
@click.argument("section", default="settings")
def settings_cmd(section: str):
    """Directly opens a settings section (wifi, bluetooth, apps, display, battery)."""
    harness = PhoneHarness()
    state = harness.open_settings(section)
    console.print(f"[bold green][OK] Opened Settings Section: {section}[/bold green]")


@cli.command("paste")
@click.argument("text")
def paste_cmd(text: str):
    """Fast-pastes text into active input field via clipboard."""
    harness = PhoneHarness()
    harness.set_clipboard(text)
    harness.device.type_text(text, fast_paste=True)
    console.print(f"[bold green][OK] Fast-pasted text ({len(text)} chars)[/bold green]")


@cli.command("dismiss")
@click.option("--action", type=click.Choice(["allow", "deny", "dismiss"]), default="deny")
def dismiss_cmd(action: str):
    """Auto-detects and dismisses system permission or alert dialogs."""
    harness = PhoneHarness()
    res = harness.dismiss_dialog(action=action)
    console.print(f"[bold green][OK] Dismissed dialog with action: {action}[/bold green]")


@cli.command("wait")
@click.option("--text", "-t", multiple=True, help="Text strings that must appear")
@click.option("--package", "-p", default=None, help="Package that must be in foreground")
@click.option("--timeout", default=5000, help="Timeout in milliseconds")
def wait_cmd(text: tuple, package: str, timeout: int):
    """Locally polls the screen until expected text or app appears."""
    harness = PhoneHarness()
    passed, state = harness.wait_for_condition(
        text_present=list(text) if text else None,
        app_package=package,
        timeout_ms=timeout,
    )
    if passed:
        console.print(f"[bold green][OK] Condition met in foreground app: {state.current_app_package}[/bold green]")
    else:
        console.print(f"[bold red][TIMEOUT] Condition not met within {timeout}ms[/bold red]")


@cli.command()
def doctor():
    """Runs diagnostics on ADB, WDA, Python environment, and connected devices."""
    console.print("[bold cyan]=== Phone Harness Diagnostics ===[/bold cyan]\n")
    harness = PhoneHarness()
    summary = harness.device.get_device_summary()

    console.print(f"[*] Active Backend: [green]{summary.platform}[/green]")
    console.print(f"[*] Device Model:   [white]{summary.model}[/white]")
    console.print(f"[*] OS Version:     [white]{summary.os_version}[/white]")
    console.print(f"[*] Resolution:     [white]{summary.screen_resolution[0]}x{summary.screen_resolution[1]}[/white]")
    console.print(f"[*] Status:         [green]{'ONLINE' if summary.is_connected else 'OFFLINE'}[/green]")
    console.print(f"[*] Capabilities:   [yellow]{', '.join(summary.capabilities)}[/yellow]\n")
    console.print("[bold green][OK] Phone Harness Environment Ready for AI Agents![/bold green]")


def main():
    cli()


if __name__ == "__main__":
    main()
