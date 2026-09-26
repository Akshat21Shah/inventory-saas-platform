from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2: the Phase 1 stub's fields get their final names (data kept)."""

    dependencies = [("retailers", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="retailer", name="uniq_retailer_phone_per_tenant"),
        migrations.RenameField(model_name="retailer", old_name="phone", new_name="mobile"),
        migrations.RenameField(model_name="retailer", old_name="contact_name", new_name="owner_name"),
    ]
