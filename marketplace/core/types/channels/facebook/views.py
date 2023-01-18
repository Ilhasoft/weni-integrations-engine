from rest_framework.decorators import action
from rest_framework.response import Response

from .serializers import FacebookSerializer, FacebookConfigureSerializer
from marketplace.core.types import views
from . import type as type_


class FacebookViewSet(views.BaseAppTypeViewSet):

    serializer_class = FacebookSerializer

    def get_queryset(self):
        return super().get_queryset().filter(code=type_.FacebookType.code)

    def perform_create(self, serializer):
        serializer.save(code=type_.FacebookType.code)

    @action(detail=True, methods=["PATCH"])
    def configure(self, request, **kwargs):
        """
        Adds a config on specified App and create a channel on weni-flows
        """
        self.serializer_class = FacebookConfigureSerializer
        serializer = self.get_serializer(self.get_object(), data=request.data)
        serializer.is_valid(raise_exception=True)

        self.perform_update(serializer)

        return Response(serializer.data)
