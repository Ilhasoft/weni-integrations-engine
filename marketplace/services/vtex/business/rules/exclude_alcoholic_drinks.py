from .interface import Rule
from marketplace.services.vtex.utils.data_processor import FacebookProductDTO


class ExcludeAlcoholicDrinks(Rule):
    """
    Rule for excluding alcoholic drinks from the product list.

    This rule checks if a given product belongs to the category of alcoholic drinks
    and excludes it from the list if it does. The categories defining alcoholic drinks
    are specified in the ALCOHOLIC_DRINKS_CATEGORIES set.

    Attributes:
        ALCOHOLIC_DRINKS_CATEGORIES (set): A set of category names that identify alcoholic drinks.
    """

    ALCOHOLIC_DRINKS_CATEGORIES = {
        "bebida alcoólica",
        "bebidas alcoólicas",
        "vinos y licores",
    }

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
        """
        Checks if the product belongs to any of the alcoholic drinks categories.

        This method compares the product's categories with the predefined set of
        alcoholic drinks categories to determine if it is an alcoholic drink.

        Args:
            product (FacebookProductDTO): The product DTO to be checked.

        Returns:
            bool: True if the product belongs to alcoholic drinks category, False otherwise.
        """
        product_categories = set(
            category.lower()
            for category in product.product_details.get(
                "ProductCategories", {}
            ).values()
        )
        return bool(self.ALCOHOLIC_DRINKS_CATEGORIES.intersection(product_categories))
