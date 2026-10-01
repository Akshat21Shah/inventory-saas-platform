"""Connection settings every database alias gets (ADR-051)."""

import pytest
from django.conf import settings
from django.db import connection

pytestmark = pytest.mark.django_db


def test_jit_is_off_on_every_connection():
    for alias, config in settings.DATABASES.items():
        assert "-c jit=off" in config["OPTIONS"]["options"], alias
    with connection.cursor() as cursor:  # and PostgreSQL applies it
        cursor.execute("SHOW jit")
        assert cursor.fetchone()[0] == "off"
