"""Setup the cli by creating the main Typer application (blockperf_app) and
adding the (sub)commands to it."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widgets import Button, Digits, Footer, Header

console = Console()


class TimeDisplay(Digits):
    """A widget to display elapsed time."""


class Stopwatch(HorizontalGroup):
    """A stopwatch widget."""

    def compose(self) -> ComposeResult:
        """Create child widgets of a stopwatch."""
        yield Button("Start", id="start", variant="success")
        yield Button("Stop", id="stop", variant="error")
        yield Button("Reset", id="reset")
        yield TimeDisplay("00:00:00.00")


class BlockperfUI(App):
    # Styles for the ui
    CSS_PATH = "stopwatch03.tcss"
    # List of tuples, that match keys to actions
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("p", "show_peers", "Show Peers"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        yield VerticalScroll(Stopwatch(), Stopwatch(), Stopwatch())

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )


def make_blockperf_ui():
    """Return the textual app"""
    return BlockperfUI()
