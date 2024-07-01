from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.db import close_old_connections
from marketplace.applications.models import App
from marketplace.interfaces.vipcommerce.interfaces import VipCommerceClientInterface
from marketplace.services.vipcommerce.exceptions import CredentialsValidationError
from marketplace.services.vipcommerce.utils.data_processor import (
    DataProcessor,
    FacebookProductDTO,
)
from marketplace.services.vipcommerce.business.rules.rules_mappings import RULE_MAPPINGS
from marketplace.wpp_products.models import Catalog


@dataclass
class APICredentials:  # todo: ajustar campos
    domain: str
    app_token: str

    def to_dict(self):
        return {
            "domain": self.domain,
            "app_token": self.app_token,
        }


class BasePrivateProductsService:
    def __init__(
        self, client: VipCommerceClientInterface, data_processor_class=DataProcessor
    ):
        self.client = client
        self.data_processor = data_processor_class()

    # manage app config
    def check_is_valid_credentials(self, credentials: APICredentials) -> bool:
        service = self.get_private_service(credentials.domain, credentials.app_token)
        if not service.validate_private_credentials(credentials.domain):
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

    def get_vip_credentials_or_raise(self, app):
        domain = app.config["api_credentials"]["domain"]
        app_key = app.config["api_credentials"]["app_key"]
        app_token = app.config["api_credentials"]["app_token"]
        if not domain or not app_key or not app_token:
            raise CredentialsValidationError()

        return domain, app_key, app_token

    # api comunication
    def list_active_sellers(self) -> List[Dict[str, Any]]:
        return self.client.list_active_sellers()

    def list_all_products(self) -> List[Dict[str, Any]]:
        return self.client.list_all_products()

    def list_all_active_products(self) -> List[Dict[str, Any]]:
        return self.client.list_all_active_products()

    def get_brand(self) -> List[Dict[str, Any]]:
        return self.client.get_brand()


class FirstProductSyncVip(BasePrivateProductsService):
    def vip_first_product_insert(
        self,
        credentials: APICredentials,
        catalog: Catalog,
        sellers: List[str],
    ):

        products_dto = self._get_and_process_products(
            credentials.domain, catalog.vtex_app.config, sellers, update_product=False
        )
        print(f"'list_all_products' returned {len(products_dto)}")
        if not products_dto:
            return None

        close_old_connections()
        print("starting bulk save process in database")
        all_success = self.product_manager.bulk_save_csv_product_data(
            products_dto, catalog, catalog.feeds.first(), self.data_processor
        )
        if not all_success:
            raise Exception(
                f"Error on save csv on database. Catalog:{self.catalog.facebook_catalog_id}"
            )

        return products_dto

    def _get_and_process_products(
        self,
        domain: str,
        config: dict,
        sellers: Optional[List[str]] = None,
        update_product=False,
    ) -> List[FacebookProductDTO]:
        active_sellers = set(self.list_active_sellers())
        if sellers is not None:
            valid_sellers = [seller for seller in sellers if seller in active_sellers]
            invalid_sellers = set(sellers) - active_sellers
            if invalid_sellers:
                print(
                    f"Warning: Sellers IDs {invalid_sellers} are not active and will be ignored."
                )
            sellers_ids = valid_sellers
        else:
            sellers_ids = list(active_sellers)

        skus_ids = self.list_all_active_products(domain)
        rules = self._load_rules(config.get("rules", []))
        store_domain = config.get("store_domain")

        # Tudo que for precisar inserir no dado do produto tem que ser passado aqui
        products_dto = self.data_processor.process_product_data(
            skus_ids, sellers_ids, self, domain, store_domain, rules, update_product
        )
        return products_dto

    def _load_rules(self, rule_names):
        rules = []
        for rule_name in rule_names:
            rule_class = RULE_MAPPINGS.get(rule_name)
            if rule_class:
                rules.append(rule_class())
            else:
                print(f"Rule {rule_name} not found or not mapped.")
        return rules
