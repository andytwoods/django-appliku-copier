#!/usr/bin/env bash
set -e

# Wait for the database to be reachable before running migrations.
# On first deploy Appliku may still be starting the database container.
for i in $(seq 1 12); do
    python manage.py migrate --noinput && break
    echo "Database not ready yet, retrying in 10s… ($i/12)"
    sleep 10
done

python manage.py collectstatic --noinput
