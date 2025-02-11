"""
Service for managing VTEX App instances within a project.
"""

import logging

from typing import Optional, List

from django.db import close_old_connections

from dataclasses import dataclass

from marketplace.applications.models import App
from marketplace.services.vtex.private.products.service import (
    PrivateProductsService,
)
from marketplace.clients.vtex.client import VtexPrivateClient
from marketplace.services.vtex.exceptions import (
    CredentialsValidationError,
)
from marketplace.services.facebook.service import (
    FacebookService,
)
from marketplace.clients.facebook.client import FacebookClient
from marketplace.wpp_products.models import ProductFeed
from marketplace.wpp_products.models import Catalog
from marketplace.services.product.product_facebook_manage import ProductFacebookManager
from marketplace.services.vtex.app_manager import AppVtexManager


logger = logging.getLogger(__name__)


@dataclass
class APICredentials:
    domain: str
    app_key: str
    app_token: str

    def to_dict(self):
        return {
            "domain": self.domain,
            "app_key": self.app_key,
            "app_token": self.app_token,
        }


class VtexServiceBase:
    fb_service_class = FacebookService
    fb_client_class = FacebookClient

    def __init__(self, *args, **kwargs):
        self._pvt_service = None
        self._fb_service = None
        self.product_manager = ProductFacebookManager()
        self.app_manager = AppVtexManager()

    def fb_service(self, app: App) -> FacebookService:  # pragma: no cover
        access_token = app.apptype.get_system_access_token(app)
        if not self._fb_service:
            self._fb_service = self.fb_service_class(self.fb_client_class(access_token))
        return self._fb_service

    def get_private_service(
        self, app_key, app_token
    ) -> PrivateProductsService:  # pragma nocover
        if not self._pvt_service:
            client = VtexPrivateClient(app_key, app_token)
            self._pvt_service = PrivateProductsService(client)
        return self._pvt_service

    def check_is_valid_credentials(self, credentials: APICredentials) -> bool:
        pvt_service = self.get_private_service(
            credentials.app_key, credentials.app_token
        )
        if not pvt_service.validate_private_credentials(credentials.domain):
            raise CredentialsValidationError()

        return True

    def configure(
        self, app, credentials: APICredentials, wpp_cloud_uuid, store_domain
    ) -> App:
        app.config["api_credentials"] = credentials.to_dict()
        app.config["wpp_cloud_uuid"] = wpp_cloud_uuid
        app.config["initial_sync_completed"] = False
        app.config["title"] = credentials.domain
        app.config["connected_catalog"] = False
        app.config["rules"] = [
            "exclude_alcoholic_drinks",
            "calculate_by_weight",
            "currency_pt_br",
            "unifies_id_with_seller",
        ]
        app.config["use_sync_v2"] = True
        app.config["store_domain"] = store_domain
        app.configured = True
        app.save()
        return app

    def get_vtex_credentials_or_raise(self, app: App) -> APICredentials:
        domain = app.config["api_credentials"]["domain"]
        app_key = app.config["api_credentials"]["app_key"]
        app_token = app.config["api_credentials"]["app_token"]
        if not domain or not app_key or not app_token:
            raise CredentialsValidationError()

        return APICredentials(
            app_key=app_key,
            app_token=app_token,
            domain=domain,
        )

    def active_sellers(self, app) -> List:
        credentials = self.get_vtex_credentials_or_raise(app)
        pvt_service = self.get_private_service(
            app_key=credentials.app_key, app_token=credentials.app_token
        )
        return pvt_service.list_active_sellers(credentials.domain)

    def synchronized_sellers(self, app: App, sellers_id: List):
        try:
            sync_service = CatalogInsertionBySeller()
            sync_service.start_insertion_by_seller(vtex_app=app, sellers=sellers_id)
        except Exception as e:
            logger.error(
                f"Error on synchronized_sellers: {str(e)}",
                exc_info=True,
                stack_info=True,
                extra={
                    "App": str(app.uuid),
                    "Sellers": sellers_id,
                },
            )
            return False

        return True


class ProductInsertionService(VtexServiceBase):
    def first_product_insert(
        self,
        credentials: APICredentials,
        catalog: Catalog,
        sellers: Optional[List[str]] = None,
    ):
        """
        Handles the first product insert process.
        """
        pvt_service = self.get_private_service(
            credentials.app_key, credentials.app_token
        )
        # TODO: calculate whether there was any success in sending to return
        products = pvt_service.list_all_products(
            domain=credentials.domain,
            catalog=catalog,
            sellers=sellers,
            upload_on_sync=True,  # Enable upload during synchronization
        )
        print(f"First product sync completed for Catalog: {catalog.name}")
        self.app_manager.initial_sync_products_completed(catalog.vtex_app)
        return products


class ProductUpdateService(VtexServiceBase):
    def __init__(
        self,
        api_credentials: APICredentials,
        catalog: Catalog,
        skus_ids: list[str] = None,
        webhook: Optional[dict] = None,
        sellers_ids: list[str] = None,
        product_feed: Optional[ProductFeed] = None,
        sellers_skus: list[str] = None,
    ):
        """
        Service for processing product updates via VTEX webhooks.
        """
        super().__init__()
        self.api_credentials = api_credentials
        self.catalog = catalog
        self.skus_ids = skus_ids
        self.product_feed = product_feed
        self.app = self.catalog.app
        self.webhook = webhook
        self.sellers_ids = sellers_ids if sellers_ids else []
        self.sellers_skus = sellers_skus if sellers_skus else []
        self.product_manager = ProductFacebookManager()

    def webhook_product_insert(self):
        """
        Processes and saves product updates based on the webhook data for the legacy synchronization method.
        """
        # Initialize private service
        pvt_service = self.get_private_service(
            self.api_credentials.app_key, self.api_credentials.app_token
        )
        seller_ids = self._get_sellers_ids(pvt_service)

        # Fetch product data
        products_dto = pvt_service.update_webhook_product_info(
            domain=self.api_credentials.domain,
            skus_ids=self.skus_ids,
            seller_ids=seller_ids,
            catalog=self.catalog,
        )
        if not products_dto:
            return None

        # Save product data in the legacy CSV format
        if not self.product_feed:
            raise ValueError("Product feed is required for legacy synchronization.")

        all_success = self.product_manager.save_csv_product_data(
            products_dto=products_dto,
            catalog=self.catalog,
            product_feed=self.product_feed,
        )

        if not all_success:
            raise Exception(
                f"Error saving products in database for Catalog: {self.catalog.facebook_catalog_id}"
            )

        return products_dto

    def process_batch_sync(self):
        """
        Processes product updates for the new batch synchronization method.
        """
        # Initialize private service
        pvt_service = self.get_private_service(
            self.api_credentials.app_key, self.api_credentials.app_token
        )

        # Fetch product data
        all_success = pvt_service.update_batch_webhook(
            domain=self.api_credentials.domain,
            sellers_skus=self.sellers_skus,
            catalog=self.catalog,
        )

        if not all_success:
            raise Exception(
                f"Error saving batch products in database for Catalog: {self.catalog.facebook_catalog_id}"
            )

        return all_success

    def _get_sellers_ids(self, service):
        seller_id = extract_sellers_ids(self.webhook)
        if seller_id:
            return [seller_id]

        all_active_sellers = service.list_all_actives_sellers(
            self.api_credentials.domain
        )
        print("Seller not found, return all actives sellers")
        return all_active_sellers


def extract_sellers_ids(webhook):
    seller_an = webhook.get("An")
    seller_chain = webhook.get("SellerChain")

    if seller_chain and seller_an:
        return seller_chain

    if seller_an and not seller_chain:
        return seller_an

    return None


class CatalogProductInsertion:
    @classmethod
    def first_product_insert_with_catalog(
        cls, vtex_app: App, catalog_id: str, sellers: Optional[List[str]] = None
    ):
        """Inserts the first product with the given catalog."""
        wpp_cloud_uuid = cls._get_wpp_cloud_uuid(vtex_app)
        credentials = cls._get_credentials(vtex_app)
        wpp_cloud = cls._get_wpp_cloud(wpp_cloud_uuid)

        catalog = cls._get_or_sync_catalog(wpp_cloud, catalog_id)
        cls._delete_existing_feeds_ifexists(catalog)
        cls._update_app_connected_catalog_flag(vtex_app)
        cls._link_catalog_to_vtex_app_if_needed(catalog, vtex_app)

        cls._send_insert_task(credentials, catalog, sellers)

    @staticmethod
    def _get_wpp_cloud_uuid(vtex_app) -> str:
        """Retrieves WPP Cloud UUID from VTEX app config."""
        wpp_cloud_uuid = vtex_app.config.get("wpp_cloud_uuid")
        if not wpp_cloud_uuid:
            raise ValueError(
                "The VTEX app does not have the WPP Cloud UUID in its configuration."
            )
        return wpp_cloud_uuid

    @staticmethod
    def _get_credentials(vtex_app) -> dict:
        """Extracts API credentials from VTEX app config."""
        api_credentials = vtex_app.config.get("api_credentials", {})
        if not all(
            key in api_credentials for key in ["app_key", "app_token", "domain"]
        ):
            raise ValueError("Missing one or more API credentials.")
        return api_credentials

    @staticmethod
    def _get_wpp_cloud(wpp_cloud_uuid) -> App:
        """Fetches the WPP Cloud app based on UUID."""
        try:
            return App.objects.get(uuid=wpp_cloud_uuid)
        except App.DoesNotExist:
            raise ValueError(
                f"The cloud app {wpp_cloud_uuid} linked to the VTEX app does not exist."
            )

    @classmethod
    def _get_or_sync_catalog(cls, wpp_cloud, catalog_id) -> Catalog:
        from marketplace.wpp_products.tasks import FacebookCatalogSyncService

        """Attempts to find the catalog, syncs if not found, and tries again."""
        catalog = wpp_cloud.catalogs.filter(facebook_catalog_id=catalog_id).first()
        if not catalog:
            print(
                f"Catalog {catalog_id} not found for cloud app: {wpp_cloud.uuid}. Starting catalog synchronization."
            )
            sync_service = FacebookCatalogSyncService(wpp_cloud)
            sync_service.sync_catalogs()
            catalog = wpp_cloud.catalogs.filter(facebook_catalog_id=catalog_id).first()
            if not catalog:
                raise ValueError(
                    f"Catalog {catalog_id} not found for cloud app: {wpp_cloud.uuid} after synchronization."
                )
        return catalog

    @staticmethod
    def _link_catalog_to_vtex_app_if_needed(catalog, vtex_app) -> None:
        from django.contrib.auth import get_user_model

        """Links the catalog to the VTEX app if not already linked."""
        if not catalog.vtex_app:
            User = get_user_model()
            catalog.vtex_app = vtex_app
            catalog.modified_by = User.objects.get_admin_user()
            catalog.save()
            print(
                f"Catalog {catalog.name} successfully linked to VTEX app: {vtex_app.uuid}."
            )

    @staticmethod
    def _delete_existing_feeds_ifexists(catalog) -> None:
        """Deletes existing feeds linked to the catalog and logs their IDs."""
        feeds = catalog.feeds.all()
        total = feeds.count()
        if total > 0:
            print(f"Deleting {total} feed(s) linked to catalog {catalog.name}.")
            for feed in feeds:
                print(f"Deleting feed with ID {feed.facebook_feed_id}.")
                feed.delete()
            print(
                f"All feeds linked to catalog {catalog.name} have been successfully deleted."
            )
        else:
            print(f"No feeds linked to catalog {catalog.name} to delete.")

    @staticmethod
    def _update_app_connected_catalog_flag(app) -> None:  # Vtex app
        """Change connected catalog status"""
        connected_catalog = app.config.get("connected_catalog", None)
        if connected_catalog is not True:
            app.config["connected_catalog"] = True
            app.save()
            print("Changed connected_catalog to True")

    @staticmethod
    def _send_insert_task(
        credentials, catalog, sellers: Optional[List[str]] = None
    ) -> None:
        from marketplace.celery import app as celery_app

        """Sends the insert task to the task queue."""
        celery_app.send_task(
            name="task_insert_vtex_products",
            kwargs={
                "credentials": credentials,
                "catalog_uuid": str(catalog.uuid),
                "sellers": sellers,
            },
            queue="product_first_synchronization",
        )
        print(
            f"Catalog: {catalog.name} was sent successfully sent to task_insert_vtex_products"
        )


class ProductInsertionBySellerService(VtexServiceBase):  # pragma: no cover
    """
    Service for inserting products by seller into the UploadProduct model.

    This service fetches products from a specific seller and places them in the upload queue
    for subsequent processing and database insertion.

    Note:
    -----
    - A feed must already be configured both locally and on the Meta platform.
    - Supports both v1 and v2 synchronization methods.

    Parameters:
    ------------
    - credentials (APICredentials): API credentials for accessing the VTEX platform.
    - catalog (Catalog): The catalog associated with the seller's products.
    - sellers (List[str]): A list of seller IDs to fetch products for.

    Methods:
    ---------
    - insertion_products_by_seller: Fetches products for the specified sellers and processes them
      for insertion into the database or further synchronization.
    """

    def insertion_products_by_seller(
        self,
        credentials: APICredentials,
        catalog: Catalog,
        sellers: List[str],
    ):
        """
        Fetches and inserts products by seller into the UploadProduct model.

        Parameters:
        ------------
        - credentials (APICredentials): API credentials for accessing the VTEX platform.
        - catalog (Catalog): The catalog associated with the seller's products.
        - sellers (List[str]): A list of seller IDs to fetch products for.

        Raises:
        -------
        - ValueError: If the `sellers` parameter is not provided.
        - Exception: If an error occurs during the bulk save process.

        Returns:
        --------
        - List[FacebookProductDTO]: A list of product DTOs if the `use_sync_v2` flag is True.
        - None: If no products are returned for v1 synchronization.
        """
        if not sellers:
            raise ValueError("'sellers' is required")

        # Initialize private service
        pvt_service = self.get_private_service(
            credentials.app_key, credentials.app_token
        )

        # Determine if synchronization v2 is used
        use_sync_v2 = catalog.vtex_app.config.get("use_sync_v2", False)
        upload_on_sync = use_sync_v2

        # Fetch product data from the VTEX platform
        products_dto = pvt_service.list_all_products(
            domain=credentials.domain,
            catalog=catalog,
            sellers=sellers,
            upload_on_sync=upload_on_sync,
            update_product=True,
            sync_specific_sellers=True,
        )

        print(
            f"Finished synchronizing products for specific sellers: {sellers}. Use sync v2: {use_sync_v2}."
        )

        # Handle v1 synchronization (non-batch upload mode)
        if not use_sync_v2:
            if not products_dto:
                return None

            # Close old database connections
            close_old_connections()
            print(f"'list_all_products' returned {len(products_dto)} products.")
            print("Starting bulk save process in the database.")

            # Save products in bulk
            all_success = self.product_manager.bulk_save_csv_product_data(
                products_dto=products_dto,
                catalog=catalog,
                product_feed=catalog.feeds.first(),
            )

            if not all_success:
                raise Exception(
                    f"Error saving CSV to the database. Catalog: {catalog.facebook_catalog_id}"
                )

        return products_dto


class CatalogInsertionBySeller:  # pragma: no cover
    @classmethod
    def start_insertion_by_seller(cls, vtex_app: App, sellers: List[str]):
        if not vtex_app:
            raise ValueError("'vtex_app' is required.")

        if not sellers:
            raise ValueError("'sellers' is required.")

        wpp_cloud_uuid = cls._get_wpp_cloud_uuid(vtex_app)
        credentials = cls._get_credentials(vtex_app)
        wpp_cloud = cls._get_wpp_cloud(wpp_cloud_uuid)

        catalog = cls._validate_link_apps(wpp_cloud, vtex_app)

        cls._validate_sync_status(vtex_app)
        use_sync_v2 = cls._use_sync_v2(vtex_app)
        if use_sync_v2 is False:
            cls._validate_catalog_feed(catalog)

        cls._validate_connected_catalog_flag(vtex_app)

        cls._send_task(credentials, catalog, sellers)

    @staticmethod
    def _get_wpp_cloud_uuid(vtex_app) -> str:
        """Retrieves WPP Cloud UUID from VTEX app config."""
        wpp_cloud_uuid = vtex_app.config.get("wpp_cloud_uuid")
        if not wpp_cloud_uuid:
            raise ValueError(
                "The VTEX app does not have the WPP Cloud UUID in its configuration."
            )
        return wpp_cloud_uuid

    @staticmethod
    def _get_credentials(vtex_app) -> dict:
        """Extracts API credentials from VTEX app config."""
        api_credentials = vtex_app.config.get("api_credentials", {})
        if not all(
            key in api_credentials for key in ["app_key", "app_token", "domain"]
        ):
            raise ValueError("Missing one or more API credentials.")
        return api_credentials

    @staticmethod
    def _validate_sync_status(vtex_app) -> None:
        can_synchronize = vtex_app.config.get("initial_sync_completed", False)
        if not can_synchronize:
            raise ValueError("Initial synchronization not completed.")

        print("validate_sync_status - Ok")

    @staticmethod
    def _get_wpp_cloud(wpp_cloud_uuid) -> App:
        """Fetches the WPP Cloud app based on UUID."""
        try:
            app = App.objects.get(uuid=wpp_cloud_uuid, code="wpp-cloud")
            if app.flow_object_uuid is None:
                print(f"Alert: App: {app.uuid} has the flow_object_uuid None field")
            return app
        except App.DoesNotExist:
            raise ValueError(
                f"The cloud app {wpp_cloud_uuid} linked to the VTEX app does not exist."
            )

    @classmethod
    def _validate_link_apps(cls, wpp_cloud, vtex_app) -> Catalog:
        """Checks for linked catalogs."""
        vtex_catalog = vtex_app.vtex_catalogs.first()

        if not vtex_catalog:
            raise ValueError(
                f"There must be a catalog linked to the vtex app {str(vtex_app.uuid)}"
            )

        catalog = wpp_cloud.catalogs.filter(
            facebook_catalog_id=vtex_catalog.facebook_catalog_id
        ).first()
        if not catalog:
            raise ValueError(
                f"Catalog {vtex_catalog.catalog_id} not found for cloud app: {wpp_cloud.uuid}."
            )

        print("validate_link_apps - Ok")
        return catalog

    @staticmethod
    def _validate_connected_catalog_flag(vtex_app) -> None:
        """Connected catalog status"""
        connected_catalog = vtex_app.config.get("connected_catalog", None)
        if connected_catalog is not True:
            raise ValueError(
                f"Change connected_catalog to True. actual is:{connected_catalog}"
            )

        print("validate_connected_catalog_flag - Ok")

    @staticmethod
    def _validate_catalog_feed(catalog) -> ProductFeed:
        if not catalog.feeds.first():
            raise ValueError("At least 1 feed created is required")

        print("validate_catalog_feed - Ok")

    @staticmethod
    def _use_sync_v2(vtex_app) -> bool:
        use_sync_v2 = vtex_app.config.get("use_sync_v2", False)
        print(f"App use_sync_v2: {use_sync_v2}")
        return use_sync_v2

    @staticmethod
    def _send_task(credentials, catalog, sellers: Optional[List[str]] = None) -> None:
        from marketplace.celery import app as celery_app

        """Sends the insert task to the task queue."""
        celery_app.send_task(
            name="task_insert_vtex_products_by_sellers",
            kwargs={
                "credentials": credentials,
                "catalog_uuid": str(catalog.uuid),
                "sellers": sellers,
            },
            queue="product_first_synchronization",
        )
        print(
            f"Catalog: {catalog.name} was sent successfully sent to task_insert_vtex_products_by_sellers"
        )
