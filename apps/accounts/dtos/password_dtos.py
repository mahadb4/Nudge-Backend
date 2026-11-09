"""Request shapes of the password endpoints. They answer with 202 or 204 and no body of their
own."""

from common.serializers import StrictSerializer, raw_field


class PasswordChangeRequest(StrictSerializer):
    current = raw_field()
    password = raw_field()


class ResetRequest(StrictSerializer):
    email = raw_field()


class ResetConfirmRequest(StrictSerializer):
    token = raw_field()
    password = raw_field()
