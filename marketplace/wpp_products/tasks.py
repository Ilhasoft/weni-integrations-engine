import logging

from functools import wraps

from celery import shared_task

from marketplace.clients.facebook.client import FacebookClient
from marketplace.wpp_products.models import Catalog
from marketplace.clients.flows.client import FlowsClient
from marketplace.core.types import APPTYPES

from django_redis import get_redis_connection


logger = logging.getLogger(__name__)


SYNC_WHATSAPP_CATALOGS_LOCK_KEY = "sync-whatsapp-catalogs-lock"


@shared_task(name="sync_facebook_catalogs")
def sync_facebook_catalogs():
    apptype = APPTYPES.get("wpp-cloud")
    flows_client = FlowsClient()

    redis = get_redis_connection()
    if redis.get(SYNC_WHATSAPP_CATALOGS_LOCK_KEY):
        logger.info("The catalogs are already syncing by another task!")
        return None

    else:
        with redis.lock(SYNC_WHATSAPP_CATALOGS_LOCK_KEY):
            for app in apptype.apps:
                client = FacebookClient(apptype.get_access_token(app))
                wa_business_id = app.config.get("wa_business_id")
                wa_waba_id = app.config.get("wa_waba_id")

                if wa_business_id and wa_waba_id:
                    local_catalog_ids = set(
                        app.catalogs.values_list("facebook_catalog_id", flat=True)
                    )

                    all_catalogs_id, all_catalogs = list_all_catalogs_task(app, client)

                    if all_catalogs_id:
                        update_catalogs_on_flows_task(app, flows_client, all_catalogs)

                        fba_catalogs_ids = set(all_catalogs_id)
                        to_create = fba_catalogs_ids - local_catalog_ids
                        to_delete = local_catalog_ids - fba_catalogs_ids

                        for catalog_id in to_create:
                            details = get_catalog_details_task(client, catalog_id)
                            if details:
                                create_catalog_task(app, details)

                        if to_delete:
                            delete_catalogs_task(app, to_delete)


def handle_exceptions(
    logger, error_msg, continue_on_exception=True, extra_info_func=None
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                extra_info_str = (
                    extra_info_func(*args, **kwargs) if extra_info_func else ""
                )
                logger.error(f"{error_msg}{extra_info_str}: {str(e)}")
                if not continue_on_exception:
                    raise

        return wrapper

    return decorator


def get_extra_info(app, *args, **kwargs):
    return f"- UUID: {app.uuid}"


@handle_exceptions(
    logger, "Error listing all catalogs for App: ", extra_info_func=get_extra_info
)
def list_all_catalogs_task(app, client):
    try:
        all_catalog_ids, all_catalogs = client.list_all_catalogs(
            wa_business_id=app.config.get("wa_business_id")
        )
        return all_catalog_ids, all_catalogs
    except Exception as e:
        logger.error(f"Error on list all catalogs for App: {str(e)}")
        return [], []


@handle_exceptions(
    logger, "Error updating catalogs for App: ", extra_info_func=get_extra_info
)
def update_catalogs_on_flows_task(app, flows_client, all_catalogs):
    flows_client.update_catalogs(str(app.flow_object_uuid), all_catalogs)


@handle_exceptions(
    logger,
    "Error getting catalog details for App",
    continue_on_exception=False,
    extra_info_func=get_extra_info,
)
def get_catalog_details_task(client, catalog_id):
    return client.get_catalog_details(catalog_id)


@handle_exceptions(
    logger, "Error creating catalog for App: ", extra_info_func=get_extra_info
)
def create_catalog_task(app, details):
    Catalog.objects.create(
        app=app,
        facebook_catalog_id=details["id"],
        name=details["name"],
        category=details["vertical"],
    )


@handle_exceptions(
    logger, "Error deleting catalogs for App: ", extra_info_func=get_extra_info
)
def delete_catalogs_task(app, to_delete):
    app.catalogs.filter(facebook_catalog_id__in=to_delete).delete()
