"""App creation, git remote detection, and app ID resolution for Appliku setup."""
import logging
import re
import subprocess
from pathlib import Path

from appliku_cli.api import ApplikuClient
from appliku_cli.credentials import Credentials, save_app_id, save_deployment_target, save_team_path

logger = logging.getLogger(__name__)

_GITHUB_RE = re.compile(r"github\.com[:/](.+?)(?:\.git)?$")
_GITLAB_RE = re.compile(r"gitlab\.com[:/](.+?)(?:\.git)?$")
_APP_NAME_RE = re.compile(r"[^a-z0-9]")


def _sanitize_app_name(name: str) -> str:
    """Convert a project name/slug to a valid Appliku app name matching [a-z0-9]+."""
    sanitized = _APP_NAME_RE.sub("", name.lower())
    if not sanitized:
        raise ValueError(f"Cannot derive a valid Appliku app name from {name!r}")
    return sanitized


def detect_git_remote(cwd: Path) -> tuple[str, str | None]:
    """Return (provider, repo_path) from the 'origin' remote URL.

    provider: "github", "gitlab", or "custom"
    repo_path: "owner/repo" string, or None for custom remotes
    Raises RuntimeError if no origin remote is found.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "No git remote 'origin' found. "
            "Ensure this directory is a git repository with an 'origin' remote configured."
        )

    remote_url = result.stdout.strip()

    match = _GITHUB_RE.search(remote_url)
    if match:
        return "github", match.group(1)

    match = _GITLAB_RE.search(remote_url)
    if match:
        return "gitlab", match.group(1)

    return "custom", None


def _git_repo_root(cwd: Path) -> Path:
    """Return the root of the git repository containing cwd, or cwd itself."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return cwd


def _current_branch(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else "main"
    except subprocess.CalledProcessError:
        return "main"


def _pick_deployment_target(client: ApplikuClient) -> tuple[int | None, int | None]:
    """Return (cluster_id, server_id) for the chosen deployment target.

    Lists clusters and servers together and lets the user pick one.
    Returns (cluster_id, None) for clusters, (None, server_id) for servers.
    """
    clusters = client.list_clusters()
    servers = client.list_servers()

    options = []
    for c in clusters:
        options.append(("cluster", int(c["id"]), c.get("name", f"Cluster {c['id']}")))
    for s in servers:
        options.append(("server", int(s["id"]), s.get("name", f"Server {s['id']}")))

    if not options:
        raise RuntimeError(
            "No clusters or servers found on your Appliku account.\n"
            "Add a server at: https://app.appliku.com/servers/"
        )

    if len(options) == 1:
        kind, obj_id, name = options[0]
        logger.info("Using %s %r (id=%s)", kind, name, obj_id)
        return (obj_id, None) if kind == "cluster" else (None, obj_id)

    print("\nWhere do you want to deploy?")
    for i, (kind, obj_id, name) in enumerate(options):
        print(f"  [{i + 1}] {name}  ({kind} id={obj_id})")
    while True:
        choice = input(f"Select [1–{len(options)}]: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                kind, obj_id, _ = options[idx]
                return (obj_id, None) if kind == "cluster" else (None, obj_id)
        except ValueError:
            pass
        print("Invalid choice, please try again.")


def _resolve_github_repo(client: ApplikuClient, repo_path: str) -> str:
    repos = client.list_github_repos()
    for r in repos:
        if r.lower() == repo_path.lower():
            return r
    raise RuntimeError(
        f"Repository {repo_path!r} not found in your Appliku GitHub integration.\n"
        "Connect GitHub under Appliku → Settings → Git Integrations, then retry."
    )


def _resolve_gitlab_repo_id(client: ApplikuClient, repo_path: str) -> int:
    repos = client.list_gitlab_repos()
    for repo in repos:
        if repo.get("path_with_namespace", "").lower() == repo_path.lower():
            return int(repo["id"])
    raise RuntimeError(
        f"Repository {repo_path!r} not found in your Appliku GitLab integration.\n"
        "Connect GitLab under Appliku → Settings → Git Integrations, then retry."
    )


def create_new_app(client: ApplikuClient, answers: dict, cwd: Path) -> int:
    """Create a new Appliku application linked to the current repo.

    Detects the git remote, validates it against Appliku's linked repos,
    picks a cluster, then calls the create-app API.
    Returns the new application ID.
    """
    project_slug: str = answers.get("project_slug", "") or answers.get("project_name", "")
    app_name = _sanitize_app_name(project_slug)
    branch = _current_branch(cwd)

    logger.info("Detecting git remote in %s", cwd)
    provider, repo_path = detect_git_remote(cwd)

    cluster_id, server_id = _pick_deployment_target(client)

    if provider == "github":
        logger.info("Resolving GitHub repository: %s", repo_path)
        resolved = _resolve_github_repo(client, repo_path)
        result = client.create_app(
            name=app_name,
            branch=branch,
            cluster_id=cluster_id,
            server_id=server_id,
            repository_provider="github",
            repository_name=resolved,
        )

    elif provider == "gitlab":
        logger.info("Resolving GitLab repository: %s", repo_path)
        gitlab_id = _resolve_gitlab_repo_id(client, repo_path)
        result = client.create_app(
            name=app_name,
            branch=branch,
            cluster_id=cluster_id,
            server_id=server_id,
            repository_provider="gitlab",
            gitlab_repository_id=gitlab_id,
        )

    else:
        logger.warning("Remote is not GitHub or GitLab — using custom provider")
        custom_url = input("Git clone URL (for Appliku custom provider): ").strip()
        result = client.create_app(
            name=app_name,
            branch=branch,
            cluster_id=cluster_id,
            server_id=server_id,
            repository_provider="custom",
            custom_git_url=custom_url,
        )

    app_id = int(result["id"])
    logger.info("App created: id=%s name=%s", app_id, app_name)
    return app_id, cluster_id, server_id


def ensure_team_path(
    credentials: Credentials,
    client: ApplikuClient,
    cwd: Path | None = None,
) -> str:
    """Return a valid team_path, auto-discovering it from the API if not set.

    If credentials.team_path is already set, returns it immediately.
    If the account has exactly one team, uses it automatically.
    If there are multiple teams, prompts the user to pick one.
    Persists the result to .env.appliku.
    """
    if credentials.team_path:
        return credentials.team_path

    teams = client.list_teams()
    if not teams:
        raise RuntimeError("No teams found on your Appliku account.")

    if len(teams) == 1:
        team_path = teams[0]["team_path"]
        logger.info("Using team %r (team_path=%s)", teams[0]["name"], team_path)
    else:
        print("\nAvailable teams:")
        for i, t in enumerate(teams):
            print(f"  [{i + 1}] {t['name']}  (team_path={t['team_path']})")
        while True:
            choice = input(f"Select team [1–{len(teams)}]: ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(teams):
                    team_path = teams[idx]["team_path"]
                    break
            except ValueError:
                pass
            print("Invalid choice, please try again.")

    cwd = cwd or Path.cwd()
    save_team_path(team_path, cwd)
    credentials.team_path = team_path
    client._team_path = team_path  # noqa: SLF001
    return team_path


def ensure_app_id(
    credentials: Credentials,
    client: ApplikuClient,
    answers: dict,
    cwd: Path | None = None,
) -> int:
    """Return a valid app_id, creating a new Appliku app if none is set.

    If credentials.app_id is already set, returns it immediately.
    Otherwise prompts the user to enter an existing ID or creates a new app,
    then persists the result to .env.appliku.
    """
    cwd = cwd or Path.cwd()

    if credentials.app_id is not None:
        return credentials.app_id

    print("\nNo APPLIKU_APP_ID is set.")
    existing = input(
        "Enter an existing Appliku app ID, or press Enter to create a new app: "
    ).strip()

    if existing:
        app_id = int(existing)
        logger.info("Using existing app_id=%s", app_id)
    else:
        print("Creating a new Appliku app…")
        app_id, cluster_id, server_id = create_new_app(client, answers, cwd)
        save_deployment_target(server_id=server_id, cluster_id=cluster_id, cwd=cwd)
        credentials.server_id = server_id
        credentials.cluster_id = cluster_id

    save_app_id(app_id, cwd)
    credentials.app_id = app_id
    client._app_id = app_id  # noqa: SLF001 — update in-place so caller's client works
    return app_id
