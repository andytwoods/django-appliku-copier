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
    def __init__(self, api_key: str, team_path: str, app_id: int) -> None:
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

    def create_datastore(self, name: str, store_type: str) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/datastores"""
        logger.info("Creating datastore name=%r store_type=%r", name, store_type)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{self._app_id}/datastores"
        return self._check(self._session.post(url, json={
            "name": name,
            "store_type": store_type,
            "is_default": True,
        }))

    def set_config_vars(self, vars: dict[str, str]) -> None:
        """PATCH /api/team/{team_path}/applications/{app_id}/config-vars"""
        logger.info("Setting config vars: %s", list(vars.keys()))
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{self._app_id}/config-vars"
        self._check(self._session.patch(url, json=vars))

    def create_volume(self, name: str, target: str) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/volumes"""
        logger.info("Creating volume name=%r target=%r", name, target)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{self._app_id}/volumes"
        return self._check(self._session.post(url, json={"name": name, "target": target}))

    def trigger_deploy(self) -> dict:
        """POST /api/team/{team_path}/applications/{app_id}/deploy"""
        logger.info("Triggering deployment for app_id=%s", self._app_id)
        url = f"{BASE_URL}/api/team/{self._team_path}/applications/{self._app_id}/deploy"
        return self._check(self._session.post(url))
