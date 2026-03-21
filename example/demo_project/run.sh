#!/usr/bin/env bash
set -e
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
