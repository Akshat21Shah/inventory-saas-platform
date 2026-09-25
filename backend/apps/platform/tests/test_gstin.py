"""GSTIN rules (spec 5.1): format, state, PAN, check character, clean-up, duplicates, and the same
rules on onboarding, super admin edits and the distributor's own business settings.

Every sample below has a valid check character unless its comment says otherwise.
"""

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.platform import tenant_services
from apps.platform.models import Tenant, TenantBranding, TenantProfile
from apps.platform.validators import gstin_check_char, gstin_format_error, normalize_gstin
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
P = "/api/v1/platform"
HINT = "Check for mix-ups like O/0, I/1 or S/5."
CHECK_36 = gstin_check_char("36AAGCK7315R1Z")


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin():
    return make_super_admin("root@platform.example.com")


@pytest.fixture
def api(admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def onboard(api, run, gstin, *, state=None, slug="gst-test"):
    body = {
        "name": "GST Test Traders",
        "legal_name": "GST Test Traders LLP",
        "gstin": gstin,
        "state_code": state if state is not None else normalize_gstin(gstin)[:2],
        "address_line1": "1 Test Road",
        "city": "Bengaluru",
        "pincode": "560001",
        "email": "office@gst-test.example.com",
        "phone": "08012345678",
        "slug": slug,
        "owner_email": f"owner@{slug}.example.com",
    }
    return run(api.post, f"{P}/tenants/", body, format="json")


def field_error(response, field):
    assert response.status_code == 400, response.json()
    return " ".join(response.json()["error"]["details"]["fields"][field])


ACCEPTED = [
    ("36AAGFK7315R1ZQ", "Telangana"),
    ("37AAGFK7315R1ZO", "Andhra Pradesh"),
    ("38AAGFK7315R1ZM", "Ladakh"),
    ("29AAGFK7315RAZC", "13th character a letter"),
    ("29AAGFK7315RDZ9", "check character is a digit"),
    ("29AAGCK7315R1ZR", "PAN holder type C (company)"),
    ("29AAGPK7315R1Z0", "PAN holder type P (person)"),
]

REJECTED = [
    # (GSTIN, field, words the message must contain)
    ("28AAGFK7315R1ZN", "gstin", "State code 28 (Andhra Pradesh (before 2014)) is no longer used"),
    ("25AAGFK7315R1ZT", "gstin", "State code 25 (Daman and Diu (before 2020)) is no longer used"),
    ("00AAGFK7315R1Z5", "gstin", "(00) are not a GST state code"),
    ("99AAGFK7315R1ZE", "gstin", "(99) are not a GST state code"),
    ("29AAGFK7315R0ZM", "gstin", "Character 13 is the registration number: 1 to 9 or a letter"),
    ("29AAGXK7315R1ZK", "gstin", "Character 6 (X) is the PAN holder type"),
    ("29AAGF17315R1Z4", "gstin", "Characters 3 to 12 are the PAN"),
    ("29AAGFK7315R1ZA", "gstin", f"the check character) does not match. {HINT}"),  # bad check
    ("29AAGFK7315R1YN", "gstin", "Character 14 must be Z"),
    ("29AAGFK7315R1Z", "gstin", "A GSTIN has 15 characters. This one has 14."),
    ("29AAGFK7315R1ZLX", "gstin", "A GSTIN has 15 characters. This one has 16."),
    ("29AAGFK-7315R1Z", "gstin", "only letters and digits"),
    ("2XAAGFK7315R1ZL", "gstin", "The first 2 characters are the state code"),
]


# --- The validator ------------------------------------------------------------------------------


@pytest.mark.parametrize(("gstin", "_why"), ACCEPTED)
def test_format_accepts(gstin, _why):
    assert gstin_format_error(gstin) is None


@pytest.mark.parametrize(
    ("gstin", "expected"),
    [(g, words) for g, _f, words in REJECTED if not g.startswith(("28", "25", "00", "99"))],
)
def test_format_names_the_wrong_part(gstin, expected):
    assert expected in (gstin_format_error(gstin) or "")


@pytest.mark.parametrize(
    "raw", [" 29AAGFK7315R1ZL ", "29aagfk7315r1zl", "29 AAGFK 7315R 1ZL", "29\tAAGFK7315R 1ZL\n"]
)
def test_input_is_cleaned_before_validation(raw):
    assert normalize_gstin(raw) == "29AAGFK7315R1ZL"
    assert gstin_format_error(normalize_gstin(raw)) is None


# --- Onboarding ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("gstin", "_why"), ACCEPTED)
def test_onboarding_accepts(api, run, gstin, _why):
    response = onboard(api, run, gstin)
    assert response.status_code == 201, response.json()
    tenant = Tenant.objects.get(gstin=gstin)
    assert (tenant.state_id, tenant.pan) == (gstin[:2], gstin[2:12])


@pytest.mark.parametrize(("gstin", "field", "expected"), REJECTED)
def test_onboarding_rejects_with_a_specific_message(api, run, gstin, field, expected):
    state = gstin[:2] if gstin[:2].isdigit() else "29"
    assert expected in field_error(onboard(api, run, gstin, state=state), field)
    assert not Tenant.objects.filter(slug="gst-test").exists()


def test_other_territory_97_is_accepted(api, run):
    """97 (Other Territory) is an active official state code (product owner, 2026-09-25)."""
    response = onboard(api, run, "97AAGFK7315R1ZI")
    assert response.status_code == 201, response.json()
    assert Tenant.objects.get(slug="gst-test").state_id == "97"


def test_state_must_match_the_gstin(api, run):
    response = onboard(api, run, "27AAGFK7315R1ZP", state="29")  # Karnataka chosen
    assert "must match the first 2 digits of the GSTIN (27)" in field_error(response, "state_code")


@pytest.mark.parametrize("raw", [" 29AAGFK7315R1ZL ", "29aagfk7315r1zl", "29 AAGFK 7315R 1ZL"])
def test_onboarding_cleans_the_gstin(api, run, raw):
    assert onboard(api, run, raw, state="29").status_code == 201
    assert Tenant.objects.get(slug="gst-test").gstin == "29AAGFK7315R1ZL"


def test_pan_is_never_an_input_it_follows_the_gstin(api, run, admin):
    """The PAN is characters 3-12 of the GSTIN. The API has no PAN field, the service ignores a
    PAN change, and a check constraint rejects any row where they differ."""
    assert onboard(api, run, "29AAGFK7316R1ZK").status_code == 201
    tenant = Tenant.objects.get(slug="gst-test")
    assert tenant.pan == "AAGFK7316R"
    tenant_services.update_tenant(tenant.pk, {"pan": "AAGFK7315R"}, by=admin)
    tenant.refresh_from_db()
    assert tenant.pan == "AAGFK7316R"
    with pytest.raises(IntegrityError), transaction.atomic():
        Tenant.objects.filter(pk=tenant.pk).update(pan="AAGFK7315R")


def test_duplicate_gstin_is_rejected_across_tenants(api, run):
    assert onboard(api, run, "29AAGFK7315R1ZL", slug="first-co").status_code == 201
    response = onboard(api, run, "29 aagfk 7315r 1zl", slug="second-co")
    assert "Another business is already registered with this GSTIN." in field_error(
        response, "gstin"
    )


def test_same_pan_in_another_state_is_a_separate_tenant(api, run):
    """A branch registration: same PAN, different state code, different GSTIN."""
    assert onboard(api, run, "29AAGFK7315R1ZL", slug="blr-branch").status_code == 201
    assert onboard(api, run, "27AAGFK7315R1ZP", slug="pune-branch").status_code == 201
    assert Tenant.objects.filter(pan="AAGFK7315R").count() == 2


# --- Edits: super admin and the distributor's own settings --------------------------------------


@pytest.fixture
def tenant(api, run):
    assert onboard(api, run, "29AAGFK7315R1ZL").status_code == 201
    return Tenant.objects.get(slug="gst-test")


@pytest.fixture
def owner_client(tenant):
    user = make_staff_in(tenant, "OWNER", email="owner@gst-test.example.com")
    with tenant_context(tenant.pk):
        TenantProfile.objects.get_or_create()
        TenantBranding.objects.get_or_create(defaults={"display_name": tenant.name})
    Tenant.objects.filter(pk=tenant.pk).update(status=Tenant.Status.ACTIVE)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def _edit_as_admin(api, run, tenant, gstin, state):
    return run(
        api.patch,
        f"{P}/tenants/{tenant.pk}/",
        {"gstin": gstin, "state_code": state},
        format="json",
    )


def _edit_as_owner(client, run, _tenant, gstin, state):
    return run(
        client.patch,
        "/api/v1/settings/business/",
        {"gstin": gstin, "state_code": state},
        format="json",
    )


@pytest.mark.parametrize("who", ["admin", "owner"])
@pytest.mark.parametrize(("gstin", "field", "expected"), REJECTED)
def test_edits_apply_the_same_rules(api, owner_client, run, tenant, who, gstin, field, expected):
    client, edit = (api, _edit_as_admin) if who == "admin" else (owner_client, _edit_as_owner)
    state = gstin[:2] if gstin[:2].isdigit() else "29"
    assert expected in field_error(edit(client, run, tenant, gstin, state), field)
    tenant.refresh_from_db()
    assert tenant.gstin == "29AAGFK7315R1ZL"


@pytest.mark.parametrize("who", ["admin", "owner"])
def test_edits_clean_the_gstin_and_move_the_pan(api, owner_client, run, tenant, who):
    client, edit = (api, _edit_as_admin) if who == "admin" else (owner_client, _edit_as_owner)
    response = edit(
        client, run, tenant, " 36 aagck 7315r 1zCHECK ".replace("CHECK", CHECK_36), "36"
    )
    assert response.status_code == 200, response.json()
    tenant.refresh_from_db()
    assert (tenant.gstin, tenant.pan, tenant.state_id) == (
        f"36AAGCK7315R1Z{CHECK_36}",
        "AAGCK7315R",
        "36",
    )


@pytest.mark.parametrize("who", ["admin", "owner"])
def test_edit_to_another_tenants_gstin_is_rejected(api, owner_client, run, tenant, who):
    assert onboard(api, run, "36AAGFK7315R1ZQ", slug="other-co").status_code == 201
    client, edit = (api, _edit_as_admin) if who == "admin" else (owner_client, _edit_as_owner)
    response = edit(client, run, tenant, "36AAGFK7315R1ZQ", "36")
    assert "Another business is already registered" in field_error(response, "gstin")
