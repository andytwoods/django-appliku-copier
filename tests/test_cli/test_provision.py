"""Tests for appliku_cli.provision — verifies correct call sequence per config."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appliku_cli.credentials import Credentials
from appliku_cli.provision import _bool, run_provision

CREDS = Credentials(api_key="key", team_path="team", app_id=1, server_id=1)
CREDS_PROVISIONED = Credentials(api_key="key", team_path="team", app_id=1, server_id=1, provisioned=True)


def _run(
    answers: dict,
    extra_prompts: list[str] | None = None,
    credentials: Credentials = CREDS,
    existing_vars: list[str] | None = None,
) -> MagicMock:
    """Run provision with a mocked client and return the mock."""
    prompts = iter(extra_prompts or [])
    mock_client = MagicMock()
    mock_client.get_config_vars.return_value = [{"name": v} for v in (existing_vars or [])]
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
    with patch("builtins.input", return_value="n"):
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


# ── All vars pushed in one batch ──────────────────────────────────────────────

def test_all_config_vars_pushed_in_single_call():
    """Email, sentry, and extra vars must all land in the same set_config_vars call as SECRET_KEY."""
    mock_client = MagicMock()
    mock_client.get_latest_deployment.return_value = {"status": "Deployed", "id": 1}
    mock_client.list_domains.return_value = []
    mock_client.get_app.return_value = {"default_subdomain": "", "is_disabled_default_subdomain": True}

    prompts = iter([
        "smtp.example.com", "587", "user@example.com", "pass",   # email
        "https://sentry.io/dsn",                                  # sentry
        "myadmin/",                                               # DJANGO_ADMIN_URL (extra)
    ])

    with (
        patch("appliku_cli.provision.ApplikuClient", return_value=mock_client),
        patch("appliku_cli.provision._prompt", side_effect=prompts),
        patch("appliku_cli.provision.time.sleep"),
        patch("appliku_cli.provision.save_provisioned"),
        patch("appliku_cli.provision.detect_secret_key_var", return_value="SECRET_KEY"),
        patch("appliku_cli.provision.detect_allowed_hosts_var", return_value="ALLOWED_HOSTS"),
        patch("appliku_cli.provision.detect_django_settings_module", return_value="config.settings.production"),
        patch("appliku_cli.provision.detect_required_env_vars", return_value=["DJANGO_ADMIN_URL"]),
        patch("appliku_cli.provision.patch_dockerfile_collectstatic", return_value=False),
    ):
        run_provision(
            CREDS,
            {"db_type": "postgresql_18", "task_runner": "none",
             "email_backend": "smtp", "use_sentry": True},
            cwd=Path("/tmp"),
        )

    # First call must contain all vars together (not spread across multiple calls)
    first_call_vars = mock_client.set_config_vars.call_args_list[0].args[0]
    assert "SECRET_KEY" in first_call_vars
    assert "EMAIL_HOST" in first_call_vars
    assert "SENTRY_DSN" in first_call_vars
    assert "DJANGO_ADMIN_URL" in first_call_vars


# ── Dockerfile patching ───────────────────────────────────────────────────────

def _run_with_patch_result(patch_result: bool, extra_vars: list[str]) -> tuple[MagicMock, MagicMock]:
    """Run provision with controlled detect results; return (client, subprocess_mock)."""
    mock_client = MagicMock()
    mock_client.get_config_vars.return_value = []
    mock_client.get_latest_deployment.return_value = {"status": "Deployed", "id": 1}
    mock_client.list_domains.return_value = []
    mock_client.get_app.return_value = {"default_subdomain": "", "is_disabled_default_subdomain": True}

    mock_sp = MagicMock()
    with (
        patch("appliku_cli.provision.ApplikuClient", return_value=mock_client),
        patch("appliku_cli.provision._prompt", return_value="value"),
        patch("appliku_cli.provision.time.sleep"),
        patch("appliku_cli.provision.save_provisioned"),
        patch("appliku_cli.provision.detect_secret_key_var", return_value="SECRET_KEY"),
        patch("appliku_cli.provision.detect_allowed_hosts_var", return_value="ALLOWED_HOSTS"),
        patch("appliku_cli.provision.detect_django_settings_module", return_value="config.settings.production"),
        patch("appliku_cli.provision.detect_required_env_vars", return_value=extra_vars),
        patch("appliku_cli.provision.patch_dockerfile_collectstatic", return_value=patch_result),
        patch("appliku_cli.provision.subprocess.run", mock_sp),
    ):
        run_provision(CREDS, {"db_type": "postgresql_18", "task_runner": "none"}, cwd=Path("/tmp"))

    return mock_client, mock_sp


def test_dockerfile_not_changed_means_no_git_calls():
    _, mock_sp = _run_with_patch_result(patch_result=False, extra_vars=[])
    mock_sp.assert_not_called()


def test_dockerfile_changed_triggers_git_add_commit_push():
    _, mock_sp = _run_with_patch_result(patch_result=True, extra_vars=["EXTRA_VAR"])
    commands = [call.args[0] for call in mock_sp.call_args_list]
    assert ["git", "add", "Dockerfile"] in commands
    assert any("git" in c and "commit" in c for c in commands)
    assert ["git", "push"] in commands


def test_dockerfile_git_push_failure_exits(tmp_path):
    mock_client = MagicMock()
    mock_client.get_config_vars.return_value = []

    with (
        patch("appliku_cli.provision.ApplikuClient", return_value=mock_client),
        patch("appliku_cli.provision._prompt", return_value="value"),
        patch("appliku_cli.provision.time.sleep"),
        patch("appliku_cli.provision.save_provisioned"),
        patch("appliku_cli.provision.detect_secret_key_var", return_value="SECRET_KEY"),
        patch("appliku_cli.provision.detect_allowed_hosts_var", return_value="ALLOWED_HOSTS"),
        patch("appliku_cli.provision.detect_django_settings_module", return_value="config.settings.production"),
        patch("appliku_cli.provision.detect_required_env_vars", return_value=["EXTRA"]),
        patch("appliku_cli.provision.patch_dockerfile_collectstatic", return_value=True),
        patch("appliku_cli.provision.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")),
    ):
        with pytest.raises(SystemExit):
            run_provision(CREDS, {"db_type": "postgresql_18", "task_runner": "none"}, cwd=tmp_path)


# ── Skip already-set vars ─────────────────────────────────────────────────────

def test_skips_secret_key_when_already_set():
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none"},
        existing_vars=["SECRET_KEY"],
    )
    all_vars = _all_pushed_vars(client)
    assert "SECRET_KEY" not in all_vars


def test_skips_email_vars_when_already_set():
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none", "email_backend": "smtp"},
        existing_vars=["EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD"],
    )
    all_vars = _all_pushed_vars(client)
    assert "EMAIL_HOST" not in all_vars


def test_prompts_only_missing_email_vars():
    """If some email vars are set but not all, only prompt for the missing ones."""
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none", "email_backend": "smtp"},
        extra_prompts=["user@example.com", "pass"],   # only USER and PASSWORD are missing
        existing_vars=["EMAIL_HOST", "EMAIL_PORT"],
    )
    all_vars = _all_pushed_vars(client)
    assert "EMAIL_HOST" not in all_vars
    assert "EMAIL_HOST_USER" in all_vars
    assert "EMAIL_HOST_PASSWORD" in all_vars


def test_skips_sentry_when_already_set():
    client = _run(
        {"db_type": "postgresql_18", "task_runner": "none", "use_sentry": True},
        existing_vars=["SENTRY_DSN"],
    )
    assert "SENTRY_DSN" not in _all_pushed_vars(client)
