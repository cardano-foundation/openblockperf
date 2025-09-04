# Version information for blockperf
# Version is read from pyproject.toml - edit the version there

import tomllib
from pathlib import Path


def _get_version():
    """Read version from pyproject.toml"""
    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
        return pyproject["project"]["version"]
    except Exception:
        return "unknown"


__version__ = _get_version()
