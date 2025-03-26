from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version(
        __name__
    )  # Use __name__ if it's installed as a package
except PackageNotFoundError:
    __version__ = "0.0.0"  # Default version when running in development
