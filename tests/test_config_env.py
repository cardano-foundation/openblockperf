"""Tests for CLI config path resolution (--config vs OPENBLOCKPERF_CONFIG)."""

from pathlib import Path

import pytest

from openblockperf.__main__ import CONFIG_ENV_VAR, resolve_config_path
from openblockperf.errors import ConfigurationError


def test_resolve_config_prefers_cli_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli_cfg = tmp_path / "cli.json"
    env_cfg = tmp_path / "env.json"
    cli_cfg.write_text("{}")
    env_cfg.write_text("{}")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(env_cfg))

    path, source = resolve_config_path(cli_cfg)
    assert path == cli_cfg
    assert source == "flag"


def test_resolve_config_uses_env_when_flag_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_cfg = tmp_path / "env.json"
    env_cfg.write_text("{}")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(env_cfg))

    path, source = resolve_config_path(None)
    assert path == env_cfg
    assert source == "env"


def test_resolve_config_none_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    path, source = resolve_config_path(None)
    assert path is None
    assert source is None


def test_resolve_config_env_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(missing))
    with pytest.raises(ConfigurationError, match=CONFIG_ENV_VAR):
        resolve_config_path(None)
