import io
import logging

from typing import List

from datetime import datetime

from django.db.models import QuerySet

from sentry_sdk import configure_scope

from marketplace.clients.facebook.client import FacebookClient
from marketplace.clients.rapidpro.client import RapidproClient
from marketplace.wpp_products.models import Catalog, ProductUploadLog, UploadProduct
from marketplace.services.facebook.service import (
    FacebookService,
)
from marketplace.services.rapidpro.service import RapidproService


logger = logging.getLogger(__name__)


class BaseProductUploader:
    fb_service_class = FacebookService
    fb_client_class = FacebookClient

    def __init__(self, catalog: Catalog, batch_size=30000):
        self.catalog = catalog
        self.batch_size = batch_size
        self.fb_service = self.initialize_fb_service()
        self.product_manager = ProductBatchFetcher(catalog, self.batch_size)
        self.product_feed = catalog.feeds.first()
        self.feed_id = (
            self.product_feed.facebook_feed_id
            if self.product_feed.facebook_feed_id
            else None
        )
        self.rapidpro_service = RapidproService(RapidproClient())

    def initialize_fb_service(self) -> FacebookService:  # pragma: no cover
        app = self.catalog.app  # Wpp-cloud App
        access_token = app.apptype.get_access_token(app)
        fb_client = self.fb_client_class(access_token)
        return FacebookService(fb_client)

    def process_and_upload(
        self, redis_client, lock_key: str, lock_expiration_time: int
    ):
        """Processes products in batches and uploads them to Meta, renewing the lock."""
        try:
            for products, products_ids in self.product_manager:
                csv_content = self.product_manager.convert_to_csv(products)
                if self.send_to_meta(csv_content):
                    self.product_manager.mark_products_as_sent(products_ids)
                    self.log_sent_products(products_ids)
                else:
                    self.product_manager.mark_products_as_error(products_ids)
                del csv_content
                redis_client.expire(lock_key, lock_expiration_time)
        except Exception as e:
            logger.error(
                f"Error on 'process_and_upload' {str(self.catalog.vtex_app.uuid)}: {e}",
                exc_info=True,
                stack_info=True,
            )
            self.product_manager.mark_products_as_error(products_ids)

    def send_to_meta(self, csv_content: io.BytesIO) -> bool:
        """To be implemented by subclasses."""
        raise NotImplementedError

    def log_sent_products(self, product_ids: List[str]):
        """Logs the successfully sent products to the log table."""
        for product_id in product_ids:
            sku_id = self.extract_sku_id(product_id)
            ProductUploadLog.objects.create(
                sku_id=sku_id, vtex_app=self.catalog.vtex_app
            )
        print(f"Logged {len(product_ids)} products as sent.")

    def extract_sku_id(self, product_id: str) -> int:
        """Extract sku_id from facebook_product_id."""
        sku_part = product_id.split("#")[0]
        if sku_part.isdigit():
            return int(sku_part)
        else:
            raise ValueError(f"Invalid SKU ID, error: {sku_part} is not a number")

    def _generate_file_upload_log(
        self, csv_content, exception, file_name, upload_id=None
    ):
        data = dict(
            catalog=self.catalog.name,
            vtex_app=str(self.catalog.vtex_app.uuid),
            feed_id=self.feed_id,
            file_name=file_name,
            upload_id=upload_id,
        )
        generate_log_with_file(csv_content=csv_content, data=data, exception=exception)


class ProductUpdateUploader(BaseProductUploader):
    def send_to_meta(self, csv_content: io.BytesIO) -> bool:
        """Sends the CSV content to Meta and returns the upload status."""
        upload_id = None
        file_name = "DefaultFile.csv"
        try:
            upload_id_in_process = self.fb_service.uploads_in_progress(self.feed_id)
            if upload_id_in_process:
                print(
                    "There is already a feed upload in progress, waiting for completion."
                )
                self.fb_service._wait_for_upload_completion(
                    self.feed_id, upload_id_in_process
                )

            current_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
            file_name = f"update_{current_time}_{self.catalog.name}"
            upload_id = self.fb_service.update_product_feed(
                self.feed_id, csv_content, file_name, update_only=True
            )
            if upload_id is None:
                self._generate_file_upload_log(
                    csv_content=csv_content,
                    exception=ValueError("Feed upload was not complete."),
                    file_name=file_name,
                    upload_id=upload_id,
                )
                return False

            upload_complete = self.fb_service._wait_for_upload_completion(
                self.feed_id, upload_id
            )
            if not upload_complete:
                self._generate_file_upload_log(
                    csv_content=csv_content,
                    exception=TimeoutError(
                        "Upload did not complete within the expected time frame."
                    ),
                    file_name=file_name,
                    upload_id=upload_id,
                )
                return False

            print("Finished updating products to Facebook")
            print("-" * 40)
            return True
        except Exception as e:
            print(
                f"Error sending data to Meta: App: {str(self.catalog.vtex_app.uuid)}. error: {e}"
            )
            self._generate_file_upload_log(
                csv_content=csv_content,
                exception=e,
                file_name=file_name,
                upload_id=upload_id,
            )
            try:
                self.rapidpro_service.create_notification(
                    catalog=self.catalog,
                    incident_name=f"Error sending data to Meta to {self.catalog.name}",
                    exception=e,
                )
            except Exception as error:
                print(f"Error on send notification error to rapidpro: {error}")
            return False


class FirstSyncProductUploader(BaseProductUploader):
    def __init__(self, catalog: Catalog):
        super().__init__(catalog, batch_size=None)

    def send_to_meta(self, csv_content: io.BytesIO) -> bool:
        """Sends the CSV content to Meta and returns the upload status."""
        upload_id = None
        file_name = self.product_feed.name
        try:
            upload_id = self.fb_service.upload_product_feed(
                feed_id=self.feed_id,
                file=csv_content,
                file_name=file_name,
                file_content_type="text/csv",
                update_only=False,
            )

            if upload_id is None:
                self._generate_file_upload_log(
                    csv_content=csv_content,
                    exception=ValueError("Feed upload was not complete."),
                    file_name=file_name,
                    upload_id=upload_id,
                )
                return False

            upload_complete = self.fb_service._wait_for_upload_completion(
                self.feed_id, upload_id
            )
            if not upload_complete:
                self._generate_file_upload_log(
                    csv_content=csv_content,
                    exception=TimeoutError(
                        "Upload did not complete within the expected time frame."
                    ),
                    file_name=file_name,
                    upload_id=upload_id,
                )
                return False

            print("Finished first sync of products to Facebook")
            print("-" * 40)
            return True
        except Exception as e:
            print(
                f"Error sending data to Meta: App: {str(self.catalog.vtex_app.uuid)}. error: {e}"
            )
            self._generate_file_upload_log(
                csv_content=csv_content,
                exception=e,
                file_name=file_name,
                upload_id=upload_id,
            )
            try:
                self.rapidpro_service.create_notification(
                    catalog=self.catalog,
                    incident_name=f"Error sending data to Meta to {self.catalog.name}",
                    exception=e,
                )
            except Exception as error:
                print(f"Error on send notification error to rapidpro: {error}")
            return False


class ProductUploadManager:
    def convert_to_csv(self, products: QuerySet, include_header=True) -> io.BytesIO:
        """Converts products to CSV format in a buffer, optionally including header."""
        header = "id,title,description,availability,status,condition,price,link,image_link,brand,sale_price"
        csv_lines = []

        if include_header:
            csv_lines.append(header)

        for product in products:
            csv_line = escape_quotes(product.data)
            csv_lines.append(csv_line)

        csv_content = "\n".join(csv_lines)

        buffer = io.BytesIO()
        buffer.write(csv_content.encode("utf-8"))
        buffer.seek(0)

        print("CSV buffer successfully generated")
        return buffer

    def mark_products_as_sent(self, product_ids: List[str]):
        updated_count = UploadProduct.objects.filter(
            facebook_product_id__in=product_ids, status="processing"
        ).update(status="success")

        print(f"{updated_count} products successfully marked as sent.")

    def mark_products_as_error(self, product_ids: List[str]):
        updated_count = UploadProduct.objects.filter(
            facebook_product_id__in=product_ids, status="processing"
        ).update(status="error")

        print(f"{updated_count} products marked as error.")


class ProductBatchFetcher(ProductUploadManager):
    def __init__(self, catalog, batch_size):
        self.catalog = catalog
        self.batch_size = batch_size

    def __iter__(self):
        return self

    def __next__(self):
        products = UploadProduct.objects.filter(
            catalog=self.catalog, status="pending"
        ).order_by("modified_on")[: self.batch_size]

        if not products.exists():
            print(f"No more pending products for catalog {self.catalog.name}.")
            raise StopIteration

        product_ids = list(products.values_list("id", flat=True))
        UploadProduct.objects.filter(id__in=product_ids).update(status="processing")
        products = UploadProduct.objects.filter(id__in=product_ids)

        print(f"Products marked as processing: {len(products)}")

        products_ids = list(products.values_list("facebook_product_id", flat=True))
        return products, products_ids


def escape_quotes(text):
    """Replaces quotes with a empty space in the provided text."""
    text = text.replace('"', "").replace("'", " ")
    return text


def generate_log_with_file(csv_content: io.BytesIO, data, exception: Exception):
    """Generates a detailed log entry with the file content for debugging."""
    with configure_scope() as scope:
        scope.add_attachment(
            bytes=csv_content.getvalue(),
            filename=data.get("file_name", "upload.csv"),
            content_type="text/csv",
        )
        # Log the error with details
        logger.error(
            f"Error on upload feed to Meta: {exception}",
            exc_info=True,
            stack_info=True,
            extra=data,
        )
