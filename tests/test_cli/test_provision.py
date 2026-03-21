"""Tests for appliku_cli.provision — verifies correct call sequence per config."""
from unittest.mock import MagicMock, call, patch

import pytest

from appliku_cli.credentials import Credentials
from appliku_cli.provision import _bool, run_provision

CREDS = Credentials(api_key="key", team_path="team", app_id=1, server_id=1)

# Default prompt responses: domain, concurrency (used in all cases)
DEFAULT_PROMPTS = ["myapp.example.com", "2"]


def _run(answers: dict, extra_prompts: list[str] | None = None) -> MagicMock:
    """Run provision with a mocked client and return the mock."""
    prompts = iter(DEFAULT_PROMPTS + (extra_prompts or []))
    mock_client = MagicMock()
    with (
        patch("appliku_cli.provision.ApplikuClient", return_value=mock_client),
        patch("appliku_cli.provision._prompt", side_effect=prompts),
        patch("appliku_cli.provision.time.sleep"),
    ):
        run_provision(CREDS, answers)
    return mock_client


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


# ── Baseline: no workers, no extras ──────────────────────────────────────────

def test_baseline_provisions_db_only():
    client = _run({"db_type": "postgresql_17", "task_runner": "none"})
    client.create_datastore.assert_called_once_with(name="db", store_type="postgresql_17", server_id=1, cluster_id=None)
    client.create_volume.assert_not_called()


def test_baseline_sets_secret_key():
    client = _run({"db_type": "postgresql_17", "task_runner": "none"})
    calls = client.set_config_vars.call_args_list
    secret_key_call = next(
        (c for c in calls if "SECRET_KEY" in c.args[0] or "SECRET_KEY" in c.kwargs.get("vars", {})),
        None,
    )
    # Find the call that contains SECRET_KEY
    found = any("SECRET_KEY" in str(c) for c in calls)
    assert found, "SECRET_KEY was never pushed"


def test_baseline_triggers_deploy():
    client = _run({"db_type": "postgresql_17", "task_runner": "none"})
    client.trigger_deploy.assert_called_once()


# ── Celery + Redis ────────────────────────────────────────────────────────────

def test_celery_redis_provisions_cache():
    client = _run({
        "db_type": "postgresql_17",
        "task_runner": "celery",
        "celery_broker": "redis",
        "redis_version": "8",
    })
    calls = [c for c in client.create_datastore.call_args_list]
    store_types = [c.kwargs["store_type"] for c in calls]
    assert "postgresql_17" in store_types
    assert "redis_8" in store_types


def test_celery_redis_no_rabbitmq():
    client = _run({
        "db_type": "postgresql_17",
        "task_runner": "celery",
        "celery_broker": "redis",
        "redis_version": "8",
    })
    store_types = [c.kwargs["store_type"] for c in client.create_datastore.call_args_list]
    assert "rabbitmq" not in store_types


# ── Celery + RabbitMQ ─────────────────────────────────────────────────────────

def test_celery_rabbitmq_provisions_broker_not_redis():
    client = _run({
        "db_type": "postgresql_17",
        "task_runner": "celery",
        "celery_broker": "rabbitmq",
        "redis_version": "8",
    })
    store_types = [c.kwargs["store_type"] for c in client.create_datastore.call_args_list]
    assert "rabbitmq" in store_types
    assert not any(s.startswith("redis_") for s in store_types)


# ── Huey ─────────────────────────────────────────────────────────────────────

def test_huey_provisions_redis():
    client = _run({
        "db_type": "postgresql_17",
        "task_runner": "huey",
        "redis_version": "7",
    })
    store_types = [c.kwargs["store_type"] for c in client.create_datastore.call_args_list]
    assert "redis_7" in store_types
    assert "rabbitmq" not in store_types


# ── PostGIS ───────────────────────────────────────────────────────────────────

def test_postgis_db_type_passed_correctly():
    client = _run({"db_type": "postgis_16_34", "task_runner": "none"})
    client.create_datastore.assert_called_once_with(name="db", store_type="postgis_16_34", server_id=1, cluster_id=None)


# ── Media storage: volume ─────────────────────────────────────────────────────

def test_media_volume_creates_volume():
    client = _run({
        "db_type": "postgresql_17",
        "task_runner": "none",
        "media_storage": "volume",
    })
    client.create_volume.assert_called_once_with(name="media", target="/app/media/")


# ── Media storage: S3 ────────────────────────────────────────────────────────

def test_s3_storage_pushes_aws_vars():
    client = _run(
        {
            "db_type": "postgresql_17",
            "task_runner": "none",
            "media_storage": "s3_compatible",
        },
        extra_prompts=["key-id", "secret", "bucket", "https://s3.example.com"],
    )
    client.create_volume.assert_not_called()
    all_vars: dict = {}
    for c in client.set_config_vars.call_args_list:
        all_vars.update(c.args[0])
    assert "AWS_ACCESS_KEY_ID" in all_vars
    assert "AWS_STORAGE_BUCKET_NAME" in all_vars


# ── Sentry ────────────────────────────────────────────────────────────────────

def test_sentry_pushes_dsn():
    client = _run(
        {"db_type": "postgresql_17", "task_runner": "none", "use_sentry": True},
        extra_prompts=["https://sentry.io/dsn"],
    )
    all_vars: dict = {}
    for c in client.set_config_vars.call_args_list:
        all_vars.update(c.args[0])
    assert "SENTRY_DSN" in all_vars


def test_sentry_false_does_not_push_dsn():
    client = _run({"db_type": "postgresql_17", "task_runner": "none", "use_sentry": False})
    all_vars: dict = {}
    for c in client.set_config_vars.call_args_list:
        all_vars.update(c.args[0])
    assert "SENTRY_DSN" not in all_vars


# ── Email ─────────────────────────────────────────────────────────────────────

def test_email_smtp_pushes_email_vars():
    client = _run(
        {"db_type": "postgresql_17", "task_runner": "none", "email_backend": "smtp"},
        extra_prompts=["smtp.example.com", "587", "user@example.com", "pass"],
    )
    all_vars: dict = {}
    for c in client.set_config_vars.call_args_list:
        all_vars.update(c.args[0])
    assert "EMAIL_HOST" in all_vars
    assert "EMAIL_HOST_PASSWORD" in all_vars


def test_email_console_does_not_push_email_vars():
    client = _run({"db_type": "postgresql_17", "task_runner": "none", "email_backend": "console"})
    all_vars: dict = {}
    for c in client.set_config_vars.call_args_list:
        all_vars.update(c.args[0])
    assert "EMAIL_HOST" not in all_vars
