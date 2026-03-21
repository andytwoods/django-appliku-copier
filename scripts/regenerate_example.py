"""Wipe and regenerate the Copier-generated files in example/demo_project/.

Run from the repo root:
    python scripts/regenerate_example.py
"""
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "template"
EXAMPLE_DIR = REPO_ROOT / "example" / "demo_project"

GENERATED_FILES = [
    "appliku.yml",
    "Dockerfile",
    "run.sh",
    "release.sh",
    "worker.sh",
    "celery-beat.sh",
]

COPIER_DATA = {
    "project_slug": "testapp1",
    "python_version": "3.13",
    "package_manager": "uv",
    "web_server": "gunicorn",
    "db_type": "postgresql_18",
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
    # Copier skips writing .copier-answers.yml when the template has no git tag.
    # Write it explicitly so `appliku-setup` can find the answers.
    answers_file = EXAMPLE_DIR / ".copier-answers.yml"
    answers = {"_src_path": str(TEMPLATE_DIR), **COPIER_DATA}
    with answers_file.open("w") as f:
        f.write("# Changes here will be overwritten by Copier\n")
        yaml.dump(answers, f, default_flow_style=False, allow_unicode=True)
    print(f"Wrote {answers_file.relative_to(REPO_ROOT)}")

    print("Regeneration complete.")


if __name__ == "__main__":
    main()
