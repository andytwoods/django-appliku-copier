"""Orchestrate Appliku resource provisioning from Copier answers."""
import logging
import secrets
import sys
import time

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import Credentials, save_deployment_target

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


def _retry_on_500(label: str, fn, *args, wait: int = 5, **kwargs):
    """Call fn(*args, **kwargs), retrying once after `wait` seconds on a 500."""
    for attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except ApplikuAPIError as e:
            if e.status_code == 500 and attempt == 0:
                print(f"  Appliku not ready yet — retrying in {wait}s…")
                _countdown("Waiting", wait)
            else:
                raise


def _create_datastore(
    client: ApplikuClient,
    name: str,
    store_type: str,
    server_id: int | None = None,
    cluster_id: int | None = None,
) -> None:
    """Create a datastore, retrying once on 500 (Appliku sometimes needs a moment)."""
    _retry_on_500(
        "Datastore creation",
        client.create_datastore,
        name=name,
        store_type=store_type,
        server_id=server_id,
        cluster_id=cluster_id,
    )


def _prompt(label: str, default: str | None = None) -> str:
    """Prompt the user for a value, accepting a default on empty input."""
    display = f"{label} [{default}]: " if default is not None else f"{label}: "
    value = input(display).strip()
    return value if value else (default or "")


def run_provision(credentials: Credentials, answers: dict) -> None:
    """Run the full Appliku provisioning sequence for a project."""
    client = ApplikuClient(
        api_key=credentials.api_key,
        team_path=credentials.team_path,
        app_id=credentials.app_id,
    )

    db_type: str = answers.get("db_type", "postgresql_17")
    task_runner: str = answers.get("task_runner", "none")
    celery_broker: str = answers.get("celery_broker", "redis")
    redis_version: str = str(answers.get("redis_version", "8"))
    media_storage: str = answers.get("media_storage", "none")
    email_backend: str = answers.get("email_backend", "console")
    use_sentry: bool = _bool(answers.get("use_sentry", False))
    server_id: int | None = credentials.server_id
    cluster_id: int | None = credentials.cluster_id

    # If neither is set (e.g. app was pre-existing), discover the deployment target now
    if server_id is None and cluster_id is None:
        from appliku_cli.app_setup import _pick_deployment_target  # noqa: PLC0415
        logger.info("No server/cluster in credentials — detecting deployment target")
        cluster_id, server_id = _pick_deployment_target(client)
        save_deployment_target(server_id=server_id, cluster_id=cluster_id)
        credentials.server_id = server_id
        credentials.cluster_id = cluster_id

    needs_redis = task_runner != "none" and (
        task_runner == "huey" or celery_broker == "redis"
    )

    # Guard: abort if the app already has datastores (means it was already provisioned)
    existing = client.list_datastores()
    if existing:
        print(
            "\nThis app has already been provisioned (datastores already exist).\n"
            "To start fresh:\n"
            "  1. Delete the app at https://app.appliku.com\n"
            f"  2. Remove APPLIKU_APP_ID from .env.appliku\n"
            "  3. Re-run appliku-setup"
        )
        return

    # Brief pause to allow Appliku to finish setting up the newly created app
    _countdown("Waiting for Appliku to initialise the app", 8)

    print("[1/7] Provisioning database…")
    _create_datastore(client, name="db", store_type=db_type, server_id=server_id, cluster_id=cluster_id)
    print(f"      ✓ {db_type} database ready")

    if needs_redis:
        redis_store_type = f"redis_{redis_version}"
        print(f"[2/7] Provisioning Redis ({redis_store_type})…")
        _create_datastore(client, name="cache", store_type=redis_store_type, server_id=server_id, cluster_id=cluster_id)
        print(f"      ✓ Redis ready")
    else:
        print("[2/7] Redis — not required, skipping")

    if task_runner == "celery" and celery_broker == "rabbitmq":
        print("[3/7] Provisioning RabbitMQ…")
        _create_datastore(client, name="broker", store_type="rabbitmq", server_id=server_id, cluster_id=cluster_id)
        print("      ✓ RabbitMQ ready")
    else:
        print("[3/7] RabbitMQ — not required, skipping")

    if media_storage == "volume":
        print("[4/7] Provisioning media volume…")
        client.create_volume(name="media", target="/app/media/")
        print("      ✓ Volume ready")
    else:
        print("[4/7] Media volume — not required, skipping")

    def push_vars(vars: dict) -> None:
        _retry_on_500("Config vars", client.set_config_vars, vars)

    print("[5/7] Pushing SECRET_KEY…")
    push_vars({"SECRET_KEY": secrets.token_urlsafe(50)})
    print("      ✓ Done")

    if media_storage == "s3_compatible":
        print("[6/7] Configuring S3-compatible storage…")
        push_vars({
            "AWS_ACCESS_KEY_ID": _prompt("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": _prompt("AWS_SECRET_ACCESS_KEY"),
            "AWS_STORAGE_BUCKET_NAME": _prompt("AWS_STORAGE_BUCKET_NAME"),
            "AWS_S3_ENDPOINT_URL": _prompt("AWS_S3_ENDPOINT_URL"),
        })
        print("      ✓ Done")
    if email_backend != "console":
        print(f"[6/7] Configuring email ({email_backend})…")
        push_vars({
            "EMAIL_HOST": _prompt("EMAIL_HOST"),
            "EMAIL_PORT": _prompt("EMAIL_PORT", default="587"),
            "EMAIL_HOST_USER": _prompt("EMAIL_HOST_USER"),
            "EMAIL_HOST_PASSWORD": _prompt("EMAIL_HOST_PASSWORD"),
        })
        print("      ✓ Done")
    if use_sentry:
        print("[6/7] Configuring Sentry…")
        push_vars({"SENTRY_DSN": _prompt("SENTRY_DSN")})
        print("      ✓ Done")

    print("[7/7] Triggering first deployment…")
    client.trigger_deploy()

    domains = client.list_domains()
    print("\nAppliku setup complete.")
    if domains:
        urls = [f"https://{d}" for d in domains]
        print(f"Your app will be available at: {', '.join(urls)}")
        print(
            "\nIMPORTANT: ensure your Django settings read ALLOWED_HOSTS from the\n"
            "environment, e.g.:\n"
            "\n"
            "    ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])\n"
            "\n"
            "The appliku.yml injects the domain automatically via 'from_domains: true',\n"
            f"so {', '.join(domains)} will be added for you — but only if settings.py\n"
            "reads ALLOWED_HOSTS from the environment."
        )
    print(
        "\nThe first build is now running. Monitor progress at:\n"
        "  https://app.appliku.com\n"
        "\nOnce the build succeeds you can add a custom domain\n"
        "from the Appliku dashboard."
    )
