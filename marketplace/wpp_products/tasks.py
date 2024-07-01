import logging

from datetime import datetime, timedelta

from celery import shared_task

from django.db import reset_queries, close_old_connections

from django.utils import timezone

from marketplace.clients.facebook.client import FacebookClient

from marketplace.wpp_products.models import (
    Catalog,
    ProductUploadLog,
    UploadProduct,
    WebhookLog,
)
from marketplace.clients.flows.client import FlowsClient
from marketplace.celery import app as celery_app
from marketplace.services.vtex.generic_service import (
    ProductUpdateService,
    ProductInsertionService,
    VtexServiceBase,
    ProductInsertionBySellerService,
)
from marketplace.services.vtex.generic_service import APICredentials
from marketplace.core.types import APPTYPES
from marketplace.applications.models import App

from django_redis import get_redis_connection

from marketplace.wpp_products.utils import (
    FirstSyncProductUploader,
    ProductUpdateUploader,
)


logger = logging.getLogger(__name__)


SYNC_WHATSAPP_CATALOGS_LOCK_KEY = "sync-whatsapp-catalogs-lock"


@shared_task(name="sync_facebook_catalogs")
def sync_facebook_catalogs():
    apptype = APPTYPES.get("wpp-cloud")
    for app in apptype.apps:
        service = FacebookCatalogSyncService(app)
        service.sync_catalogs()


class FacebookCatalogSyncService:
    SYNC_WHATSAPP_CATALOGS_LOCK_KEY = "sync-whatsapp-catalogs-lock"

    def __init__(self, app):
        self.app = app
        self.client = FacebookClient(app.apptype.get_access_token(app))
        self.flows_client = FlowsClient()
        self.redis = get_redis_connection()

    def sync_catalogs(self):
        if self.redis.get(self.SYNC_WHATSAPP_CATALOGS_LOCK_KEY):
            print("The catalogs are already syncing by another task!")
            return

        with self.redis.lock(self.SYNC_WHATSAPP_CATALOGS_LOCK_KEY):
            wa_business_id = self.app.config.get("wa_business_id")
            wa_waba_id = self.app.config.get("wa_waba_id")

            if not (wa_business_id and wa_waba_id):
                print(f"Business ID or WABA ID missing for app: {self.app.uuid}")
                return

            try:
                local_catalog_ids = set(
                    self.app.catalogs.values_list("facebook_catalog_id", flat=True)
                )
                all_catalogs_id, all_catalogs = self._list_all_catalogs()

                if all_catalogs_id:
                    self._update_catalogs_on_flows(all_catalogs)
                    self._sync_local_catalogs(all_catalogs_id, local_catalog_ids)
            except Exception as e:
                logger.error(f"Error during sync process for App {self.app.name}: {e}")

    def _list_all_catalogs(self):
        try:
            return self.client.list_all_catalogs(self.app.config.get("wa_business_id"))
        except Exception as e:
            logger.error(
                f"Error on list all catalogs for App: {self.app.uuid} {str(e)}"
            )
            return [], []

    def _update_catalogs_on_flows(self, all_catalogs):
        try:
            self.flows_client.update_catalogs(
                str(self.app.flow_object_uuid), all_catalogs
            )
        except Exception as e:
            logger.error(
                f"Error updating catalogs on flows for App: {self.app.uuid} error: {str(e)}"
            )

    def _sync_local_catalogs(self, all_catalogs_id, local_catalog_ids):
        fba_catalogs_ids = set(all_catalogs_id)
        to_create = fba_catalogs_ids - local_catalog_ids
        to_delete = local_catalog_ids - fba_catalogs_ids

        for catalog_id in to_create:
            try:
                details = self.client.get_catalog_details(catalog_id)
                if details:
                    Catalog.objects.create(
                        app=self.app,
                        facebook_catalog_id=details["id"],
                        name=details["name"],
                        category=details["vertical"],
                    )
            except Exception as e:
                logger.error(f"Error creating catalog {catalog_id} for App: {str(e)}")
                # Continues with the next catalog_id

        if to_delete:
            self.app.catalogs.filter(facebook_catalog_id__in=to_delete).delete()

        print(f"Success in synchronizing the app's catalogs for app: {self.app.uuid}")


@celery_app.task(name="task_insert_vtex_products")
def task_insert_vtex_products(**kwargs):
    print("Starting task: 'task_insert_vtex_products'")
    vtex_service = ProductInsertionService()

    credentials = kwargs.get("credentials")
    catalog_uuid = kwargs.get("catalog_uuid")
    sellers = kwargs.get("sellers")

    if not all([credentials, catalog_uuid]):
        logger.error(
            "Missing required parameters [credentials, catalog_uuid] for task_insert_vtex_products"
        )
        return

    try:
        catalog = Catalog.objects.get(uuid=catalog_uuid)
        api_credentials = APICredentials(
            app_key=credentials["app_key"],
            app_token=credentials["app_token"],
            domain=credentials["domain"],
        )
        print(f"Starting first product insert for catalog: {str(catalog.name)}")
        products = vtex_service.first_product_insert(api_credentials, catalog, sellers)
        if products is None:
            print("There are no products to be shipped after processing the rules")
            return

        celery_app.send_task(
            "task_upload_vtex_products",
            kwargs={"app_vtex_uuid": str(catalog.vtex_app.uuid), "first_sync": True},
            queue="vtex-product-upload",
        )

    except Exception as e:
        logger.exception(
            f"An error occurred during the first insertion of vtex products for catalog {catalog.name}, {e}"
        )
        return
    finally:
        close_old_connections()

    print(
        f"finishing creation products, task: 'task_insert_vtex_products' catalog {catalog.name}"
    )
    print("=" * 40)


@celery_app.task(name="task_update_vtex_products")
def task_update_vtex_products(**kwargs):
    start_time = datetime.now()
    vtex_base_service = VtexServiceBase()

    app_uuid = kwargs.get("app_uuid")
    webhook = kwargs.get("webhook")

    sku_id = webhook.get("IdSku")
    seller_an = webhook.get("An")
    seller_chain = webhook.get("SellerChain")
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        logger.info(
            f"Processing product update for App UUID: {app_uuid}, "
            f"SKU_ID: {sku_id} at {current_time}. "
            f"'An':{seller_an}, 'SellerChain': {seller_chain}."
        )
        vtex_app = App.objects.get(uuid=app_uuid, configured=True, code="vtex")
        (
            domain,
            app_key,
            app_token,
        ) = vtex_base_service.get_vtex_credentials_or_raise(vtex_app)
        api_credentials = APICredentials(
            app_key=app_key, app_token=app_token, domain=domain
        )

        catalog = vtex_app.vtex_catalogs.first()
        if not catalog or not catalog.feeds.first():
            logger.info(
                f"No data feed found in the database. Vtex app: {vtex_app.uuid}"
            )
            return

        product_feed = catalog.feeds.first()

        vtex_update_service = ProductUpdateService(
            api_credentials, catalog, [sku_id], product_feed, webhook
        )
        products = vtex_update_service.webhook_product_insert()
        if products is None:
            logger.info(
                f"No products to process after treatment for VTEX app {app_uuid}. Task ending."
            )
            return

        close_old_connections()
        # Webhook Log
        WebhookLog.objects.create(sku_id=sku_id, data=webhook, vtex_app=vtex_app)

    except Exception as e:
        logger.error(
            f"An error occurred during the updating Webhook vtex products for app {app_uuid}, {str(e)}"
        )

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    minutes, seconds = divmod(duration, 60)

    logger.info(
        f"Finishing process update vtex product to SKU:{sku_id} App: {app_uuid}"
    )
    logger.info(f"Task completed in {int(minutes)} minutes and {int(seconds)} seconds.")

    redis_client = get_redis_connection()
    lock_key = f"upload_lock:{app_uuid}"
    # Check for existing upload lock for the vtex app
    if not redis_client.exists(lock_key):
        print(f"No active upload task for App: {app_uuid}, starting upload.")
        celery_app.send_task(
            "task_upload_vtex_products",
            kwargs={"app_vtex_uuid": app_uuid},
            queue="vtex-product-upload",
        )
    else:
        print(f"An upload task is already in progress for App: {app_uuid}.")

    print("=" * 40)


@celery_app.task(name="task_forward_vtex_webhook")
def task_forward_vtex_webhook(**kwargs):
    app_uuid = kwargs.get("app_uuid")
    webhook = kwargs.get("webhook")

    try:
        app = App.objects.get(uuid=app_uuid, configured=True, code="vtex")
    except App.DoesNotExist:
        logger.info(f"No VTEX App configured with the provided UUID: {app_uuid}")
        return

    can_synchronize = app.config.get("initial_sync_completed", False)

    celery_queue = app.config.get("celery_queue_name", "product_synchronization")

    if not can_synchronize:
        print(f"Initial sync not completed. App:{str(app.uuid)}")
        return

    sku_id = webhook.get("IdSku")

    if not sku_id:
        raise ValueError(f"SKU ID not provided in the request. App:{str(app.uuid)}")

    celery_app.send_task(
        "task_update_vtex_products",
        kwargs={"app_uuid": str(app_uuid), "webhook": webhook},
        queue=celery_queue,
        ignore_result=True,
    )


@celery_app.task(name="task_upload_vtex_products")
def task_upload_vtex_products(**kwargs):
    app_vtex_uuid = kwargs.get("app_vtex_uuid")
    first_sync = kwargs.get("first_sync", False)  # Flag to identify the first sync

    app_vtex = App.objects.get(uuid=app_vtex_uuid)

    redis_client = get_redis_connection()
    lock_key = f"upload_lock:{app_vtex_uuid}"
    lock_expiration_time = 15 * 60  # 15 minutes

    if redis_client.set(lock_key, "locked", nx=True, ex=lock_expiration_time):
        try:
            catalogs = app_vtex.vtex_catalogs.all()
            if not catalogs.exists():
                print("No catalogs found.")
                return

            for catalog in catalogs:
                if catalog.feeds.first():
                    print(f"Processing upload for catalog: {catalog.name}")
                    if first_sync:
                        uploader = FirstSyncProductUploader(catalog=catalog)
                    else:
                        uploader = ProductUpdateUploader(catalog=catalog)
                    uploader.process_and_upload(
                        redis_client, lock_key, lock_expiration_time
                    )

        finally:
            redis_client.delete(lock_key)
    else:
        print(f"Upload task for App: {app_vtex_uuid} is already in progress.")

    print(f"Processing upload for App: {app_vtex_uuid}")


@celery_app.task(name="task_cleanup_vtex_logs_and_uploads")
def task_cleanup_vtex_logs_and_uploads():
    # Delete all records from the ProductUploadLog and WebhookLog tables
    ProductUploadLog.objects.all().delete()
    WebhookLog.objects.all().delete()

    # Delete all UploadProduct records with "success" status
    UploadProduct.objects.filter(status="success").delete()

    # Update status to "pending" for all UploadProduct records with "error" status
    error_queryset = UploadProduct.objects.filter(status="error")
    if error_queryset.exists():
        error_queryset.update(status="pending")

    # Update status to "pending" for records that have been "processing" for more than 20 minutes
    time_threshold = timezone.now() - timedelta(minutes=20)
    in_processing = UploadProduct.objects.filter(
        status="processing", modified_on__lt=time_threshold
    )
    if in_processing.exists():
        in_processing.update(status="pending")

    print("Logs and successful uploads have been cleaned up.")


def send_sync(app_uuid: str, webhook: dict):
    try:
        app = App.objects.get(uuid=app_uuid, configured=True, code="vtex")
    except App.DoesNotExist:
        logger.info(f"No VTEX App configured with the provided UUID: {app_uuid}")
        return

    can_synchronize = app.config.get("initial_sync_completed", False)

    if not can_synchronize:
        print(f"Initial sync not completed. App:{str(app.uuid)}")
        return

    celery_queue = app.config.get("celery_queue_name", "product_synchronization")
    sku_id = webhook.get("IdSku")

    if not sku_id:
        raise ValueError(f"SKU ID not provided in the request. App:{str(app.uuid)}")

    celery_app.send_task(
        "task_update_vtex_products",
        kwargs={"app_uuid": str(app_uuid), "webhook": webhook},
        queue=celery_queue,
        ignore_result=True,
    )


@celery_app.task(name="task_insert_vtex_products_by_sellers")
def task_insert_vtex_products_by_sellers(**kwargs):
    print("Starting insertion products by seller")
    vtex_service = ProductInsertionBySellerService()

    credentials = kwargs.get("credentials")
    catalog_uuid = kwargs.get("catalog_uuid")
    sellers = kwargs.get("sellers")

    if not sellers:
        logger.error(
            "Missing required parameters [seller] for task_insert_vtex_products_by_sellers"
        )
        return

    if not all([credentials, catalog_uuid]):
        logger.error(
            "Missing required parameters [credentials, catalog_uuid] for task_insert_vtex_products"
        )
        return

    try:
        # Reset queries and close old connections for a clean state and performance.
        # Prevents memory leak from stored queries and unstable database connections
        reset_queries()
        close_old_connections()

        catalog = Catalog.objects.get(uuid=catalog_uuid)
        api_credentials = APICredentials(
            app_key=credentials["app_key"],
            app_token=credentials["app_token"],
            domain=credentials["domain"],
        )
        print(
            f"Starting 'insertion_products_by_seller' for catalog: {str(catalog.name)}"
        )
        products = vtex_service.insertion_products_by_seller(
            api_credentials, catalog, sellers
        )
        if products is None:
            print("There are no products to be shipped after processing the rules.")
            return

    except Exception as e:
        logger.exception(
            f"An error occurred during the 'insertion_products_by_seller' for catalog {catalog.name}, {e}"
        )
        return
    finally:
        close_old_connections()

    print(f"finishing 'insertion_products_by_seller'catalog {catalog.name}")
    print("=" * 40)
