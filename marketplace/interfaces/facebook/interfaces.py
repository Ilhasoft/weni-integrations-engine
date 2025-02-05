from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple


class ProfileHandlerInterface(ABC):
    @abstractmethod
    def get_profile(self):
        pass

    @abstractmethod
    def set_profile(self):
        pass

    @abstractmethod
    def delete_profile_photo(self):
        pass


class BusinessProfileHandlerInterface(ABC):
    @abstractmethod
    def get_profile(self):
        pass

    @abstractmethod
    def set_profile(self):
        pass


class TemplatesRequestsInterface(ABC):
    @abstractmethod
    def create_template_message(
        self, waba_id: str, name: str, category: str, components: list, language: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_template_analytics(
        self, waba_id: str, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def enable_template_insights(self, waba_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def list_template_messages(self, waba_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_template_namespace(self, waba_id: str) -> str:
        pass

    @abstractmethod
    def update_template_message(
        self, message_template_id: str, name: str, components: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def delete_template_message(self, waba_id: str, name: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def create_library_template_message(
        self, waba_id: str, template_data: dict
    ) -> Dict[str, Any]:
        pass


class PhotoAPIRequestsInterface(ABC):
    @abstractmethod
    def create_upload_session(self, file_length: int, file_type: str) -> str:
        pass

    @abstractmethod
    def upload_photo(
        self, upload_session_id: str, photo: Any, is_uploading: bool = False
    ) -> str:
        pass

    @abstractmethod
    def set_photo(self, photo: Any, phone_number_id: str) -> Any:
        pass

    @abstractmethod
    def upload_session(
        self, upload_session_id: str, file_type: str, data: bytes
    ) -> str:
        pass


class PhoneNumbersRequestsInterface(ABC):
    @abstractmethod
    def get_phone_numbers(self, waba_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_phone_number(self, phone_number_id: str) -> Dict[str, Any]:
        pass


class CloudProfileRequestsInterface(ABC):
    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def set_profile(self, **kwargs) -> Dict[str, Any]:
        pass

    @abstractmethod
    def delete_profile_photo(self) -> None:
        pass


class BusinessMetaRequestsInterface(ABC):
    @abstractmethod
    def exchange_auth_code_to_token(self, auth_code: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_waba_info(
        self, fields: str, user_access_token: str, waba_id: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def assign_system_user(self, waba_id: str, permission: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def share_credit_line(self, waba_id: str, waba_currency: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def subscribe_app(self, waba_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def register_phone_number(
        self, phone_number_id: str, user_access_token: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass


class CatalogsRequestsInterface(ABC):
    @abstractmethod
    def create_catalog(
        self, business_id: str, name: str, category: str = "commerce"
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def destroy_catalog(self, catalog_id: str) -> bool:
        pass

    @abstractmethod
    def create_product_feed(self, product_catalog_id: str, name: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def upload_product_feed(
        self,
        feed_id: str,
        file: Any,
        file_name: str,
        file_content_type: str,
        update_only: bool = False,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def create_product_feed_by_url(
        self,
        product_catalog_id: str,
        name: str,
        feed_url: str,
        file_type: str,
        interval: str,
        hour: int,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_all_upload_status(
        self, feed_id: str, max_attempts: int = 10, wait_time: int = 30
    ) -> Any:
        pass

    @abstractmethod
    def list_products_by_feed(self, feed_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def list_all_products_by_feed(self, feed_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_all_catalogs(
        self, wa_business_id: str
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        pass

    @abstractmethod
    def destroy_feed(self, feed_id: str) -> bool:
        pass

    @abstractmethod
    def get_connected_catalog(self, waba_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def enable_catalog(self, waba_id: str, catalog_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def disable_catalog(self, waba_id: str, catalog_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_catalog_details(self, catalog_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def toggle_cart(
        self, wa_phone_number_id: str, enable: bool = True
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def toggle_catalog_visibility(
        self, wa_phone_number_id: str, make_visible: bool = True
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_wpp_commerce_settings(self, wa_phone_number_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_upload_status_by_feed(self, feed_id: str, upload_id: str) -> bool:
        pass

    @abstractmethod
    def get_uploads_in_progress_by_feed(self, feed_id: str) -> Any:
        pass

    @abstractmethod
    def upload_items_batch(
        self, catalog_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Uploads a batch of items to a catalog.

        :param catalog_id: The ID of the catalog.
        :param payload: The payload containing batch requests.
        :return: A dictionary with the response from the API.
        """
        pass
