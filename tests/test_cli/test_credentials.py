"""Tests for appliku_cli.credentials."""
from pathlib import Path
from unittest.mock import patch

import pytest

from appliku_cli.credentials import (
    Credentials,
    ENV_FILENAME,
    GITIGNORE_FILENAME,
    _ensure_gitignored,
    _parse_env_file,
    load_credentials,
)


def _write_env(tmp_path: Path) -> Path:
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text(
        "APPLIKU_API_KEY=testkey\n"
        "APPLIKU_TEAM_PATH=my-team\n"
        "APPLIKU_APP_ID=42\n"
    )
    return env_file


def test_parse_env_file(tmp_path):
    env_file = _write_env(tmp_path)
    values = _parse_env_file(env_file)
    assert values["APPLIKU_API_KEY"] == "testkey"
    assert values["APPLIKU_TEAM_PATH"] == "my-team"
    assert values["APPLIKU_APP_ID"] == "42"


def test_parse_env_file_ignores_comments(tmp_path):
    env_file = tmp_path / ENV_FILENAME
    env_file.write_text(
        "# comment\n"
        "APPLIKU_API_KEY=testkey\n"
        "\n"
        "APPLIKU_TEAM_PATH=my-team\n"
        "APPLIKU_APP_ID=42\n"
    )
    values = _parse_env_file(env_file)
    assert len(values) == 3


def test_load_credentials_reads_existing_file(tmp_path):
    _write_env(tmp_path)
    # Create a .gitignore so _ensure_gitignored doesn't create one
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    creds = load_credentials(cwd=tmp_path)
    assert isinstance(creds, Credentials)
    assert creds.api_key == "testkey"
    assert creds.team_path == "my-team"
    assert creds.app_id == 42


def test_load_credentials_prompts_when_missing(tmp_path):
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    inputs = iter(["mykey", "their-team", "99"])
    with patch("builtins.input", side_effect=inputs):
        creds = load_credentials(cwd=tmp_path)
    assert creds.api_key == "mykey"
    assert creds.team_path == "their-team"
    assert creds.app_id == 99


def test_load_credentials_writes_env_file_after_prompt(tmp_path):
    (tmp_path / GITIGNORE_FILENAME).write_text(f"{ENV_FILENAME}\n")
    inputs = iter(["mykey", "their-team", "99"])
    with patch("builtins.input", side_effect=inputs):
        load_credentials(cwd=tmp_path)
    env_file = tmp_path / ENV_FILENAME
    assert env_file.exists()
    content = env_file.read_text()
    assert "APPLIKU_API_KEY=mykey" in content
    assert "APPLIKU_APP_ID=99" in content


def test_ensure_gitignored_creates_gitignore(tmp_path):
    _ensure_gitignored(tmp_path)
    gitignore = tmp_path / GITIGNORE_FILENAME
    assert gitignore.exists()
    assert ENV_FILENAME in gitignore.read_text()


def test_ensure_gitignored_appends_to_existing(tmp_path):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text("*.pyc\n")
    _ensure_gitignored(tmp_path)
    assert ENV_FILENAME in gitignore.read_text()
    assert "*.pyc" in gitignore.read_text()


def test_ensure_gitignored_idempotent(tmp_path):
    gitignore = tmp_path / GITIGNORE_FILENAME
    gitignore.write_text(f"{ENV_FILENAME}\n")
    _ensure_gitignored(tmp_path)
    _ensure_gitignored(tmp_path)
    count = gitignore.read_text().count(ENV_FILENAME)
    assert count == 1
