#!/usr/bin/env bash
set -e

# Wait for the database to be reachable before running migrations.
# On first deploy Appliku may still be starting the database container.
for i in $(seq 1 12); do
    python manage.py migrate --noinput && break
    echo "Database not ready yet, retrying in 10s… ($i/12)"
    sleep 10
done

echo "=== Creating superuser (if needed) ==="
python manage.py shell -c "
import os, secrets
from django.contrib.auth import get_user_model
User = get_user_model()
email = os.environ.get('SUPERUSER_EMAIL', '')
if not email:
    print('SUPERUSER_EMAIL not set — skipping superuser creation.')
elif User.objects.filter(is_superuser=True).exists():
    print('Superuser already exists — skipping.')
else:
    password = os.environ.get('SUPERUSER_PASSWORD') or secrets.token_urlsafe(12)
    kwargs = {'password': password}
    kwargs[User.USERNAME_FIELD] = email if User.USERNAME_FIELD == 'email' else email.split('@')[0]
    if 'email' not in kwargs and hasattr(User, 'email'):
        kwargs['email'] = email
    User.objects.create_superuser(**kwargs)
    print('=== SUPERUSER CREATED ===')
    print(f'Email: {email}')
    print(f'Password: {password}')
    print('=========================')
"
