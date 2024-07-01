from typing import Dict, Any, List
from abc import ABC, abstractmethod


class VipCommerceClientInterface(ABC):
    @abstractmethod
    def list_active_sellers(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_all_products(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_all_active_products(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_brand(self) -> List[Dict[str, Any]]:
        pass
