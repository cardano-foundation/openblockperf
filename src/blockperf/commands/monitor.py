import asyncio
import time

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from blockperf.core.async_utils import run_async

console = Console()


def monitor_app_callback(verboze: bool = False):
    console.print("My farts stink hard")


# Create the monitor command group
monitor_app = typer.Typer(
    name="monitor",
    help="Real-time monitoring commands",
    invoke_without_command=True,
    callback=monitor_app_callback,
)


@monitor_app.command(name="blocks")
def monitor_blocks(
    duration: int = typer.Option(
        0,
        "--duration",
        "-d",
        help="Duration to monitor in seconds (0 for indefinite)",
    ),
    network: str = typer.Option(
        "mainnet", "--network", "-n", help="Network to monitor"
    ),
) -> None:
    """Monitor blocks in real-time.

    Args:
        duration: Duration to monitor in seconds (0 for indefinite)
        network: Network to monitor blocks from
    """
    try:
        run_async(_monitor_blocks_async(duration, network))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitoring stopped.[/]")


async def _monitor_blocks_async(duration: int, network: str) -> None:
    """Async implementation of block monitoring.

    Args:
        duration: Duration to monitor in seconds (0 for indefinite)
        network: Network to monitor blocks from
    """
    start_time = time.time()
    block_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Monitoring blocks..."),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Monitoring", total=duration if duration > 0 else None
        )

        while True:
            # Check if we've reached the duration
            if duration > 0:
                elapsed = time.time() - start_time
                progress.update(task, completed=elapsed)
                if elapsed >= duration:
                    break

            # Simulate receiving a new block
            block_count += 1
            console.print(f"New block received: #{block_count} on {network}")

            # Wait for next block
            await asyncio.sleep(2)  # Simulate block time

    console.print(
        f"[bold green]Monitoring complete! Observed {block_count} blocks.[/]"
    )
