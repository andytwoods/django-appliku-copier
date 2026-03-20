# django-appliku-copier

A [Copier](https://copier.readthedocs.io/) template that adds Appliku deployment boilerplate to an **existing** Django project. Generated files support future updates via `copier update`.

## What it generates

Always:
- `appliku.yml` — Appliku app config
- `Dockerfile` — Python slim image
- `run.sh` — gunicorn entrypoint
- `release.sh` — migrate + collectstatic

Conditionally:
- `celery-worker.sh` — if Celery or Huey is selected
- `celery-beat.sh` — if Celery beat is selected

## Quick start

```bash
copier copy gh:your-org/django-appliku-copier /path/to/your/django/project
```

After scaffolding, run the Phase 2 CLI to provision datastores and push config vars:

```bash
appliku-setup
```

## Template options

| Variable | Choices | Default |
|---|---|---|
| `project_name` | string | — |
| `python_version` | string | `3.12` |
| `db_type` | `postgresql_17`, `postgresql_18`, `postgresql_16`, `postgresql_15`, `postgis_16_34`, `postgresql_16_pgvector`, `timescale_db_17`, `mysql_8` | `postgresql_17` |
| `task_runner` | `none`, `celery`, `huey` | `none` |
| `celery_broker` | `redis`, `rabbitmq` | `redis` |
| `use_beat` | bool | `false` |
| `media_storage` | `none`, `s3_compatible`, `volume` | `none` |
| `email_backend` | `console`, `smtp`, `sendgrid`, `mailgun`, `ses` | `console` |
| `use_sentry` | bool | `false` |

## Repository layout

```
template/           Copier template (.jinja files + copier.yml)
example/            Minimal Django project with generated files applied
  demo_project/
appliku_cli/        Phase 2 CLI (datastore provisioning, config-vars, deploy)
scripts/
  regenerate_example.py     Wipe and re-apply template to example project
  update_appliku_docs.sh    Re-fetch APPLIKU.md from appliku.com/llms.txt
reference/          Hand-written reference files (not deployed — ground truth)
tests/              Snapshot tests, YAML validation, Django check
```

## Key documents

| File | Purpose |
|---|---|
| [`OVERVIEW.md`](OVERVIEW.md) | Full project goals, architecture, variable reference, and API details |
| [`TASKS.md`](TASKS.md) | Phased implementation plan used to build the project |
| [`APPLIKU.md`](APPLIKU.md) | Appliku platform reference (fetched from `appliku.com/llms.txt`) |
| [`CLAUDE.md`](CLAUDE.md) | Instructions for AI coding assistants working in this repo |
| [`.junie/guidelines.md`](.junie/guidelines.md) | Python/Django coding conventions |

## Development workflow

1. Edit a template in `template/`
2. Run `python scripts/regenerate_example.py` — wipes generated files, re-runs `copier copy`
3. Inspect the diff on the generated files
4. Run `cd example/demo_project && python manage.py check`
5. Run `pytest` — snapshot tests, YAML validation, Django check

## Keeping Appliku docs current

`APPLIKU.md` is a snapshot of `appliku.com/llms.txt`. Re-fetch it before working on Appliku-related features:

```bash
bash scripts/update_appliku_docs.sh
```

## Phase 2 CLI

The `appliku-setup` command reads `.copier-answers.yml` from the project root and automates:

1. Database datastore provisioning
2. Redis / RabbitMQ provisioning (if task runner selected)
3. Volume provisioning (if `media_storage == "volume"`)
4. `SECRET_KEY` generation and push to config vars
5. `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` push
6. Storage / email / Sentry env vars (prompted)
7. First deployment trigger

Credentials are stored in `.env.appliku` (git-ignored). See [`OVERVIEW.md`](OVERVIEW.md) for the full API sequence.
