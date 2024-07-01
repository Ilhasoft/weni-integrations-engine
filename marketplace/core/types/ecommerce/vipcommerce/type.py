from marketplace.applications.models import App
from ..base import EcommerceAppType
from .views import VipCommerceViewSet


class VipCommerceType(EcommerceAppType):
    view_class = VipCommerceViewSet
    code = "vip"
    flows_type_code = None
    name = "Vip Commerce"
    description = "vipcommerce.data.description"
    summary = "vipcommerce.data.summary"
    bg_color = None
    developer = "Weni"
    config_design = "pre-popup"
    platform = App.PLATFORM_VIP

    def can_add(self, project_uuid: str) -> bool:
        return not App.objects.filter(
            code=self.code, project_uuid=project_uuid
        ).exists()
