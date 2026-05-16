"""Tests for appliku_cli.detect — static analysis helpers."""
from pathlib import Path

import pytest

from appliku_cli.detect import patch_dockerfile_collectstatic


def _write_dockerfile(tmp_path: Path, content: str) -> Path:
    df = tmp_path / "Dockerfile"
    df.write_text(content)
    return df


_BASIC_LINE = "RUN SECRET_KEY=build-only python manage.py collectstatic --noinput\n"
_FULL_LINE = (
    "RUN SECRET_KEY=build-only DJANGO_SETTINGS_MODULE=config.settings.production"
    " python manage.py collectstatic --noinput\n"
)


class TestPatchDockerfileCollectstatic:
    def test_returns_false_when_no_dockerfile(self, tmp_path):
        assert patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", None, []) is False

    def test_returns_false_when_no_collectstatic_line(self, tmp_path):
        _write_dockerfile(tmp_path, "FROM python:3.12-slim\nRUN pip install -r requirements.txt\n")
        assert patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", None, []) is False

    def test_returns_false_when_already_correct(self, tmp_path):
        _write_dockerfile(tmp_path, _FULL_LINE)
        assert patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", "config.settings.production", []) is False

    def test_returns_true_and_rewrites_when_extra_vars_added(self, tmp_path):
        _write_dockerfile(tmp_path, _FULL_LINE)
        changed = patch_dockerfile_collectstatic(
            tmp_path, "SECRET_KEY", "config.settings.production", ["BREVO_API_KEY", "DJANGO_ADMIN_URL"]
        )
        assert changed is True
        content = (tmp_path / "Dockerfile").read_text()
        assert "BREVO_API_KEY=build-only" in content
        assert "DJANGO_ADMIN_URL=build-only" in content
        assert "python manage.py collectstatic --noinput" in content

    def test_uses_custom_secret_key_var_name(self, tmp_path):
        _write_dockerfile(tmp_path, "RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput\n")
        patch_dockerfile_collectstatic(tmp_path, "DJANGO_SECRET_KEY", None, ["EXTRA"])
        content = (tmp_path / "Dockerfile").read_text()
        assert content.startswith("RUN DJANGO_SECRET_KEY=build-only")
        assert "EXTRA=build-only" in content

    def test_omits_settings_module_when_none(self, tmp_path):
        _write_dockerfile(tmp_path, _BASIC_LINE)
        patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", None, ["EXTRA"])
        content = (tmp_path / "Dockerfile").read_text()
        assert "DJANGO_SETTINGS_MODULE" not in content

    def test_includes_settings_module_when_given(self, tmp_path):
        _write_dockerfile(tmp_path, _BASIC_LINE)
        patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", "config.settings.production", [])
        content = (tmp_path / "Dockerfile").read_text()
        assert "DJANGO_SETTINGS_MODULE=config.settings.production" in content

    def test_preserves_surrounding_dockerfile_content(self, tmp_path):
        _write_dockerfile(tmp_path, (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            + _BASIC_LINE +
            "EXPOSE 8000\n"
        ))
        patch_dockerfile_collectstatic(tmp_path, "SECRET_KEY", None, ["EXTRA"])
        content = (tmp_path / "Dockerfile").read_text()
        assert content.startswith("FROM python:3.12-slim\n")
        assert "EXPOSE 8000" in content
