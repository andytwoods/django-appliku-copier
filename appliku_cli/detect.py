"""Auto-detection of Django project settings for Appliku provisioning."""
import ast
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


def _module_to_path(cwd: Path, module: str) -> Path | None:
    """Convert a dotted module name to a filesystem path."""
    candidate = cwd / f"{module.replace('.', '/')}.py"
    return candidate if candidate.exists() else None


def detect_required_env_vars(cwd: Path, settings_module: str, skip_vars: set[str]) -> list[str]:
    """Parse a settings file and return env var names that have no default.

    Detects django-environ/decouple style calls:
      env("VAR")              → required
      env("VAR", default=...) → optional, skipped
      env.bool("VAR")         → required
      os.environ["VAR"]       → required

    skip_vars: set of var names already handled by the template (DATABASE_URL etc.)
    Returns a deduplicated list in order of appearance.
    """
    path = _module_to_path(cwd, settings_module)
    if not path:
        return []

    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (SyntaxError, OSError):
        return []

    required: list[str] = []
    seen: set[str] = set(skip_vars)

    for node in ast.walk(tree):
        var_name: str | None = None
        is_required = False

        # env("VAR") / env.type("VAR") / config("VAR")
        if isinstance(node, ast.Call):
            func = node.func
            is_env_call = (
                (isinstance(func, ast.Name) and func.id in ("env", "config"))
                or (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id in ("env", "config")
                )
            )
            if is_env_call and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    var_name = first.value
                    has_default = (
                        any(kw.arg == "default" for kw in node.keywords)
                        or len(node.args) > 1
                    )
                    is_required = not has_default

        # os.environ["VAR"]
        elif isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
            ):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    var_name = key.value
                    is_required = True

        if is_required and var_name and var_name not in seen:
            required.append(var_name)
            seen.add(var_name)

    return required
