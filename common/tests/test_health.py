"""GET /api/v1/health/: service unit tests with fake repositories, HTTP tests, and the real
repository on nudge_test."""

import pytest
from rest_framework.test import APIClient

from common.errors import ServiceUnavailable
from common.health.domain.entities import HealthReport
from common.health.dtos.health_dtos import HealthResponse
from common.health.mappers.health_mapper import to_health_response
from common.health.repositories.health_repository import PostgresHealthRepository
from common.health.services.health_service import HealthService
from common.messages import Messages
from config import container

URL = "/api/v1/health/"


class UpRepository:
    def is_database_available(self) -> bool:
        return True


class DownRepository:
    def is_database_available(self) -> bool:
        return False


def test_service_reports_ok():
    assert HealthService(UpRepository()).check() == HealthReport(database_ok=True)


def test_service_raises_when_the_database_is_down():
    with pytest.raises(ServiceUnavailable):
        HealthService(DownRepository()).check()


@pytest.mark.django_db
def test_real_repository_on_the_test_database():
    assert PostgresHealthRepository().is_database_available() is True


@pytest.mark.django_db
def test_health_200():
    response = APIClient().get(URL)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Type"] == "application/json"


def test_health_503_when_the_repository_fails(monkeypatch):
    monkeypatch.setattr(container, "health_service", lambda: HealthService(DownRepository()))
    response = APIClient().get(URL)
    assert response.status_code == 503
    assert response.json() == {
        "code": "COMMON_SERVICE_UNAVAILABLE",
        "detail": Messages.COMMON_SERVICE_UNAVAILABLE.value,
    }
    assert response["Cache-Control"] == "no-store"


def test_health_needs_no_authentication_and_refuses_post(monkeypatch):
    monkeypatch.setattr(container, "health_service", lambda: HealthService(UpRepository()))
    response = APIClient().post(URL, {}, format="json")
    assert response.status_code == 405
    assert response.json()["code"] == "COMMON_METHOD_NOT_ALLOWED"


def test_unknown_api_path_is_json_404():
    response = APIClient().get("/api/v1/does-not-exist/")
    assert response.status_code == 404
    assert response.json()["code"] == "COMMON_NOT_FOUND"


def test_mapper_builds_the_response_dto():
    assert to_health_response(HealthReport(database_ok=True)) == HealthResponse(
        status="ok", database="ok"
    )
    assert to_health_response(HealthReport(database_ok=False)) == HealthResponse(
        status="ok", database="unavailable"
    )


def test_response_dto_has_a_to_dict_helper():
    assert HealthResponse(status="ok", database="ok").to_dict() == {
        "status": "ok",
        "database": "ok",
    }
