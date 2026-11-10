from django.urls import path

from apps.crm.api.company_api import CompanyApi, CompanyListApi
from apps.crm.api.contact_api import ContactApi, ContactListApi
from apps.crm.api.stage_api import DealStageApi, DealStageDetailApi, DealStageOrderApi

urlpatterns = [
    path("contacts/", ContactListApi.as_view(), name="contacts"),
    path("contacts/<uuid:contact_id>/", ContactApi.as_view(), name="contact"),
    path("companies/", CompanyListApi.as_view(), name="companies"),
    path("companies/<uuid:company_id>/", CompanyApi.as_view(), name="company"),
    path("deal-stages/", DealStageApi.as_view(), name="deal-stages"),
    path("deal-stages/order/", DealStageOrderApi.as_view(), name="deal-stages-order"),
    path("deal-stages/<uuid:stage_id>/", DealStageDetailApi.as_view(), name="deal-stage"),
]
