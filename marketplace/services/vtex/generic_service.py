"""
Service for managing VTEX App instances within a project.
"""

from datetime import datetime

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
from marketplace.services.vtex.exceptions import (
    UnexpectedFacebookApiResponseValidationError,
)
from marketplace.services.vtex.app_manager import AppVtexManager


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
        access_token = app.apptype.get_access_token(app)
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
        app.config["store_domain"] = store_domain
        app.configured = True
        app.save()
        return app

    def get_vtex_credentials_or_raise(self, app):
        domain = app.config["api_credentials"]["domain"]
        app_key = app.config["api_credentials"]["app_key"]
        app_token = app.config["api_credentials"]["app_token"]
        if not domain or not app_key or not app_token:
            raise CredentialsValidationError()

        return domain, app_key, app_token


class ProductInsertionService(VtexServiceBase):
    def first_product_insert(
        self,
        credentials: APICredentials,
        catalog: Catalog,
        sellers: Optional[List[str]] = None,
    ):
        has_product_feed = self._check_if_feed_exists(catalog=catalog)

        if has_product_feed:
            print("There is already a feed created, to continue there must be no feeds")
            return

        pvt_service = self.get_private_service(
            credentials.app_key, credentials.app_token
        )
        products_dto = pvt_service.list_all_products(
            credentials.domain, catalog.vtex_app.config, sellers
        )
        if not products_dto:
            return None

        product_feed = self._create_product_feed()

        close_old_connections()
        all_success = self.product_manager.bulk_save_csv_product_data(
            products_dto, self.catalog, product_feed, pvt_service.data_processor
        )

        # TODO: move this code to the task that will upload to meta
        self.app_manager.initial_sync_products_completed(catalog.vtex_app)

        return all_success

    def _check_if_feed_exists(self, catalog: Catalog) -> bool:
        print("check if feed exists")
        service = self.fb_service(catalog.app)
        response = service.get_product_feed_by_catalog(catalog.facebook_catalog_id)
        return response

    def _create_product_feed(self) -> ProductFeed:
        print("Creating the product feed")
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
        file_name = f"csv_vtex_products_{current_time}.csv"
        service = self.fb_service(self.catalog.app)
        response = service.create_product_feed(
            self.catalog.facebook_catalog_id, file_name
        )

        if "id" not in response:
            raise UnexpectedFacebookApiResponseValidationError()

        product_feed = ProductFeed.objects.create(
            facebook_feed_id=response["id"],
            name=file_name,
            catalog=self.catalog,
            created_by=self.catalog.created_by,
        )
        return product_feed


class ProductUpdateService(VtexServiceBase):
    def __init__(
        self,
        api_credentials: APICredentials,
        catalog: Catalog,
        skus_ids: list,
        product_feed: ProductFeed,
        webhook: dict,
    ):
        super().__init__()
        self.api_credentials = api_credentials
        self.catalog = catalog
        self.skus_ids = skus_ids
        self.product_feed = product_feed
        self.app = self.catalog.app
        self.webhook = webhook

    def webhook_product_insert(self):
        pvt_service = self.get_private_service(
            self.api_credentials.app_key, self.api_credentials.app_token
        )
        seller_ids = self._get_sellers_ids(pvt_service)

        products_dto = pvt_service.update_webhook_product_info(
            self.api_credentials.domain,
            self.skus_ids,
            seller_ids,
            self.catalog.vtex_app.config,
        )
        if not products_dto:
            return None

        all_success = self.product_manager.save_csv_product_data(
            products_dto, self.catalog, self.product_feed, pvt_service.data_processor
        )
        if not all_success:
            raise Exception(
                f"Error on save csv on database. Catalog:{self.catalog.facebook_catalog_id}"
            )

        return products_dto

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
        cls._update_app_connected_catalog_flag(wpp_cloud)
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
    def _update_app_connected_catalog_flag(app) -> None:
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
    Service for inserting products by seller into UploadProduct model.

    This class is used to fetch products from a specific seller and place them in the upload queue
    for subsequent processing and insertion into the database.

    Important:
    ----------
    It is necessary to have a feed already configured both locally and on the Meta platform.
    """

    def insertion_products_by_seller(
        self,
        credentials: APICredentials,
        catalog: Catalog,
        sellers: List[str],
    ):
        if not sellers:
            raise ValueError("'sellers' is required")

        pvt_service = self.get_private_service(
            credentials.app_key, credentials.app_token
        )
        products_dto = pvt_service.list_all_products(
            credentials.domain, catalog.vtex_app.config, sellers, update_product=True
        )
        print(f"'list_all_products' returned {len(products_dto)}")
        if not products_dto:
            return None

        close_old_connections()
        print("starting bulk save process in database")
        all_success = self.product_manager.bulk_save_csv_product_data(
            products_dto, catalog, catalog.feeds.first(), pvt_service.data_processor
        )
        if not all_success:
            raise Exception(
                f"Error on save csv on database. Catalog:{self.catalog.facebook_catalog_id}"
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
            raise ValueError("Missing one or more API credentials.")

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
