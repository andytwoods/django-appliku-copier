"""CLI entry point: appliku-setup."""
import argparse
import logging
import re
import sys
from pathlib import Path

import yaml
from colorama import Fore, Style, init as colorama_init

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.app_setup import ensure_app_id, ensure_team_path
from appliku_cli.credentials import load_credentials
from appliku_cli.detect import detect_build_dummy_env, detect_django_settings_module, detect_secret_key_var, detect_whitenoise_manifest
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


_COLLECTSTATIC_RE = re.compile(
    r"(RUN\s+)(.*?)(python\s+manage\.py\s+collectstatic\s+--noinput)"
)


def _check_dockerfile_collectstatic(cwd: Path) -> None:
    """If whitenoise manifest storage is in use, ensure the Dockerfile runs collectstatic
    with the production settings module so the manifest is generated at build time.
    Patches the Dockerfile in-place and asks the user to commit+push if changed.
    """
    import re as _re

    dockerfile = cwd / "Dockerfile"
    if not dockerfile.exists():
        return
    if not detect_whitenoise_manifest(cwd):
        return

    production_module = detect_django_settings_module(cwd)
    if not production_module:
        return

    content = dockerfile.read_text()
    m = _COLLECTSTATIC_RE.search(content)
    if not m:
        return

    env_part = m.group(2)

    # Already using the production module — nothing to do
    if f"DJANGO_SETTINGS_MODULE={production_module}" in env_part:
        return

    # Build the corrected env prefix
    secret_key_var = detect_secret_key_var(cwd)
    always_skip = {secret_key_var, "DATABASE_URL", "ALLOWED_HOSTS", "DJANGO_ALLOWED_HOSTS",
                   "CSRF_TRUSTED_ORIGINS", "REDIS_URL", "CELERY_BROKER_URL", "DJANGO_SETTINGS_MODULE"}
    dummy_env = detect_build_dummy_env(cwd, production_module, always_skip)

    parts = [f"{secret_key_var}=build-only", f"DJANGO_SETTINGS_MODULE={production_module}"]
    parts += [f"{k}={v}" for k, v in dummy_env.items()]
    new_env = " ".join(parts) + " "

    new_line = m.group(1) + new_env + m.group(3)
    new_content = content[: m.start()] + new_line + content[m.end() :]

    if new_content == content:
        return

    dockerfile.write_text(new_content)

    print(
        f"\n{Fore.YELLOW}Whitenoise manifest storage detected.{Style.RESET_ALL}\n"
        f"{Fore.YELLOW}The Dockerfile collectstatic step has been updated to use "
        f"{Fore.CYAN}{production_module}{Fore.YELLOW} so the manifest is generated at build time.{Style.RESET_ALL}\n"
    )
    if dummy_env:
        print(
            f"{Fore.YELLOW}Dummy build-time env vars added: "
            f"{Fore.CYAN}{', '.join(dummy_env)}{Style.RESET_ALL}\n"
        )
    print(f"{Fore.YELLOW}Please commit and push the updated Dockerfile before continuing.{Style.RESET_ALL}")
    input("Press Enter once you have committed and pushed…\n")


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

    print(
        f"{Fore.YELLOW}Before continuing, make sure you have committed and pushed all "
        f"changes to your remote repository — Appliku deploys from there.{Style.RESET_ALL}\n"
    )
    input("Press Enter to continue…")

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

    _check_dockerfile_collectstatic(Path.cwd())

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
