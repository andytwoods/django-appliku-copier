# OVERVIEW

## Goal

Build a reusable Copier-based scaffold that adds Appliku deployment boilerplate to an **existing** Django repository, while allowing those generated files to receive future template updates.

The system generates:

- `appliku.yml`
- `Dockerfile`
- `run.sh`
- `release.sh`
- optional service scripts:
  - `worker.sh`
  - `celery-beat.sh`

This scaffold is specifically for **Django deployments on Appliku**. It does not create a new Django project — it adds deployment infrastructure to one that already exists.

---

## Core Product Decision

Use **Copier**, not Cookiecutter.

### Why Copier

Generated files must support future updates via:

```bash
copier update
```

This is critical because deployment infrastructure evolves over time:

- `appliku.yml` structure
- Docker patterns
- release/start scripts
- worker/beat setup
- security improvements

Cookiecutter does not support this lifecycle cleanly.

---

## Scope

### Phase 1 – scaffold/template

Add a **small, opinionated set of deployment files** to an existing Django project.

Supported features:

- Django (existing project)
- Postgres / PostGIS / pgvector / TimescaleDB (choice)
- Redis (optional, driven by task runner choice)
- Celery or Huey task runner (optional)
- Celery beat scheduler (optional)
- Media file storage: local volume or S3-compatible (optional)
- Email backend configuration (optional)
- Sentry error tracking (optional)

The template does not touch Django source files.

### Phase 2 – optional automation (later)

- Appliku API integration
- CLI tooling
- Postgres/PostGIS/pgvector datastore provisioning
- Redis or RabbitMQ datastore provisioning (when task runner selected)
- Media storage volume provisioning (when `media_storage == "volume"`)
- `SECRET_KEY` generation and push to Appliku config-vars
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` push to config-vars
- Storage/email/Sentry env vars push to config-vars
- First deployment trigger
- Domain setup

---

## Architecture

Use a hybrid structure:

- Copier template → scaffolding (deployment files only)
- standalone Python CLI → platform/API automation (Phase 2)

### Rule

Do NOT make this primarily a Django package.

Reason:

- bootstrap happens before Django runs
- deployment ≠ Django runtime
- API interaction belongs in CLI layer

---

## Repository Structure

```text
template/
  copier.yml
  appliku.yml.jinja
  Dockerfile.jinja
  run.sh.jinja
  release.sh.jinja
  worker.sh.jinja   (conditional)
  celery-beat.sh.jinja     (conditional)

example/
  demo_project/            (existing Django project with generated files applied)

scripts/
  regenerate_example.py

tests/
```

### Rules

- Template MUST NOT generate or modify any Django source files
- Example project MUST be committed
- Example MUST be regeneratable

---

## Template Variables (copier.yml)

```yaml
project_name:    str
project_slug:    str
python_version:  str                        # e.g. "3.12"

# Database — selects store_type for Appliku datastore provisioning
db_type:         ["postgresql_18", "postgresql_17", "postgresql_16", "postgresql_15",
                  "postgis_16_34", "postgresql_16_pgvector",
                  "timescale_db_17", "mysql_8"]   # default "postgresql_17"

# Task runner
task_runner:     ["none", "celery", "huey"]       # default "none"

# Celery broker — asked only if task_runner == "celery"
celery_broker:   ["redis", "rabbitmq"]            # default "redis"

# Redis version — asked only if task_runner != "none" or celery_broker == "redis"
redis_version:   ["8", "7", "6"]                  # default "8"

# Beat scheduler — asked only if task_runner == "celery" (Huey has built-in scheduler)
use_beat:        bool                             # default false

# Media file storage
media_storage:   ["none", "s3_compatible", "volume"]  # default "none"

# Email backend
email_backend:   ["console", "smtp", "sendgrid", "mailgun", "ses"]  # default "console"

# Error tracking
use_sentry:      bool                             # default false
```

### Conditional question logic

| Variable | Shown when |
|---|---|
| `celery_broker` | `task_runner == "celery"` |
| `redis_version` | `task_runner != "none"` AND (`task_runner == "huey"` OR `celery_broker == "redis"`) |
| `use_beat` | `task_runner == "celery"` (Huey has a built-in scheduler, no separate beat process) |

`python_version` and env tooling details are owned by the existing project. `db_type` and `redis_version` drive Appliku datastore provisioning in Phase 2.

A `Dockerfile` is always generated.

### Rule

Templates MUST conditionally render:

- `appliku.yml` sections (datastores, worker/beat processes)
- scripts (`worker.sh`, `celery-beat.sh`)

based strictly on these variables.

---

## Generated Files (MVP)

Always generated:

- `appliku.yml`
- `Dockerfile`
- `run.sh`
- `release.sh`

Generated only when flag is set:

- `worker.sh` (if `task_runner != "none"`)
- `celery-beat.sh` (if `use_beat`)

---

## Development Workflow

The repo contains a small committed Django project (`example/demo_project/`) used to validate the templates during development.

**Loop:**

1. Edit a template in `template/`
2. Run `python scripts/regenerate_example.py` — wipes generated files, re-runs `copier copy`
3. Inspect the diff on the generated files
4. Run `cd example/demo_project && python manage.py check`
5. Optionally deploy to Appliku to verify a real deploy

The Django app in `example/demo_project/` is **static** — written once and committed. Only the generated deployment files are wiped and recreated by the regeneration script.

---

## Example Django App

The app in `example/demo_project/` must be a real, minimal working Django project. It is maintained by hand (not generated by Copier).

### Required files

```
example/demo_project/
  manage.py
  requirements.txt
  config/
    settings.py
    urls.py
    wsgi.py
    asgi.py
  app/
    views.py
    urls.py
    apps.py
```

### Required endpoint

`/health` → returns `200 OK` with body `"ok"`

Used by Appliku for health checks.

### Required dependencies (in requirements.txt)

- `django`
- `gunicorn`
- `whitenoise`
- `dj-database-url` or `django-environ` (project owner's choice)
- `psycopg2-binary`
- `celery` and `redis` (if `task_runner == "celery"` and `celery_broker == "redis"`)
- `celery` and `pika` (if `task_runner == "celery"` and `celery_broker == "rabbitmq"`)
- `huey` and `redis` (if `task_runner == "huey"`)
- `django-storages` and `boto3` (if `media_storage == "s3_compatible"`)
- `sentry-sdk` (if `use_sentry`)

### Settings requirements

`config/settings.py` must read from environment variables:

```python
SECRET_KEY    = os.environ["SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
# DATABASE_URL  → parsed via dj-database-url or django-environ
# REDIS_URL     → parsed if task runner enabled
# AWS_*         → parsed if media_storage == "s3_compatible"
# SENTRY_DSN    → parsed if use_sentry
```

`STATIC_ROOT` must be set and whitenoise must be added to `MIDDLEWARE`.

### Rule

The example app must pass `manage.py check` with no errors after the generated files are applied.

---

## Requirements on the Existing Django Project

The target project must expose:

- `/health` → returns `"ok"` (used by Appliku for health checks)

The template assumes:

- `gunicorn` is (or will be) in the project's dependencies
- `whitenoise` is (or will be) in the project's dependencies
- environment variables `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`, and (if Redis) `REDIS_URL` are sourced from the environment at runtime

The template does not install or configure these — it is the project owner's responsibility.

---

## Deployment Requirements

### WSGI

`run.sh` uses:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers $WEB_CONCURRENCY
```

`WEB_CONCURRENCY` is set as an Appliku config var, allowing worker count to be tuned without regenerating files.

### Static files

Template assumes whitenoise is configured in the existing project's settings.

### Media files

| `media_storage` | Approach |
|---|---|
| `none` | No media storage configured |
| `s3_compatible` | `django-storages` + env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL` |
| `volume` | Appliku persistent volume mounted at `/app/media`; only suitable for single web process |

### Environment variables

| Variable | When required |
|---|---|
| `SECRET_KEY` | always |
| `DATABASE_URL` | always |
| `ALLOWED_HOSTS` | always |
| `CSRF_TRUSTED_ORIGINS` | always |
| `REDIS_URL` | `task_runner != "none"` |
| `WEB_CONCURRENCY` | always (gunicorn workers) |
| `AWS_*` | `media_storage == "s3_compatible"` |
| `SENTRY_DSN` | `use_sentry` |
| `EMAIL_*` | `email_backend != "console"` |

---

## Credentials Storage

Appliku credentials are stored in `.env.appliku` in the project root. This file is added to `.gitignore` automatically by the Phase 2 CLI on first run.

```ini
APPLIKU_API_KEY=
APPLIKU_TEAM_PATH=
APPLIKU_APP_ID=
```

The Phase 2 CLI reads this file before making any API calls. If it does not exist, the CLI prompts for the values and writes them.

`.env.appliku` must never be committed to version control.

---

## Appliku Automation (Phase 2)

The Phase 2 CLI uses the Appliku API (`Authorization: Token <api_key>`) to automate setup after `copier copy` runs.

### Datastore provisioning

All datastores are created via:

```
POST /api/team/{team_path}/applications/{application_id}/datastores
{"name": "<name>", "store_type": "<store_type_enum>", "is_default": true}
```

Setting `is_default: true` causes Appliku to automatically write the connection URL as a config var (`DATABASE_URL`, `REDIS_URL`, etc.).

| Variable | `store_type` value | When |
|---|---|---|
| `db_type` value | e.g. `postgresql_17`, `postgis_16_34`, `postgresql_16_pgvector` | always |
| Redis | `redis_7`, `redis_8`, etc. | `task_runner != "none"` AND broker is Redis |
| RabbitMQ | `rabbitmq` | `task_runner == "celery"` AND `celery_broker == "rabbitmq"` |
| Volume | via volumes API | `media_storage == "volume"` |

### Config vars pushed by CLI

```
PATCH /api/team/{team_path}/applications/{id}/config-vars
```

| Var | Source |
|---|---|
| `SECRET_KEY` | `secrets.token_urlsafe(50)` |
| `ALLOWED_HOSTS` | domain entered by user |
| `CSRF_TRUSTED_ORIGINS` | derived from domain |
| `WEB_CONCURRENCY` | default `2`, user can override |
| `AWS_*` | entered by user (if `media_storage == "s3_compatible"`) |
| `SENTRY_DSN` | entered by user (if `use_sentry`) |
| `EMAIL_*` | entered by user (if `email_backend != "console"`) |

### Full Phase 2 setup sequence

1. Read `.env.appliku` (prompt and write if missing)
2. Provision database datastore (`db_type`)
3. If `task_runner != "none"` and broker is Redis: provision Redis datastore
4. If `task_runner == "celery"` and `celery_broker == "rabbitmq"`: provision RabbitMQ
5. If `media_storage == "volume"`: provision volume
6. Generate and push `SECRET_KEY`
7. Prompt for domain, push `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
8. Push `WEB_CONCURRENCY` (default `2`)
9. If applicable: prompt for and push storage / email / Sentry vars
10. Trigger first deployment via `POST .../deploy`

---

## Bash Script Rules

All `.sh` files must begin with:

```bash
#!/usr/bin/env bash
set -e
```

Keep scripts simple.

---

## Testing Strategy

### A. Snapshot tests

Test the following combinations:

| `db_type` | `task_runner` | `celery_broker` | `use_beat` | `media_storage` | Notes |
|---|---|---|---|---|---|
| `postgresql_17` | none | — | false | none | baseline |
| `postgresql_17` | celery | redis | false | none | +Celery/Redis |
| `postgresql_17` | celery | redis | true | none | +Celery beat |
| `postgresql_17` | celery | rabbitmq | false | none | +RabbitMQ |
| `postgresql_17` | celery | rabbitmq | true | none | +RabbitMQ beat |
| `postgis_16_34` | none | — | false | none | +PostGIS |
| `postgresql_17` | huey | redis | false | none | +Huey (no beat — built-in) |
| `postgresql_17` | none | — | false | s3_compatible | +S3 storage |
| `postgresql_17` | celery | redis | true | s3_compatible | full |

### B. Validation checks

Run against the example project:

```bash
python manage.py check
python manage.py migrate
```

### C. YAML validation

- `appliku.yml` must parse without errors

### D. Real deploy

At least one example must deploy successfully on Appliku.

---

## Example Project

Must:

- be an existing minimal Django project (not generated by this template)
- have the Copier-generated deployment files applied and committed
- be regeneratable via `scripts/regenerate_example.py`

---

## Regeneration Script

Must:

- delete existing generated files from `example/demo_project/`
- run `copier copy` with fixed inputs
- recommit the result

---

## Relation to SpeedPy

Reference repo: https://github.com/speedpy/speedpy

### Allowed usage

- copy patterns
- reuse ideas
- optionally sync selected files

### Rules

Do NOT:

- blindly copy files once
- tightly couple to SpeedPy
- auto-overwrite local files

Preferred approach:

- treat SpeedPy as upstream reference
- manually merge useful changes
- optionally build sync script

---

## Anti-Hallucination Rules

The implementing LLM MUST:

- NOT invent Appliku fields or `store_type` values not listed in this document
- NOT invent Django settings
- NOT add extra services beyond spec
- NOT expand feature scope
- NOT generate or modify Django source files
- NOT introduce unnecessary complexity

---

## Implementation Steps

Step 1
Gather a real, working `appliku.yml` + `Dockerfile` + scripts from a known-good Appliku Django deployment. Commit as reference.

Step 2
Convert those files to Copier templates (`.jinja`), parameterised by `copier.yml`.

Step 3
Add the example project (an existing minimal Django app) and apply the template to it.

Step 4
Add `scripts/regenerate_example.py`.

Step 5
Add tests (snapshot + validation).

Step 6 (later)
Add Phase 2 CLI and Appliku API features.

---

## Definition of Done

The implementation is complete when:

- `copier copy` on an existing Django project generates all required deployment files
- generated `appliku.yml` reflects selected options correctly
- example project regenerates successfully
- `manage.py check` passes on the example project
- at least one deployment works on Appliku

---

## Non-Goals

Do NOT include:

- generation of Django source files
- full Django introspection
- full SpeedPy sync
- advanced API automation (Phase 1)
- ASGI / Django Channels support
- multi-region or multi-cluster setup

Keep it simple.

---

## Summary

Build:

- Copier-based scaffold that adds Appliku deployment files to existing Django projects
- support for Postgres variants (PostGIS, pgvector, TimescaleDB), task runners (Celery/Huey), media storage (S3/volume), email, and Sentry
- committed example project (existing Django app + generated files)
- regeneration script
- clear upgrade path via `copier update`
- Phase 2 CLI for full Appliku provisioning: datastores, config-vars, first deploy

Focus on:

- simplicity
- correctness
- maintainability
- updatability
