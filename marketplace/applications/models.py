from typing import TYPE_CHECKING, Generator

from django.db import models
from django.db.models import Q
from django.db.models.constraints import UniqueConstraint
from django.utils.translation import ugettext_lazy as _

from marketplace.core.models import AppTypeBaseModel

if TYPE_CHECKING:
    from marketplace.core.types.base import AppType


class App(AppTypeBaseModel):
    name: str = None
    description: str = None
    summary: str = None
    flows_type_code: str = None
    # TODO: Add `icon` property

    PLATFORM_IA = "IA"
    PLATFORM_WENI_FLOWS = "WF"
    PLATFORM_RC = "RC"
    PLATFORM_VTEX = "VT"
    PLATFORM_VIP = "VP"

    PLATFORM_CHOICES = (
        (PLATFORM_IA, "inteligence-artificial"),
        (PLATFORM_WENI_FLOWS, "weni-flows"),
        (PLATFORM_RC, "rocketchat"),
        (PLATFORM_VTEX, "vtex"),
    )

    config = models.JSONField(default=dict)
    project_uuid = models.UUIDField("Project UUID")
    platform = models.CharField(choices=PLATFORM_CHOICES, max_length=2)
    flow_object_uuid = models.UUIDField(null=True, unique=True)
    configured = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("App")
        verbose_name_plural = _("Apps")

    def __str__(self) -> str:
        return self.code

    def __init__(self, *args, **kwargs):
        """Copy some properties from their respective AppType"""
        super().__init__(*args, **kwargs)
        app_type = self.apptype
        self.name = app_type.name
        self.description = app_type.description
        self.summary = app_type.summary
        self.flows_type_code = app_type.flows_type_code
        # TODO: Add `icon` property


class AppTypeAsset(AppTypeBaseModel):
    ASSET_TYPE_IMAGE_BANNER = "IB"
    ASSET_TYPE_ICON = "IC"
    ASSET_TYPE_ATTACHMENT = "AT"
    ASSET_TYPE_LINK = "LK"

    ASSET_TYPE_CHOICES = (
        (ASSET_TYPE_IMAGE_BANNER, "Image Banner"),
        (ASSET_TYPE_ICON, "Icon"),
        (ASSET_TYPE_ATTACHMENT, "Attachment"),
        (ASSET_TYPE_LINK, "Link"),
    )

    asset_type = models.CharField("Type", choices=ASSET_TYPE_CHOICES, max_length=2)
    attachment = models.FileField(null=True, blank=True)
    url = models.CharField(max_length=2047, null=True, blank=True)
    description = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "App Type Asset"
        verbose_name_plural = "App Type Assets"
        constraints = [
            UniqueConstraint(
                fields=["asset_type", "code"],
                condition=Q(asset_type="IC"),
                name="unique_asset_type_icon_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.apptype.name} - {(self.code).upper()} - {dict(self.ASSET_TYPE_CHOICES).get(self.asset_type)}"


class AppTypeFeatured(AppTypeBaseModel):
    priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "AppType Featured"
        verbose_name_plural = "AppType Featureds"
        constraints = [
            UniqueConstraint(fields=["code"], name="unique_app_type_featured_code")
        ]

    def __str__(self) -> str:
        return self.apptype.name

    @classmethod
    def get_apptype_featureds(cls) -> Generator[None, None, "AppType"]:
        for featured in cls.objects.order_by("priority"):
            yield featured.apptype
