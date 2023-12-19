import uuid
from typing import TYPE_CHECKING

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError, PermissionDenied

from marketplace.core.types import views
from .serializers import WhatsAppDemoSerializer
from marketplace.connect.client import ConnectProjectClient, WPPRouterChannelClient
from marketplace.accounts.models import ProjectAuthorization


if TYPE_CHECKING:
    from rest_framework.request import Request  # pragma: no cover


class WhatsAppDemoViewSet(views.BaseAppTypeViewSet):
    serializer_class = WhatsAppDemoSerializer

    def get_queryset(self):
        return super().get_queryset().filter(code=self.type_class.code)

    def perform_create(self, serializer):
        user = self.request.user
        type_class = self.type_class
        app = serializer.save(code=self.type_class.code)

        channel_client = ConnectProjectClient()
        channel_token_client = WPPRouterChannelClient()

        type_class.configure_app(app, user, channel_client, channel_token_client)

    @action(detail=False, methods=["GET"])
    def url(self, request: "Request", **kwargs):
        project_uuid = request.query_params.get("project", None)

        if project_uuid is None:
            raise ValidationError(dict(detail="“project“ is a required parameter"))

        try:
            uuid.UUID(project_uuid)
        except ValueError:
            raise ValidationError(dict(detail=f"“{project_uuid}” is not a valid UUID."))

        permission = request.user.authorizations.filter(
            project_uuid=project_uuid
        ).first()

        if not permission or permission.role == ProjectAuthorization.ROLE_NOT_SETTED:
            raise PermissionDenied(
                detail="You do not have permission to access this project"
            )

        app = self.type_class.apps.filter(project_uuid=project_uuid).first()

        if not app:
            raise NotFound("This project does not have an integrated WhatsApp Demo")

        redirect_url = app.config.get("redirect_url")

        return Response(dict(url=redirect_url))
