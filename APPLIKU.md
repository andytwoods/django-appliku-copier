# Appliku

Appliku is a Platform-as-a-Service (PaaS) that deploys your applications to your own servers — not Appliku's infrastructure. You bring your VPS or cloud server; Appliku handles the deployment pipeline.

- Docker-based: every app runs in containers
- Runs on any Linux server via Docker Swarm (cluster) or single-server mode
- Supports any language or framework that can run in Docker
- Key concepts: Team → Servers → Applications → Deployments

Documentation: https://docs.appliku.com
App dashboard: https://app.appliku.com
YouTube Channel: https://youtube.com/@appliku

## Deployment Flow

1. Connect a Linux server to your Appliku team
2. Create an application and connect a git repository
3. Push code → Appliku builds and deploys automatically

Configuration lives in `appliku.yml` at the repository root. Build phase runs first, then the release command, then services start.

## appliku.yml Reference

Full format:

```yaml
build_settings:
  build_image: python-3.13          # see available images below
  build_command: "pip install -r requirements.txt && python manage.py collectstatic --noinput"
  container_port: 8000
  # dockerfile: Dockerfile          # use this instead of build_image for custom Dockerfiles
  environment_variables:
    - name: DATABASE_URL
      from_database:
        name: mydb                  # auto-inject connection string from a managed database
        property: connection_url
    - name: ALLOWED_HOSTS
      from_domains: true            # auto-inject comma-separated list of app domains
    - name: SECRET_KEY
      source: manual                # set value in the dashboard
    - name: MY_STATIC_VAR
      value: "some_value"           # static value baked into build

services:
  web:
    command: "gunicorn myproject.wsgi:application --bind 0.0.0.0:8000"
    scale: 1
    resources_limits_memory: 512M
    resources_limits_cpus: "0.5"
  worker:
    command: "celery -A myproject worker -l info"
    scale: 1
  beat:
    command: "celery -A myproject beat -l info"
    scale: 1
  release:
    command: "python manage.py migrate"   # runs once after each build, before services start

databases:
  mydb:
    type: postgresql_17   # see database types below

volumes:
  media:
    target: /app/media/
    url: /media/
    environment_variable: MEDIA_ROOT

cronjobs:
  my_management_command:
    schedule: "0 * * * *"
    command: python manage.py my_management_command
```

### Available build_image values

- `python-3.13`
- `python-3.13-uv`
- `python-3.13-node-20.18`
- `python-3.12`
- `python-3.12-uv`
- `python-3.11`
- `python-3.11-uv`
- `node-20-npm`
- `node-20-yarn`
- `ruby-3.4.1`
- `dockerfile` (uses your own Dockerfile)

### Available database types

- `postgresql_17`, `postgresql_16`, `postgresql_15`
- `postgresql_16_pgvector`
- `redis_7`
- `mysql_8`
- `rabbitmq`
- `elasticsearch_8_17`

## Python / Django

### Two workflows

**pip (requirements.txt):**
```
build_image: python-3.13
build_command: "pip install -r requirements.txt && python manage.py collectstatic --noinput"
```

**uv (pyproject.toml):**
```
build_image: python-3.13-uv
build_command: "uv sync && uv run python manage.py collectstatic --noinput"
```

### Required packages

```
django-environ
gunicorn
psycopg2-binary   # or psycopg[binary] for psycopg3 — do NOT use psycopg[c]; it requires libpq-dev which is not in slim images
whitenoise        # for serving static files
```

### settings.py requirements

```python
import environ

env = environ.Env()
environ.Env.read_env()

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)

DATABASES = {
    "default": env.db("DATABASE_URL")
}

# Appliku injects domains via from_domains: true
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Required when running behind Appliku's reverse proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STATIC_URL = env.str("STATIC_URL", default="/static/")
STATIC_ROOT = env.str("STATIC_ROOT", default=BASE_DIR / "staticfiles")
# WhiteNoise serves static files directly from Django — add to MIDDLEWARE right after SecurityMiddleware:
# MIDDLEWARE = [
#     "django.middleware.security.SecurityMiddleware",
#     "whitenoise.middleware.WhiteNoiseMiddleware",  # must be second
#     ...
# ]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

# Media files — must use an Appliku volume for persistence across deployments
# In the dashboard: Volumes tab → target=/app/media, enable Nginx checkbox
# In appliku.yml: volumes: [{target: /app/media, url: /media, environment_variable: MEDIA_ROOT}]
MEDIA_ROOT = env("MEDIA_ROOT", default=BASE_DIR / "media")
MEDIA_URL = env("MEDIA_PATH", default="/media/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"": {"handlers": ["console"], "level": "DEBUG"}},
}
```

### Full Django appliku.yml example (with Celery)

```yaml
build_settings:
  build_image: python-3.13
  build_command: "pip install -r requirements.txt && python manage.py collectstatic --noinput"
  container_port: 8000
  environment_variables:
    - name: DATABASE_URL
      from_database:
        name: db
        property: connection_url
    - name: ALLOWED_HOSTS
      from_domains: true
    - name: SECRET_KEY
      source: manual
    - name: DEBUG
      value: "False"

services:
  web:
    command: "gunicorn myproject.wsgi:application --bind 0.0.0.0:8000 --workers 2"
    scale: 1
  worker:
    command: "celery -A myproject worker -l info --concurrency 2"
    scale: 1
  beat:
    command: "celery -A myproject beat -l info"
    scale: 1
  release:
    command: "python manage.py migrate"

databases:
  db:
    type: postgresql_17

volumes:
  media:
    target: /app/media/
    url: /media/
    environment_variable: MEDIA_ROOT
```

**Without Celery** — omit the `worker` and `beat` services.

### Common mistakes to avoid

- Do not hardcode `ALLOWED_HOSTS = ["*"]` in production — use `from_domains: true`
- Do not use `python-decouple` — Appliku injects `DATABASE_URL` in the format `django-environ` expects
- Run `migrate` in the `release` service, not in `build_command`
- Collect static files during build (`build_command`), not at runtime
- Use WhiteNoise to serve static files — Django does not serve them in production by default
- User-uploaded media files will be lost on every redeploy unless you use an Appliku volume — containers have ephemeral filesystems
- SQLite requires a volume too — the container filesystem is ephemeral, so the database file is wiped on every deploy; create a volume at `/db/` and set `DATABASE_URL=sqlite:////db/db.sqlite3` (four slashes) as a manual env var; for production, prefer PostgreSQL
- App must bind to `0.0.0.0`, not `127.0.0.1`

### FastAPI / other Python frameworks

Same pattern — replace gunicorn with uvicorn:

```
command: "uvicorn main:app --host 0.0.0.0 --port 8000"
```

## Node.js

```yaml
build_settings:
  build_image: node-20-npm
  build_command: "npm install && npm run build"
  container_port: 3000
  environment_variables:
    - name: DATABASE_URL
      from_database:
        name: db
        property: connection_url

services:
  web:
    command: "npm start"
```

- Appliku injects a `PORT` environment variable — your app must listen on it
- For Next.js: `command: "node .next/standalone/server.js"` or `npm start`

## Ruby on Rails

```yaml
build_settings:
  build_image: ruby-3.4.1
  build_command: "bundle install && bundle exec rails assets:precompile"
  container_port: 3000
  environment_variables:
    - name: DATABASE_URL
      from_database:
        name: db
        property: connection_url
    - name: SECRET_KEY_BASE
      source: manual
    - name: RAILS_ENV
      value: "production"

services:
  web:
    command: "bundle exec rails server -b 0.0.0.0 -p 3000"
  release:
    command: "bundle exec rails db:migrate"

databases:
  db:
    type: postgresql_17
```

Rails reads `DATABASE_URL` natively if `config/database.yml` uses it (the default in modern Rails).

## Static Sites

```yaml
build_settings:
  build_image: node-20-npm
  build_command: "npm install && npm run build"
  is_static_site: true
  output_directory: dist   # or: out, build, public
```

No `services` block needed for static sites — Appliku serves files directly.

## Documentation Index

### Getting Started
- https://docs.appliku.com/docs/getting-started/ — What is Appliku
- https://docs.appliku.com/docs/getting-started/quickstart — Quickstart Guide
- https://docs.appliku.com/docs/getting-started/concepts — Core Concepts
- https://docs.appliku.com/docs/getting-started/supported-stacks — Supported Languages & Runtimes

### Deploy Guides
- https://docs.appliku.com/docs/deploy/ — Deployment Overview
- https://docs.appliku.com/docs/deploy/django — Deploy Django
- https://docs.appliku.com/docs/deploy/nextjs — Deploy Next.js
- https://docs.appliku.com/docs/deploy/nodejs — Deploy Node.js
- https://docs.appliku.com/docs/deploy/python-generic — Deploy Flask / FastAPI
- https://docs.appliku.com/docs/deploy/rails — Deploy Ruby on Rails
- https://docs.appliku.com/docs/deploy/static-sites — Deploy Static Sites
- https://docs.appliku.com/docs/deploy/from-dockerfile — Deploy from a Dockerfile
- https://docs.appliku.com/docs/deploy/streamlit — Deploy Streamlit
- https://docs.appliku.com/docs/deploy/heroku-migration — Migrate from Heroku

### Applications
- https://docs.appliku.com/docs/applications/ — Application Management Overview
- https://docs.appliku.com/docs/applications/appliku-yml — appliku.yml Configuration
- https://docs.appliku.com/docs/applications/build-settings — Build Settings
- https://docs.appliku.com/docs/applications/environment-variables — Environment Variables
- https://docs.appliku.com/docs/applications/domains — Custom Domains & SSL
- https://docs.appliku.com/docs/applications/volumes — Persistent Volumes
- https://docs.appliku.com/docs/applications/processes — Managing Processes
- https://docs.appliku.com/docs/applications/scaling — Scaling Applications
- https://docs.appliku.com/docs/applications/cron-jobs — Cron Jobs
- https://docs.appliku.com/docs/applications/deployments — Deployments & Build Logs
- https://docs.appliku.com/docs/applications/application-logs — Application Logs
- https://docs.appliku.com/docs/applications/webhooks — Deployment Webhooks
- https://docs.appliku.com/docs/applications/run-one-off-commands — Run One-Off Commands
- https://docs.appliku.com/docs/applications/nginx-settings — Nginx Settings
- https://docs.appliku.com/docs/applications/create-from-github — Create App from GitHub
- https://docs.appliku.com/docs/applications/create-from-gitlab — Create App from GitLab
- https://docs.appliku.com/docs/applications/create-from-custom-git — Create App from Custom Git Repo
- https://docs.appliku.com/docs/applications/change-git-repository — Changing Git Repository
- https://docs.appliku.com/docs/applications/delete-application — Deleting an Application

### Databases
- https://docs.appliku.com/docs/databases/ — Database Management Overview
- https://docs.appliku.com/docs/databases/postgresql — PostgreSQL
- https://docs.appliku.com/docs/databases/mysql — MySQL
- https://docs.appliku.com/docs/databases/redis — Redis
- https://docs.appliku.com/docs/databases/rabbitmq — RabbitMQ
- https://docs.appliku.com/docs/databases/elasticsearch — Elasticsearch
- https://docs.appliku.com/docs/databases/specialized-postgres — Specialized PostgreSQL (PostGIS, pgvector, TimescaleDB)
- https://docs.appliku.com/docs/databases/sqlite-with-django — Using SQLite with Django
- https://docs.appliku.com/docs/databases/backups — Database Backups
- https://docs.appliku.com/docs/databases/migrations — Database Import/Export

### Servers
- https://docs.appliku.com/docs/servers/ — Server Management Overview
- https://docs.appliku.com/docs/servers/add-digitalocean — Add a DigitalOcean Server
- https://docs.appliku.com/docs/servers/add-aws-ec2 — Add an AWS EC2 Server
- https://docs.appliku.com/docs/servers/add-custom-server — Add a Custom Server (SSH)
- https://docs.appliku.com/docs/servers/server-setup-process — What Happens During Server Setup
- https://docs.appliku.com/docs/servers/server-monitoring — Server Monitoring
- https://docs.appliku.com/docs/servers/docker-management — Docker Management
- https://docs.appliku.com/docs/servers/run-commands — Run Commands on a Server
- https://docs.appliku.com/docs/servers/server-settings — Server Settings
- https://docs.appliku.com/docs/servers/nginx-management — Nginx Management

### Clusters (Docker Swarm)
- https://docs.appliku.com/docs/clusters/ — Clusters Overview
- https://docs.appliku.com/docs/clusters/setup-cluster — Setting Up a Cluster
- https://docs.appliku.com/docs/clusters/deploy-to-cluster — Deploying to a Cluster
- https://docs.appliku.com/docs/clusters/scaling-in-clusters — Scaling in Clusters
- https://docs.appliku.com/docs/clusters/container-registry — Container Registry Setup
- https://docs.appliku.com/docs/clusters/cluster-limitations — Cluster Limitations & Gotchas

### How-To Guides
- https://docs.appliku.com/docs/how-to/django-celery — Run Django Celery Workers
- https://docs.appliku.com/docs/how-to/django-static-files — Serve Django Static Files with WhiteNoise
- https://docs.appliku.com/docs/how-to/django-media-files — Serve Django Media Files
- https://docs.appliku.com/docs/how-to/cicd-integration — CI/CD Integration
- https://docs.appliku.com/docs/how-to/zero-downtime-deploys — Zero-Downtime Deployments
- https://docs.appliku.com/docs/how-to/connect-to-s3 — Connect to Amazon S3
- https://docs.appliku.com/docs/how-to/multiple-apps-one-server — Run Multiple Apps on One Server
- https://docs.appliku.com/docs/how-to/custom-nginx-config — Custom Nginx Configuration
- https://docs.appliku.com/docs/how-to/expose-non-http-port — Expose Non-HTTP Ports
- https://docs.appliku.com/docs/how-to/automate-custom-domains — Automate Custom Domain Management
- https://docs.appliku.com/docs/how-to/use-uv-package-manager — Use uv Package Manager
- https://docs.appliku.com/docs/how-to/ai-coding-assistants — Using AI Coding Assistants with Appliku
- https://docs.appliku.com/docs/how-to/jetbrains-space — Deploy from JetBrains Space
- https://docs.appliku.com/docs/how-to/rstudio — Self-hosting RStudio

### Reference
- https://docs.appliku.com/docs/reference/appliku-yml-reference — appliku.yml Reference
- https://docs.appliku.com/docs/reference/build-images — Build Images
- https://docs.appliku.com/docs/reference/database-types — Database Types
- https://docs.appliku.com/docs/reference/env-vars-reference — Environment Variables Reference
- https://docs.appliku.com/docs/reference/predefined-dockerfiles — Predefined Dockerfiles
- https://docs.appliku.com/docs/reference/server-requirements — Server Requirements
- https://docs.appliku.com/docs/reference/directory-structure — Server Directory Structure
- https://docs.appliku.com/docs/reference/api-overview — API Overview

### Team & Account
- https://docs.appliku.com/docs/team-management/ — Teams Overview
- https://docs.appliku.com/docs/team-management/members-and-roles — Members & Roles
- https://docs.appliku.com/docs/team-management/billing — Billing & Plans
- https://docs.appliku.com/docs/team-management/cloud-providers — Cloud Provider Credentials
- https://docs.appliku.com/docs/team-management/notifications — Notifications
- https://docs.appliku.com/docs/team-management/sub-teams — Sub-Teams
- https://docs.appliku.com/docs/team-management/account-settings — Account Settings

### Troubleshooting
- https://docs.appliku.com/docs/troubleshooting/ — Troubleshooting Overview
- https://docs.appliku.com/docs/troubleshooting/build-failures — Build Failures
- https://docs.appliku.com/docs/troubleshooting/deployment-failures — Deployment Failures
- https://docs.appliku.com/docs/troubleshooting/app-not-responding — App Not Responding
- https://docs.appliku.com/docs/troubleshooting/database-connection — Database Connection Issues
- https://docs.appliku.com/docs/troubleshooting/domain-ssl-issues — Domain & SSL Issues
- https://docs.appliku.com/docs/troubleshooting/disk-space — Disk Space Issues
- https://docs.appliku.com/docs/troubleshooting/memory-issues — Memory Issues
- https://docs.appliku.com/docs/troubleshooting/server-setup-failures — Server Setup Failures

### CLI & SDK
- https://docs.appliku.com/docs/cli-sdk/ - CLI & SDK

## General Advice (all stacks)

- Always read config from environment variables — never hardcode credentials or connection strings
- `SECRET_KEY`, API keys, and similar secrets: use `source: manual` in `appliku.yml` and set values in the Appliku dashboard
- Database connection strings are auto-injected via `from_database` — don't hardcode them
- App must bind to `0.0.0.0`, not `127.0.0.1`
- The `release` service runs once after each successful build, before services restart — use it for database migrations
