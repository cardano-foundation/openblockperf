# Version information for blockperf
# Version is read from pyproject.toml - edit the version there

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.version import Version


def get_version() -> Version | None:
    """
    Returns the version if openblockperf. Either from installed package
    or the pyproject.toml file during development
    """
    try:
        return Version(version("openblockperf"))
    except PackageNotFoundError:
        pass

    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject = tomllib.load(f)
            return Version(pyproject["project"]["version"])
        except Exception:
            pass

    return None


__version__: Version = get_version()
