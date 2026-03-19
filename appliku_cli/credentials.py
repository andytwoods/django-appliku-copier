"""Read and write Appliku credentials from .env.appliku."""
import dataclasses
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_FILENAME = ".env.appliku"
GITIGNORE_FILENAME = ".gitignore"


@dataclasses.dataclass
class Credentials:
    api_key: str
    team_path: str
    app_id: int | None  # None until ensure_app_id() resolves it


def load_credentials(cwd: Path | None = None) -> Credentials:
    """Load credentials from .env.appliku, prompting the user if the file is missing.

    APPLIKU_APP_ID is optional at this stage — call ensure_app_id() afterwards
    when you need a resolved app ID.
    """
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME

    if env_file.exists():
        values = _parse_env_file(env_file)
    else:
        values = _prompt_and_write(env_file)

    _ensure_gitignored(base)

    raw_app_id = values.get("APPLIKU_APP_ID", "").strip()
    return Credentials(
        api_key=values["APPLIKU_API_KEY"],
        team_path=values["APPLIKU_TEAM_PATH"],
        app_id=int(raw_app_id) if raw_app_id else None,
    )


def save_app_id(app_id: int, cwd: Path | None = None) -> None:
    """Persist APPLIKU_APP_ID to .env.appliku."""
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        if any(line.startswith("APPLIKU_APP_ID=") for line in lines):
            lines = [
                f"APPLIKU_APP_ID={app_id}" if line.startswith("APPLIKU_APP_ID=") else line
                for line in lines
            ]
            env_file.write_text("\n".join(lines) + "\n")
        else:
            with env_file.open("a") as f:
                f.write(f"APPLIKU_APP_ID={app_id}\n")
    else:
        with env_file.open("a") as f:
            f.write(f"APPLIKU_APP_ID={app_id}\n")
    logger.info("APPLIKU_APP_ID=%s saved to %s", app_id, env_file)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _prompt_and_write(env_file: Path) -> dict[str, str]:
    print(f"No {ENV_FILENAME} found. Please enter your Appliku credentials:")
    api_key = input("APPLIKU_API_KEY: ").strip()
    team_path = input("APPLIKU_TEAM_PATH: ").strip()

    values = {
        "APPLIKU_API_KEY": api_key,
        "APPLIKU_TEAM_PATH": team_path,
    }
    env_file.write_text(
        f"APPLIKU_API_KEY={api_key}\n"
        f"APPLIKU_TEAM_PATH={team_path}\n"
    )
    logger.info("Credentials written to %s", env_file)
    return values


def _ensure_gitignored(base: Path) -> None:
    gitignore = base / GITIGNORE_FILENAME
    if not gitignore.exists():
        gitignore.write_text(f"{ENV_FILENAME}\n")
        logger.info("Created .gitignore with %s", ENV_FILENAME)
        return
    content = gitignore.read_text()
    if ENV_FILENAME not in content:
        with gitignore.open("a") as f:
            f.write(f"\n{ENV_FILENAME}\n")
        logger.info("Added %s to .gitignore", ENV_FILENAME)
