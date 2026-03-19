"""Verify manage.py check passes on the example project after template is applied."""
import subprocess
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "example" / "demo_project"


def test_manage_check():
    result = subprocess.run(
        ["python", "manage.py", "check"],
        cwd=EXAMPLE_DIR,
        env={
            **__import__("os").environ,
            "SECRET_KEY": "test-secret-key-for-ci",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"manage.py check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "no issues" in result.stdout.lower() or "0 silenced" in result.stdout
