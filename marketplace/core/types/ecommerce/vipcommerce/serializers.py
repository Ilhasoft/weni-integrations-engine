from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from marketplace.core.serializers import AppTypeBaseSerializer
from marketplace.applications.models import App


class VipCommerceSerializer(serializers.Serializer):
    domain = serializers.CharField(required=True)
    app_key = serializers.CharField(required=True)
    app_token = serializers.CharField(required=True)
    wpp_cloud_uuid = serializers.UUIDField(required=True)
    uuid = serializers.UUIDField(required=True)
    project_uuid = serializers.UUIDField(required=True)
    store_domain = serializers.CharField(required=True)

    def validate_wpp_cloud_uuid(self, value):
        """
        Check that the wpp_cloud_uuid corresponds to an existing App with code 'wpp-cloud'.
        """
        try:
            App.objects.get(uuid=value, code="wpp-cloud")
        except App.DoesNotExist:
            raise ValidationError(
                "The wpp_cloud_uuid does not correspond to a valid 'wpp-cloud' App."
            )
        return str(value)


class VipCommerceAppSerializer(AppTypeBaseSerializer):
    config = serializers.SerializerMethodField()

    class Meta:
        model = App
        fields = (
            "code",
            "uuid",
            "project_uuid",
            "platform",
            "config",
            "created_by",
            "created_on",
            "modified_by",
        )
        read_only_fields = ("code", "uuid", "platform")

    def get_config(self, obj):
        config = obj.config.copy()
        api_credentials = config.get("api_credentials", {})
        if api_credentials:
            api_credentials["domain"] = "***"
            api_credentials["app_token"] = "***"

        return config
