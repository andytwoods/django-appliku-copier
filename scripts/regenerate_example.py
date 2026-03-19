"""Wipe and regenerate the Copier-generated files in example/demo_project/.

Run from the repo root:
    python scripts/regenerate_example.py
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "template"
EXAMPLE_DIR = REPO_ROOT / "example" / "demo_project"

GENERATED_FILES = [
    "appliku.yml",
    "Dockerfile",
    "run.sh",
    "release.sh",
    "celery-worker.sh",
    "celery-beat.sh",
]

COPIER_DATA = {
    "project_name": "Demo Project",
    "project_slug": "config",
    "python_version": "3.12",
    "db_type": "postgresql_17",
    "task_runner": "none",
    "media_storage": "none",
    "email_backend": "console",
    "use_sentry": "false",
}


def main() -> None:
    for filename in GENERATED_FILES:
        target = EXAMPLE_DIR / filename
        if target.exists():
            target.unlink()
            print(f"Removed {target.relative_to(REPO_ROOT)}")

    data_args = []
    for key, value in COPIER_DATA.items():
        data_args += ["--data", f"{key}={value}"]

    subprocess.run(
        [
            "copier",
            "copy",
            str(TEMPLATE_DIR),
            str(EXAMPLE_DIR),
            "--defaults",
            "--overwrite",
            "--trust",
            *data_args,
        ],
        check=True,
    )
    print("Regeneration complete.")


if __name__ == "__main__":
    main()
