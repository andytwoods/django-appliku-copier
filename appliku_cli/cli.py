"""CLI entry point: appliku-setup."""
import argparse
import logging
import sys
from pathlib import Path

import yaml

from appliku_cli.api import ApplikuClient
from appliku_cli.app_setup import ensure_app_id, ensure_team_path
from appliku_cli.credentials import load_credentials
from appliku_cli.provision import run_provision

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COPIER_ANSWERS_FILE = ".copier-answers.yml"


def _load_answers(path: Path) -> dict:
    if not path.exists():
        logger.error("Copier answers file not found: %s", path)
        sys.exit(1)
    with path.open() as f:
        answers = yaml.safe_load(f)
    # Strip Copier-internal keys (prefixed with _)
    return {k: v for k, v in answers.items() if not str(k).startswith("_")}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision Appliku resources for a Django project.",
    )
    parser.add_argument(
        "--copier-answers-file",
        type=Path,
        default=Path.cwd() / COPIER_ANSWERS_FILE,
        help=f"Path to copier answers file (default: ./{COPIER_ANSWERS_FILE})",
    )
    args = parser.parse_args()

    answers = _load_answers(args.copier_answers_file)
    credentials = load_credentials()

    client = ApplikuClient(
        api_key=credentials.api_key,
        team_path=credentials.team_path,
        app_id=credentials.app_id,
    )

    # Resolve team and app before provisioning
    ensure_team_path(credentials, client)
    ensure_app_id(credentials, client, answers)

    run_provision(credentials, answers)
    print("Appliku setup complete.")


if __name__ == "__main__":
    main()
