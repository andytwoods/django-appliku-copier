FROM python:3.14-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --no-dev --extra production

COPY . .

RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000
