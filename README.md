# Django Appliku

Adds Appliku deployment files to an existing Django project, then provisions
everything on the platform for you.

---

## How it works

There are two separate steps:

**Step 1 — `copier copy`** generates deployment files for your project:
`Dockerfile`, `appliku.yml`, `run.sh`, `release.sh`, and optionally
`celery-worker.sh` / `celery-beat.sh`. You commit these files to git.

**Step 2 — `appliku-setup`** connects to Appliku and does the one-time setup:
creates the app, provisions databases and queues, pushes config vars,
and triggers the first deploy.

---

## Prerequisites

- Python 3.11+
- [Copier](https://copier.readthedocs.io/) 9.0+
- An existing Django project with `gunicorn` and `whitenoise` installed
- An [Appliku](https://appliku.com) account with your GitHub or GitLab repo
  connected under **Settings → Git Integrations**

Install Copier if you don't have it:

```bash
pip install copier
# or: uv tool install copier
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
| Python version | e.g. `3.12` | `3.12` |
| Database | `postgresql_17/16/15/18`, `postgis_16_34`, `postgresql_16_pgvector`, `timescale_db_17`, `mysql_8` | `postgresql_17` |
| Task runner | `none`, `celery`, `huey` | `none` |
| Celery broker | `redis`, `rabbitmq` | `redis` *(if Celery)* |
| Redis version | `8`, `7`, `6` | `8` *(if Redis needed)* |
| Celery beat? | yes/no | `no` *(if Celery)* |
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
pip install djangoappliku
# or: uv add djangoappliku
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

**Packages** (`requirements.txt`):

```
gunicorn
whitenoise
psycopg2-binary
django-environ        # or dj-database-url
```

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

To regenerate the example project after changing templates:

```bash
python scripts/regenerate_example.py
uv run --group dev pytest
```
