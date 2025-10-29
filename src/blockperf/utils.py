"""Asyncio utilities for BlockPerf."""

import asyncio
import functools
import signal
import sys
from functools import wraps
from typing import Any, Callable, Coroutine, Optional, TypeVar, cast

T = TypeVar("T")


def async_command(func):
    """Decorator to run async typer commands"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def run_async(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine in the current thread.

    This function properly handles asyncio event loop creation and cleanup,
    and also handles keyboard interrupts gracefully.

    Args:
        coroutine: The coroutine to run

    Returns:
        The result of the coroutine
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(coroutine)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()

        # Run the event loop until all tasks are cancelled
        loop.run_until_complete(
            asyncio.gather(*pending, return_exceptions=True)
        )
        raise
    finally:
        loop.close()


async def with_timeout(coroutine: Coroutine[Any, Any, T], timeout: int) -> T:
    """Run a coroutine with a timeout.

    Args:
        coroutine: The coroutine to run
        timeout: Timeout in seconds

    Returns:
        The result of the coroutine

    Raises:
        asyncio.TimeoutError: If the coroutine times out
    """
    return await asyncio.wait_for(coroutine, timeout=timeout)


def async_to_sync(
    func: Callable[..., Coroutine[Any, Any, T]],
) -> Callable[..., T]:
    """Decorator to convert an async function to a sync function.

    Args:
        func: The async function to convert

    Returns:
        A synchronous function that runs the async function
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return run_async(func(*args, **kwargs))

    return wrapper
