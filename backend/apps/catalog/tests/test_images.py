"""Product images (ADR-034): validation, background resizing, stable long-cache URLs, deletion,
tenant isolation, and the worker running under the runtime (RLS) database role."""

import io
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Product, ProductImage, ProductTaxRate, Unit
from apps.catalog.tasks import process_product_image
from common.dates import today_ist
from common.storage import IMMUTABLE, InMemoryStorage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    InMemoryStorage.public_objects.clear()
    yield
    cache.clear()
    InMemoryStorage.objects.clear()
    InMemoryStorage.public_objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def _client(tenant):
    client = APIClient()
    token = issue_tokens(make_staff_in(tenant, "OWNER"), tenant.pk).access
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def _product(tenant, code="IMG-1"):
    with tenant_context(tenant.pk):
        product = Product.objects.create(
            code=code,
            name="Soap",
            unit=Unit.objects.get(code="PCS"),
            hsn_code="3401",
            base_price=Decimal("30"),
        )
        ProductTaxRate.objects.create(
            product=product, gst_rate=Decimal("18"), effective_from=today_ist()
        )
        return product


def _image(size=(2000, 1000), fmt="PNG", color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]
    return SimpleUploadedFile(f"photo.{ext}", buffer.getvalue(), content_type=f"image/{ext}")


@covers("catalog-product-images", "catalog-product-image-detail")
def test_upload_resizes_in_background_with_stable_long_cache_urls(tenant_a, tenant_b, run):
    a, b = _client(tenant_a), _client(tenant_b)
    product = _product(tenant_a)
    url = f"{API}/products/{product.pk}/images/"
    response = run(a.post, url, {"file": _image(), "alt_text": "Front"}, format="multipart")
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "PROCESSING" and response.json()["urls"] is None

    listing = a.get(url).json()
    assert isinstance(listing, list), listing
    [image] = listing
    assert image["status"] == "READY"
    urls = image["urls"]
    assert set(urls) == {"thumb", "medium", "large"}
    # Public, unguessable, versioned, cached forever; the original stays private.
    for name, link in urls.items():
        key = link.removeprefix("https://cdn.test/")
        assert key.startswith(f"tenants/{tenant_a.pk}/products/{product.pk}/")
        data, content_type, cache_control = InMemoryStorage.public_objects[key]
        assert (content_type, cache_control) == ("image/webp", IMMUTABLE)
        assert (
            max(Image.open(io.BytesIO(data)).size)
            == {"thumb": 160, "medium": 640, "large": 1280}[name]
        )
    assert len(key.split("/")[-2]) > 30  # random token + content hash
    assert [k for k in InMemoryStorage.objects if "/originals/" in k]
    # The same URL on every load (no per-request signing), also in the product list.
    assert a.get(url).json()[0]["urls"] == urls
    listed = a.get(f"{API}/products/").json()["results"][0]
    assert listed["thumbnail_url"] == urls["thumb"]

    # A new upload always gets a new URL, even for identical pixels.
    run(a.post, url, {"file": _image()}, format="multipart")
    second = a.get(url).json()[1]["urls"]
    assert second["thumb"] != urls["thumb"]

    # Other tenants can't see, change or delete it.
    image_url = f"{url}{image['id']}/"
    assert b.get(url).status_code == 404
    assert b.post(url, {"file": _image()}, format="multipart").status_code == 404
    assert b.patch(image_url, {"sort_order": 5}, format="json").status_code == 404
    assert b.delete(image_url).status_code == 404

    assert (
        a.patch(image_url, {"sort_order": 5, "alt_text": "Back"}, format="json").json()["alt_text"]
        == "Back"
    )
    assert run(a.delete, image_url).status_code == 204
    assert not any(
        key.endswith("thumb.webp") and urls["thumb"].endswith(key)
        for key in InMemoryStorage.public_objects
    )


@pytest.mark.parametrize(
    ("upload", "message"),
    [
        (
            SimpleUploadedFile(
                "x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"
            ),
            "PNG, JPEG or WebP",
        ),
        (
            SimpleUploadedFile("big.png", b"\x89PNG" + b"0" * (5 * 1024 * 1024), "image/png"),
            "larger than 5 MB",
        ),
    ],
)
def test_upload_validation(tenant_a, run, upload, message):
    a = _client(tenant_a)
    product = _product(tenant_a)
    response = run(
        a.post, f"{API}/products/{product.pk}/images/", {"file": upload}, format="multipart"
    )
    assert message in response.json()["error"]["details"]["fields"]["file"][0]


def test_a_broken_original_is_marked_failed(tenant_a, run):
    product = _product(tenant_a)
    with tenant_context(tenant_a.pk):
        image = ProductImage.objects.create(product=product, original_key="k/broken.png")
    InMemoryStorage.objects["k/broken.png"] = (b"not an image", "image/png")
    process_product_image.apply(kwargs={"image_id": str(image.pk), "tenant_id": str(tenant_a.pk)})
    with tenant_context(tenant_a.pk):
        assert ProductImage.objects.get(pk=image.pk).status == ProductImage.Status.FAILED


@pytest.mark.django_db(transaction=True)
def test_the_worker_processes_images_under_the_runtime_rls_role(make_tenant):
    """Tests normally run as the table owner, which RLS does not restrict. Here the task runs as
    ``app_user`` with no outer transaction, exactly like a worker: it must still find its rows."""
    tenant = make_tenant(slug="rls-images")
    product = _product(tenant, code="RLS-1")
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (0, 120, 0)).save(buffer, format="JPEG")
    with tenant_context(tenant.pk):
        image = ProductImage.objects.create(product=product, original_key="k/rls.jpg")
    InMemoryStorage.objects["k/rls.jpg"] = (buffer.getvalue(), "image/jpeg")
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE app_user")
    try:
        process_product_image.apply(kwargs={"image_id": str(image.pk), "tenant_id": str(tenant.pk)})
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    with tenant_context(tenant.pk):
        assert ProductImage.objects.get(pk=image.pk).status == ProductImage.Status.READY
