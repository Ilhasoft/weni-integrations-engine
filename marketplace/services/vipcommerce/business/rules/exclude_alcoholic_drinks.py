from .interface import Rule
from marketplace.services.vtex.utils.data_processor import FacebookProductDTO


class ExcludeAlcoholicDrinks(Rule):
    def apply(self, product: FacebookProductDTO, **kwargs) -> bool:
        """
        Determines if the product should be excluded based on its categories.

        Args:
            product (FacebookProductDTO): The product DTO to be checked.

        Returns:
            bool: True if the product does not belong to alcoholic drinks category, False otherwise.
        """
        return not self._is_alcoholic_drink(product)

    def _is_alcoholic_drink(self, product: FacebookProductDTO) -> bool:
        return bool(product.product_details.get("bebida_alcoolica"))
