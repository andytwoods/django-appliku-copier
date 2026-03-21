"""Tests for appliku_cli.app_setup."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from appliku_cli.app_setup import (
    _current_branch,
    _pick_cluster,
    _resolve_github_repo,
    _resolve_gitlab_repo_id,
    _sanitize_app_name,
    create_new_app,
    detect_git_remote,
    ensure_app_id,
    ensure_team_path,
)
from appliku_cli.credentials import Credentials


# ── _sanitize_app_name ────────────────────────────────────────────────────────

@pytest.mark.parametrize("input_name,expected", [
    ("myapp", "myapp"),
    ("my_app", "myapp"),
    ("my-app", "myapp"),
    ("My App", "myapp"),
    ("my_app_123", "myapp123"),
    ("MyProject2", "myproject2"),
])
def test_sanitize_app_name(input_name, expected):
    assert _sanitize_app_name(input_name) == expected


def test_sanitize_app_name_raises_on_empty_result():
    with pytest.raises(ValueError):
        _sanitize_app_name("---")


# ── detect_git_remote ─────────────────────────────────────────────────────────

def _mock_git(url: str):
    return patch(
        "subprocess.run",
        return_value=MagicMock(stdout=url + "\n", returncode=0),
    )


@pytest.mark.parametrize("url,provider,repo", [
    ("git@github.com:acme/myapp.git", "github", "acme/myapp"),
    ("https://github.com/acme/myapp.git", "github", "acme/myapp"),
    ("https://github.com/acme/myapp", "github", "acme/myapp"),
    ("git@gitlab.com:acme/myapp.git", "gitlab", "acme/myapp"),
    ("https://gitlab.com/acme/myapp.git", "gitlab", "acme/myapp"),
    ("https://bitbucket.org/acme/myapp.git", "custom", None),
])
def test_detect_git_remote(url, provider, repo, tmp_path):
    with patch(
        "appliku_cli.app_setup.subprocess.run",
        return_value=MagicMock(stdout=url + "\n", returncode=0),
    ):
        detected_provider, detected_repo = detect_git_remote(tmp_path)
    assert detected_provider == provider
    assert detected_repo == repo


def test_detect_git_remote_raises_when_no_remote(tmp_path):
    with patch(
        "appliku_cli.app_setup.subprocess.run",
        side_effect=subprocess.CalledProcessError(128, "git"),
    ):
        with pytest.raises(RuntimeError, match="No git remote"):
            detect_git_remote(tmp_path)


# ── _current_branch ───────────────────────────────────────────────────────────

def test_current_branch_returns_branch_name(tmp_path):
    with patch(
        "appliku_cli.app_setup.subprocess.run",
        return_value=MagicMock(stdout="feature/my-branch\n", returncode=0),
    ):
        assert _current_branch(tmp_path) == "feature/my-branch"


def test_current_branch_defaults_to_main_on_error(tmp_path):
    with patch(
        "appliku_cli.app_setup.subprocess.run",
        side_effect=subprocess.CalledProcessError(128, "git"),
    ):
        assert _current_branch(tmp_path) == "main"


def test_current_branch_defaults_to_main_for_detached_head(tmp_path):
    with patch(
        "appliku_cli.app_setup.subprocess.run",
        return_value=MagicMock(stdout="HEAD\n", returncode=0),
    ):
        assert _current_branch(tmp_path) == "main"


# ── _pick_cluster ─────────────────────────────────────────────────────────────

def test_pick_cluster_single_cluster():
    client = MagicMock()
    client.list_clusters.return_value = [{"id": 7, "name": "prod"}]
    assert _pick_cluster(client) == 7


def test_pick_cluster_multiple_prompts_user():
    client = MagicMock()
    client.list_clusters.return_value = [
        {"id": 7, "name": "prod", "apps_count": 3},
        {"id": 8, "name": "staging", "apps_count": 1},
    ]
    with patch("builtins.input", return_value="2"):
        assert _pick_cluster(client) == 8


def test_pick_cluster_raises_when_empty():
    client = MagicMock()
    client.list_clusters.return_value = []
    with pytest.raises(RuntimeError, match="No clusters"):
        _pick_cluster(client)


# ── _resolve_github_repo ──────────────────────────────────────────────────────

def test_resolve_github_repo_found():
    client = MagicMock()
    client.list_github_repos.return_value = ["acme/myapp", "acme/other"]
    assert _resolve_github_repo(client, "acme/myapp") == "acme/myapp"


def test_resolve_github_repo_case_insensitive():
    client = MagicMock()
    client.list_github_repos.return_value = ["Acme/MyApp"]
    assert _resolve_github_repo(client, "acme/myapp") == "Acme/MyApp"


def test_resolve_github_repo_not_found():
    client = MagicMock()
    client.list_github_repos.return_value = ["acme/other"]
    with pytest.raises(RuntimeError, match="not found"):
        _resolve_github_repo(client, "acme/myapp")


# ── _resolve_gitlab_repo_id ───────────────────────────────────────────────────

def test_resolve_gitlab_repo_id_found():
    client = MagicMock()
    client.list_gitlab_repos.return_value = [
        {"id": 7, "path_with_namespace": "acme/myapp"},
    ]
    assert _resolve_gitlab_repo_id(client, "acme/myapp") == 7


def test_resolve_gitlab_repo_id_not_found():
    client = MagicMock()
    client.list_gitlab_repos.return_value = [{"id": 9, "path_with_namespace": "acme/other"}]
    with pytest.raises(RuntimeError, match="not found"):
        _resolve_gitlab_repo_id(client, "acme/myapp")


# ── create_new_app ────────────────────────────────────────────────────────────

def _mock_git_detection(provider: str, repo: str | None, branch: str = "main"):
    return patch.multiple(
        "appliku_cli.app_setup",
        detect_git_remote=MagicMock(return_value=(provider, repo)),
        _current_branch=MagicMock(return_value=branch),
        _pick_cluster=MagicMock(return_value=1),
    )


def test_create_new_app_github(tmp_path):
    client = MagicMock()
    client.list_github_repos.return_value = ["acme/myapp"]
    client.create_app.return_value = {"id": 55}
    answers = {"project_slug": "myapp"}

    with _mock_git_detection("github", "acme/myapp"):
        app_id = create_new_app(client, answers, tmp_path)

    assert app_id == 55
    client.create_app.assert_called_once()
    call_kwargs = client.create_app.call_args.kwargs
    assert call_kwargs["repository_provider"] == "github"
    assert call_kwargs["repository_name"] == "acme/myapp"
    assert call_kwargs["branch"] == "main"


def test_create_new_app_gitlab(tmp_path):
    client = MagicMock()
    client.list_gitlab_repos.return_value = [{"id": 7, "path_with_namespace": "acme/myapp"}]
    client.create_app.return_value = {"id": 56}
    answers = {"project_slug": "myapp"}

    with _mock_git_detection("gitlab", "acme/myapp"):
        app_id = create_new_app(client, answers, tmp_path)

    assert app_id == 56
    call_kwargs = client.create_app.call_args.kwargs
    assert call_kwargs["repository_provider"] == "gitlab"
    assert call_kwargs["gitlab_repository_id"] == 7


def test_create_new_app_custom_remote(tmp_path):
    client = MagicMock()
    client.create_app.return_value = {"id": 57}
    answers = {"project_slug": "myapp"}

    with _mock_git_detection("custom", None):
        with patch("builtins.input", return_value="https://mygit.com/repo.git"):
            app_id = create_new_app(client, answers, tmp_path)

    assert app_id == 57
    call_kwargs = client.create_app.call_args.kwargs
    assert call_kwargs["repository_provider"] == "custom"
    assert call_kwargs["custom_git_url"] == "https://mygit.com/repo.git"


def test_create_new_app_sanitizes_slug(tmp_path):
    client = MagicMock()
    client.list_github_repos.return_value = ["acme/my-app"]
    client.create_app.return_value = {"id": 58}
    answers = {"project_slug": "my-app"}

    with _mock_git_detection("github", "acme/my-app"):
        create_new_app(client, answers, tmp_path)

    call_kwargs = client.create_app.call_args.kwargs
    assert call_kwargs["name"] == "myapp"


# ── ensure_app_id ─────────────────────────────────────────────────────────────

def test_ensure_app_id_returns_existing(tmp_path):
    creds = Credentials(api_key="k", team_path="t", app_id=42)
    client = MagicMock()
    app_id = ensure_app_id(creds, client, {}, cwd=tmp_path)
    assert app_id == 42
    client.create_app.assert_not_called()


def test_ensure_app_id_uses_entered_existing_id(tmp_path):
    (tmp_path / ".env.appliku").write_text("APPLIKU_API_KEY=k\nAPPLIKU_TEAM_PATH=t\n")
    creds = Credentials(api_key="k", team_path="t", app_id=None)
    client = MagicMock()
    with patch("builtins.input", return_value="77"):
        app_id = ensure_app_id(creds, client, {}, cwd=tmp_path)
    assert app_id == 77
    assert creds.app_id == 77
    assert "APPLIKU_APP_ID=77" in (tmp_path / ".env.appliku").read_text()


def test_ensure_app_id_creates_new_app_on_blank_input(tmp_path):
    (tmp_path / ".env.appliku").write_text("APPLIKU_API_KEY=k\nAPPLIKU_TEAM_PATH=t\n")
    creds = Credentials(api_key="k", team_path="t", app_id=None)
    client = MagicMock()

    with patch("appliku_cli.app_setup.create_new_app", return_value=99) as mock_create:
        with patch("builtins.input", return_value=""):
            app_id = ensure_app_id(creds, client, {"project_slug": "myapp"}, cwd=tmp_path)

    assert app_id == 99
    mock_create.assert_called_once()
    assert "APPLIKU_APP_ID=99" in (tmp_path / ".env.appliku").read_text()


# ── ensure_team_path ──────────────────────────────────────────────────────────

def test_ensure_team_path_returns_existing(tmp_path):
    creds = Credentials(api_key="k", team_path="my-team", app_id=None)
    client = MagicMock()
    result = ensure_team_path(creds, client, cwd=tmp_path)
    assert result == "my-team"
    client.list_teams.assert_not_called()


def test_ensure_team_path_single_team_auto_selected(tmp_path):
    (tmp_path / ".env.appliku").write_text("APPLIKU_API_KEY=k\n")
    creds = Credentials(api_key="k", team_path=None, app_id=None)
    client = MagicMock()
    client.list_teams.return_value = [{"id": 1, "name": "My Team", "team_path": "my-team"}]
    result = ensure_team_path(creds, client, cwd=tmp_path)
    assert result == "my-team"
    assert creds.team_path == "my-team"
    assert client._team_path == "my-team"
    assert "APPLIKU_TEAM_PATH=my-team" in (tmp_path / ".env.appliku").read_text()


def test_ensure_team_path_multiple_prompts_user(tmp_path):
    (tmp_path / ".env.appliku").write_text("APPLIKU_API_KEY=k\n")
    creds = Credentials(api_key="k", team_path=None, app_id=None)
    client = MagicMock()
    client.list_teams.return_value = [
        {"id": 1, "name": "Personal", "team_path": "personal"},
        {"id": 2, "name": "Work", "team_path": "work-team"},
    ]
    with patch("builtins.input", return_value="2"):
        result = ensure_team_path(creds, client, cwd=tmp_path)
    assert result == "work-team"


def test_ensure_team_path_raises_when_no_teams(tmp_path):
    creds = Credentials(api_key="k", team_path=None, app_id=None)
    client = MagicMock()
    client.list_teams.return_value = []
    with pytest.raises(RuntimeError, match="No teams"):
        ensure_team_path(creds, client, cwd=tmp_path)
