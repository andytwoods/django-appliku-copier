#!/usr/bin/env bash
set -e
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${WEB_CONCURRENCY:-2}"
