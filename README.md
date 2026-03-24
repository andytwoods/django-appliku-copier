# Django Appliku

Adds Appliku deployment files to an existing Django project, then provisions
everything on the platform for you.

---

## How it works

There are two separate steps:

**Step 1 — `copier copy`** asks you about your project's infrastructure needs
(database variant, task runner, media storage, etc.) and generates deployment
files tailored to your answers: `Dockerfile`, `appliku.yml`, `run.sh`,
`release.sh`, and optionally a worker script (`worker.sh` for Celery/Huey,
`celery-beat.sh` for Celery beat).
You commit these files to git.

**Step 2 — `appliku-setup`** connects to Appliku and does the one-time setup:
creates the app, provisions databases and queues, pushes config vars,
and triggers the first deploy.

---

## Prerequisites

- Python 3.11+
- [Copier](https://copier.readthedocs.io/) 9.0+
- An existing Django project
- An [Appliku](https://appliku.com) account with your GitHub or GitLab repo
  connected under **Settings → Git Integrations**

Install Copier if you don't have it:

```bash
uv tool install copier
# or: pip install copier
```

---

## Step 1 — generate deployment files

Run inside your Django project directory:

```bash
copier copy gh:andytwoods/djangoappliku . --trust
```

Copier asks a series of questions:

| Question | Options | Default |
|---|---|---|
| Project name | any string | — |
| Project slug | Python module name (e.g. `my_app`) | derived from name |
| Python version | e.g. `3.13` | `3.13` |
| Package manager | `uv`, `pip` | `uv` |
| Web server | `gunicorn`, `uvicorn` | `gunicorn` |
| Database | `postgresql_17/16/15/18`, `postgis_16_34`, `postgresql_16_pgvector`, `timescale_db_17`, `mysql_8` | `postgresql_17` |
| Task runner | `none`, `celery`, `huey` | `none` |
| Celery broker | `redis`, `rabbitmq` | `redis` *(if Celery)* |
| Redis version | `8`, `7`, `6` | `8` *(if Redis needed)* |
| Celery beat? | yes/no | `no` *(if Celery — Huey has a built-in scheduler)* |
| Media storage | `none`, `s3_compatible`, `volume` | `none` |
| Email backend | `console`, `smtp`, `sendgrid`, `mailgun`, `ses` | `console` |
| Sentry? | yes/no | `no` |

After answering, commit the generated files before moving on:

```bash
git add .
git commit -m "Add Appliku deployment files"
```

---

## Step 2 — provision Appliku

Install this package:

```bash
uv add djangoappliku
# or: pip install djangoappliku
```

If the package is not yet on PyPI, install directly from GitHub:

```bash
uv add git+https://github.com/andytwoods/django-appliku-copier.git
# or: pip install git+https://github.com/andytwoods/django-appliku-copier.git
```

Run from your Django project directory:

```bash
appliku-setup
```

On first run it will:

1. Check `.env.appliku` for your **API key** — if missing, it will ask for it
   and save it to `.env.appliku` (which is gitignored automatically).
   Find your key at: **Appliku → Account → API Keys**
2. Detect your Appliku team automatically (or let you pick if you have several)
3. Ask whether to link an existing app or create a new one:
   - **New app**: detects your git remote, validates it against Appliku,
     lets you pick a cluster, creates the app
   - **Existing app**: enter the app ID from your Appliku dashboard URL
4. Provision your database, Redis, RabbitMQ, or media volume as configured
5. Generate a `SECRET_KEY`, push all config vars to Appliku
6. Trigger the first deployment

Re-running `appliku-setup` is safe — it reads `.env.appliku` and skips
anything already configured.

---

## Django project requirements

The template does not touch your Django source files. You need these in place
before deploying.

**Packages** — add to `pyproject.toml` (uv) or `requirements.txt` (pip):

```
psycopg2-binary
django-environ        # or dj-database-url
gunicorn              # if you chose gunicorn (default)
uvicorn               # if you chose uvicorn
```

The generated `release.sh` runs `collectstatic`. If you use
[whitenoise](https://whitenoise.readthedocs.io/) for static files (recommended
for simplicity), add it to your requirements and middleware. If you serve
static files another way (S3, CDN, etc.), ignore the whitenoise references.

Add these based on your choices:

| Choice | Extra packages |
|---|---|
| Celery + Redis | `celery redis` |
| Celery + RabbitMQ | `celery pika` |
| Huey | `huey redis` |
| S3 media | `django-storages boto3` |
| Sentry | `sentry-sdk` |

**Settings** (`settings.py`) must read from environment variables:

```python
import os

SECRET_KEY = os.environ["SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
# DATABASE_URL — written automatically by Appliku when a database is attached
# REDIS_URL    — written automatically when a Redis datastore is attached
```

`STATIC_ROOT` must be set and `whitenoise.middleware.WhiteNoiseMiddleware`
must be in `MIDDLEWARE`.

**Health check endpoint** — Appliku uses this to verify deployments:

```python
# urls.py
from django.http import HttpResponse
urlpatterns = [
    path("health", lambda r: HttpResponse("ok")),
    ...
]
```

---

## Updating deployment files later

When a new version of this template is released, pull the changes into your
project:

```bash
copier update --trust
```

Copier shows a diff and lets you review before applying. This is why we use
Copier instead of a one-shot generator.

---

## The `.env.appliku` file

`appliku-setup` stores credentials in `.env.appliku` in your project root:

```ini
APPLIKU_API_KEY=your-api-key
APPLIKU_TEAM_PATH=your-team-slug   # discovered automatically
APPLIKU_APP_ID=12345               # set on first run
```

This file is added to `.gitignore` automatically. **Never commit it.**

---

## Repository layout

```
template/           Copier template (.jinja files + copier.yml)
example/
  demo_project/     Minimal Django app with the template already applied
appliku_cli/        CLI source (credentials, API client, provisioning)
scripts/
  regenerate_example.py   Re-apply the template to the example project
reference/          Hand-written reference files (ground truth, not deployed)
tests/              Snapshot tests, YAML validation, Django check
```

---

## Contributing / developing this package

### Setup

```bash
git clone https://github.com/andytwoods/djangoappliku
cd djangoappliku
uv sync --group dev
```

### Running the tests

```bash
uv run --group dev pytest
```

The test suite has three layers:

**Template tests** (`tests/test_snapshots.py`, `tests/test_yaml.py`) — run
`copier copy` for each combination in the test matrix and verify the output.
These cover all 9 combinations of database, task runner, storage, and email
options defined in `OVERVIEW.md`:

```bash
uv run --group dev pytest tests/test_snapshots.py tests/test_yaml.py -v
```

**Django check** (`tests/test_django_check.py`) — runs `manage.py check` on
the committed example project to verify the generated files produce a valid
Django configuration:

```bash
uv run --group dev pytest tests/test_django_check.py -v
```

**CLI tests** (`tests/test_cli/`) — unit tests for the `appliku-setup` command:
credentials loading, API client, git remote detection, team/app resolution,
and provisioning logic. All HTTP calls are mocked:

```bash
uv run --group dev pytest tests/test_cli/ -v
```

### Changing a template

1. Edit the relevant `.jinja` file in `template/`
2. Regenerate the example project to see the result:
   ```bash
   python scripts/regenerate_example.py
   ```
3. Inspect the diff on the generated files in `example/demo_project/`
4. Run the full test suite:
   ```bash
   uv run --group dev pytest
   ```
5. If `appliku.yml` snapshots need updating (expected change):
   ```bash
   uv run --group dev pytest tests/test_snapshots.py --snapshot-update
   ```

### Trying the Copier template interactively

Run `copier copy` with `--overwrite` from the example project to re-answer
all questions and regenerate the files in place:

```bash
cd example/demo_project
copier copy ../../template . --overwrite --trust
```

This prompts for every question fresh and overwrites the generated files —
no need to delete `.copier-answers.yml` first. Useful for checking how the
generated output looks for different combinations of answers.

> **Note:** `.copier-answers.yml` will **not** be updated by this command.
> Copier only writes that file when the template has a git version tag; a local
> path has none. This is fine for template testing — you care about the
> generated files (Dockerfile, appliku.yml, worker.sh …), not the answers
> record. To reset the example project back to its committed baseline, run:
> ```bash
> python scripts/regenerate_example.py
> ```

### Testing `appliku-setup` against a real Appliku account

Install the package in editable mode:

```bash
uv pip install -e .
# or: pip install -e .
```

Then run it from inside the included example project (which already has
`.copier-answers.yml` and all generated files in place):

```bash
cd example/demo_project
appliku-setup
```

It will prompt for your API key on first run and save it to `.env.appliku`.
To reset and start fresh, delete `.env.appliku`.

### Adding a new Copier question

1. Add the variable to `template/copier.yml` with a `when:` condition if needed
2. Update the relevant `.jinja` templates to use it
3. Add the variable to `BASE_DATA` in `tests/conftest.py`
4. Add a test case to the matrix in `tests/conftest.py` if it affects generated output
5. Update the README table in the "Step 1" section

## License

MIT — see [LICENSE](LICENSE).

## Attribution

Some template files were adapted from [SpeedPy](https://github.com/speedpy/speedpy).
