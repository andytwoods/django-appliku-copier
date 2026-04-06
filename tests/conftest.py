"""Shared fixtures and data for the test suite."""
import subprocess
from pathlib import Path
from typing import Any

import pytest

TEMPLATE_DIR = Path(__file__).resolve().parent.parent  # repo root; copier.yml + _subdirectory: template

BASE_DATA: dict[str, Any] = {
    "project_slug": "test_project",
    "secret_key_var": "SECRET_KEY",
    "production_settings_module": "config.settings.production",
    "use_whitenoise_manifest": False,
    "python_version": "3.13",
    "package_manager": "uv",
    "web_server": "gunicorn",
    "db_type": "postgresql_18",
    "task_runner": "none",
    "media_storage": "none",
    "email_backend": "console",
    "use_sentry": "false",
    "superuser_email": "",
}


def render_template(tmp_path: Path, overrides: dict[str, Any] | None = None) -> Path:
    """Run copier copy into tmp_path and return the destination path."""
    data = {**BASE_DATA, **(overrides or {})}
    data_args = []
    for key, value in data.items():
        data_args += ["--data", f"{key}={value}"]

    subprocess.run(
        [
            "copier",
            "copy",
            str(TEMPLATE_DIR),
            str(tmp_path),
            "--defaults",
            "--overwrite",
            "--trust",
            *data_args,
        ],
        check=True,
        capture_output=True,
    )
    return tmp_path


MATRIX = [
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "none"},
        False, False,
        id="baseline",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "celery", "celery_broker": "redis", "redis_version": "8"},
        True, False,
        id="celery-redis",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "celery", "celery_broker": "redis", "redis_version": "8", "use_beat": "true"},
        True, True,
        id="celery-redis-beat",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "celery", "celery_broker": "rabbitmq", "redis_version": "8"},
        True, False,
        id="celery-rabbitmq",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "celery", "celery_broker": "rabbitmq", "redis_version": "8", "use_beat": "true"},
        True, True,
        id="celery-rabbitmq-beat",
    ),
    pytest.param(
        {"db_type": "postgis_16_34", "task_runner": "none"},
        False, False,
        id="postgis",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "huey", "redis_version": "8"},
        True, False,
        id="huey",
    ),
    pytest.param(
        {"db_type": "postgresql_18", "task_runner": "none", "media_storage": "s3_compatible"},
        False, False,
        id="s3-storage",
    ),
    pytest.param(
        {
            "db_type": "postgresql_18",
            "task_runner": "celery",
            "celery_broker": "redis",
            "redis_version": "8",
            "use_beat": "true",
            "media_storage": "s3_compatible",
            "email_backend": "smtp",
            "use_sentry": "true",
        },
        True, True,
        id="full",
    ),
]


@pytest.fixture()
def render(tmp_path: Path):
    """Fixture that returns a render_template callable bound to tmp_path."""

    def _render(overrides: dict[str, Any] | None = None) -> Path:
        return render_template(tmp_path, overrides)

    return _render
