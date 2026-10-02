"""ADR-057 item 3: shop return requests."""

import common.fields
import common.ids
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from common.db_ops import EnableRLS


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_free_lines'),
        ('platform', '0008_free_goods_flag'),
        ('retailers', '0008_retaileraddress_distance_km'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReturnRequest',
            fields=[
                ('id', models.UUIDField(default=common.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('number', models.CharField(max_length=24)),
                ('status', models.CharField(choices=[('REQUESTED', 'Waiting for a decision'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('CANCELLED', 'Cancelled by the shop')], default='REQUESTED', max_length=10)),
                ('reason', models.CharField(choices=[('DAMAGED', 'Damaged'), ('EXPIRED', 'Expired'), ('WRONG_ITEM', 'Wrong item'), ('EXCESS_SUPPLY', 'Excess supply'), ('OTHER', 'Other')], max_length=14)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('decision_note', models.CharField(blank=True, default='', max_length=300)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('credit_note', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='billing.creditnote')),
                ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='return_requests', to='billing.invoice')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('retailer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='retailers.retailer')),
                ('tenant', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='platform.tenant')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='ReturnRequestLine',
            fields=[
                ('id', models.UUIDField(default=common.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('quantity', common.fields.QtyField(decimal_places=3, max_digits=14)),
                ('approved_quantity', common.fields.QtyField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('disposition', models.CharField(blank=True, choices=[('RETURN_TO_STOCK', 'Return to stock'), ('DAMAGED', 'Received damaged'), ('NOT_RETURNED', 'Not physically returned')], default='', max_length=16)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('invoice_line', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='billing.invoiceline')),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='billing.returnrequest')),
                ('tenant', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='platform.tenant')),
            ],
            options={
                'ordering': ['invoice_line__line_no'],
            },
        ),
        migrations.AddIndex(
            model_name='returnrequest',
            index=models.Index(fields=['tenant', 'status', 'created_at'], name='return_request_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='returnrequest',
            constraint=models.UniqueConstraint(fields=('tenant', 'number'), name='uniq_return_request_number'),
        ),
        migrations.AddConstraint(
            model_name='returnrequest',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('status', 'APPROVED'), _negated=True), ('credit_note__isnull', False), _connector='OR'), name='return_request_approved_has_note'),
        ),
        migrations.AddConstraint(
            model_name='returnrequestline',
            constraint=models.UniqueConstraint(fields=('request', 'invoice_line'), name='uniq_return_request_line'),
        ),
        migrations.AddConstraint(
            model_name='returnrequestline',
            constraint=models.CheckConstraint(condition=models.Q(('quantity__gt', 0)), name='return_request_qty_pos'),
        ),
        migrations.AddConstraint(
            model_name='returnrequestline',
            constraint=models.CheckConstraint(condition=models.Q(('approved_quantity__isnull', True), models.Q(('approved_quantity__gte', 0), ('approved_quantity__lte', models.F('quantity'))), _connector='OR'), name='return_request_approved_within_asked'),
        ),
        EnableRLS("ReturnRequest"),
        EnableRLS("ReturnRequestLine"),
    ]
