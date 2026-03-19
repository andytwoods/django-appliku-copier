"""Tests for appliku_cli.api using responses mock library."""
import pytest
import responses as responses_lib

from appliku_cli.api import ApplikuAPIError, ApplikuClient

TEAM = "my-team"
APP_ID = 42
API_KEY = "testkey"
BASE = "https://api.appliku.com"


@pytest.fixture()
def client():
    return ApplikuClient(api_key=API_KEY, team_path=TEAM, app_id=APP_ID)


@responses_lib.activate
def test_create_datastore_success(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/datastores"
    responses_lib.add(responses_lib.POST, url, json={"id": 1, "name": "db"}, status=201)
    result = client.create_datastore(name="db", store_type="postgresql_17")
    assert result["id"] == 1
    assert responses_lib.calls[0].request.method == "POST"
    import json
    body = json.loads(responses_lib.calls[0].request.body)
    assert body["store_type"] == "postgresql_17"
    assert body["is_default"] is True


@responses_lib.activate
def test_create_datastore_error(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/datastores"
    responses_lib.add(responses_lib.POST, url, json={"detail": "not found"}, status=404)
    with pytest.raises(ApplikuAPIError) as exc_info:
        client.create_datastore(name="db", store_type="postgresql_17")
    assert exc_info.value.status_code == 404


@responses_lib.activate
def test_set_config_vars_success(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/config-vars"
    responses_lib.add(responses_lib.PATCH, url, json={}, status=200)
    client.set_config_vars({"SECRET_KEY": "abc123"})
    import json
    body = json.loads(responses_lib.calls[0].request.body)
    assert body["SECRET_KEY"] == "abc123"


@responses_lib.activate
def test_set_config_vars_error(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/config-vars"
    responses_lib.add(responses_lib.PATCH, url, body="forbidden", status=403)
    with pytest.raises(ApplikuAPIError) as exc_info:
        client.set_config_vars({"SECRET_KEY": "abc"})
    assert exc_info.value.status_code == 403


@responses_lib.activate
def test_create_volume_success(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/volumes"
    responses_lib.add(responses_lib.POST, url, json={"id": 5}, status=201)
    result = client.create_volume(name="media", target="/app/media/")
    assert result["id"] == 5
    import json
    body = json.loads(responses_lib.calls[0].request.body)
    assert body["target"] == "/app/media/"


@responses_lib.activate
def test_trigger_deploy_success(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/deploy"
    responses_lib.add(responses_lib.POST, url, json={"id": 99}, status=200)
    result = client.trigger_deploy()
    assert result["id"] == 99


@responses_lib.activate
def test_trigger_deploy_no_json_body(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/deploy"
    responses_lib.add(responses_lib.POST, url, body="", status=200)
    result = client.trigger_deploy()
    assert result == {}


@responses_lib.activate
def test_api_error_message_contains_status_and_body(client):
    url = f"{BASE}/api/team/{TEAM}/applications/{APP_ID}/datastores"
    responses_lib.add(responses_lib.POST, url, body="server error", status=500)
    with pytest.raises(ApplikuAPIError) as exc_info:
        client.create_datastore(name="db", store_type="postgresql_17")
    assert "500" in str(exc_info.value)
    assert "server error" in str(exc_info.value)
