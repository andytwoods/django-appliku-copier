"""YAML validity tests — appliku.yml must parse cleanly for every combination."""
import yaml
import pytest

from tests.conftest import MATRIX


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_parses(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    content = (dest / "appliku.yml").read_text()
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict), "appliku.yml must parse to a dict"
    assert "build_settings" in parsed
    assert "services" in parsed
    assert "databases" in parsed


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_db_type(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    parsed = yaml.safe_load((dest / "appliku.yml").read_text())
    db_type = overrides.get("db_type", "postgresql_17")
    assert parsed["databases"]["db"]["type"] == db_type


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_web_service(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    parsed = yaml.safe_load((dest / "appliku.yml").read_text())
    assert "web" in parsed["services"]
    assert parsed["services"]["web"]["command"] == "bash run.sh"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_worker_service(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    parsed = yaml.safe_load((dest / "appliku.yml").read_text())
    if expect_worker:
        assert "worker" in parsed["services"]
    else:
        assert "worker" not in parsed["services"]


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_beat_service(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    parsed = yaml.safe_load((dest / "appliku.yml").read_text())
    if expect_beat:
        assert "beat" in parsed["services"]
    else:
        assert "beat" not in parsed["services"]
