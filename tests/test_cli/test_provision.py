"""Tests for appliku_cli.provision — verifies correct call sequence per config."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appliku_cli.credentials import Credentials
from appliku_cli.provision import _bool, run_provision

CREDS = Credentials(api_key="key", team_path="team", app_id=1, server_id=1)
CREDS_PROVISIONED = Credentials(api_key="key", team_path="team", app_id=1, server_id=1, provisioned=True)


def _run(answers: dict, extra_prompts: list[str] | None = None, credentials: Credentials = CREDS) -> MagicMock:
    """Run provision with a mocked client and return the mock."""
    prompts = iter(extra_prompts or [])
    mock_client = MagicMock()
    with (
        patch("appliku_cli.provision.ApplikuClient", return_value=mock_client),
        patch("appliku_cli.provision._prompt", side_effect=prompts),
        patch("appliku_cli.provision.time.sleep"),
        patch("appliku_cli.provision.save_provisioned"),
    ):
        run_provision(credentials, answers, cwd=Path("/tmp"))
    return mock_client


def _all_pushed_vars(client: MagicMock) -> dict:
    """Merge all set_config_vars calls into one dict."""
    merged: dict = {}
    for c in client.set_config_vars.call_args_list:
        merged.update(c.args[0])
    return merged


# ── _bool helper ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (True, True),
    (False, False),
    ("true", True),
    ("false", False),
    ("True", True),
    ("1", True),
    ("0", False),
])
def test_bool_coercion(value, expected):
    assert _bool(value) == expected


# ── Already-provisioned guard ─────────────────────────────────────────────────

def test_provisioned_guard_aborts(capsys):
    client = _run({"db_type": "postgresql_18", "task_runner": "none"}, credentials=CREDS_PROVISIONED)
    client.trigger_deploy.assert_not_called()
    client.set_config_vars.assert_not_called()
    assert "already been provisioned" in capsys.readouterr().out


# ── Baseline ──────────────────────────────────────────────────────────────────

def test_baseline_sets_secret_key():
    client = _run({"db_type": "postgresql_18", "task_runner": "none"})
    assert "SECRET_KEY" in _all_pushed_vars(client)


def test_baseline_triggers_deploy():
    client = _run({"db_type": "postgresql_18", "task_runner": "none"})
    client.trigger_deploy.assert_called_once()


def test_baseline_does_not_create_datastore():
    """Datastores are handled by appliku.yml — not via API."""
    client = _run({"db_type": "postgresql_18", "task_runner": "none"})
    client.create_datastore.assert_not_called()


# ── Media storage: S3 ────────────────────────────────────────────────────────

def test_s3_storage_pushes_aws_vars():
    client = _run(
        {
            "db_type": "postgresql_18",
            "task_runner": "none",
            "media_storage": "s3_compatible",
        },
        extra_prompts=["key-id", "secret", "bucket", "https://s3.example.com"],
    )
    client.create_volume.assert_not_called()
    all_vars = _all_pushed_vars(client)
    assert "AWS_ACCESS_KEY_ID" in all_vars
    assert "AWS_STORAGE_BUCKET_NAME" in all_vars


# ── Sentry ────────────────────────────────────────────────────────────────────

def test_sentry_pushes_dsn():
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none", "use_sentry": True},
        extra_prompts=["https://sentry.io/dsn"],
    )
    assert "SENTRY_DSN" in _all_pushed_vars(client)


def test_sentry_false_does_not_push_dsn():
    client = _run({"db_type": "postgresql_18", "task_runner": "none", "use_sentry": False})
    assert "SENTRY_DSN" not in _all_pushed_vars(client)


# ── Email ─────────────────────────────────────────────────────────────────────

def test_email_smtp_pushes_email_vars():
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none", "email_backend": "smtp"},
        extra_prompts=["smtp.example.com", "587", "user@example.com", "pass"],
    )
    all_vars = _all_pushed_vars(client)
    assert "EMAIL_HOST" in all_vars
    assert "EMAIL_HOST_PASSWORD" in all_vars


def test_email_console_does_not_push_email_vars():
    client = _run({"db_type": "postgresql_18", "task_runner": "none", "email_backend": "console"})
    assert "EMAIL_HOST" not in _all_pushed_vars(client)
