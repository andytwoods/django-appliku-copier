"""Auto-detection of Django project settings for Appliku provisioning."""
import re
from pathlib import Path

# Matches lines like:
#   SECRET_KEY = os.environ.get('MY_SECRET_KEY', ...)
#   SECRET_KEY = os.environ['MY_SECRET_KEY']
#   SECRET_KEY = env('MY_SECRET_KEY')
#   SECRET_KEY = env.str('MY_SECRET_KEY')
#   SECRET_KEY = config('MY_SECRET_KEY')
#   SECRET_KEY = os.getenv('MY_SECRET_KEY')
_SECRET_KEY_RE = re.compile(
    r"SECRET_KEY\s*=.*?"
    r"(?:"
    r"(?:getenv|get|env(?:\.str)?|config)\s*\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
    r"|environ\s*\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
    r")"
)

_SETTINGS_MODULE_RE = re.compile(
    r"""setdefault\s*\(\s*['"]DJANGO_SETTINGS_MODULE['"]\s*,\s*['"]([^'"]+)['"]"""
)

_SKIP_DIRS = {".venv", "venv", "env", ".env", "node_modules", "__pycache__", ".git"}

_SETTINGS_STEMS = {"settings", "production", "base", "common", "prod", "live"}
_SETTINGS_PARENTS = {"settings", "config"}


def _candidate_settings_files(cwd: Path) -> list[Path]:
    """Find Python files likely to be Django settings modules."""
    results = []
    for p in cwd.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.stem.lower() in _SETTINGS_STEMS or p.parent.name.lower() in _SETTINGS_PARENTS:
            results.append(p)
    return results


def detect_secret_key_var(cwd: Path) -> str:
    """Scan Django settings to find the env var name used for SECRET_KEY.

    Returns 'SECRET_KEY' if nothing more specific is found.
    """
    for settings_file in _candidate_settings_files(cwd):
        try:
            content = settings_file.read_text(errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            m = _SECRET_KEY_RE.search(line)
            if m:
                var = m.group(1) or m.group(2)
                if var:
                    return var
    return "SECRET_KEY"


def detect_django_settings_module(cwd: Path) -> str | None:
    """Return the DJANGO_SETTINGS_MODULE to use, preferring production.py.

    Reads the default from manage.py, then checks if production.py exists
    in the same settings package and returns that module path if so.
    Returns None if manage.py is not found or has no DJANGO_SETTINGS_MODULE default.
    """
    manage_py = cwd / "manage.py"
    if not manage_py.exists():
        return None

    try:
        manage_content = manage_py.read_text(errors="replace")
    except OSError:
        return None

    m = _SETTINGS_MODULE_RE.search(manage_content)
    if not m:
        return None

    current_module = m.group(1)

    # If the current module is already production-like, use it as-is
    if current_module.split(".")[-1] in ("production", "prod", "live"):
        return current_module

    # Check if production.py exists alongside the current settings module
    parts = current_module.rsplit(".", 1)
    if len(parts) == 2:
        package_path = parts[0]
        settings_dir = cwd / package_path.replace(".", "/")
        if (settings_dir / "production.py").exists():
            return f"{package_path}.production"
    else:
        # Single-segment module like 'settings' — check if it's a package
        settings_dir = cwd / current_module
        if settings_dir.is_dir() and (settings_dir / "production.py").exists():
            return f"{current_module}.production"

    return current_module
