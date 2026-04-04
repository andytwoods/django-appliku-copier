"""Audit and remove Appliku datastores across all apps."""
import re
import sys
from pathlib import Path

from colorama import Fore, Style, init as colorama_init

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import load_credentials

colorama_init(autoreset=True)


def _ok(msg: str) -> str:
    return f"{Fore.GREEN}{msg}{Style.RESET_ALL}"

def _warn(msg: str) -> str:
    return f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"

def _err(msg: str) -> str:
    return f"{Fore.RED}{msg}{Style.RESET_ALL}"

def _info(msg: str) -> str:
    return f"{Fore.CYAN}{msg}{Style.RESET_ALL}"

def _bold(msg: str) -> str:
    return f"{Style.BRIGHT}{msg}{Style.RESET_ALL}"

def _dim(msg: str) -> str:
    return f"{Style.DIM}{msg}{Style.RESET_ALL}"


_TYPE_LABEL = {
    "postgresql": "postgres",
    "redis":      "redis",
    "mysql":      "mysql",
    "rabbitmq":   "rabbitmq",
}

def _short_type(store_type: str) -> str:
    s = (store_type or "").lower()
    for key, label in _TYPE_LABEL.items():
        if key in s:
            return label
    return store_type or "?"


# Docker container names for Appliku-managed datastores follow the pattern "{id}-db"
_DATASTORE_CONTAINER_RE = re.compile(r"\b(\d+)-db\b")
# Stock image names that indicate a database container
_STOCK_DB_IMAGES = re.compile(r"\b(postgres|redis|mysql|rabbitmq):", re.IGNORECASE)
# App containers follow the pattern "{appname}_{service}:{deployment_id}"
_APP_CONTAINER_RE = re.compile(r"^([a-z0-9]+)_([a-z0-9_]+):\d+$")


def _parse_docker_db_containers(docker_info: str) -> dict[int, str]:
    """Parse the server's docker_info string and return {datastore_id: image_name}
    for all running database containers.

    Handles both Appliku-named containers ({id}-db) and stock-image containers.
    """
    found: dict[int, str] = {}
    for line in docker_info.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        image = parts[1]
        # Named datastore: image name is "{id}-db"
        m = _DATASTORE_CONTAINER_RE.search(image)
        if m:
            found[int(m.group(1))] = image
            continue
        # Stock image (older deployments): postgres:16, redis:8, etc.
        if _STOCK_DB_IMAGES.search(image):
            # Use a sentinel negative ID so we know it's unnamed
            found[-(len(found) + 1)] = image
    return found


def _parse_docker_app_containers(docker_info: str) -> list[dict]:
    """Parse docker_info and return a list of running app containers.

    Each entry: {container_id, image, app_name, service}
    Only returns containers matching the Appliku app-image pattern
    "{appname}_{service}:{deployment_id}".
    """
    containers = []
    for line in docker_info.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        container_id = parts[0]
        image = parts[1]
        m = _APP_CONTAINER_RE.match(image)
        if m:
            containers.append({
                "container_id": container_id,
                "image":        image,
                "app_name":     m.group(1),
                "service":      m.group(2),
            })
    return containers


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Audit Appliku datastores across all apps. "
            "Lists every postgres/redis/etc, which app it belongs to, "
            "and flags any running on the server that are not attached to any app."
        ),
    )
    parser.add_argument(
        "--remove-stray",
        action="store_true",
        help="Interactively prompt to delete datastores that are not attached to any app.",
    )
    args = parser.parse_args()

    credentials = load_credentials()
    if not credentials.team_path:
        # Auto-discover team
        client_no_team = ApplikuClient(api_key=credentials.api_key)
        teams = client_no_team.list_teams()
        if not teams:
            print(_err("No teams found on your Appliku account."))
            sys.exit(1)
        credentials.team_path = teams[0]["team_path"]

    client = ApplikuClient(api_key=credentials.api_key, team_path=credentials.team_path)

    # ── Fetch all apps and their datastores ───────────────────────────────────
    print(_info("Fetching apps…"))
    apps = client.list_apps()
    if not apps:
        print(_warn("No apps found."))
        return

    # {datastore_id: {app_id, app_name, name, store_type}}
    attached: dict[int, dict] = {}

    for app in apps:
        app_id = app["id"]
        app_name = app.get("name", str(app_id))
        try:
            ds_list = client._check(
                client._session.get(
                    f"https://api.appliku.com/api/team/{credentials.team_path}"
                    f"/applications/{app_id}/datastores"
                )
            )
        except ApplikuAPIError:
            continue
        for ds in ds_list if isinstance(ds_list, list) else []:
            ds_id = ds.get("id")
            if ds_id is not None:
                attached[ds_id] = {
                    "app_id":     app_id,
                    "app_name":   app_name,
                    "name":       ds.get("name", ""),
                    "store_type": ds.get("store_type") or ds.get("type", ""),
                }

    # ── Get server docker info to find running containers ────────────────────
    docker_running: dict[int, str] = {}
    stray_app_containers: list[dict] = []
    known_app_names = {app.get("name", "").lower() for app in apps}

    try:
        servers = client.list_servers()
        for srv in servers:
            docker_info = srv.get("docker_info", "")
            if not docker_info:
                continue
            docker_running.update(_parse_docker_db_containers(docker_info))
            for c in _parse_docker_app_containers(docker_info):
                if c["app_name"].lower() not in known_app_names:
                    stray_app_containers.append(c)
    except ApplikuAPIError:
        pass  # server info is best-effort

    # ── Compute stray: in docker but ID not in attached ────────────────────────
    # Only numbered containers ({id}-db) can be definitively identified as stray.
    stray: dict[int, str] = {
        ds_id: image
        for ds_id, image in docker_running.items()
        if ds_id > 0 and ds_id not in attached
    }

    # ── Print report ──────────────────────────────────────────────────────────
    print()
    print(_bold("═" * 64))
    print(_bold("  APPLIKU DATASTORE AUDIT"))
    print(_bold("═" * 64))

    # Group attached by app
    by_app: dict[str, list] = {}
    for ds_id, info in sorted(attached.items()):
        by_app.setdefault(info["app_name"], []).append((ds_id, info))

    for app_name, datastores in sorted(by_app.items()):
        print()
        print(_bold(f"  {app_name}"))
        for ds_id, info in datastores:
            label = _short_type(info["store_type"])
            in_docker = ds_id in docker_running
            status = _ok("running") if in_docker else _warn("not running")
            print(f"    [{ds_id:5d}]  {label:12s}  {info['name']:20s}  {status}")

    if stray:
        print()
        print(_bold("─" * 64))
        print(_err("  STRAY DATASTORES  (running on server, not attached to any app)"))
        print(_bold("─" * 64))
        for ds_id, image in sorted(stray.items()):
            print(f"    [{ds_id:5d}]  {image}")
    else:
        print()
        print(_ok("  No stray datastores detected."))

    # Unnamed stock-image containers can't be identified by ID
    unnamed = {ds_id: img for ds_id, img in docker_running.items() if ds_id < 0}
    if unnamed:
        print()
        print(_warn("  Note: the following DB containers use stock images and cannot be"))
        print(_warn("  matched to a datastore ID — check the Appliku dashboard if needed:"))
        for _, image in sorted(unnamed.items(), key=lambda kv: kv[1]):
            print(f"    {_dim(image)}")

    # ── Stray app containers ──────────────────────────────────────────────────
    if stray_app_containers:
        print()
        print(_bold("─" * 64))
        print(_err("  STRAY APP CONTAINERS  (running on server, app no longer in Appliku)"))
        print(_bold("─" * 64))
        for c in stray_app_containers:
            print(f"    {c['container_id'][:12]}  {c['image']}")
        print()
        print(_warn("  These cannot be removed via the API — the app is already deleted."))
        print(_warn("  To remove them, SSH into your server and run:"))
        for c in stray_app_containers:
            cid = c["container_id"][:12]
            print(f"    {_dim(f'docker rm -f {cid}')}")
    else:
        print()
        print(_ok("  No stray app containers detected."))

    print()
    print(_bold("═" * 64))
    print(f"  Attached: {_ok(str(len(attached)))}   "
          f"Stray DBs: {_err(str(len(stray))) if stray else _ok('0')}   "
          f"Stray containers: {_err(str(len(stray_app_containers))) if stray_app_containers else _ok('0')}")
    print(_bold("═" * 64))

    # ── Remove stray ──────────────────────────────────────────────────────────
    if args.remove_stray and not stray and not stray_app_containers:
        print(_info("\nNothing to remove."))
        return

    if args.remove_stray and stray:
        print()
        print(_warn("The following stray datastores will be permanently deleted:"))
        for ds_id, image in sorted(stray.items()):
            print(f"  [{ds_id}]  {image}")
        print()
        confirm = input(_warn("Type 'yes' to confirm deletion: ")).strip().lower()
        if confirm != "yes":
            print(_info("Aborted."))
            return

        for ds_id, image in sorted(stray.items()):
            # Stray datastores have no app_id in our list.
            # Try to delete via a scan of all app IDs (in case the app was recently deleted).
            # If that fails, report manual cleanup instructions.
            deleted = False
            for app in apps:
                try:
                    client.delete_datastore(app["id"], ds_id)
                    print(_ok(f"  ✓ Deleted [{ds_id}] {image}"))
                    deleted = True
                    break
                except ApplikuAPIError:
                    continue
            if not deleted:
                print(_warn(
                    f"  Could not delete [{ds_id}] {image} via API "
                    f"(app may already be deleted).\n"
                    f"  Remove it manually on your server:\n"
                    f"    docker rm -f $(docker ps -q --filter ancestor={image})"
                ))
