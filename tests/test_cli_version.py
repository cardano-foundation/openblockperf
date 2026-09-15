"""CLI smoke tests for global flags."""

from typer.testing import CliRunner

from openblockperf import __version__
from openblockperf.__main__ import BlockperfCli

runner = CliRunner()


class TestVersionFlag:
    def test_long_option_prints_package_version(self):
        result = runner.invoke(BlockperfCli, ["--version"])
        assert result.exit_code == 0
        assert f"openblockperf {__version__}" in result.stdout

    def test_short_option_prints_package_version(self):
        result = runner.invoke(BlockperfCli, ["-V"])
        assert result.exit_code == 0
        assert f"openblockperf {__version__}" in result.stdout
