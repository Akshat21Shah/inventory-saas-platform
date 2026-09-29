"""Templates per audience (Phase 6 final review): the shop's words and the office's. Existing
texts keep the audience they were written for; the missing ones are seeded from the catalogue."""

from django.conf import settings
from django.db import migrations, models

from apps.notifications.catalog import whatsapp_template_name
from apps.notifications.defaults import sync_platform_templates

# Events whose single text was written for the office before templates had an audience.
WRITTEN_FOR_STAFF = {
    "order.placed",
    "order.on_hold",
    "order.cancelled_by_shop",
    "backorder.proposed",
    "backorder.skipped_credit",
    "backorder.skipped_blocked",
    "backorder.cancelled_by_shop",
    "stock.alert_opened",
    "payment.handed_over",
    "handover.reminder",
    "tax.rate_change_upcoming",
}


def forwards(apps, schema_editor):
    platform = apps.get_model("notifications", "PlatformTemplate")
    tenant = apps.get_model("notifications", "NotificationTemplate")
    for model in (platform, tenant):
        model.objects.filter(event_code__in=WRITTEN_FOR_STAFF).update(audience="STAFF")
    for row in platform.objects.filter(channel="WHATSAPP"):
        row.whatsapp_template_name = whatsapp_template_name(row.event_code, row.audience)
        row.save(update_fields=["whatsapp_template_name"])
    sync_platform_templates(platform)


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0005_bounced_cheque_texts'),
        ('platform', '0005_settings_overrides'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='notificationtemplate',
            name='uniq_tenant_template',
        ),
        migrations.RemoveConstraint(
            model_name='platformtemplate',
            name='uniq_platform_template',
        ),
        migrations.AddField(
            model_name='notificationtemplate',
            name='audience',
            field=models.CharField(choices=[('SHOP', 'The shop'), ('STAFF', 'Staff')], default='SHOP', max_length=5),
        ),
        migrations.AddField(
            model_name='platformtemplate',
            name='audience',
            field=models.CharField(choices=[('SHOP', 'The shop'), ('STAFF', 'Staff')], default='SHOP', max_length=5),
        ),
        migrations.AddConstraint(
            model_name='notificationtemplate',
            constraint=models.UniqueConstraint(fields=('tenant', 'event_code', 'audience', 'channel', 'locale'), name='uniq_tenant_template_audience'),
        ),
        migrations.AddConstraint(
            model_name='platformtemplate',
            constraint=models.UniqueConstraint(fields=('event_code', 'audience', 'channel', 'locale'), name='uniq_platform_template_audience'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
