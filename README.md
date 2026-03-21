# Django Appliku

Adds Appliku deployment files to an existing Django project and provisions
everything on the platform — databases, queues, config vars, and a first deploy.

---

## What it does

**Step 1 — generate deployment files** (via [Copier](https://copier.readthedocs.io/)):

- `Dockerfile`
- `appliku.yml`
- `run.sh` (starts gunicorn)
- `release.sh` (runs migrations + collectstatic)
- `celery-worker.sh` and `celery-beat.sh` (if you use Celery/Huey)

**Step 2 — provision Appliku** (via the `appliku-setup` CLI):

- Creates the app on Appliku, linked to your GitHub/GitLab repo
- Provisions your database (Postgres, PostGIS, pgvector, TimescaleDB, MySQL)
- Provisions Redis or RabbitMQ (if you use Celery or Huey)
- Creates a persistent volume for media files (if needed)
- Generates a `SECRET_KEY` and pushes all config vars
- Triggers the first deployment

---

## Prerequisites

- Python 3.11+
- [Copier](https://copier.readthedocs.io/) 9.0+
- An existing Django project with `gunicorn` and `whitenoise` installed
- An [Appliku](https://appliku.com) account with your repo connected under
  **Settings → Git Integrations**

Install Copier:

```bash
pip install copier
# or with uv: uv tool install copier
```

---

## Step 1 — apply the template

Run this inside your existing Django project directory:

```bash
cd /path/to/your/django/project
copier copy gh:andytwoods/djangoappliku . --trust
```

Copier will ask a series of questions:

| Question | Options | Default |
|---|---|---|
| Project name | any string | — |
| Project slug | Python module name (e.g. `my_app`) | derived from name |
| Python version | e.g. `3.12` | `3.12` |
| Database type | `postgresql_17/16/15/18`, `postgis_16_34`, `postgresql_16_pgvector`, `timescale_db_17`, `mysql_8` | `postgresql_17` |
| Task runner | `none`, `celery`, `huey` | `none` |
| Celery broker | `redis`, `rabbitmq` | `redis` *(if Celery selected)* |
| Redis version | `8`, `7`, `6` | `8` *(if Redis needed)* |
| Celery beat? | yes/no | `no` *(if Celery selected)* |
| Media storage | `none`, `s3_compatible`, `volume` | `none` |
| Email backend | `console`, `smtp`, `sendgrid`, `mailgun`, `ses` | `console` |
| Sentry? | yes/no | `no` |

After answering, the deployment files are written to your project directory.
Commit them to git.

---

## Step 2 — provision Appliku

Install this package:

```bash
pip install djangoappliku
# or with uv: uv add djangoappliku
```

Then run from your Django project directory:

```bash
appliku-setup
```

On the first run it will:

1. Ask for your **Appliku API key** (find it under Appliku → Account → API Keys)
2. Auto-discover your team (or let you pick if you have multiple)
3. Ask whether to link an existing Appliku app or create a new one
   - **Create new**: detects your git remote, validates it against Appliku, lets you pick a cluster, and creates the app
   - **Use existing**: enter the app ID shown in the Appliku dashboard URL
4. Provision all resources based on your Copier answers (database, Redis, etc.)
5. Push config vars and trigger the first deploy

Credentials are saved to `.env.appliku` in your project root (gitignored automatically).
Re-running `appliku-setup` later is safe — it skips anything already configured.

---

## Django project requirements

The template does not touch your Django source files. You need to have these
in place before deploying:

**Packages** (`requirements.txt`):

```
gunicorn
whitenoise
psycopg2-binary        # or psycopg[binary]
django-environ         # or dj-database-url
```

Additional packages depending on your choices:

| Choice | Add to requirements.txt |
|---|---|
| Celery + Redis | `celery redis` |
| Celery + RabbitMQ | `celery pika` |
| Huey | `huey redis` |
| S3 media storage | `django-storages boto3` |
| Sentry | `sentry-sdk` |

**Settings** — `settings.py` must read from environment variables:

```python
import os

SECRET_KEY = os.environ["SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
# DATABASE_URL is written automatically by Appliku when a database is attached
# REDIS_URL is written automatically when a Redis datastore is attached
```

`STATIC_ROOT` must be set and `whitenoise.middleware.WhiteNoiseMiddleware` must
be in `MIDDLEWARE`.

**Health check endpoint** — Appliku uses this to verify deployments succeeded:

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

When a new version of this template is released, update your generated files with:

```bash
cd /path/to/your/django/project
copier update --trust
```

Copier shows a diff and lets you review changes before applying them.

---

## Repository layout

```
template/           Copier template (.jinja files + copier.yml)
example/
  demo_project/     Minimal Django project with generated files applied
appliku_cli/        CLI source (credentials, API client, provisioning)
scripts/
  regenerate_example.py   Re-apply template to example project
reference/          Hand-written reference files (ground truth, not deployed)
tests/              Snapshot tests, YAML validation, Django check
```

---

## Credentials file

`appliku-setup` reads and writes `.env.appliku` in your project root:

```ini
APPLIKU_API_KEY=your-api-key
APPLIKU_TEAM_PATH=your-team-slug   # discovered automatically on first run
APPLIKU_APP_ID=12345               # set on first run
```

This file is added to `.gitignore` automatically. Never commit it.

---

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Regenerate the example project
python scripts/regenerate_example.py

# Run all tests
uv run --group dev pytest
```
