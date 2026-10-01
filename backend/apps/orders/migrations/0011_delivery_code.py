"""ADR-057: proof of delivery (the delivery code) and how a delivery was confirmed."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0010_free_goods"),
    ]

    operations = [
        migrations.AddField(
            model_name="fulfilment",
            name="delivered_via",
            field=models.CharField(
                blank=True,
                choices=[
                    ("STAFF", "Marked by staff"),
                    ("CODE", "With the delivery code"),
                    ("NO_CODE", "Without the delivery code"),
                    ("SHOP", "Confirmed by the shop"),
                ],
                default="",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="fulfilment",
            name="delivery_code",
            field=models.CharField(blank=True, default="", max_length=4),
        ),
        migrations.AddField(
            model_name="fulfilment",
            name="delivery_code_failures",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="fulfilment",
            name="delivery_code_locked_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="fulfilment",
            name="delivery_note",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
    ]
