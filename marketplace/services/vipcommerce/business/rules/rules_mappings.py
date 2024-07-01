# marketplace/services/vtex/business/rules/rule_mappings.py
from .currency_br import CurrencyBRL
from .exclude_alcoholic_drinks import ExcludeAlcoholicDrinks
from .unifies_id_with_seller import UnifiesIdWithSeller


RULE_MAPPINGS = {
    "currency_pt_br": CurrencyBRL,
    "exclude_alcoholic_drinks": ExcludeAlcoholicDrinks,
    "unifies_id_with_seller": UnifiesIdWithSeller,
}
