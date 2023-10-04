from rest_framework import serializers
from marketplace.core.types.channels.whatsapp_base.mixins import QueryParamsParser


class AnalyticsSerializer(serializers.Serializer):
    start = serializers.CharField()
    end = serializers.CharField()
    fba_template_ids = serializers.ListField()

    def validate(self, data):
        parse_data = QueryParamsParser(data)
        try:
            data["start"] = parse_data.start
            data["end"] = parse_data.end
        except ValueError:
            raise serializers.ValidationError("Date must be in the format MM-DD-YYYY")

        if data["start"] >= data["end"]:
            raise serializers.ValidationError(
                "End date must occur after the start date"
            )

        return data
