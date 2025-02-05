import time
import logging
import requests

from typing import List, Dict, Any

from marketplace.applications.models import App
from marketplace.wpp_products.models import Catalog
from marketplace.interfaces.facebook.interfaces import (
    TemplatesRequestsInterface,
    PhotoAPIRequestsInterface,
    PhoneNumbersRequestsInterface,
    CloudProfileRequestsInterface,
    BusinessMetaRequestsInterface,
    CatalogsRequestsInterface,
)


logger = logging.getLogger(__name__)


class FacebookService:  # TODO: Change the name to CatalogService
    def __init__(self, client: CatalogsRequestsInterface):
        self.client = client

    # ================================
    # Public Methods
    # ================================

    def create_vtex_catalog(self, validated_data, app, vtex_app, user):
        business_id = self._get_app_facebook_credentials(app=app).get("wa_business_id")
        response = self.client.create_catalog(business_id, validated_data["name"])

        if response and response.get("id"):
            data = {
                "app": app,
                "facebook_catalog_id": response.get("id"),
                "vtex_app": vtex_app,
                "name": validated_data["name"],
                "created_by": user,
            }
            catalog = self._create_catalog_object(data)
            self._update_connected_catalog_flag(vtex_app)
            return catalog, response.get("id")

        return None, None

    def catalog_deletion(self, catalog):
        return self.client.destroy_catalog(catalog.facebook_catalog_id)

    def enable_catalog(self, catalog):
        waba_id = self._get_app_facebook_credentials(app=catalog.app).get("wa_waba_id")
        response = self.client.enable_catalog(
            waba_id=waba_id, catalog_id=catalog.facebook_catalog_id
        )
        success = response.get("success") is True
        return success, response

    def disable_catalog(self, catalog):
        waba_id = self._get_app_facebook_credentials(app=catalog.app).get("wa_waba_id")
        response = self.client.disable_catalog(
            waba_id=waba_id, catalog_id=catalog.facebook_catalog_id
        )
        success = response.get("success") is True
        return success, response

    def get_connected_catalog(self, app):
        waba_id = self._get_app_facebook_credentials(app=app).get("wa_waba_id")
        response = self.client.get_connected_catalog(waba_id=waba_id)

        if len(response.get("data")) > 0:
            return response.get("data")[0].get("id")

        return []

    def toggle_cart(self, app, enable=True):
        business_phone_number_id = self._get_app_facebook_credentials(app=app).get(
            "wa_phone_number_id"
        )
        return self.client.toggle_cart(business_phone_number_id, enable)

    def toggle_catalog_visibility(self, app, visible=True):
        business_phone_number_id = self._get_app_facebook_credentials(app=app).get(
            "wa_phone_number_id"
        )
        return self.client.toggle_catalog_visibility(business_phone_number_id, visible)

    def wpp_commerce_settings(self, app):
        business_phone_number_id = self._get_app_facebook_credentials(app=app).get(
            "wa_phone_number_id"
        )
        return self.client.get_wpp_commerce_settings(business_phone_number_id)

    def create_product_feed(self, product_catalog_id, name):
        return self.client.create_product_feed(product_catalog_id, name)

    def upload_product_feed(
        self, feed_id, file, file_name, file_content_type, update_only=False
    ):
        return self.client.upload_product_feed(
            feed_id, file, file_name, file_content_type, update_only
        )

    def get_upload_status_by_feed(self, feed_id, upload_id) -> bool:
        return self.client.get_upload_status_by_feed(feed_id, upload_id)

    def get_in_process_uploads_by_feed(self, feed_id) -> str:
        return self.client.get_uploads_in_progress_by_feed(feed_id)

    def update_product_feed(self, feed_id, csv_file, file_name):
        response = self.upload_product_feed(
            feed_id, csv_file, file_name, "text/csv", update_only=True
        )
        if "id" not in response:
            return None
        return response["id"]

    def uploads_in_progress(self, feed_id):
        upload_id = self.get_in_process_uploads_by_feed(feed_id)
        return upload_id if upload_id else False

    # ================================
    # Private Methods
    # ================================

    def _get_app_facebook_credentials(self, app):
        wa_business_id = app.config.get("wa_business_id")
        wa_waba_id = app.config.get("wa_waba_id")
        wa_phone_number_id = app.config.get("wa_phone_number_id")

        if not wa_business_id or not wa_waba_id or not wa_phone_number_id:
            raise ValueError(
                "Not found 'wa_waba_id', 'wa_business_id' or wa_phone_number_id in app.config "
            )
        return {
            "wa_business_id": wa_business_id,
            "wa_waba_id": wa_waba_id,
            "wa_phone_number_id": wa_phone_number_id,
        }

    def _create_catalog_object(self, data):
        return Catalog.objects.create(
            app=data.get("app"),
            facebook_catalog_id=data.get("facebook_catalog_id"),
            vtex_app=data.get("vtex_app"),
            name=data.get("name"),
            created_by=data.get("created_by"),
        )

    def _update_connected_catalog_flag(self, app) -> None:
        app.config["connected_catalog"] = True
        app.save()

    def _wait_for_upload_completion(self, feed_id, upload_id):
        wait_time = 5
        max_wait_time = 15 * 60
        total_wait_time = 0
        attempt = 1

        while total_wait_time < max_wait_time:
            upload_complete = self.get_upload_status_by_feed(feed_id, upload_id)
            if upload_complete:
                return True

            print(
                f"Attempt {attempt}: Waiting {wait_time} seconds "
                f"to get feed: {feed_id} upload {upload_id} status."
            )
            time.sleep(wait_time)
            total_wait_time += wait_time
            wait_time = min(wait_time * 2, 20)
            attempt += 1

        logger.error(
            f"Exceeded max wait time for upload completion. "
            f"Feed ID: {feed_id}, Upload ID: {upload_id}"
        )
        return False

    def upload_batch(self, catalog_id: str, payload: dict):
        """
        Sends the prepared payload to the client for batch upload.

        :param catalog_id: The ID of the Facebook catalog.
        :param payload: The prepared payload containing batch requests.
        :return: The response from the client.
        """
        print(
            f"Sending batch payload with {len(payload.get('requests', []))} requests."
        )
        return self.client.upload_items_batch(catalog_id, payload)


class TemplateService:
    def __init__(self, client: TemplatesRequestsInterface):
        self.client = client

    def create_template_message(
        self,
        waba_id: str,
        name: str,
        category: str,
        components: List[Any],
        language: str,
    ) -> Dict[str, Any]:
        return self.client.create_template_message(
            waba_id=waba_id,
            name=name,
            category=category,
            components=self._clean_components(components),
            language=language,
        )

    def get_template_analytics(
        self, waba_id: str, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self.client.get_template_analytics(waba_id=waba_id, fields=fields)

    def enable_template_insights(self, waba_id: str) -> Dict[str, Any]:
        return self.client.enable_template_insights(waba_id=waba_id)

    def list_template_messages(self, waba_id: str) -> Dict[str, Any]:
        return self.client.list_template_messages(waba_id)

    def get_template_namespace(self, waba_id: str) -> str:
        return self.client.get_template_namespace(waba_id)

    def update_template_message(
        self, message_template_id: str, name: str, components: str
    ) -> Dict[str, Any]:
        return self.client.update_template_message(
            message_template_id, name, components
        )

    def delete_template_message(self, waba_id: str, name: str) -> Dict[str, Any]:
        response = self.client.delete_template_message(waba_id, name)
        # TODO: check what value retuned if succes delete
        return response

    def _clean_components(self, components):
        if isinstance(components, dict):
            return {k: self._clean_components(v) for k, v in components.items()}
        elif isinstance(components, list):
            return [self._clean_components(item) for item in components]
        elif isinstance(components, str):
            return self._clean_text(components)
        else:
            return components

    def _clean_text(self, text):
        # Replace non-breaking spaces with normal spaces
        text = text.replace("\xa0", " ")
        return text.strip()

    def create_library_template_message(
        self,
        app: App,
        template_data: dict,
    ) -> Dict[str, Any]:
        waba_id = app.config["wa_waba_id"]
        return self.client.create_library_template_message(
            waba_id=waba_id,
            template_data=template_data,
        )


class PhotoAPIService:
    def __init__(self, client: PhotoAPIRequestsInterface):
        self.client = client

    def create_upload_session(self, file_length: int, file_type: str) -> str:
        return self.client.create_upload_session(file_length, file_type)

    def upload_photo(
        self, upload_session_id: str, photo: Any, is_uploading: bool = False
    ) -> str:
        return self.client.upload_photo(upload_session_id, photo, is_uploading)

    def set_photo(self, photo: Any, phone_number_id: str) -> requests.Response:
        return self.client.set_photo(photo, phone_number_id)

    def upload_session(
        self, upload_session_id: str, file_type: str, data: bytes
    ) -> dict:
        return self.client.upload_session(upload_session_id, file_type, data)


class PhoneNumbersService:
    def __init__(self, client: PhoneNumbersRequestsInterface):
        self.client = client

    def get_phone_numbers(self, waba_id: str) -> List[Dict[str, Any]]:
        return self.client.get_phone_numbers(waba_id)

    def get_phone_number(self, phone_number_id: str) -> Dict[str, Any]:
        return self.client.get_phone_number(phone_number_id)


class CloudProfileService:
    def __init__(self, client: CloudProfileRequestsInterface):
        self.client = client

    def get_profile(self) -> Dict[str, Any]:
        return self.client.get_profile()

    def set_profile(self, **kwargs) -> Dict[str, Any]:
        return self.client.set_profile(**kwargs)

    def delete_profile_photo(self) -> None:
        return self.client.delete_profile_photo()


class BusinessMetaService:
    def __init__(self, client: BusinessMetaRequestsInterface):
        self.client = client

    def exchange_auth_code_to_token(self, auth_code: str) -> Dict[str, Any]:
        return self.client.exchange_auth_code_to_token(auth_code)

    def get_waba_info(
        self, fields: str, user_access_token: str, waba_id: str
    ) -> Dict[str, Any]:
        return self.client.get_waba_info(fields, user_access_token, waba_id)

    def assign_system_user(self, waba_id: str, permission: str) -> Dict[str, Any]:
        return self.client.assign_system_user(waba_id, permission)

    def share_credit_line(self, waba_id: str, waba_currency: str) -> Dict[str, Any]:
        return self.client.share_credit_line(waba_id, waba_currency)

    def subscribe_app(self, waba_id: str) -> Dict[str, Any]:
        return self.client.subscribe_app(waba_id)

    def register_phone_number(
        self, phone_number_id: str, user_access_token: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self.client.register_phone_number(
            phone_number_id, user_access_token, data
        )

    def configure_whatsapp_cloud(
        self, auth_code: str, waba_id: str, phone_number_id: str, waba_currency: str
    ) -> Dict[str, Any]:
        # Exchanges auth code for user access token
        user_access_token = self.exchange_auth_code_to_token(auth_code).get(
            "access_token"
        )
        # Retrieves WABA information including business ID and message template namespace
        fields = "on_behalf_of_business_info,message_template_namespace"
        waba_info = self.get_waba_info(fields, user_access_token, waba_id)
        business_id = waba_info.get("on_behalf_of_business_info").get("id")
        message_template_namespace = waba_info.get("message_template_namespace")
        # Assigns system user to the WABA with MANAGE permission
        self.assign_system_user(waba_id, permission="MANAGE")
        # Shares the credit line and retrieves allocation configuration ID
        allocation_config_id = self.share_credit_line(waba_id, waba_currency).get(
            "allocation_config_id"
        )
        # Subscribes the app to the WABA
        self.subscribe_app(waba_id)

        return {
            "user_access_token": user_access_token,
            "business_id": business_id,
            "message_template_namespace": message_template_namespace,
            "allocation_config_id": allocation_config_id,
        }
