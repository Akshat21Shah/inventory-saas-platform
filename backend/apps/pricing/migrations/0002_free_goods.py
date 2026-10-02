"""ADR-056 item 7: free-goods schemes."""

import common.fields
import common.ids
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from common.db_ops import EnableRLS


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_own_brand_cost_price"),
        ("platform", "0008_free_goods_flag"),
        ("pricing", "0001_initial"),
        ("retailers", "0008_retaileraddress_distance_km"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FreeGoodsScheme",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=common.ids.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("buy_qty", common.fields.QtyField(decimal_places=3, max_digits=14)),
                ("free_qty", common.fields.QtyField(decimal_places=3, max_digits=14)),
                ("repeat", models.BooleanField(default=True)),
                (
                    "max_free_qty",
                    common.fields.QtyField(blank=True, decimal_places=3, max_digits=14, null=True),
                ),
                (
                    "audience_type",
                    models.CharField(
                        choices=[
                            ("ALL", "All shops"),
                            ("PRICE_LIST", "Shops on a price list"),
                            ("RETAILER", "One shop"),
                        ],
                        max_length=12,
                    ),
                ),
                ("valid_from", models.DateField(blank=True, null=True)),
                ("valid_to", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "buy_product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="catalog.product",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "free_product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="catalog.product",
                    ),
                ),
                (
                    "price_list",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="pricing.pricelist",
                    ),
                ),
                (
                    "retailer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="retailers.retailer",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="platform.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [
                    models.Index(
                        fields=["tenant", "buy_product", "is_active"], name="scheme_buy_product_idx"
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("buy_qty__gt", 0)), name="scheme_buy_qty_pos"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("free_qty__gt", 0)), name="scheme_free_qty_pos"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("max_free_qty__isnull", True), ("max_free_qty__gt", 0), _connector="OR"
                        ),
                        name="scheme_max_free_qty_pos",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("audience_type", "ALL"),
                                ("price_list__isnull", True),
                                ("retailer__isnull", True),
                            ),
                            models.Q(
                                ("audience_type", "PRICE_LIST"),
                                ("price_list__isnull", False),
                                ("retailer__isnull", True),
                            ),
                            models.Q(
                                ("audience_type", "RETAILER"),
                                ("price_list__isnull", True),
                                ("retailer__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="scheme_audience_matches_target",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("valid_from__isnull", True),
                            ("valid_to__isnull", True),
                            ("valid_to__gte", models.F("valid_from")),
                            _connector="OR",
                        ),
                        name="scheme_valid_range",
                    ),
                ],
            },
        ),
        EnableRLS("FreeGoodsScheme"),
    ]
