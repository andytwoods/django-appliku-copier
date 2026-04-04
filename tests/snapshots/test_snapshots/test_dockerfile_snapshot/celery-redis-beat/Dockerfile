FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN if python3 -c "import sys,tomllib; d=tomllib.load(open('pyproject.toml','rb')); sys.exit(0 if 'production' in d.get('project',{}).get('optional-dependencies',{}) else 1)" 2>/dev/null; \
    then UV_PROJECT_ENVIRONMENT=/usr/local UV_PYTHON_PREFERENCE=system uv sync --frozen --no-dev --extra production; \
    else UV_PROJECT_ENVIRONMENT=/usr/local UV_PYTHON_PREFERENCE=system uv sync --frozen --no-dev; \
    fi

COPY . .

RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000
