import pytest
from django.test import override_settings

from common.testing.isolation import COVERED, EXEMPT, api_routes
from common.tests import views
from common.tests.testapp.models import Widget

pytestmark = [pytest.mark.django_db, pytest.mark.urls("common.tests.urls")]


def test_jwt_tid_claim_activates_tenant_in_context_and_database(
    api_client_for, staff_user, tenant_a
):
    body = api_client_for(staff_user, tenant_a).get("/test-api/whoami/").json()
    assert body == {"tenant": str(tenant_a.id), "db_tenant": str(tenant_a.id)}


def test_token_without_tenant_claim_has_no_tenant(api_client_for, staff_user):
    body = api_client_for(staff_user).get("/test-api/whoami/").json()
    assert body == {"tenant": None, "db_tenant": None}


def test_unauthenticated_request_uses_error_envelope(client):
    response = client.get("/test-api/whoami/")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_domain_error_envelope_and_rollback(api_client_for, staff_user, tenant_a):
    response = api_client_for(staff_user, tenant_a).post(
        "/test-api/errors/?mode=domain", {}, format="json"
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "CREDIT_LIMIT_EXCEEDED",
            "message": "Credit limit exceeded.",
            "details": {"limit": "100.00"},
        }
    }
    assert Widget.objects.unscoped().count() == 0  # the write before the error was rolled back


def test_validation_error_envelope(api_client_for, staff_user, tenant_a):
    response = api_client_for(staff_user, tenant_a).post(
        "/test-api/errors/?mode=validation", {"name": "too-long-name"}, format="json"
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "name" in error["details"]["fields"]
    assert Widget.objects.unscoped().count() == 0


def test_unexpected_error_is_generic_and_rolled_back(api_client_for, staff_user, tenant_a):
    response = api_client_for(staff_user, tenant_a).post(
        "/test-api/errors/?mode=crash", {}, format="json"
    )
    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong. Please try again.",
        "details": {},
    }
    assert "boom" not in response.content.decode()
    assert Widget.objects.unscoped().count() == 0


def test_success_commits(api_client_for, staff_user, tenant_a):
    response = api_client_for(staff_user, tenant_a).post("/test-api/errors/", {}, format="json")
    assert response.status_code == 201
    assert Widget.objects.unscoped().count() == 1


def test_has_permission_fails_closed(api_client_for, staff_user, tenant_a):
    response = api_client_for(staff_user, tenant_a).get("/test-api/guarded/")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_request_id_generated_and_echoed(client):
    generated = client.get("/health/live")
    assert len(generated["X-Request-ID"]) == 32
    echoed = client.get("/health/live", HTTP_X_REQUEST_ID="req-abc-12345")
    assert echoed["X-Request-ID"] == "req-abc-12345"


def test_host_context_prefers_forwarded_host(client):
    response = client.get(
        "/test-api/public/", HTTP_HOST="localhost", HTTP_X_FORWARDED_HOST="sharma.localhost"
    )
    assert response.json() == {"host_kind": "TENANT"}


def test_health_endpoints(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "cache": "ok"}


@override_settings(ROOT_URLCONF="config.urls")
def test_openapi_schema_generates(client, staff_user, api_client_for):
    response = api_client_for(staff_user).get("/api/v1/schema/")
    assert response.status_code == 200
    assert b"Inventory Platform API" in response.content


@override_settings(ROOT_URLCONF="config.urls")
def test_every_api_endpoint_has_isolation_coverage():
    routes = api_routes()
    unnamed = [route for route, name in routes if name is None]
    assert not unnamed, f"API routes must be named: {unnamed}"
    missing = sorted({name for _, name in routes if name} - COVERED - set(EXEMPT))
    assert not missing, f"API routes without a tenant-isolation test: {missing}"


def test_views_module_loaded():
    assert views.CALLS is not None


@override_settings(ROOT_URLCONF="config.urls")
def test_meta_endpoint_is_public_and_tenant_free(client):
    body = client.get("/api/v1/meta/").json()
    assert body == {
        "api_version": "1.0.0",
        "environment": "local",
        "platform_domain": "localhost",
        "display_time_zone": "Asia/Kolkata",
    }
