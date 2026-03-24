"""Orchestrate Appliku resource provisioning from Copier answers."""
import logging
import secrets
import sys
import time
from pathlib import Path

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import Credentials, save_deployment_target, save_provisioned

logger = logging.getLogger(__name__)


def _bool(value: object) -> bool:
    """Coerce copier answer values to bool (handles both bool and string)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _countdown(message: str, seconds: int) -> None:
    """Show a live countdown so the user knows something is happening."""
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\r  {message} ({remaining}s)…")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write(f"\r  {message} — done.          \n")
    sys.stdout.flush()


def _retry_on_500(label: str, fn, *args, wait: int = 10, retries: int = 3, **kwargs):
    """Call fn(*args, **kwargs), retrying up to `retries` times on a 500."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except ApplikuAPIError as e:
            if e.status_code == 500 and attempt < retries - 1:
                print(f"  Appliku not ready yet — retrying in {wait}s… (attempt {attempt + 1}/{retries - 1})")
                _countdown("Waiting", wait)
            else:
                raise


def _prompt(label: str, default: str | None = None) -> str:
    """Prompt the user for a value, accepting a default on empty input."""
    display = f"{label} [{default}]: " if default is not None else f"{label}: "
    value = input(display).strip()
    return value if value else (default or "")


def run_provision(credentials: Credentials, answers: dict, cwd: Path | None = None) -> None:
    """Run the full Appliku provisioning sequence for a project.

    Database and cache provisioning is handled declaratively by the `databases:`
    section in appliku.yml — Appliku auto-creates them when the app initialises.
    This function only pushes config vars (secrets, optional integrations) and
    triggers the first deployment.
    """
    cwd = cwd or Path.cwd()

    if credentials.provisioned:
        print(
            "\nThis app has already been provisioned.\n"
            "To start fresh:\n"
            "  1. Delete the app at https://app.appliku.com\n"
            f"  2. Remove APPLIKU_APP_ID and APPLIKU_PROVISIONED from .env.appliku\n"
            "  3. Re-run appliku-setup"
        )
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

    def push_vars(vars: dict) -> None:
        _retry_on_500("Config vars", client.set_config_vars, vars)

    step = 1

    print(f"[{step}/2] Pushing config vars…")
    config_vars: dict[str, str] = {"SECRET_KEY": secrets.token_urlsafe(50)}
    domains = client.list_domains()
    if domains:
        config_vars["ALLOWED_HOSTS"] = ",".join(domains)
        config_vars["CSRF_TRUSTED_ORIGINS"] = ",".join(f"https://{d}" for d in domains)
    superuser_password: str | None = None
    if superuser_email:
        superuser_password = secrets.token_urlsafe(12)
        config_vars["SUPERUSER_EMAIL"] = superuser_email
        config_vars["SUPERUSER_PASSWORD"] = superuser_password
    push_vars(config_vars)
    print("      ✓ Done")
    step += 1

    if media_storage == "s3_compatible":
        print(f"[{step}/2] Configuring S3-compatible storage…")
        push_vars({
            "AWS_ACCESS_KEY_ID": _prompt("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": _prompt("AWS_SECRET_ACCESS_KEY"),
            "AWS_STORAGE_BUCKET_NAME": _prompt("AWS_STORAGE_BUCKET_NAME"),
            "AWS_S3_ENDPOINT_URL": _prompt("AWS_S3_ENDPOINT_URL"),
        })
        print("      ✓ Done")
    if email_backend != "console":
        print(f"[{step}/2] Configuring email ({email_backend})…")
        push_vars({
            "EMAIL_HOST": _prompt("EMAIL_HOST"),
            "EMAIL_PORT": _prompt("EMAIL_PORT", default="587"),
            "EMAIL_HOST_USER": _prompt("EMAIL_HOST_USER"),
            "EMAIL_HOST_PASSWORD": _prompt("EMAIL_HOST_PASSWORD"),
        })
        print("      ✓ Done")
    if use_sentry:
        print(f"[{step}/2] Configuring Sentry…")
        push_vars({"SENTRY_DSN": _prompt("SENTRY_DSN")})
        print("      ✓ Done")

    print(f"[2/2] Triggering first deployment…")
    client.trigger_deploy()

    save_provisioned(cwd=cwd)

    if superuser_email and superuser_password:
        print("\n" + "=" * 50)
        print("  SUPERUSER CREDENTIALS")
        print(f"  Email:    {superuser_email}")
        print(f"  Password: {superuser_password}")
        print("=" * 50)
        print("  Save this password — it won't be shown again.")
        print("  After your first deploy completes, remove")
        print("  SUPERUSER_EMAIL and SUPERUSER_PASSWORD from")
        print("  Appliku → App → Environment Variables.")
        print("=" * 50 + "\n")

    print("\nAppliku setup complete.")
    if domains:
        urls = [f"https://{d}" for d in domains]
        print(f"Your app will be available at: {', '.join(urls)}")
    print(
        "\nThe first build is now running. Monitor progress at:\n"
        "  https://app.appliku.com\n"
        "\nOnce the build succeeds you can add a custom domain\n"
        "from the Appliku dashboard."
    )
