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
    def __init__(self, api_key: str, team_path: str, app_id: int | None = None) -> None:
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

    # ── Team-level (no app_id needed) ─────────────────────────────────────────

    def list_clusters(self) -> list[dict]:
        """GET /api/team/{team_path}/clusters"""
        logger.info("Listing clusters for team %r", self._team_path)
        url = f"{BASE_URL}/api/team/{self._team_path}/clusters"
        return self._check(self._session.get(url))

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
        cluster_id: int,
        repository_provider: str,
        repository_name: str | None = None,
        gitlab_repository_id: int | None = None,
        custom_git_url: str | None = None,
    ) -> dict:
        """POST /api/team/{team_path}/applications/create/"""
        logger.info("Creating app name=%r branch=%r cluster=%s", name, branch, cluster_id)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/create/"
        payload: dict = {
            "name": name,
            "branch": branch,
            "cluster": cluster_id,
            "build_pack": "dockerfile",
            "yml_config_file_path": "appliku.yml",
            "repository_provider": repository_provider,
        }
        if repository_name is not None:
            payload["repository_name"] = repository_name
        if gitlab_repository_id is not None:
            payload["gitlab_repository_id"] = gitlab_repository_id
        if custom_git_url is not None:
            payload["custom_git_url"] = custom_git_url
        return self._check(self._session.post(url, json=payload))

    # ── App-level (app_id required) ───────────────────────────────────────────

    def create_datastore(self, name: str, store_type: str) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/datastores"""
        app_id = self._require_app_id()
        logger.info("Creating datastore name=%r store_type=%r", name, store_type)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{app_id}/datastores"
        return self._check(self._session.post(url, json={
            "name": name,
            "store_type": store_type,
            "is_default": True,
        }))

    def set_config_vars(self, vars: dict[str, str]) -> None:
        """PATCH /api/team/{team_path}/applications/{app_id}/config-vars"""
        app_id = self._require_app_id()
        logger.info("Setting config vars: %s", list(vars.keys()))
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{app_id}/config-vars"
        self._check(self._session.patch(url, json=vars))

    def create_volume(self, name: str, target: str) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/volumes"""
        app_id = self._require_app_id()
        logger.info("Creating volume name=%r target=%r", name, target)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{app_id}/volumes"
        return self._check(self._session.post(url, json={"name": name, "target": target}))

    def trigger_deploy(self) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/deploy"""
        app_id = self._require_app_id()
        logger.info("Triggering deployment for app_id=%s", app_id)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{app_id}/deploy"
        return self._check(self._session.post(url))
