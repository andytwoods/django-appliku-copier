"""Thin wrapper around the Appliku REST API."""
import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.appliku.com"


class ApplikuAPIError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Appliku API error {status_code}: {body}")


class ApplikuClient:
    def __init__(self, api_key: str, team_path: str | None = None, app_id: int | None = None) -> None:
        self._team_path = team_path
        self._app_id = app_id
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        })

    def _check(self, response: requests.Response) -> dict:
        if not response.ok:
            raise ApplikuAPIError(response.status_code, response.text)
        try:
            return response.json()
        except ValueError:
            return {}

    def _require_app_id(self) -> int:
        if self._app_id is None:
            raise RuntimeError("app_id is required for this operation; call ensure_app_id() first")
        return self._app_id

    def _require_team_path(self) -> str:
        if not self._team_path:
            raise RuntimeError("team_path is required for this operation; call ensure_team_path() first")
        return self._team_path

    # ── Account-level (no team_path needed) ───────────────────────────────────

    def list_teams(self) -> list[dict]:
        """GET /api/team — returns list of {id, name, team_path, ...}."""
        logger.info("Listing teams")
        url = f"{BASE_URL}/api/team"
        return self._check(self._session.get(url))

    # ── Team-level (no app_id needed) ─────────────────────────────────────────

    def list_clusters(self) -> list[dict]:
        """GET /api/team/{team_path}/clusters"""
        team_path = self._require_team_path()
        logger.info("Listing clusters for team %r", team_path)
        url = f"{BASE_URL}/api/team/{team_path}/clusters"
        result = self._check(self._session.get(url))
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    def list_servers(self) -> list[dict]:
        """GET /api/team/{team_path}/server_list"""
        team_path = self._require_team_path()
        logger.info("Listing servers for team %r", team_path)
        url = f"{BASE_URL}/api/team/{team_path}/server_list"
        result = self._check(self._session.get(url))
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []

    def list_github_repos(self) -> list[str]:
        """GET /api/github/repositories/ — returns list of 'owner/repo' strings."""
        logger.info("Listing GitHub repositories")
        url = f"{BASE_URL}/api/github/repositories/"
        result = self._check(self._session.get(url))
        return result if isinstance(result, list) else []

    def list_gitlab_repos(self) -> list[dict]:
        """GET /api/gitlab/repositories/ — returns list of {id, path_with_namespace, ...}."""
        logger.info("Listing GitLab repositories")
        url = f"{BASE_URL}/api/gitlab/repositories/"
        result = self._check(self._session.get(url))
        return result if isinstance(result, list) else []

    def create_app(
        self,
        name: str,
        branch: str,
        repository_provider: str,
        cluster_id: int | None = None,
        server_id: int | None = None,
        repository_name: str | None = None,
        gitlab_repository_id: int | None = None,
        custom_git_url: str | None = None,
        dockerfile_context_path: str | None = None,
        yml_config_file_path: str = "appliku.yml",
    ) -> dict:
        """POST /api/team/{team_path}/applications/create/"""
        team_path = self._require_team_path()
        logger.info("Creating app name=%r branch=%r", name, branch)
        url = f"{BASE_URL}/api/team/{team_path}/applications/create/"
        payload: dict = {
            "name": name,
            "branch": branch,
            "build_pack": "dockerfile",
            "dockerfile_path": "Dockerfile",
            "yml_config_file_path": yml_config_file_path,
            "repository_provider": repository_provider,
        }
        if cluster_id is not None:
            payload["cluster"] = cluster_id
        if server_id is not None:
            payload["server"] = server_id
        if repository_name is not None:
            payload["repository_name"] = repository_name
        if gitlab_repository_id is not None:
            payload["gitlab_repository_id"] = gitlab_repository_id
        if custom_git_url is not None:
            payload["custom_git_url"] = custom_git_url
        if dockerfile_context_path is not None:
            payload["dockerfile_context_path"] = dockerfile_context_path
        return self._check(self._session.post(url, json=payload))

    # ── App-level (app_id required) ───────────────────────────────────────────

    def list_datastores(self) -> list[dict]:
        """GET /api/team/{team_path}/applications/{app_id}/datastores"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/datastores"
        result = self._check(self._session.get(url))
        return result if isinstance(result, list) else []

    def create_datastore(
        self,
        name: str,
        store_type: str,
        server_id: int | None = None,
        cluster_id: int | None = None,
    ) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/datastores"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        logger.info("Creating datastore name=%r store_type=%r", name, store_type)
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/datastores"
        payload: dict = {"name": name, "store_type": store_type}
        if server_id is not None:
            payload["server"] = server_id
        if cluster_id is not None:
            payload["cluster"] = cluster_id
        return self._check(self._session.post(url, json=payload))

    def get_config_vars(self) -> list[dict]:
        """GET /api/team/{team_path}/applications/{app_id}/config-vars"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/config-vars"
        result = self._check(self._session.get(url))
        return result.get("env_vars", [])

    def set_config_vars(self, vars: dict[str, str]) -> None:
        """PATCH /api/team/{team_path}/applications/{app_id}/config-vars"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        logger.info("Setting config vars: %s", list(vars.keys()))
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/config-vars"
        payload = {"env_vars": [{"name": k, "value": v} for k, v in vars.items()]}
        self._check(self._session.patch(url, json=payload))

    def delete_config_vars(self, names: list[str]) -> None:
        """Remove config vars by name (fetches current vars and PATCHes without the removed ones)."""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        logger.info("Deleting config vars: %s", names)
        names_set = set(names)
        current = self.get_config_vars()
        remaining = [
            {"name": v["name"], "value": v["value"], "mode": v.get("mode")}
            for v in current
            if v["name"] not in names_set
        ]
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/config-vars"
        self._check(self._session.patch(url, json={"env_vars": remaining}))

    def create_volume(self, name: str, target: str) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/volumes"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        logger.info("Creating volume name=%r target=%r", name, target)
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/volumes"
        return self._check(self._session.post(url, json={"name": name, "container_path": target}))

    def trigger_deploy(self) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/deploy"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        logger.info("Triggering deployment for app_id=%s", app_id)
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/deploy"
        return self._check(self._session.post(url))

    def get_latest_deployment(self) -> dict:
        """GET /api/team/{team_path}/applications/{app_id}/deployments/latest"""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/deployments/latest"
        return self._check(self._session.get(url))

    def list_domains(self) -> list[str]:
        """GET /api/team/{team_path}/applications/{app_id}/domains — returns domain strings."""
        team_path = self._require_team_path()
        app_id = self._require_app_id()
        url = f"{BASE_URL}/api/team/{team_path}/applications/{app_id}/domains"
        result = self._check(self._session.get(url))
        if isinstance(result, list):
            return [entry["domain"] for entry in result if entry.get("domain")]
        return []
