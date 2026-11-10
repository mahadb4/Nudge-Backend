"""Request shape of PATCH /auth/me/. Only the fields the client sends are changed."""

from common.serializers import StrictSerializer, raw_field


class ProfileUpdateRequest(StrictSerializer):
    name = raw_field()
    phone = raw_field()
    timezone = raw_field()
    quiet_hours_start = raw_field()
    quiet_hours_end = raw_field()
