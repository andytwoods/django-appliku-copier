"""Snapshot tests for all template combinations from the OVERVIEW matrix."""
import pytest

from tests.conftest import MATRIX

ALWAYS_PRESENT = ["appliku.yml", "Dockerfile", "run.sh", "release.sh"]
WORKER_SCRIPT = "celery-worker.sh"
BEAT_SCRIPT = "celery-beat.sh"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_required_files_present(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    for filename in ALWAYS_PRESENT:
        assert (dest / filename).exists(), f"Missing required file: {filename}"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_worker_script_presence(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    if expect_worker:
        assert (dest / WORKER_SCRIPT).exists(), "celery-worker.sh should exist"
    else:
        assert not (dest / WORKER_SCRIPT).exists(), "celery-worker.sh should not exist"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_beat_script_presence(render, overrides, expect_worker, expect_beat):
    dest = render(overrides)
    if expect_beat:
        assert (dest / BEAT_SCRIPT).exists(), "celery-beat.sh should exist"
    else:
        assert not (dest / BEAT_SCRIPT).exists(), "celery-beat.sh should not exist"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_worker_shebang(render, overrides, expect_worker, expect_beat):
    if not expect_worker:
        pytest.skip("no worker script in this combination")
    dest = render(overrides)
    first_line = (dest / WORKER_SCRIPT).read_text().splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", "Shebang must be on line 1"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_beat_shebang(render, overrides, expect_worker, expect_beat):
    if not expect_beat:
        pytest.skip("no beat script in this combination")
    dest = render(overrides)
    first_line = (dest / BEAT_SCRIPT).read_text().splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", "Shebang must be on line 1"


def test_dockerfile_uv(render):
    dest = render({"package_manager": "uv"})
    content = (dest / "Dockerfile").read_text()
    assert "uv sync --frozen --no-dev" in content
    assert "pyproject.toml" in content
    assert "requirements.txt" not in content


def test_dockerfile_pip(render):
    dest = render({"package_manager": "pip"})
    content = (dest / "Dockerfile").read_text()
    assert "pip install" in content
    assert "requirements.txt" in content
    assert "uv sync" not in content


def test_run_sh_gunicorn(render):
    dest = render({"web_server": "gunicorn"})
    content = (dest / "run.sh").read_text()
    assert "gunicorn" in content
    assert "uvicorn" not in content
    assert content.splitlines()[0] == "#!/usr/bin/env bash"


def test_run_sh_uvicorn(render):
    dest = render({"web_server": "uvicorn"})
    content = (dest / "run.sh").read_text()
    assert "uvicorn" in content
    assert "gunicorn" not in content
    assert "asgi" in content
    assert content.splitlines()[0] == "#!/usr/bin/env bash"


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_appliku_yml_snapshot(render, overrides, expect_worker, expect_beat, snapshot):
    dest = render(overrides)
    content = (dest / "appliku.yml").read_text()
    snapshot.assert_match(content, "appliku.yml")


@pytest.mark.parametrize("overrides,expect_worker,expect_beat", MATRIX)
def test_dockerfile_snapshot(render, overrides, expect_worker, expect_beat, snapshot):
    dest = render(overrides)
    content = (dest / "Dockerfile").read_text()
    snapshot.assert_match(content, "Dockerfile")
