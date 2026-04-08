import platform
import sys

import httpx
from packaging.version import Version
from rich.console import Console

from openblockperf import __version__
from openblockperf.logging import logger
from openblockperf.utils import async_command

console = Console()


@async_command
async def version_cmd() -> None:
    """Display the version of BlockPerf.

    Args:
        verbose: Display more detailed version information
    """
    response = httpx.get("https://pypi.org/pypi/openblockperf/json", timeout=3)
    latest = Version(response.json()["info"]["version"])
    if latest > __version__:
        console.print(f"[bold yellow]New Version available '{str(latest)}' (current: {str(__version__)}[/]")
    else:
        console.print(f"Installed version: [bold green]{__version__}[/]")
    console.print(f"Python version: [cyan]{sys.version}[/]")
    console.print(f"Platform: [cyan]{platform.platform()}[/]")
