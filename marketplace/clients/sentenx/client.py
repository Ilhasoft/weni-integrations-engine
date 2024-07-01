from django.conf import settings

from marketplace.clients.base import RequestClient


class SentenXClient(RequestClient):
    def __init__(self):
        self.base_url = settings.SEXTENX_URL

    def send_products(self, products):
        url = f"{self.base_url}/products/batch"

        response = self.make_request(
            url,
            method="PUT",
            headers=self.authentication_instance.headers,
            json=products,
        )
        return response
