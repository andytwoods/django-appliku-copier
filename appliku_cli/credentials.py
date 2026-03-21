"""Read and write Appliku credentials from .env.appliku."""
import dataclasses
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_FILENAME = ".env.appliku"
GITIGNORE_FILENAME = ".gitignore"


@dataclasses.dataclass
class Credentials:
    api_key: str
    team_path: str | None  # None until ensure_team_path() resolves it
    app_id: int | None  # None until ensure_app_id() resolves it
    server_id: int | None = None   # set when app is deployed to a server
    cluster_id: int | None = None  # set when app is deployed to a cluster
    provisioned: bool = False      # True after successful appliku-setup run


def load_credentials(cwd: Path | None = None) -> Credentials:
    """Load credentials from .env.appliku, prompting the user if the file is missing.

    APPLIKU_TEAM_PATH and APPLIKU_APP_ID are optional at this stage —
    call ensure_team_path() then ensure_app_id() afterwards.
    """
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME

    if env_file.exists():
        values = _parse_env_file(env_file)
    else:
        values = _prompt_and_write(env_file)

    _ensure_gitignored(base)

    # Prompt for API key if missing
    if not values.get("APPLIKU_API_KEY", "").strip():
        print(f"APPLIKU_API_KEY not found in {ENV_FILENAME}.")
        print("Find yours at: Appliku → Account → API Keys")
        values["APPLIKU_API_KEY"] = input("APPLIKU_API_KEY: ").strip()
        _write_env_file(env_file, values)
        print(f"Saved to {ENV_FILENAME}.")

    raw_team = values.get("APPLIKU_TEAM_PATH", "").strip()
    raw_app_id = values.get("APPLIKU_APP_ID", "").strip()
    raw_server_id = values.get("APPLIKU_SERVER_ID", "").strip()
    raw_cluster_id = values.get("APPLIKU_CLUSTER_ID", "").strip()
    return Credentials(
        api_key=values["APPLIKU_API_KEY"],
        team_path=raw_team or None,
        app_id=int(raw_app_id) if raw_app_id else None,
        server_id=int(raw_server_id) if raw_server_id else None,
        cluster_id=int(raw_cluster_id) if raw_cluster_id else None,
        provisioned=values.get("APPLIKU_PROVISIONED", "").strip().lower() == "true",
    )


def save_deployment_target(
    server_id: int | None,
    cluster_id: int | None,
    cwd: Path | None = None,
) -> None:
    """Persist APPLIKU_SERVER_ID or APPLIKU_CLUSTER_ID to .env.appliku."""
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME
    values = _parse_env_file(env_file) if env_file.exists() else {}
    if server_id is not None:
        values["APPLIKU_SERVER_ID"] = str(server_id)
    if cluster_id is not None:
        values["APPLIKU_CLUSTER_ID"] = str(cluster_id)
    _write_env_file(env_file, values)
    logger.info("Deployment target saved to %s", env_file)


def save_team_path(team_path: str, cwd: Path | None = None) -> None:
    """Persist APPLIKU_TEAM_PATH to .env.appliku."""
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME
    values = _parse_env_file(env_file) if env_file.exists() else {}
    values["APPLIKU_TEAM_PATH"] = team_path
    _write_env_file(env_file, values)
    logger.info("APPLIKU_TEAM_PATH=%s saved to %s", team_path, env_file)


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


def save_provisioned(cwd: Path | None = None) -> None:
    """Mark this app as fully provisioned in .env.appliku."""
    base = cwd or Path.cwd()
    env_file = base / ENV_FILENAME
    values = _parse_env_file(env_file) if env_file.exists() else {}
    values["APPLIKU_PROVISIONED"] = "true"
    _write_env_file(env_file, values)
    logger.info("APPLIKU_PROVISIONED=true saved to %s", env_file)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _prompt_and_write(env_file: Path) -> dict[str, str]:
    print(f"No {ENV_FILENAME} found.")
    print("Find your API key at: Appliku → Account → API Keys")
    api_key = input("APPLIKU_API_KEY: ").strip()
    values = {"APPLIKU_API_KEY": api_key}
    _write_env_file(env_file, values)
    print(f"Saved to {ENV_FILENAME} (gitignored).")
    return values


_TRAILING_KEYS = ("APPLIKU_APP_ID", "APPLIKU_SERVER_ID", "APPLIKU_CLUSTER_ID", "APPLIKU_PROVISIONED")


def _write_env_file(env_file: Path, values: dict[str, str]) -> None:
    lines = "\n".join(
        f"{k}={v}" for k, v in values.items() if k not in _TRAILING_KEYS
    ) + "\n"
    for key in _TRAILING_KEYS:
        val = values.get(key, "").strip()
        if val:
            lines += f"{key}={val}\n"
    env_file.write_text(lines)
    logger.info("Credentials written to %s", env_file)


def _ensure_gitignored(base: Path) -> None:
    gitignore = base / GITIGNORE_FILENAME
    added = False

    if not gitignore.exists():
        gitignore.write_text(f"{ENV_FILENAME}\n")
        logger.info("Created .gitignore with %s", ENV_FILENAME)
        added = True
    else:
        content = gitignore.read_text()
        if ENV_FILENAME not in content:
            with gitignore.open("a") as f:
                f.write(f"\n{ENV_FILENAME}\n")
            logger.info("Added %s to .gitignore", ENV_FILENAME)
            added = True

    if added:
        print(f"\n*** WARNING: {ENV_FILENAME} has been added to .gitignore. ***")
        print(f"*** It contains your Appliku API key — never commit it.   ***\n")

    # Check whether git is already tracking the file (e.g. committed by mistake)
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ENV_FILENAME],
            cwd=base,
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"\n{'!' * 60}")
            print(f"  DANGER: {ENV_FILENAME} is tracked by git!")
            print(f"  Your API key may already be in your commit history.")
            print(f"  Remove it immediately:")
            print(f"    git rm --cached {ENV_FILENAME}")
            print(f"    git commit -m 'Remove {ENV_FILENAME} from tracking'")
            print(f"  Then rotate your API key in Appliku → Account → API Keys.")
            print(f"{'!' * 60}\n")
    except FileNotFoundError:
        pass  # git not available
