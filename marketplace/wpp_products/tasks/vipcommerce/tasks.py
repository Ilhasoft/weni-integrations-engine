from django.db import close_old_connections, reset_queries
from marketplace.services.vipcommerce.service import APICredentials, FirstProductSyncVip
from marketplace.wpp_products.models import Catalog
from marketplace.celery import app as celery_app
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="task_insert_vtex_products_by_sellers")
def task_insert_vip_commerce_products_by_sellers(**kwargs):
    print("Starting insertion products by seller")
    vip_service = FirstProductSyncVip()

    credentials = kwargs.get("credentials")
    catalog_uuid = kwargs.get("catalog_uuid")
    sellers = kwargs.get("sellers")

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
            app_token=credentials["app_token"],
            domain=credentials["domain"],
        )
        print(
            f"Starting 'insertion_products_by_seller' for catalog: {str(catalog.name)}"  # AJUSTAR PRNTS
        )
        products = vip_service.vip_first_product_insert(
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
