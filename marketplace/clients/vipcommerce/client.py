import json
import os
from typing import Any, Dict, List

from django.conf import settings

from marketplace.clients.base import RequestClient
from marketplace.clients.decorators import retry_on_exception
from marketplace.interfaces.vipcommerce.interfaces import VipCommerceClientInterface


class VipCommerceAuthorization(RequestClient):
    def __init__(self, app_token, domain):
        self.domain = domain
        self.app_token = app_token

    def _get_headers(self):
        headers = {
            "Accept": "application/json",
            "DomainKey": self.domain,
            "Authorization": f"Basic {self.app_token}",
        }
        return headers

    @property
    def _url(self):
        return f"https://{settings.VIPCOMMERCE_URL}/{self.domain}"


class VipCommerceClient(VipCommerceAuthorization, VipCommerceClientInterface):
    @retry_on_exception()
    def is_valid_credentials(self, domain: str) -> bool:
        try:
            url = f"{self._url}/importacao/produtos?limit=1"
            headers = self._get_headers()
            response = self.make_request(url, method="GET", headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    @retry_on_exception()
    def list_active_sellers(self) -> List[Dict[str, Any]]:
        url = f"{self._url}/importacao/centro-distribuicoes"
        headers = self._get_headers()
        response = self.make_request(url, method="GET", headers=headers)
        sellers_data = response.json()
        return sellers_data

    @retry_on_exception()
    def list_all_active_products(self) -> List[Dict[str, Any]]:
        url = f"{self._url}/importacao/produtos"
        headers = self._get_headers()
        params = {"desativado": 0}
        response = self.make_request(url, params=params, method="GET", headers=headers)
        data = response.json().get("data", {})
        arquivo_teste = os.path.join(settings.BASE_DIR, "retorno_active.json")
        with open(arquivo_teste, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
        return data

    @retry_on_exception()
    def list_all_products(self) -> List[Dict[str, Any]]:
        url = f"{self._url}/importacao/produtos"
        headers = self._get_headers()
        response = self.make_request(url, method="GET", headers=headers)
        data = response.json().get("data", {})
        arquivo_teste = os.path.join(settings.BASE_DIR, "retorno_all.json")
        with open(arquivo_teste, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
        return data

    @retry_on_exception()
    def get_brand(self, id) -> List[Dict[str, Any]]:
        url = f"{self._url}/importacao/marcas/{id}"
        headers = self._get_headers()
        response = self.make_request(url, method="GET", headers=headers)
        data = response.json().get("data", {})

        return data
