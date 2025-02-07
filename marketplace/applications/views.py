from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework import views

from marketplace.applications.serializers import AppTypeSerializer, MyAppSerializer
from marketplace.core import types
from marketplace.applications.models import App, AppTypeFeatured
from marketplace.accounts.models import ProjectAuthorization
from marketplace.accounts.permissions import is_crm_user
from marketplace.internal.permissions import CanCommunicateInternally


class AppTypeViewSet(viewsets.ViewSet):
    serializer_class = AppTypeSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def get_serializer(self, *args, **kwargs):
        kwargs["context"] = {"request": self.request}
        return self.serializer_class(*args, **kwargs)

    def list(self, request):
        category = request.query_params.get("category", None)
        apptypes = types.APPTYPES

        if category is not None:
            apptypes = apptypes.filter(
                lambda apptype: apptype.get_category_display()
                == request.query_params.get("category")
            )

        # TODO: remove the "wpp" from this filter when whatsapp leaves beta
        apptypes = apptypes.filter(
            lambda apptype: apptype.code != "wpp" and apptype.code != "generic"
        )

        serializer = self.get_serializer(apptypes.values(), many=True)

        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            apptype = types.APPTYPES.get(pk)
        except KeyError:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(apptype)

        return Response(serializer.data)

    @action(detail=False)
    def featureds(self, request, **kwargs):
        apptypes = AppTypeFeatured.get_apptype_featureds()
        serializer = self.get_serializer(apptypes, many=True)

        return Response(serializer.data)


class MyAppViewSet(viewsets.ReadOnlyModelViewSet):
    lookup_field = "uuid"
    serializer_class = MyAppSerializer
    queryset = App.objects
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        queryset = super().get_queryset()

        query_params = self.request.query_params
        project_uuid = query_params.get("project_uuid")
        configured = query_params.get("configured")

        if not project_uuid:
            raise ValidationError("project_uuid is a required parameter!")

        user = self.request.user

        if not is_crm_user(user):
            try:
                user.authorizations.get(project_uuid=project_uuid)
            except ProjectAuthorization.DoesNotExist:
                raise PermissionDenied()

        queryset = queryset.filter(project_uuid=project_uuid)

        if configured is not None:
            if configured == "true":
                queryset = queryset.filter(configured=True)

            elif configured == "false":
                queryset = queryset.filter(configured=False)

            else:
                raise ValidationError(
                    f"Expected a boolean param in configured, but recived `{configured}`"
                )

        return queryset


class CheckAppIsIntegrated(views.APIView):

    permission_classes = [CanCommunicateInternally]

    def get(self, request):
        project_uuid = request.query_params.get("project_uuid", None)

        if not project_uuid:
            return Response({"error": "project_uuid is required on query params"}, status=status.HTTP_400_BAD_REQUEST)

        apps = App.objects.filter(code="wpp-cloud", project_uuid=project_uuid)

        if not apps.exists():
            return Response({
                "message": "Project with whatsapp integrations not exists",
                "data": {
                    "has_whatsapp": False
                }
            })

        app = apps.first()

        return Response(
                {
                    "message": "Project with whatsapp integrations exists",
                    "data": {
                        "has_whatsapp": True,
                        "wpp_cloud_app_uuid": str(app.uuid),
                        "flows_channel_uuid": str(app.flow_object_uuid)
                    }
                }, status=status.HTTP_200_OK)
