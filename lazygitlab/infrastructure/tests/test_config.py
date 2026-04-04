"""lazygitlab.infrastructure.config のユニットテスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from lazygitlab.infrastructure.config import ConfigError, ConfigManager
from lazygitlab.models import AppConfig


def _make_toml(
    url: str = "https://gitlab.com",
    token: str = "glpat-validtoken",
    editor: str = "vi",
    log_level: str = "INFO",
    theme: str = "dark",
    remote_name: str = "",
) -> str:
    return (
        f'[gitlab]\nurl = "{url}"\n'
        f'[auth]\ntoken = "{token}"\n'
        f'[editor]\ncommand = "{editor}"\n'
        f'[logging]\nlevel = "{log_level}"\n'
        f'[appearance]\ntheme = "{theme}"\n'
        f'[git]\nremote_name = "{remote_name}"\n'
    )


class TestConfigManagerLoad:
    def test_有効な設定ファイルをロードする(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(_make_toml(), encoding="utf-8")
        manager = ConfigManager(config_path=config_file)
        config = manager.load()
        assert config.gitlab_url == "https://gitlab.com"
        assert config.token == "glpat-validtoken"

    def test_URLの末尾スラッシュが除去される(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(_make_toml(url="https://gitlab.com/"), encoding="utf-8")
        manager = ConfigManager(config_path=config_file)
        config = manager.load()
        assert config.gitlab_url == "https://gitlab.com"

    def test_ファイルが存在しない場合にウィザードが起動する(self, tmp_path):
        config_file = tmp_path / "config.toml"
        manager = ConfigManager(config_path=config_file)
        with patch.object(manager, "_run_setup_wizard") as mock_wizard:
            mock_wizard.return_value = AppConfig(gitlab_url="https://gitlab.com", token="glpat-x")
            result = manager.load()
        mock_wizard.assert_called_once()
        assert result.gitlab_url == "https://gitlab.com"

    def test_TOMLパースエラー時にYを入力するとウィザードが起動する(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.toml"
        config_file.write_text("NOT VALID TOML ][[[", encoding="utf-8")
        manager = ConfigManager(config_path=config_file)

        monkeypatch.setattr("builtins.input", lambda _: "y")
        with patch.object(manager, "_run_setup_wizard") as mock_wizard:
            mock_wizard.return_value = AppConfig(gitlab_url="https://gitlab.com", token="glpat-x")
            result = manager.load()
        mock_wizard.assert_called_once()

    def test_TOMLパースエラー時にNを入力すると終了する(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.toml"
        config_file.write_text("NOT VALID TOML ][[[", encoding="utf-8")
        manager = ConfigManager(config_path=config_file)

        monkeypatch.setattr("builtins.input", lambda _: "n")
        with pytest.raises(SystemExit):
            manager.load()


class TestConfigManagerValidation:
    def _manager(self) -> ConfigManager:
        return ConfigManager(config_path=Path("/dev/null"))

    def test_有効な設定ではエラーが発生しない(self):
        cfg = AppConfig(gitlab_url="https://gitlab.com", token="glpat-abc")
        errors = ConfigManager._validate_gitlab_url(cfg.gitlab_url)
        assert errors == []

    def test_URLが空の場合はエラーになる(self):
        errors = ConfigManager._validate_gitlab_url("")
        assert len(errors) == 1
        assert "必須" in errors[0]

    def test_スキームなしのURLはエラーになる(self):
        errors = ConfigManager._validate_gitlab_url("gitlab.com")
        assert len(errors) == 1
        assert "http" in errors[0]

    def test_HTTPのURLは有効である(self):
        errors = ConfigManager._validate_gitlab_url("http://gitlab.example.com")
        assert errors == []

    def test_トークンが空の場合はエラーになる(self):
        errors = ConfigManager._validate_token("")
        assert len(errors) == 1
        assert "必須" in errors[0]

    def test_プレースホルダーのトークンはエラーになる(self):
        for placeholder in ["your-token-here", "xxx", "changeme"]:
            errors = ConfigManager._validate_token(placeholder)
            assert len(errors) == 1, f"Expected error for {placeholder!r}"
            assert "プレースホルダー" in errors[0]

    def test_有効なトークンはエラーにならない(self):
        errors = ConfigManager._validate_token("glpat-validtoken123")
        assert errors == []

    def test_無効なログレベルはエラーになる(self):
        errors = ConfigManager._validate_log_level("VERBOSE")
        assert len(errors) == 1
        assert "VERBOSE" in errors[0]

    def test_有効なログレベルはエラーにならない(self):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            assert ConfigManager._validate_log_level(level) == []

    def test_ログレベルの大小文字を区別しない(self):
        assert ConfigManager._validate_log_level("debug") == []

    def test_無効なテーマはエラーになる(self):
        errors = ConfigManager._validate_theme("myamazingtheme")
        assert len(errors) == 1
        assert "myamazingtheme" in errors[0]

    def test_有効なテーマはエラーにならない(self):
        assert ConfigManager._validate_theme("dark") == []
        assert ConfigManager._validate_theme("light") == []


class TestConfigManagerDefaultGeneration:
    def test_デフォルト設定が有効なTOMLである(self):
        manager = ConfigManager(config_path=Path("/dev/null"))
        content = manager.generate_default("https://gitlab.com", "glpat-xyz", "vi")
        parsed = tomllib.loads(content)
        assert parsed["gitlab"]["url"] == "https://gitlab.com"
        assert parsed["auth"]["token"] == "glpat-xyz"
        assert parsed["editor"]["command"] == "vi"


class TestConfigManagerPathResolution:
    def test_デフォルトパスがホームディレクトリを使用する(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        manager = ConfigManager()
        assert "lazygitlab" in str(manager.config_path)
        assert str(manager.config_path).endswith("config.toml")

    def test_XDG_CONFIG_HOMEが尊重される(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        manager = ConfigManager()
        assert str(manager.config_path).startswith(str(tmp_path))

    def test_明示的なパスが使用される(self, tmp_path):
        custom = tmp_path / "my_config.toml"
        manager = ConfigManager(config_path=custom)
        assert manager.config_path == custom


class TestConfigManagerMapToConfig:
    def test_無効な設定でConfigErrorが発生する(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            _make_toml(url="not-a-url", token="your-token-here"),
            encoding="utf-8",
        )
        manager = ConfigManager(config_path=config_file)
        with pytest.raises(ConfigError):
            manager.load()
