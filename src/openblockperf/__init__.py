# Version information for blockperf
# Version is read from pyproject.toml - edit the version there

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def get_version() -> str:
    """
    Returns the version if openblockperf. Either from installed package
    or the pyproject.toml file during development
    """
    try:
        return version("openblockperf")
    except PackageNotFoundError:
        pass

    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject = tomllib.load(f)
            return pyproject["project"]["version"]
        except Exception:
            pass

    return "unknown"


__version__ = get_version()
