from django.urls import path

from common.health.api.health_api import HealthApi

urlpatterns = [
    path("health/", HealthApi.as_view(), name="health"),
]
