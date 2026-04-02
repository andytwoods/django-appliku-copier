"""CLI entry point: appliku-setup."""
import argparse
import logging
import sys
from pathlib import Path

import yaml
from colorama import Fore, Style, init as colorama_init

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.app_setup import ensure_app_id, ensure_team_path
from appliku_cli.credentials import load_credentials
from appliku_cli.provision import run_provision

colorama_init(autoreset=True)

_LEVEL_COLOURS = {
    "DEBUG": Fore.WHITE + Style.DIM,
    "INFO": Fore.BLUE,
    "WARNING": Fore.YELLOW,
    "ERROR": Fore.RED,
    "CRITICAL": Fore.RED + Style.BRIGHT,
}

class _ColouredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        return f"{colour}{record.levelname} {record.getMessage()}{Style.RESET_ALL}"

_handler = logging.StreamHandler()
_handler.setFormatter(_ColouredFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
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

    try:
        run_provision(credentials, answers, cwd=Path.cwd())
    except ApplikuAPIError as exc:
        if "doesn't exist" in exc.body or "does not exist" in exc.body:
            print(
                "\nError: Appliku can't find the app referenced by APPLIKU_APP_ID "
                f"({credentials.app_id}).\n"
                "It may have been deleted from the Appliku dashboard.\n\n"
                "To fix:\n"
                "  1. Remove APPLIKU_APP_ID from .env.appliku\n"
                "  2. Re-run appliku-setup  (a new app will be created)"
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
