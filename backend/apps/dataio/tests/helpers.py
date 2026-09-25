"""Shared helpers for the import tests (files, upload, commit, messages)."""

import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens

API = "/api/v1"


def _client(tenant, role="OWNER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_staff_in(tenant, role), tenant.pk).access}"
    )
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def xlsx(rows, *, merge=None, name="products.xlsx"):
    book = Workbook()
    sheet = book.worksheets[0]
    for row in rows:
        sheet.append(row)
    for cells in merge or []:
        sheet.merge_cells(cells)
    buffer = io.BytesIO()
    book.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def csv_file(rows, *, encoding="utf-8", delimiter=",", name="products.csv", bom=b""):
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter).writerows(rows)
    return SimpleUploadedFile(name, bom + buffer.getvalue().encode(encoding))


def upload(client, run, file, mode="ADD_ONLY", kind="PRODUCTS"):
    response = run(
        client.post,
        f"{API}/imports/",
        {"kind": kind, "mode": mode, "file": file},
        format="multipart",
    )
    assert response.status_code == 201, response.json()
    return client.get(f"{API}/imports/{response.json()['id']}/").json()


def commit(client, run, job):
    response = run(client.post, f"{API}/imports/{job['id']}/commit/")
    assert response.status_code == 200, response.json()
    return client.get(f"{API}/imports/{job['id']}/").json()


def messages(job):
    return [m for row in job["errors"] for m in row["messages"]]
