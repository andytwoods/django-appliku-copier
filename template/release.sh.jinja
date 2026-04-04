#!/usr/bin/env bash
set -e

# Fail fast if Django can't load settings (missing env vars, bad config, etc.).
# No point retrying — this won't fix itself.
echo "=== Checking Django configuration ==="
python -c "import django; django.setup()" || {
    echo "ERROR: Django failed to start. Check your environment variables in Appliku." >&2
    exit 1
}


echo "=== Running migrations ==="
python manage.py migrate --noinput


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
