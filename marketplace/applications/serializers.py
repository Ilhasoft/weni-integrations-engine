from rest_framework import serializers
from marketplace.applications.types.base import AppType


class ColorSerializer(serializers.Serializer):
    red = serializers.IntegerField()
    green = serializers.IntegerField()
    blue = serializers.IntegerField()
    alpha = serializers.FloatField()


class AppTypeSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    summary = serializers.CharField()
    category = serializers.ChoiceField(choices=AppType.CATEGORY_CHOICES, source="get_category_display")
    icon = serializers.URLField(source="get_icon_url")
    bg_color = ColorSerializer()

    assets = serializers.SerializerMethodField()

    def get_assets(self, obj):
        return [
            {
                "type": asset.get_asset_type_display(),
                "url": asset.attachment.url,
                "description": asset.description,
            }
            for asset in obj.assets
        ]
