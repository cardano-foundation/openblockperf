"""Configure and provide common logging."""

__all__ = ["logger", "setup_logging"]

import sys

from loguru import logger


def formatter(record: dict) -> str:
    """Format a given log record as text."""
    extra = record["extra"]
    format_string = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSSSSS}</green>|"
        "<level>{level: <5}</level>|"
        "<cyan>{name}</cyan>:<cyan>{line}</cyan>|"
        "<level>{message}</level>"
    )
    if extra:
        parts = []
        for k, v in extra.items():
            # Escape braces to prevent format_map collision
            v_str = repr(v).replace("{", "{{").replace("}", "}}")
            parts.append(f"<yellow>{k}</yellow>=<white>{v_str}</white>")
        format_string += " - " + " ".join(parts)

    return format_string + "\n"


def setup_logging(level: str):
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        colorize=True,
        format=formatter,
    )
