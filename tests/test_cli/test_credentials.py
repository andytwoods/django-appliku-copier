"""Tests for appliku_cli.credentials."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appliku_cli.credentials import (
    Credentials,
    ENV_FILENAME,
    GITIGNORE_FILENAME,
    _ensure_gitignored,
    _parse_env_file,
    load_credentials,
    save_app_id,
    save_team_path,
)


def _write_env(tmp_path: Path, include_app_id: bool = True) -> Path:
    env_file = tmp_path / ENV_FILENAME
    content = "APPLIKU_API_KEY=testkey\nAPPLIKU_TEAM_PATH=my-team\n"
    if include_app_id:
        content += "APPLIKU_APP_ID=42\n"
    env_file.write_text(content)
    return env_file


def test_parse_env_file(tmp_path):
    env_file = _write_env(tmp_path)
    values = _parse_env_file(env_file)
    assert values["APPLIKU_API_KEY"] == "testkey"
    assert values["APPLIKU_TEAM_PATH"] == "my-team"
    assert values["APPLIKU_APP_ID"] == "42"


def test_parse_env_file_ignores_comments(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text("# comment\nAPPLIKU_API_KEY=testkey\n\nAPPLIKU_TEAM_PATH=my-team\n")
    values = _parse_env_file(env_file)
    assert len(values) == 2


def test_load_credentials_with_app_id(tmp_path):
    _write_env(tmp_path)
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    creds = load_credentials(cwd=tmp_path)
    assert creds.api_key == "testkey"
    assert creds.team_path == "my-team"
    assert creds.app_id == 42


def test_load_credentials_without_app_id(tmp_path):
    _write_env(tmp_path, include_app_id=False)
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    creds = load_credentials(cwd=tmp_path)
    assert creds.app_id is None


def test_load_credentials_prompts_when_missing(tmp_path):
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    with patch("builtins.input", return_value="mykey"):
        creds = load_credentials(cwd=tmp_path)
    assert creds.api_key == "mykey"
    assert creds.team_path is None  # not prompted — handled by ensure_team_path
    assert creds.app_id is None  # not prompted — handled by ensure_app_id


def test_load_credentials_writes_env_file_after_prompt(tmp_path):
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    with patch("builtins.input", return_value="mykey"):
        load_credentials(cwd=tmp_path)
    env_file = tmp_path / ENV_FILENAME
    assert env_file.exists()
    assert "APPLIKU_API_KEY=mykey" in env_file.read_text()


def test_save_team_path_appends_when_missing(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text("APPLIKU_API_KEY=k\n")
    save_team_path("my-team", cwd=tmp_path)
    assert "APPLIKU_TEAM_PATH=my-team" in env_file.read_text()


def test_load_credentials_team_path_optional(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text("APPLIKU_API_KEY=k\n")
    creds = load_credentials(cwd=tmp_path)
    assert creds.team_path is None


def test_save_app_id_appends_when_missing(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text("APPLIKU_API_KEY=k\nAPPLIKU_TEAM_PATH=t\n")
    save_app_id(99, cwd=tmp_path)
    assert "APPLIKU_APP_ID=99" in env_file.read_text()


def test_save_app_id_replaces_existing(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text("APPLIKU_API_KEY=k\nAPPLIKU_TEAM_PATH=t\nAPPLIKU_APP_ID=0\n")
    save_app_id(42, cwd=tmp_path)
    content = env_file.read_text()
    assert "APPLIKU_APP_ID=42" in content
    assert "APPLIKU_APP_ID=0" not in content


def test_ensure_gitignored_creates_gitignore(tmp_path, capsys):
    _ensure_gitignored(tmp_path)
    gitignore = tmp_path / GITIGNORE_FILENAME
    assert gitignore.exists()
    assert ENV_FILENAME in gitignore.read_text()
    assert "WARNING" in capsys.readouterr().out


def test_ensure_gitignored_appends_to_existing(tmp_path):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text("*.pyc\n")
    _ensure_gitignored(tmp_path)
    assert ENV_FILENAME in gitignore.read_text()
    assert "*.pyc" in gitignore.read_text()


def test_ensure_gitignored_idempotent(tmp_path, capsys):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text(f"{ENV_FILENAME}\n")
    _ensure_gitignored(tmp_path)
    _ensure_gitignored(tmp_path)
    assert gitignore.read_text().count(ENV_FILENAME) == 1
    # No warning when already gitignored
    assert "WARNING" not in capsys.readouterr().out


def test_ensure_gitignored_warns_if_git_tracked(tmp_path, capsys):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text(f"{ENV_FILENAME}\n")
    mock_result = MagicMock(returncode=0)
    with patch("appliku_cli.credentials.subprocess.run", return_value=mock_result):
        _ensure_gitignored(tmp_path)
    assert "DANGER" in capsys.readouterr().out


def test_ensure_gitignored_no_danger_when_not_tracked(tmp_path, capsys):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text(f"{ENV_FILENAME}\n")
    mock_result = MagicMock(returncode=1)
    with patch("appliku_cli.credentials.subprocess.run", return_value=mock_result):
        _ensure_gitignored(tmp_path)
    assert "DANGER" not in capsys.readouterr().out
