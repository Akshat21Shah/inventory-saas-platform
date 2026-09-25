"""Staff management and invitations (spec 5.2, PLAN §3.4, ADR-030)."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Invitation, Membership
from apps.accounts.tests.factories import make_membership, make_staff, make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform.models import FeatureFlag, Plan, Subscription, Tenant, TenantFeature
from apps.platform.tests.factories import TenantFactory
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

PASSWORD = "a-strong-password"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _client(user, tenant):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def owner_a(tenant_a):
    return make_staff_in(tenant_a, "OWNER", email="owner-a@example.com")


@pytest.fixture
def invite(owner_a, tenant_a, django_capture_on_commit_callbacks):
    def _invite(email="new@example.com", role_code="SALES"):
        with django_capture_on_commit_callbacks(execute=True):
            response = _client(owner_a, tenant_a).post(
                "/api/v1/staff/invitations/",
                {"email": email, "role_code": role_code},
                format="json",
            )
        return response

    return _invite


def _token_from_email():
    match = re.search(r"/invite/([A-Za-z0-9_\-]+)", str(mail.outbox[-1].body))
    assert match, mail.outbox[-1].body
    return match.group(1)


def _public(path, data, host):
    return APIClient().post(path, data, format="json", HTTP_X_FORWARDED_HOST=host)


# --- Inviting -----------------------------------------------------------------------------------


@covers("staff-invitations")
def test_owner_invites_by_email_and_the_link_points_at_the_tenant(tenant_a, tenant_b, invite):
    response = invite("Asha@Example.com", "SALES")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["email"] == "asha@example.com"
    assert body["role"] == {"code": "SALES", "name": "Sales"}
    assert body["status"] == "PENDING"
    assert mail.outbox[-1].to == ["asha@example.com"]
    assert "alpha.localhost" in str(mail.outbox[-1].body)
    assert AuditLog.objects.filter(action="staff.invited", tenant=tenant_a).exists()
    # Tenant B sees none of it.
    owner_b = make_staff_in(tenant_b, "OWNER", email="owner-b@example.com")
    assert _client(owner_b, tenant_b).get("/api/v1/staff/invitations/").json()["results"] == []


@pytest.mark.parametrize(
    ("email", "role", "field"),
    [
        ("owner-a@example.com", "SALES", None),  # already an active member
        ("x@example.com", "PLATFORM_ADMIN", "role_code"),
        ("x@example.com", "NOPE", "role_code"),
    ],
)
def test_invalid_invitations(invite, email, role, field):
    response = invite(email, role)
    if field is None:
        assert response.json()["error"]["code"] == "ALREADY_A_MEMBER"
    else:
        assert field in response.json()["error"]["details"]["fields"]


def test_platform_account_email_cannot_be_invited(invite):
    from apps.accounts.tests.factories import make_super_admin

    make_super_admin("root@platform.example.com")
    response = invite("root@platform.example.com", "SALES")
    assert "email" in response.json()["error"]["details"]["fields"]


def test_second_pending_invitation_for_same_email_is_refused(invite):
    assert invite("dup@example.com").status_code == 201
    assert "email" in invite("dup@example.com").json()["error"]["details"]["fields"]


def test_plan_staff_limit_applies_only_when_enforced(settings, tenant_a, invite):
    small = Plan.objects.create(code="SMALL", name="Small", max_staff=1)
    with tenant_context(tenant_a.id):
        Subscription.objects.create(plan=small, starts_at=timezone.now())
        TenantFeature.objects.create(
            flag=FeatureFlag.objects.get(code="subscriptions_enforcement"), enabled=True
        )
    assert invite("one@example.com").status_code == 201  # enforcement off by default
    settings.PLAN_ENFORCEMENT_ENABLED = True
    cache.clear()
    assert invite("two@example.com").json()["error"]["code"] == "PLAN_LIMIT_REACHED"


@covers("staff-invitation-resend", "staff-invitation-revoke")
def test_resend_replaces_the_link_and_revoke_kills_it(
    tenant_a, tenant_b, invite, owner_a, django_capture_on_commit_callbacks
):
    invitation_id = invite().json()["id"]
    old_token = _token_from_email()
    owner_b = make_staff_in(tenant_b, "OWNER", email="owner-b@example.com")
    assert (
        _client(owner_b, tenant_b)
        .post(f"/api/v1/staff/invitations/{invitation_id}/resend/")
        .status_code
        == 404
    )
    assert (
        _client(owner_b, tenant_b)
        .post(f"/api/v1/staff/invitations/{invitation_id}/revoke/")
        .status_code
        == 404
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert (
            _client(owner_a, tenant_a)
            .post(f"/api/v1/staff/invitations/{invitation_id}/resend/")
            .status_code
            == 200
        )
    new_token = _token_from_email()
    assert new_token != old_token
    assert (
        _public(
            "/api/v1/auth/invitations/preview/", {"token": old_token}, "alpha.localhost"
        ).status_code
        == 400
    )
    assert (
        _public(
            "/api/v1/auth/invitations/preview/", {"token": new_token}, "alpha.localhost"
        ).status_code
        == 200
    )

    revoked = _client(owner_a, tenant_a).post(f"/api/v1/staff/invitations/{invitation_id}/revoke/")
    assert revoked.json()["status"] == "REVOKED"
    assert (
        _public(
            "/api/v1/auth/invitations/preview/", {"token": new_token}, "alpha.localhost"
        ).json()["error"]["code"]
        == "TOKEN_INVALID"
    )


# --- Accepting ----------------------------------------------------------------------------------


@covers("auth-invitation-preview", "auth-invitation-accept")
def test_new_person_accepts_and_is_signed_in_to_that_tenant_only(tenant_a, invite):
    invite("asha@example.com", "WAREHOUSE")
    token = _token_from_email()
    wrong_host = _public("/api/v1/auth/invitations/preview/", {"token": token}, "bravo.localhost")
    assert wrong_host.json()["error"]["code"] == "TOKEN_INVALID"  # isolation: only A's subdomain

    preview = _public(
        "/api/v1/auth/invitations/preview/", {"token": token}, "alpha.localhost"
    ).json()
    assert preview["tenant_name"] == tenant_a.name
    assert preview["role"]["code"] == "WAREHOUSE"
    assert preview["existing_account"] is False

    weak = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Asha", "password": "123"},
        "alpha.localhost",
    )
    assert "password" in weak.json()["error"]["details"]["fields"]
    accepted = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Asha Rao", "password": "a-new-strong-passphrase"},
        "alpha.localhost",
    )
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["status"] == "authenticated"
    assert AccessToken(accepted.json()["access"])["tid"] == str(tenant_a.pk)
    membership = Membership.objects.unscoped().get(user__email="asha@example.com")
    assert (membership.tenant_id, membership.role.code) == (tenant_a.pk, "WAREHOUSE")
    again = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "x", "password": "a-new-strong-passphrase"},
        "alpha.localhost",
    )
    assert again.json()["error"]["code"] == "TOKEN_INVALID"
    assert AuditLog.objects.filter(action="staff.invitation_accepted", tenant=tenant_a).exists()


def test_existing_staff_member_elsewhere_joins_with_their_password(tenant_a, tenant_b, invite):
    existing = make_staff_in(tenant_b, "OWNER", email="multi@example.com")
    invite("multi@example.com", "ACCOUNTS")
    token = _token_from_email()
    preview = _public(
        "/api/v1/auth/invitations/preview/", {"token": token}, "alpha.localhost"
    ).json()
    assert preview["existing_account"] is True
    wrong = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "password": "nope-nope-nope"},
        "alpha.localhost",
    )
    assert "password" in wrong.json()["error"]["details"]["fields"]
    ok = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "password": PASSWORD},
        "alpha.localhost",
    )
    assert ok.json()["status"] == "authenticated"
    assert Membership.objects.unscoped().filter(user=existing).count() == 2


def test_expired_invitation_cannot_be_used(invite):
    invite()
    token = _token_from_email()
    Invitation.objects.unscoped().update(expires_at=timezone.now() - timedelta(seconds=1))
    assert (
        _public("/api/v1/auth/invitations/preview/", {"token": token}, "alpha.localhost").json()[
            "error"
        ]["code"]
        == "TOKEN_INVALID"
    )


def test_owner_accepting_activates_an_onboarding_tenant(django_capture_on_commit_callbacks):
    from apps.accounts import staff_services
    from apps.accounts.tests.factories import make_super_admin

    tenant = TenantFactory.create(slug="newco", status=Tenant.Status.ONBOARDING)
    admin = make_super_admin()
    with django_capture_on_commit_callbacks(execute=True), tenant_context(tenant.id):
        staff_services.invite_staff(
            email="founder@example.com", role_code="OWNER", invited_by=admin
        )
    token = _token_from_email()
    accepted = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Founder", "password": "a-new-strong-passphrase"},
        "newco.localhost",
    )
    assert accepted.json()["status"] == "authenticated", accepted.json()
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ACTIVE
    assert AuditLog.objects.filter(action="tenant.activated", tenant=tenant).exists()


def test_suspended_tenant_invitations_are_on_hold(tenant_a, invite):
    invite()
    token = _token_from_email()
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    assert (
        _public("/api/v1/auth/invitations/preview/", {"token": token}, "alpha.localhost").json()[
            "error"
        ]["code"]
        == "TENANT_UNAVAILABLE"
    )


# --- Members & owner rules (ADR-030) ------------------------------------------------------------


@covers("staff-list", "staff-detail")
def test_staff_list_and_detail_are_tenant_scoped(tenant_a, tenant_b, owner_a):
    member = make_staff_in(tenant_a, "SALES", email="sales@example.com")
    owner_b = make_staff_in(tenant_b, "OWNER", email="owner-b@example.com")
    emails = {
        m["user"]["email"]
        for m in _client(owner_a, tenant_a).get("/api/v1/staff/").json()["results"]
    }
    assert emails == {"owner-a@example.com", "sales@example.com"}
    membership_id = Membership.objects.unscoped().get(user=member).pk
    assert _client(owner_b, tenant_b).get(f"/api/v1/staff/{membership_id}/").status_code == 404
    patch = _client(owner_b, tenant_b).patch(
        f"/api/v1/staff/{membership_id}/", {"is_active": False}, format="json"
    )
    assert patch.status_code == 404
    assert Membership.objects.unscoped().get(pk=membership_id).is_active


def test_role_change_is_audited(tenant_a, owner_a):
    member = make_staff_in(tenant_a, "SALES", email="sales@example.com")
    membership_id = Membership.objects.unscoped().get(user=member).pk
    response = _client(owner_a, tenant_a).patch(
        f"/api/v1/staff/{membership_id}/", {"role_code": "MANAGER"}, format="json"
    )
    assert response.json()["role"]["code"] == "MANAGER"
    entry = AuditLog.objects.get(action="staff.role_changed")
    assert entry.changes == {"role": ["SALES", "MANAGER"]}


def test_last_active_owner_cannot_be_demoted_or_deactivated(tenant_a, owner_a):
    other = make_staff_in(tenant_a, "MANAGER", email="manager@example.com")
    own_id = Membership.objects.unscoped().get(user=owner_a).pk
    client = _client(owner_a, tenant_a)
    assert (
        client.patch(f"/api/v1/staff/{own_id}/", {"role_code": "MANAGER"}, format="json").json()[
            "error"
        ]["code"]
        == "LAST_OWNER"
    )
    other_id = Membership.objects.unscoped().get(user=other).pk
    assert (
        client.patch(
            f"/api/v1/staff/{other_id}/", {"role_code": "OWNER"}, format="json"
        ).status_code
        == 200
    )
    # With two owners, the first may step down.
    assert (
        client.patch(
            f"/api/v1/staff/{own_id}/", {"role_code": "MANAGER"}, format="json"
        ).status_code
        == 200
    )


def test_nobody_can_deactivate_themselves(tenant_a, owner_a):
    make_staff_in(tenant_a, "OWNER", email="owner2@example.com")
    own_id = Membership.objects.unscoped().get(user=owner_a).pk
    response = _client(owner_a, tenant_a).patch(
        f"/api/v1/staff/{own_id}/", {"is_active": False}, format="json"
    )
    assert "is_active" in response.json()["error"]["details"]["fields"]


def test_deactivated_member_loses_access_immediately(tenant_a, owner_a):
    member = make_staff_in(tenant_a, "SALES", email="sales@example.com")
    member_client = _client(member, tenant_a)
    assert member_client.get("/api/v1/auth/me/").status_code == 200
    membership_id = Membership.objects.unscoped().get(user=member).pk
    _client(owner_a, tenant_a).patch(
        f"/api/v1/staff/{membership_id}/", {"is_active": False}, format="json"
    )
    assert member_client.get("/api/v1/auth/me/").status_code == 401
    assert AuditLog.objects.filter(action="staff.deactivated").exists()


@covers("roles-list", "permissions-list")
def test_role_and_permission_catalogues(tenant_a, tenant_b, owner_a):
    roles = _client(owner_a, tenant_a).get("/api/v1/roles/").json()
    assert {r["code"] for r in roles} == {"OWNER", "MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS"}
    owner_role = next(r for r in roles if r["code"] == "OWNER")
    assert "staff.manage" in owner_role["permissions"]
    perms = _client(owner_a, tenant_a).get("/api/v1/permissions/").json()
    assert not any(p["code"].startswith("platform.") for p in perms)
    owner_b = make_staff_in(tenant_b, "OWNER", email="owner-b@example.com")
    assert _client(owner_b, tenant_b).get("/api/v1/roles/").json() == roles  # system roles only


# --- Permission matrix: only OWNER manages staff ------------------------------------------------

STAFF_ENDPOINTS = [
    ("get", "/api/v1/staff/"),
    ("get", "/api/v1/staff/invitations/"),
    ("post", "/api/v1/staff/invitations/"),
    ("get", "/api/v1/roles/"),
    ("get", "/api/v1/permissions/"),
]


@pytest.mark.parametrize("role", ["MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS"])
@pytest.mark.parametrize(("method", "path"), STAFF_ENDPOINTS)
def test_only_owners_manage_staff(tenant_a, role, method, path):
    user = make_staff_in(tenant_a, role)
    response = getattr(_client(user, tenant_a), method)(
        path, {"email": "x@example.com", "role_code": "SALES"}, format="json"
    )
    assert response.status_code == 403


def test_member_endpoints_forbidden_for_non_owners(tenant_a, owner_a):
    manager = make_staff_in(tenant_a, "MANAGER")
    own_id = Membership.objects.unscoped().get(user=owner_a).pk
    client = _client(manager, tenant_a)
    assert client.get(f"/api/v1/staff/{own_id}/").status_code == 403
    assert (
        client.patch(f"/api/v1/staff/{own_id}/", {"is_active": False}, format="json").status_code
        == 403
    )


def test_staff_management_views_are_marked_impersonation_blocked():
    from apps.accounts.api import staff_views

    for view in (
        staff_views.StaffListView,
        staff_views.StaffDetailView,
        staff_views.InvitationListCreateView,
        staff_views.InvitationResendView,
        staff_views.InvitationRevokeView,
    ):
        assert view.impersonation_blocked is True


def test_reactivating_a_former_member_by_invitation(tenant_a, owner_a, invite):
    former = make_staff(email="former@example.com")
    make_membership(former, tenant_a, "SALES", is_active=False)
    invite("former@example.com", "WAREHOUSE")
    token = _token_from_email()
    ok = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "password": PASSWORD},
        "alpha.localhost",
    )
    assert ok.json()["status"] == "authenticated"
    membership = Membership.objects.unscoped().get(user=former)
    assert membership.is_active and membership.role.code == "WAREHOUSE"
