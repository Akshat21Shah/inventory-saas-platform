"""ADR-056 item 10: free lines on invoices."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_invoiceline_unit_cost'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceline',
            name='is_free',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='invoiceline',
            name='scheme_name',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
