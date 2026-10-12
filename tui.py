#!/usr/bin/env -S uv run python
"""Textual TUI for exercising the Lumagen Radiance Pro TCP client."""

from __future__ import annotations

import json
import logging
import pathlib
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, ClassVar, cast

import typer
from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.widgets import Header, Input, RichLog, Static

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parent / "custom_components" / "lumagen"),
)

from client import (
    ASPECT_COMMANDS,
    REMOTE_COMMANDS,
    InputMemory,
    LabelCategory,
    LumagenClient,
    LumagenConnectionError,
    LumagenState,
)

# ---------------------------------------------------------------------------
# Instrumented client — captures raw protocol traffic
# ---------------------------------------------------------------------------


class CommandInput(Input):
    """Input with readline-style tab completion."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "complete", "Tab completion", show=False),
        Binding("up", "history_prev", "Previous command", show=False),
        Binding("down", "history_next", "Next command", show=False),
    ]

    def __init__(self, completions: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._completions = completions
        self._history: list[str] = []
        self._history_idx: int = 0
        self._saved_input: str = ""

    def add_to_history(self, cmd: str) -> None:
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._history_idx = len(self._history)
        self._saved_input = ""

    def action_history_prev(self) -> None:
        if not self._history:
            return
        if self._history_idx == len(self._history):
            self._saved_input = self.value
        if self._history_idx > 0:
            self._history_idx -= 1
            self.value = self._history[self._history_idx]
            self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        if self._history_idx >= len(self._history):
            return
        self._history_idx += 1
        if self._history_idx == len(self._history):
            self.value = self._saved_input
        else:
            self.value = self._history[self._history_idx]
        self.cursor_position = len(self.value)

    def action_complete(self) -> None:
        """Readline-style tab completion."""
        text = self.value.lower()
        if not text:
            return

        matches = [c for c in self._completions if c.lower().startswith(text)]
        if not matches:
            return

        if len(matches) == 1:
            # Unique match — complete it, add trailing space if it's a full command
            completed = matches[0]
            if not any(
                c.lower().startswith(completed.lower()) and c != completed
                for c in self._completions
            ):
                completed += " "
            self.value = completed
            self.cursor_position = len(self.value)
        else:
            # Multiple matches — complete the common prefix
            prefix = matches[0]
            for m in matches[1:]:
                while not m.lower().startswith(prefix.lower()):
                    prefix = prefix[:-1]
            if len(prefix) > len(text):
                self.value = prefix
                self.cursor_position = len(self.value)
            else:
                # Show options in the log
                log = self.app.query_one("#log", RichLog)
                log.write("[dim]  " + "  ".join(sorted(matches)) + "[/]")


class WrappingRichLog(RichLog):
    """RichLog that re-wraps content when the widget is resized."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._writes: list[str] = []
        self._rewrapping = False
        self._last_width: int | None = None

    def write(
        self,
        content: object,
        *args: Any,
        **kwargs: Any,
    ) -> WrappingRichLog:
        if not self._rewrapping and isinstance(content, str):
            self._writes.append(content)
        super().write(content, *args, **kwargs)
        return self

    def clear(self) -> WrappingRichLog:
        self._writes.clear()
        super().clear()
        return self

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        prev = self._last_width
        self._last_width = event.size.width
        if prev is not None and event.size.width != prev:
            self.set_timer(0.05, self._rewrap)

    def rewrap(self) -> None:
        """Force a re-render of all buffered writes (e.g. after visibility change)."""
        self._rewrap()

    def _rewrap(self) -> None:
        at_end = self.scroll_offset.y >= self.virtual_size.height - self.size.height
        self._rewrapping = True
        super().clear()
        for content in self._writes:
            super().write(content)
        self._rewrapping = False
        if at_end:
            self.scroll_end(animate=False)


class InstrumentedClient(LumagenClient):
    """LumagenClient subclass that emits send/receive events for the TUI."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port)
        self._on_line_sent: list[Callable[[str], None]] = []
        self._on_line_received: list[Callable[[str], None]] = []

    async def _send_command(self, cmd: str) -> None:
        for cb in self._on_line_sent:
            cb(cmd)
        await super()._send_command(cmd)

    def _on_readline(self, line: str) -> None:
        for cb in self._on_line_received:
            cb(line)
        super()._on_readline(line)


# ---------------------------------------------------------------------------
# State panel widget
# ---------------------------------------------------------------------------


def _source_summary(s: LumagenState) -> str:
    if s.source_vertical_resolution is None:
        return "—"
    mode = (s.source_mode or "")[0:1].lower() if s.source_mode else ""
    rate = f" {s.source_vertical_rate}Hz" if s.source_vertical_rate else ""
    return f"{s.source_vertical_resolution}{mode}{rate}"


def _output_summary(s: LumagenState) -> str:
    if s.output_vertical_resolution is None:
        return "—"
    mode = (s.output_mode or "Progressive")[0:1].lower() if s.output_mode else "p"
    rate = f" {s.output_vertical_rate}Hz" if s.output_vertical_rate else ""
    return f"{s.output_vertical_resolution}{mode}{rate}"


def _outputs_on(s: LumagenState) -> str:
    if s.outputs_on is None:
        return "—"
    active = [str(i + 1) for i in range(16) if s.outputs_on & (1 << i)]
    return ", ".join(active) if active else "None"


def _input_summary(s: LumagenState) -> str:
    if s.logical_input is None:
        return "—"
    mem = s.input_memory or "A"
    suffix = f" ({s.input_label})" if s.input_label else ""
    return f"{s.logical_input}{mem}{suffix}"


def _physical_in(s: LumagenState) -> str:
    return str(s.physical_input) if s.physical_input is not None else "—"


def _cms(s: LumagenState) -> str:
    if s.output_cms is None:
        return "—"
    suffix = f" ({s.cms_label})" if s.cms_label else ""
    return f"{s.output_cms + 1}{suffix}"


def _style(s: LumagenState) -> str:
    if s.output_style is None:
        return "—"
    suffix = f" ({s.style_label})" if s.style_label else ""
    return f"{s.output_style + 1}{suffix}"


_STATE_FIELDS: list[tuple[str, str, Callable[[LumagenState], str | None] | None]] = [
    ("Connected", "connected", lambda s: "Yes" if s.connected else "No"),
    (
        "Power",
        "power",
        lambda s: {True: "On", False: "Off", None: "—"}[s.power],
    ),
    ("Model", "model_name", lambda s: s.model_name or "—"),
    ("Firmware", "software_revision", lambda s: s.software_revision or "—"),
    ("Serial", "serial_number", lambda s: s.serial_number or "—"),
    ("", "", None),  # spacer
    ("Input", "logical_input", _input_summary),
    ("Physical In", "physical_input", _physical_in),
    ("Video Status", "input_video_status", lambda s: s.input_video_status or "—"),
    ("", "", None),
    ("Source", "_source_summary", _source_summary),
    ("Dynamic Range", "source_dynamic_range", lambda s: s.source_dynamic_range or "—"),
    ("Source Aspect", "source_aspect", lambda s: s.source_aspect or "—"),
    (
        "Content Aspect",
        "source_content_aspect",
        lambda s: s.source_content_aspect or "—",
    ),
    ("Raster Aspect", "source_raster_aspect", lambda s: s.source_raster_aspect or "—"),
    ("NLS", "nls", lambda s: {True: "Active", False: "Off", None: "—"}[s.nls]),
    ("Source 3D", "source_3d_mode", lambda s: s.source_3d_mode or "—"),
    ("", "", None),
    ("Output", "_output_summary", _output_summary),
    ("Output Aspect", "output_aspect", lambda s: s.output_aspect or "—"),
    ("Colorspace", "output_colorspace", lambda s: s.output_colorspace or "—"),
    ("Output 3D", "output_3d_mode", lambda s: s.output_3d_mode or "—"),
    ("Outputs On", "outputs_on", _outputs_on),
    ("CMS", "_cms", _cms),
    ("Style", "_style", _style),
    ("", "", None),
    (
        "Auto Aspect",
        "auto_aspect",
        lambda s: {True: "On", False: "Off", None: "—"}[s.auto_aspect],
    ),
]


class StatePanel(Static):
    """Displays current device state as a formatted table."""

    DEFAULT_CSS = """
    StatePanel {
        width: 1fr;
        padding: 0 0 0 1;
    }
    """

    _LABEL_WIDTH = max(len(label) + 1 for label, _, fmt in _STATE_FIELDS if fmt)

    def render_state(self, state: LumagenState) -> str:
        lines: list[str] = []
        for label, _key, fmt in _STATE_FIELDS:
            if fmt is None:
                lines.append("")
                continue
            val = fmt(state) or "—"
            lines.append(f"{label + ':':<{self._LABEL_WIDTH}s} {val}")
        return "\n".join(lines)

    def update_state(self, state: LumagenState) -> None:
        self.update(self.render_state(state))


# ---------------------------------------------------------------------------
# TUI app
# ---------------------------------------------------------------------------

HELP_TEXT = """\
[bold]Power & Input[/]
  on / off — power on or off
  <1-19> — select input
  a / b / c / d — input memory

[bold]Video Processing[/]
  aspect <name> — 1.33, 1.78, 2.40, …
  nls — non-linear stretch
  autoaspect on / off — auto aspect

[bold]Labels & OSD[/]
  labels — show all labels
  label <id> <text> — e.g. label A1 Apple TV
  osd \\[0-9] <text> — OSD message (| for line break)
  osd — clear OSD

[bold]Navigation & System[/]
  remote <cmd> — menu, up, ok, exit, …
  save — save config to flash
  restart — restart outputs (ALT+PREV)

[bold]Raw RS232[/]
  %CMD — e.g. %ZQS01, %ZQI24 (\\r=CR, \\n=NL)

[bold]Keys[/]
  Ctrl+H help     Ctrl+Q quit
  Ctrl+I info     Ctrl+R reload
  Ctrl+L clear log"""

# All completable command prefixes for the suggester
_COMMAND_SUGGESTIONS = sorted(
    {
        "on",
        "off",
        *[f"aspect {a}" for a in ASPECT_COMMANDS],
        "autoaspect on",
        "autoaspect off",
        "nls",
        "labels",
        "label ",
        "osd ",
        *[f"remote {k}" for k in REMOTE_COMMANDS if not k.isdigit()],
        "remote 0..9",
        "remote 10+",
        "save",
        "restart",
    }
)


class LumagenTUI(App[None]):
    """Textual TUI for the Lumagen Radiance Pro."""

    CSS = """
    #main {
        height: 1fr;
    }
    #state-panel {
        width: 34;
        border: solid $accent;
        border-title-color: $text;
    }
    #log-panel {
        width: 1fr;
        border: solid $accent;
        border-title-color: $text;
    }
    #log {
        scrollbar-size: 1 1;
    }
    #help-panel {
        width: 1fr;
        border: solid $success;
        border-title-color: $text;
        scrollbar-size: 1 1;
        display: none;
    }
    #help-panel.visible {
        display: block;
    }
    #help-content {
        padding: 0 1;
    }
    #input-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear log"),
        ("ctrl+i", "refresh_info", "Refresh info"),
        ("ctrl+r", "reload_config", "Reload config"),
        ("ctrl+h", "toggle_help", "Help"),
    ]

    _STATE_FILE = pathlib.Path(__file__).resolve().parent / "tui.state"

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._client = InstrumentedClient(host, port)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="state-panel"):
                yield StatePanel(id="state")
            with Vertical(id="log-panel"):
                yield WrappingRichLog(
                    id="log",
                    highlight=True,
                    markup=True,
                    wrap=True,
                    min_width=0,
                )
            with VerticalScroll(id="help-panel"):
                yield Static(HELP_TEXT, id="help-content", markup=True)
        yield CommandInput(
            _COMMAND_SUGGESTIONS,
            placeholder="Enter command (Ctrl+H for help; Ctrl+Q to quit)",
            id="input-bar",
        )

    def on_mount(self) -> None:
        self.title = f"Lumagen — {self._host}:{self._port}"
        self.query_one("#state-panel").border_title = "State"
        self.query_one("#log-panel").border_title = "Protocol Log"
        self.query_one("#help-panel").border_title = "Help (Ctrl+H)"

        self._client._on_line_sent.append(self._log_sent)  # pyright: ignore[reportPrivateUsage]
        self._client._on_line_received.append(self._log_received)  # pyright: ignore[reportPrivateUsage]

        self.query_one("#input-bar", Input).focus()
        self._connect_client()

    @work(exclusive=True)
    async def _connect_client(self) -> None:
        log = self.query_one("#log", RichLog)

        has_stored = self._load_state()
        if has_stored:
            log.write("[dim]Loaded stored state.[/]")
            self._refresh_state()

        log.write("[dim]Connecting…[/]")

        await self._client.connect(
            on_state_changed=self._on_state_changed,
            on_connection_changed=self._on_connection_changed,
        )

        if self._client.state.connected:
            if not has_stored:
                log.write("[dim]Fetching config…[/]")
                await self._client.query_config()
                self._save_state()
            await self._client.query_runtime()
            self._refresh_state()
        else:
            log.write("[red]Connection failed.[/]")

    def _on_state_changed(self) -> None:
        self.call_later(self._refresh_state)

    def _on_connection_changed(self, connected: bool) -> None:
        def _update() -> None:
            log = self.query_one("#log", RichLog)
            if connected:
                log.write("[green]Connected.[/]")
            else:
                log.write("[red]Disconnected.[/]")
            self._refresh_state()

        self.call_later(_update)

    def _refresh_state(self) -> None:
        panel = self.query_one("#state", StatePanel)
        panel.update_state(self._client.state)

    def _save_state(self) -> None:
        """Persist identity, config, and labels to tui.state."""
        data = self._client.state.to_stored_dict()
        self._STATE_FILE.write_text(json.dumps(data, indent=2) + "\n")

    def _load_state(self) -> bool:
        """Load stored state into client. Returns True if file existed."""
        if not self._STATE_FILE.exists():
            return False
        try:
            data = json.loads(self._STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        self._client.state.load_stored_dict(data)
        return True

    def _log_sent(self, cmd: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.call_later(
            self.query_one("#log", RichLog).write,
            f"[dim]{ts}[/] [bold cyan]→[/] {escape(cmd)}",
        )

    def _log_received(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.call_later(
            self.query_one("#log", RichLog).write,
            f"[dim]{ts}[/] [bold green]←[/] {escape(line)}",
        )

    # -- Input handling ----------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return
        self.query_one("#input-bar", CommandInput).add_to_history(raw)
        try:
            await self._dispatch_command(raw)
        except LumagenConnectionError as err:
            self.query_one("#log", RichLog).write(f"[red]{escape(str(err))}[/]")

    async def _dispatch_command(self, raw: str) -> None:
        log = self.query_one("#log", RichLog)
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "on":
            await self._client.power_on()
            return
        if cmd == "off":
            await self._client.power_off()
            return

        # Bare letter → input memory shortcut
        if cmd in "abcd" and not arg:
            await self._client.select_memory(cast("InputMemory", cmd))
            return

        # Bare number → input shortcut
        if cmd.isdigit() and not arg:
            num = int(cmd)
            if not 1 <= num <= 19:
                log.write(f"[red]Input number must be 1-19, got {num}[/]")
                return
            await self._client.select_input(num)
            return

        if cmd == "aspect" and arg:
            if arg in ASPECT_COMMANDS:
                await self._client.set_aspect(arg)
            else:
                names = ", ".join(sorted(ASPECT_COMMANDS.keys()))
                log.write(f"[red]Unknown aspect: {arg}[/]")
                log.write(f"[dim]  Valid: {names}[/]")
            return

        if cmd == "autoaspect":
            if arg.lower() in ("on", "1"):
                await self._client.set_auto_aspect(True)
            elif arg.lower() in ("off", "0"):
                await self._client.set_auto_aspect(False)
            else:
                log.write("[red]Usage: autoaspect on / off[/]")
            return

        if cmd == "nls":
            await self._client.send_nls_command()
            return

        if cmd == "label" and arg:
            label_parts = arg.split(maxsplit=1)
            if len(label_parts) < 2 or len(label_parts[0]) < 2:
                log.write("[red]Usage: label <id> <text> (e.g. label A1 Apple TV)[/]")
                return
            label_id = label_parts[0].upper()
            category = label_id[0]
            try:
                user_idx = int(label_id[1:])
            except ValueError:
                log.write(f"[red]Invalid label id: {label_parts[0]}[/]")
                return
            # User-facing is 1-based, protocol is 0-based
            proto_idx = user_idx - 1
            if proto_idx < 0:
                log.write("[red]Label index must be >= 1[/]")
                return
            label_text = label_parts[1]
            max_len = 10 if category in "ABCD0" else 7 if category == "1" else 8
            if len(label_text) > max_len:
                label_text = label_text[:max_len]
                log.write(f"[yellow]Truncated to {max_len} chars: {label_text}[/]")
            cat = cast("LabelCategory", category)
            await self._client.set_label(cat, proto_idx, label_text)
            self._save_state()
            self._refresh_state()
            log.write(f"[green]Set label {label_id} = {label_parts[1]}[/]")
            return

        if cmd == "save":
            await self._client.save_config()
            log.write("[green]Config saved to flash[/]")
            return

        if cmd == "restart":
            await self._client.restart_outputs()
            log.write("[green]Outputs restarted[/]")
            return

        if cmd == "remote" and arg:
            if arg.lower() in REMOTE_COMMANDS:
                await self._client.send_remote_command(arg)
            else:
                names = ", ".join(
                    k for k in sorted(REMOTE_COMMANDS.keys()) if not k.isdigit()
                )
                log.write(f"[red]Unknown remote command: {arg}[/]")
                log.write(f"[dim]  Valid: {names}[/]")
            return

        if cmd == "osd":
            rest = raw.split(maxsplit=1)
            if len(rest) < 2:
                await self._client.clear_osd_message()
                return
            body = rest[1]
            # Optional leading digit sets duration (0=persistent, 1-8=seconds)
            if len(body) >= 2 and body[0].isdigit() and body[1] == " ":
                duration = int(body[0])
                body = body[2:]
            else:
                duration = 3
            # | separates line one and line two
            parts = body.split("|", maxsplit=1)
            line_one = parts[0]
            line_two = parts[1] if len(parts) > 1 else ""
            await self._client.show_osd_message(line_one, line_two, duration=duration)
            return

        if cmd == "labels" and not arg:
            self._show_labels(log)
            return

        # Raw RS232 commands start with %
        if raw.startswith("%"):
            payload = raw[1:].strip()
            if not payload:
                log.write("[red]Empty raw command — usage: %CMD[/]")
                return
            payload = payload.replace("\\r", "\r").replace("\\n", "\n")
            await self._client.send_raw_command(payload)
            return

        log.write(f"[red]Unknown command: {raw}[/]")
        log.write("[dim]Press Ctrl+H for help.[/]")

    def _show_labels(self, log: RichLog) -> None:
        """Display cached labels in the log panel."""
        state = self._client.state
        label_sets: list[tuple[str, str]] = [
            ("Inputs (Mem A)", "A"),
            ("Inputs (Mem B)", "B"),
            ("Inputs (Mem C)", "C"),
            ("Inputs (Mem D)", "D"),
            ("Custom Modes", "1"),
            ("CMS", "2"),
            ("Styles", "3"),
        ]
        for heading, prefix in label_sets:
            group = state.labels_by_prefix(prefix)
            if group:
                log.write(f"[bold]{heading}:[/]")
                for lid, text in group.items():
                    display_id = f"{lid[0]}{int(lid[1:]) + 1}"
                    log.write(f"  {display_id}: {text}")

    # -- Actions -----------------------------------------------------------

    _LOG_MIN_WIDTH = 25

    def action_toggle_help(self) -> None:
        self.query_one("#help-panel").toggle_class("visible")
        self._update_log_visibility()

    def _update_log_visibility(self) -> None:
        """Hide the log pane when it would be too narrow to be useful."""
        help_panel = self.query_one("#help-panel")
        log_panel = self.query_one("#log-panel")
        was_hidden = not log_panel.display
        if not help_panel.has_class("visible"):
            log_panel.display = True
        else:
            # State panel (fixed 40) + help panel (49) + log + borders/gaps
            # Estimate remaining space for the log pane
            main = self.query_one("#main")
            available = main.size.width - 34 - 49  # state + help widths
            log_panel.display = available >= self._LOG_MIN_WIDTH
        # Rewrap after becoming visible — writes while hidden rendered at zero
        # width and are effectively lost from the display.
        if was_hidden and log_panel.display:
            rich_log = self.query_one("#log", WrappingRichLog)
            rich_log.set_timer(0.05, rich_log.rewrap)

    def on_resize(self, event: Resize) -> None:
        self._update_log_visibility()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    async def action_refresh_info(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[dim]Refreshing signal info…[/]")
        await self._client.query_runtime()
        self._refresh_state()

    async def action_reload_config(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[dim]Reloading config & labels…[/]")
        if await self._client.query_config():
            self._save_state()
            self._refresh_state()
            log.write("[green]Config reloaded.[/]")
        else:
            log.write("[red]Config reload incomplete — stored state not updated[/]")

    async def on_unmount(self) -> None:
        await self._client.disconnect()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(
    host: Annotated[str, typer.Argument(envvar="LUMAGEN_HOST", help="Hostname or IP")],
    port: Annotated[int, typer.Argument(envvar="LUMAGEN_PORT", help="TCP port")] = 4999,
) -> None:
    """Lumagen Radiance Pro TUI."""
    # Log all client protocol traffic to tui.log
    client_logger = logging.getLogger("client")
    handler = logging.FileHandler("tui.log")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    client_logger.addHandler(handler)
    client_logger.setLevel(logging.DEBUG)

    app = LumagenTUI(host, port)
    app.run()


if __name__ == "__main__":
    typer.run(main)
