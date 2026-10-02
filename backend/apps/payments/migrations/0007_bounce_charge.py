"""ADR-057 item 4: the charge debited when a cheque bounces."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ledger', '0007_invoice_cancelled_entry'),
        ('payments', '0006_online_checkout'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='bounce_charge',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='ledger.ledgeradjustment'),
        ),
    ]
