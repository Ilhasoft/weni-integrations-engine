import concurrent.futures
import pandas as pd
import io
import dataclasses
import threading
import re

from dataclasses import dataclass

from typing import List

from tqdm import tqdm
from queue import Queue

from marketplace.clients.exceptions import CustomAPIException


@dataclass
class FacebookProductDTO:
    id: str
    title: str
    description: str
    availability: str
    status: str
    condition: str
    price: str
    link: str
    image_link: str
    brand: str
    sale_price: str
    product_details: dict  # TODO: Implement ProductDetailsDTO


class DataProcessor:
    def __init__(self):
        self.max_workers = 100
        self.progress_lock = threading.Lock()

    @staticmethod
    def clean_text(text: str) -> str:
        """Cleans up text by removing HTML tags, replacing quotes with empty space,
        replacing commas with semicolons, and normalizing whitespace."""
        # Remove HTML tags
        text = re.sub(r"<[^>]*>", "", text)
        # Replace double and single quotes with empty space
        text = text.replace('"', "").replace("'", " ")
        # Replace commas with semicolons
        text = text.replace(",", ";")
        # Normalize new lines and carriage returns to space and remove excessive whitespace
        text = re.sub(r"\s+", " ", text.strip())
        # Remove bullet points
        text = text.replace("•", "")
        return text

    @staticmethod
    def extract_fields(
        store_domain, product_details, availability_details, brand_name
    ) -> FacebookProductDTO:
        price = (
            availability_details["price"]
            if availability_details["price"] is not None
            else 0
        )
        list_price = (
            availability_details["list_price"]
            if availability_details["list_price"] is not None
            else 0
        )

        image_url = (
            product_details.get("imagemUrls", [])[0].get("ImageUrl")
            if product_details.get("imagemUrls")
            else product_details.get("imagem_placeholder")
        )
        sku_id = product_details["id"]
        product_url = (
            f"https://{store_domain}{product_details.get('link')}?idsku={sku_id}"
        )
        description = (
            product_details["informacoes"]
            if product_details["informacoes"] != ""
            else product_details["descricao"]
        )
        title = product_details["descricao"].title()
        # Applies the .title() before clearing the text
        title = title[:200].title()
        description = description[:9999].title()
        # Clean title and description
        title = DataProcessor.clean_text(title)
        description = DataProcessor.clean_text(description)

        availability = availability_details["is_available"]
        status = "Active" if availability == "in stock" else "archived"

        return FacebookProductDTO(
            id=sku_id,
            title=title,
            description=description,
            availability=availability,
            status=status,
            condition="new",
            price=list_price,
            link=product_url,
            image_link=image_url,
            brand=brand_name,
            sale_price=price,
            product_details=product_details,
        )

    def process_product_data(
        self,
        skus_ids,
        service,
        domain,
        store_domain,
        rules,
        update_product=False,
    ) -> List[FacebookProductDTO]:
        self.queue = Queue()
        self.results = []
        self.service = service
        self.domain = domain
        self.store_domain = store_domain
        self.rules = rules
        self.update_product = update_product
        self.invalid_products_count = 0

        # Preparing the tqdm progress bar
        print("Initiated process of product treatment:")
        self.progress_bar = tqdm(
            total=len(skus_ids),
            desc="[✓:0, ✗:0]",
            ncols=0,
        )

        # Initializing the queue with SKUs
        for sku_id in skus_ids:
            self.queue.put(sku_id)

        # Starting the workers
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = [executor.submit(self.worker) for _ in range(self.max_workers)]

        # Waiting for all the workers to finish
        for future in futures:
            future.result()

        self.progress_bar.close()

        return self.results

    def worker(self):
        while not self.queue.empty():
            sku_id = self.queue.get()
            result = self.process_single_sku(sku_id)

            with self.progress_lock:
                if result:
                    self.results.extend(result)
                    valid_count = len(result)
                    # Updates progress for each SKU processed, valid or not.
                    self.progress_bar.update(valid_count)

                self.progress_bar.set_description(
                    f"[✓:{len(self.results)}, ✗:{self.invalid_products_count}]"
                )

    def process_sku_id(self, product):
        facebook_products = []

        sellers = product.get("produto_estoque_precos")
        for seller in sellers:
            try:
                brand = self.service.get_brand(product.get("marca_id"))
                brand_name = brand.get("data").get("descricao")
            except CustomAPIException as e:
                if e.status_code == 404:
                    print(f"Brand id {product.get('marca_id')} not found. Skipping...")
                elif e.status_code == 500:
                    print(
                        f"Brand id {product.get('marca_id')} returned status: {e.status_code}. Skipping..."
                    )

                brand_name = "N/A"
                print(
                    f"An error {e} ocurred on get_product_details. Brand id:{product.get('marca_id')}"
                )

            seller_id = seller.get("centro_distribuicao_id")
            availability_details = self._verify_availability(seller)
            # Verificar se é atualização ou primeira inserção para permitir cadastrar itens em estoque
            # ou indisponiveis

            product_dto = DataProcessor.extract_fields(
                store_domain=self.store_domain,
                product_details=product,
                availability_details=availability_details,
                brand_name=brand_name,
            )
            if not self._validate_product_dto(product_dto):
                continue

            params = {"seller_id": seller_id}
            all_rules_applied = True
            for rule in self.rules:
                if not rule.apply(product_dto, **params):
                    all_rules_applied = False
                    break

            if all_rules_applied:
                facebook_products.append(product_dto)

        return facebook_products

    @staticmethod
    def products_to_csv(products: List[FacebookProductDTO]) -> io.BytesIO:
        print("Generating CSV file")
        product_dicts = [dataclasses.asdict(product) for product in products]
        df = pd.DataFrame(product_dicts)
        df = df.drop(columns=["product_details"])
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding="utf-8")
        buffer.seek(0)
        print("CSV file successfully generated in memory")
        return buffer

    @staticmethod
    def product_to_csv_line(product: FacebookProductDTO) -> str:
        product_dict = dataclasses.asdict(product)
        df = pd.DataFrame([product_dict])
        df = df.drop(columns=["product_details"])
        csv_line = df.to_csv(index=False, header=False, encoding="utf-8").strip()
        return csv_line

    @staticmethod
    def clear_csv_buffer(buffer: io.BytesIO):
        buffer.close()

    @staticmethod
    def convert_dtos_to_dicts_list(dtos: List[FacebookProductDTO]) -> List[dict]:
        print("Converting DTO's into dictionary.")
        dicts_list = []
        for dto in dtos:
            dto_dict = dataclasses.asdict(dto)
            dto_dict.pop("product_details", None)
            dicts_list.append(dto_dict)

        print("Products successfully converted to dictionary.")
        return dicts_list

    def _validate_product_dto(self, product_dto: FacebookProductDTO) -> bool:
        """
        Verifies that all required fields in the FacebookProductDTO are filled in.
        Returns True if the product is valid, False otherwise.
        """
        required_fields = [
            "id",
            "title",
            "description",
            "availability",
            "status",
            "condition",
            "link",
            "image_link",
            "brand",
        ]

        if (
            product_dto.availability == "in stock" and not product_dto.price
        ):  # None or 0
            print(
                f"Product {product_dto.id} in stock without a valid price, ignoring the product."
            )
            return False

        for field in required_fields:
            if not getattr(product_dto, field, None):
                print(
                    f"Product {product_dto.id} without the field: {field}, ignoring the product."
                )
                return False

        return True

    def _verify_availability(self, seller):
        if seller.get("estoque") > 0:
            is_available = "in stock"
        else:
            is_available = "out of stock"

        return {
            "is_available": is_available,
            "price": seller.preco,
            "list_price": seller.preco,
        }
