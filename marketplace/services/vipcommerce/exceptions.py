from rest_framework import status  # TODO: Create status enumeration class
from rest_framework.exceptions import APIException


class NoVipCommerceAppConfiguredException(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "There is no Vip Commerce App configured."
    default_code = "no_vipcommerce_app_configured"


class MultipleVipCommerceAppsConfiguredException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Multiple Vip Commerce Apps are configured, which is not expected."
    default_code = "multiple_vipcommerce_apps_configured"


class CredentialsValidationError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The credentials provided are invalid."
    default_code = "invalid_credentials"


class UnexpectedFacebookApiResponseValidationError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Unexpected response from Facebook API."
    default_code = "unexpected_response_facebook_api"
