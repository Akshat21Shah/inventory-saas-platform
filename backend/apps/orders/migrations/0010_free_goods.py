"""ADR-056 item 8: free order lines (linked to the line that earned them, with the scheme)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_own_brand_cost_price"),
        ("orders", "0009_order_salesperson_order_order_salesperson_idx"),
        ("platform", "0008_free_goods_flag"),
        ("pricing", "0002_free_goods"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="orderline",
            name="free_of_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="free_lines",
                to="orders.orderline",
            ),
        ),
        migrations.AddField(
            model_name="orderline",
            name="scheme",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="pricing.freegoodsscheme",
            ),
        ),
        migrations.AddField(
            model_name="orderline",
            name="scheme_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orderline",
            name="scheme_rule",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="orderline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("free_of_line__isnull", True),
                    models.Q(("discount_amount", 0), ("unit_price", 0)),
                    _connector="OR",
                ),
                name="order_line_free_at_zero",
            ),
        ),
    ]
