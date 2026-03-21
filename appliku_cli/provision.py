"""Orchestrate Appliku resource provisioning from Copier answers."""
import logging
import secrets
import time

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import Credentials

logger = logging.getLogger(__name__)


def _bool(value: object) -> bool:
    """Coerce copier answer values to bool (handles both bool and string)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _create_datastore(
    client: ApplikuClient,
    name: str,
    store_type: str,
    server_id: int | None = None,
    cluster_id: int | None = None,
) -> None:
    """Create a datastore, retrying once on 500 (Appliku sometimes needs a moment)."""
    for attempt in range(2):
        try:
            client.create_datastore(
                name=name,
                store_type=store_type,
                server_id=server_id,
                cluster_id=cluster_id,
            )
            return
        except ApplikuAPIError as e:
            if e.status_code == 500 and attempt == 0:
                logger.warning("Datastore creation got 500 — waiting 5s and retrying")
                time.sleep(5)
            else:
                raise


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

    needs_redis = task_runner != "none" and (
        task_runner == "huey" or celery_broker == "redis"
    )

    # Brief pause to allow Appliku to finish setting up the newly created app
    time.sleep(3)

    # Step 1: Provision database
    logger.info("Step 1/11: Provisioning database (%s)", db_type)
    _create_datastore(client, name="db", store_type=db_type, server_id=server_id, cluster_id=cluster_id)

    # Step 2: Provision Redis
    if needs_redis:
        redis_store_type = f"redis_{redis_version}"
        logger.info("Step 2/11: Provisioning Redis (%s)", redis_store_type)
        _create_datastore(client, name="cache", store_type=redis_store_type, server_id=server_id, cluster_id=cluster_id)
    else:
        logger.info("Step 2/11: Redis not required — skipping")

    # Step 3: Provision RabbitMQ
    if task_runner == "celery" and celery_broker == "rabbitmq":
        logger.info("Step 3/11: Provisioning RabbitMQ")
        _create_datastore(client, name="broker", store_type="rabbitmq", server_id=server_id, cluster_id=cluster_id)
    else:
        logger.info("Step 3/11: RabbitMQ not required — skipping")

    # Step 4: Provision media volume
    if media_storage == "volume":
        logger.info("Step 4/11: Provisioning media volume")
        client.create_volume(name="media", target="/app/media/")
    else:
        logger.info("Step 4/11: Media volume not required — skipping")

    # Step 5: SECRET_KEY
    logger.info("Step 5/11: Generating and pushing SECRET_KEY")
    secret_key = secrets.token_urlsafe(50)
    client.set_config_vars({"SECRET_KEY": secret_key})

    # Step 6: Domain → ALLOWED_HOSTS + CSRF_TRUSTED_ORIGINS
    logger.info("Step 6/11: Configuring domain")
    domain = _prompt("Domain (e.g. myapp.example.com)")
    client.set_config_vars({
        "ALLOWED_HOSTS": domain,
        "CSRF_TRUSTED_ORIGINS": f"https://{domain}",
    })

    # Step 7: WEB_CONCURRENCY
    logger.info("Step 7/11: Setting WEB_CONCURRENCY")
    concurrency = _prompt("WEB_CONCURRENCY", default="2")
    client.set_config_vars({"WEB_CONCURRENCY": concurrency})

    # Step 8: S3-compatible storage
    if media_storage == "s3_compatible":
        logger.info("Step 8/11: Configuring S3-compatible storage")
        client.set_config_vars({
            "AWS_ACCESS_KEY_ID": _prompt("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": _prompt("AWS_SECRET_ACCESS_KEY"),
            "AWS_STORAGE_BUCKET_NAME": _prompt("AWS_STORAGE_BUCKET_NAME"),
            "AWS_S3_ENDPOINT_URL": _prompt("AWS_S3_ENDPOINT_URL"),
        })
    else:
        logger.info("Step 8/11: S3 storage not required — skipping")

    # Step 9: Email
    if email_backend != "console":
        logger.info("Step 9/11: Configuring email backend (%s)", email_backend)
        client.set_config_vars({
            "EMAIL_HOST": _prompt("EMAIL_HOST"),
            "EMAIL_PORT": _prompt("EMAIL_PORT", default="587"),
            "EMAIL_HOST_USER": _prompt("EMAIL_HOST_USER"),
            "EMAIL_HOST_PASSWORD": _prompt("EMAIL_HOST_PASSWORD"),
        })
    else:
        logger.info("Step 9/11: Email backend is console — skipping")

    # Step 10: Sentry
    if use_sentry:
        logger.info("Step 10/11: Configuring Sentry")
        client.set_config_vars({"SENTRY_DSN": _prompt("SENTRY_DSN")})
    else:
        logger.info("Step 10/11: Sentry not enabled — skipping")

    # Step 11: Trigger first deployment
    logger.info("Step 11/11: Triggering first deployment")
    result = client.trigger_deploy()
    logger.info("Deployment triggered: %s", result)
