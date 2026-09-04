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
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="MCP transport mechanism")
@click.option("--host", default="127.0.0.1", help="Host address for HTTP/SSE transport")
@click.option("--port", default=8080, type=int, help="Port for HTTP/SSE transport")
@click.option("--auth-token", default=None, help="Bearer token for HTTP/SSE authentication")
def serve(transport: str, host: str, port: int, auth_token: str):
    """Starts the Model Context Protocol (MCP) server over stdio or HTTP/SSE."""
    server = PhoneHarnessMCPServer()
    if transport == "sse":
        from phone_harness.transport.sse_server import MCPSSEBridge
        console.print(f"[bold green][*] Starting Phone Harness MCP SSE Bridge on http://{host}:{port}[/bold green]")
        if auth_token:
            console.print("[yellow][*] Bearer token authentication enabled.[/yellow]")
        bridge = MCPSSEBridge(mcp_server=server, host=host, port=port, auth_token=auth_token)
        try:
            bridge.start(background=False)
        except KeyboardInterrupt:
            console.print("[yellow]Shutting down SSE bridge...[/yellow]")
            bridge.stop()
    else:
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


@cli.command("screenshot")
@click.argument("output_path", default="screenshot.png")
@click.option("--som/--no-som", default=False, help="Include Set-of-Marks indexed badges")
def screenshot_cmd(output_path: str, som: bool):
    """Captures and saves a phone screenshot locally (.png or .jpg)."""
    harness = PhoneHarness()
    w, h = harness.save_screenshot(output_path, include_som=som)
    mode = "Set-of-Marks" if som else "Raw"
    console.print(f"[bold green][OK] Saved {mode} screenshot to {output_path} ({w}x{h})[/bold green]")


@cli.command("clipboard")
@click.option("--set", "set_text", default=None, help="Text to copy to device clipboard")
def clipboard_cmd(set_text: str = None):
    """Gets or sets the device system clipboard."""
    harness = PhoneHarness()
    if set_text is not None:
        harness.set_clipboard(set_text)
        console.print(f"[bold green][OK] Set clipboard to: {set_text}[/bold green]")
    else:
        content = harness.get_clipboard()
        console.print(f"[bold green][OK] Clipboard content: {content}[/bold green]")


@cli.command("report")
@click.option("--optimal-steps", default=5, help="Baseline expected steps for the task")
def report_cmd(optimal_steps: int):
    """Displays step budget and latency efficiency report."""
    import json
    harness = PhoneHarness()
    rep = harness.get_efficiency_report(optimal_steps=optimal_steps)
    console.print(Panel(json.dumps(rep, indent=2), title="Phone Harness Efficiency Report"))


@cli.command("replay")
@click.argument("trace_path")
@click.option("--self-heal/--no-self-heal", default=True, help="Enable automatic self-healing re-grounding")
def replay_cmd(trace_path: str, self_heal: bool):
    """Replays an interaction session trace (.trace.jsonl)."""
    harness = PhoneHarness()
    summary = harness.replay_trace(trace_path, enable_self_healing=self_heal)
    status_color = "green" if summary.is_success else "red"
    console.print(f"[{status_color}]Trace Replay Finished: {summary.executed_steps}/{summary.total_steps} steps executed ({summary.healed_steps} healed)[/{status_color}]")


@cli.command("crawl")
@click.option("--package", default=None, help="Target app package to audit")
@click.option("--max-depth", default=5, type=int, help="Maximum screen exploration depth")
@click.option("--budget", default=20, type=int, help="Step budget for exploration")
@click.option("--output-dir", default="./crawler_audit", help="Output directory for QA report")
def crawl_cmd(package: str, max_depth: int, budget: int, output_dir: str):
    """Autonomously explores an app state graph and outputs an executive QA audit report."""
    harness = PhoneHarness()
    report = harness.crawl_app(target_package=package, max_depth=max_depth, step_budget=budget, output_directory=output_dir)
    console.print(f"[bold green][OK] Crawl finished: Discovered {report.screens_discovered} screens, {report.transitions_explored} transitions.[/bold green]")
    console.print(f"[*] Executive QA Report saved to: [cyan]{report.report_markdown_path}[/cyan]")


@cli.command("settle")
@click.option("--timeout", default=2.0, type=float, help="Max seconds to wait for visual stabilization")
def settle_cmd(timeout: float):
    """Waits for screen animations to visually settle using perceptual differencing."""
    harness = PhoneHarness()
    is_settled = harness.wait_for_settle(max_wait_seconds=timeout)
    if is_settled:
        console.print("[bold green][OK] Screen settled visually.[/bold green]")
    else:
        console.print("[yellow][!] Settle timeout reached before motion ceased.[/yellow]")


def main():
    cli()


if __name__ == "__main__":
    main()

