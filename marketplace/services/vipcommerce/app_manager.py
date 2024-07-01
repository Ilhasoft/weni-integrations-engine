import uuid

from django.core.exceptions import MultipleObjectsReturned

from marketplace.services.vipcommerce.exceptions import (
    NoVipCommerceAppConfiguredException,
    MultipleVipCommerceAppsConfiguredException,
)
from marketplace.applications.models import App


class AppVipCommerceManager:
    def get_vip_commerce_app_or_error(self, project_uuid):
        try:
            app_vip_commerce = App.objects.get(
                code="vip", project_uuid=str(project_uuid), configured=True
            )
            return app_vip_commerce
        except App.DoesNotExist:
            raise NoVipCommerceAppConfiguredException()
        except MultipleObjectsReturned:
            raise MultipleVipCommerceAppsConfiguredException()

    def initial_sync_products_completed(self, app: App):
        try:
            app.config["initial_sync_completed"] = True
            app.save()
            return True
        except Exception as e:
            raise e

    def get_vip_commerce_app_uuid(self):
        while True:
            new_uuid = str(uuid.uuid4())
            try:
                App.objects.get(uuid=new_uuid)
            except App.DoesNotExist:
                return new_uuid
