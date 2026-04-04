"""Orchestrate Appliku resource provisioning from Copier answers."""
import logging
import secrets
import sys
import time
from pathlib import Path

from colorama import Fore, Style, init as colorama_init

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import Credentials, save_deployment_target, save_provisioned
from appliku_cli.detect import detect_django_settings_module, detect_required_env_vars, detect_secret_key_var

colorama_init(autoreset=True)

def _ok(msg: str) -> str:
    return f"{Fore.GREEN}{msg}{Style.RESET_ALL}"

def _err(msg: str) -> str:
    return f"{Fore.RED}{msg}{Style.RESET_ALL}"

def _info(msg: str) -> str:
    return f"{Fore.CYAN}{msg}{Style.RESET_ALL}"

def _warn(msg: str) -> str:
    return f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"

def _bold(msg: str) -> str:
    return f"{Style.BRIGHT}{msg}{Style.RESET_ALL}"

def _log(msg: str) -> str:
    return f"  {Fore.YELLOW}{Style.DIM}{msg}{Style.RESET_ALL}"

logger = logging.getLogger(__name__)


def _bool(value: object) -> bool:
    """Coerce copier answer values to bool (handles both bool and string)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _countdown(message: str, seconds: int) -> None:
    """Show a live countdown so the user knows something is happening."""
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(_info(f"\r  {message} ({remaining}s)…"))
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write(_ok(f"\r  {message} — done.          \n"))
    sys.stdout.flush()


def _retry_on_500(label: str, fn, *args, wait: int = 10, retries: int = 3, **kwargs):
    """Call fn(*args, **kwargs), retrying up to `retries` times on a 500."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except ApplikuAPIError as e:
            if e.status_code == 500 and attempt < retries - 1:
                print(_warn(f"  Appliku not ready yet — retrying in {wait}s… (attempt {attempt + 1}/{retries - 1})"))
                _countdown("Waiting", wait)
            else:
                raise


def _prompt(label: str, default: str | None = None) -> str:
    """Prompt the user for a value, accepting a default on empty input."""
    display = f"{label} [{default}]: " if default is not None else f"{label}: "
    value = input(display).strip()
    return value if value else (default or "")


_TERMINAL_STATUSES = {"Deployed", "Finished", "Failed", "Timeout", "Aborted"}
_POLL_INTERVAL = 10
_POLL_MAX_ATTEMPTS = 72  # 72 × 10s = 12 minutes


_ERROR_KEYWORDS = ("error", "exception", "traceback", "keyerror", "improperlyconfigured",
                   "fatal", "failed", "cannot", "could not", "no such")


def _extract_failure_reason(log: str) -> list[str]:
    """Return lines from the log that look like error messages."""
    hits = []
    for line in log.splitlines():
        lower = line.lower()
        if any(kw in lower for kw in _ERROR_KEYWORDS):
            hits.append(line.strip())
    return hits


def _print_deployment_log(client: ApplikuClient, deployment_id: int, failed: bool = False) -> None:
    """Fetch and print the full deployment log, indented and dimmed.

    If failed=True, also extract and highlight the likely failure reason.
    """
    try:
        deployment = client.get_deployment(deployment_id)
    except ApplikuAPIError:
        logger.debug("Could not fetch deployment detail for id=%s", deployment_id)
        return

    # Try known field names for the log text
    log = ""
    for field in ("log", "output", "build_log", "release_log", "deployment_log"):
        log = deployment.get(field) or ""
        if log:
            break

    if not log:
        logger.debug("Deployment object fields: %s", list(deployment.keys()))
        return

    print(_info("\n── Deployment log ──────────────────────────────────"))
    for line in log.splitlines():
        print(_log(line))
    print(_info("────────────────────────────────────────────────────\n"))

    if failed:
        reasons = _extract_failure_reason(log)
        if reasons:
            print(_err("── Likely failure reason ───────────────────────────"))
            for line in reasons:
                print(_err(f"  {line}"))
            print(_err("────────────────────────────────────────────────────\n"))


def _wait_for_deployment(client: ApplikuClient) -> bool:
    """Poll the latest deployment until it reaches a terminal status. Returns True on success."""
    print(_info("\nWaiting for deployment to complete…"))
    last_status = None
    last_deployment_id = None
    for attempt in range(_POLL_MAX_ATTEMPTS):
        try:
            deployment = client.get_latest_deployment()
        except ApplikuAPIError:
            time.sleep(_POLL_INTERVAL)
            continue

        status = deployment.get("status", "")
        last_deployment_id = deployment.get("id")
        if status != last_status:
            print(_info(f"  Status: {status}"))
            last_status = status

        if status in _TERMINAL_STATUSES:
            success = status in ("Deployed", "Finished")
            if last_deployment_id:
                _print_deployment_log(client, last_deployment_id, failed=not success)
            if success:
                print(_ok("  ✓ Deployment succeeded."))
                return True
            else:
                print(_err(f"  ✗ Deployment ended with status: {status}"))
                return False

        time.sleep(_POLL_INTERVAL)

    print(_err("  Timed out waiting for deployment."))
    return False


def _get_domains(client: ApplikuClient) -> list[str]:
    """Return all domains for the app: custom domains first, then the default subdomain."""
    domains = client.list_domains()
    if not domains:
        app = client.get_app()
        subdomain = app.get("default_subdomain", "")
        if subdomain and not app.get("is_disabled_default_subdomain"):
            domains = [subdomain]
    return domains


def _check_site(url: str) -> bool:
    """Return True if the site responds with a non-5xx status code."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _check_site_and_offer_redeploy(client: ApplikuClient, url: str) -> bool:
    """Check the site URL; if it fails, offer to redeploy once and recheck.

    Returns True if the site is confirmed working, False otherwise.
    """
    print(_info(f"\nChecking site at {url} …"))
    if _check_site(url):
        print(_ok(f"  ✓ Site is up: {url}"))
        return True

    print(
        _warn("  The site returned an error (often a transient nginx routing issue on first deploy).") + "\n"
        + _warn("  Would you like to trigger a second deployment to fix it? [Y/n] "),
        end="",
    )
    answer = input().strip().lower()
    if answer in ("", "y", "yes"):
        print(_info("  Triggering redeploy…"))
        client.trigger_deploy()
        deployed = _wait_for_deployment(client)
        if not deployed:
            print(_err(f"  Redeploy failed. Check the logs at https://app.appliku.com"))
            return False
        print(_info(f"\nRe-checking {url} …"))
        if _check_site(url):
            print(_ok(f"  ✓ Site is up: {url}"))
            return True
        else:
            print(_err(
                f"  Site still not responding at {url}\n"
                "  Check the deployment logs at https://app.appliku.com"
            ))
            return False
    else:
        print(_info(f"\nVisit {url} when ready."))
        return False


def run_provision(credentials: Credentials, answers: dict, cwd: Path | None = None) -> None:
    """Run the full Appliku provisioning sequence for a project.

    Database and cache provisioning is handled declaratively by the `databases:`
    section in appliku.yml — Appliku auto-creates them when the app initialises.
    This function only pushes config vars (secrets, optional integrations) and
    triggers the first deployment.
    """
    cwd = cwd or Path.cwd()

    if credentials.provisioned:
        print(_warn(
            "\nThis app has already been provisioned.\n"
            "To start fresh:\n"
            "  1. Delete the app at https://app.appliku.com\n"
            f"  2. Remove APPLIKU_APP_ID and APPLIKU_PROVISIONED from .env.appliku\n"
            "  3. Re-run appliku-setup"
        ))
        return

    client = ApplikuClient(
        api_key=credentials.api_key,
        team_path=credentials.team_path,
        app_id=credentials.app_id,
    )

    media_storage: str = answers.get("media_storage", "none")
    email_backend: str = answers.get("email_backend", "console")
    use_sentry: bool = _bool(answers.get("use_sentry", False))
    superuser_email: str = answers.get("superuser_email", "").strip()

    # If neither server nor cluster is set (e.g. app was pre-existing), discover now
    server_id: int | None = credentials.server_id
    cluster_id: int | None = credentials.cluster_id
    if server_id is None and cluster_id is None:
        from appliku_cli.app_setup import _pick_deployment_target  # noqa: PLC0415
        logger.info("No server/cluster in credentials — detecting deployment target")
        cluster_id, server_id = _pick_deployment_target(client)
        save_deployment_target(server_id=server_id, cluster_id=cluster_id, cwd=cwd)

    # Vars already handled by the template or other provision steps — never prompt again
    _HANDLED_VARS = {
        "DATABASE_URL", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "WEB_CONCURRENCY",
        "CELERY_BROKER_URL", "REDIS_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_STORAGE_BUCKET_NAME", "AWS_S3_ENDPOINT_URL", "EMAIL_HOST", "EMAIL_PORT",
        "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "SENTRY_DSN", "DJANGO_SETTINGS_MODULE",
        "SUPERUSER_EMAIL", "SUPERUSER_PASSWORD", "MEDIA_ROOT",
    }

    def push_vars(vars: dict) -> None:
        _retry_on_500("Config vars", client.set_config_vars, vars)

    step = 1

    secret_key_var = detect_secret_key_var(cwd)
    settings_module = detect_django_settings_module(cwd)
    if secret_key_var != "SECRET_KEY":
        logger.info("Detected SECRET_KEY env var name: %s", secret_key_var)
    if settings_module:
        logger.info("Detected DJANGO_SETTINGS_MODULE: %s", settings_module)

    skip_vars = _HANDLED_VARS | {secret_key_var}
    extra_env_vars = detect_required_env_vars(cwd, settings_module, skip_vars) if settings_module else []
    if extra_env_vars:
        logger.info("Detected %d additional required env var(s): %s", len(extra_env_vars), ", ".join(extra_env_vars))

    print(_bold(f"[{step}/2] Pushing config vars…"))
    config_vars: dict[str, str] = {secret_key_var: secrets.token_urlsafe(50)}
    if settings_module:
        config_vars["DJANGO_SETTINGS_MODULE"] = settings_module
    superuser_password: str | None = None
    if superuser_email:
        superuser_password = secrets.token_urlsafe(12)
        config_vars["SUPERUSER_EMAIL"] = superuser_email
        config_vars["SUPERUSER_PASSWORD"] = superuser_password
    push_vars(config_vars)
    print(_ok("      ✓ Done"))
    step += 1

    if media_storage == "s3_compatible":
        print(_bold(f"[{step}/2] Configuring S3-compatible storage…"))
        push_vars({
            "AWS_ACCESS_KEY_ID": _prompt("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": _prompt("AWS_SECRET_ACCESS_KEY"),
            "AWS_STORAGE_BUCKET_NAME": _prompt("AWS_STORAGE_BUCKET_NAME"),
            "AWS_S3_ENDPOINT_URL": _prompt("AWS_S3_ENDPOINT_URL"),
        })
        print(_ok("      ✓ Done"))
    if email_backend != "console":
        print(_bold(f"[{step}/2] Configuring email ({email_backend})…"))
        push_vars({
            "EMAIL_HOST": _prompt("EMAIL_HOST"),
            "EMAIL_PORT": _prompt("EMAIL_PORT", default="587"),
            "EMAIL_HOST_USER": _prompt("EMAIL_HOST_USER"),
            "EMAIL_HOST_PASSWORD": _prompt("EMAIL_HOST_PASSWORD"),
        })
        print(_ok("      ✓ Done"))
    if use_sentry:
        print(_bold(f"[{step}/2] Configuring Sentry…"))
        push_vars({"SENTRY_DSN": _prompt("SENTRY_DSN")})
        print(_ok("      ✓ Done"))
    _EXTRA_VAR_DEFAULTS: dict[str, str] = {
        "DJANGO_ADMIN_URL": "myadmin/",
    }

    if extra_env_vars:
        print(_bold(f"Additional required env vars detected in {settings_module}:"))
        extra_values = {}
        for var in extra_env_vars:
            value = _prompt(f"  {var}", default=_EXTRA_VAR_DEFAULTS.get(var))
            if value:
                extra_values[var] = value
        if extra_values:
            push_vars(extra_values)
        print(_ok("      ✓ Done"))

    print(_bold("[2/2] Triggering first deployment…"))
    client.trigger_deploy()

    if superuser_email and superuser_password:
        print("\n" + _bold("=" * 50))
        print(_bold("  SUPERUSER CREDENTIALS"))
        print(_bold(f"  Email:    {superuser_email}"))
        print(_bold(f"  Password: {superuser_password}"))
        print(_bold("=" * 50))
        print(_warn("  Save this password — it won't be shown again."))
        print(_bold("=" * 50) + "\n")

    deployed = _wait_for_deployment(client)

    if deployed:
        save_provisioned(cwd=cwd)
        domains = _get_domains(client)
        if domains:
            url = f"https://{domains[0]}"
            site_up = _check_site_and_offer_redeploy(client, url)
        else:
            site_up = True  # can't verify but deployment succeeded
            print(_warn("\nNo domain found after waiting — check the Appliku dashboard."))

        if site_up and superuser_email:
            print(
                _info("\nWould you like to remove SUPERUSER_EMAIL and SUPERUSER_PASSWORD\n"
                "from Appliku now that the superuser has been created? [Y/n] "),
                end="",
            )
            if input().strip().lower() in ("", "y", "yes"):
                client.delete_config_vars(["SUPERUSER_EMAIL", "SUPERUSER_PASSWORD"])
                print(_ok("  ✓ Superuser credentials removed from Appliku environment variables."))
    else:
        print(_err(
            "\nDeployment did not succeed. Check the build logs at:\n"
            "  https://app.appliku.com"
        ))
        return

    print(_ok("\nAppliku setup complete."))
    print(_info("Once you're ready, add a custom domain from the Appliku dashboard."))
