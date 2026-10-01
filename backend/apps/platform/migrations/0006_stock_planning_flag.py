"""ADR-053 item 9: the ``stock_planning`` flag (off by default); ``ai`` now covers only smart
search and the data assistant."""

from django.db import migrations

from apps.platform.reference_data import FEATURE_FLAGS, seed_reference_data


def forwards(apps, schema_editor):
    seed_reference_data(apps)
    FeatureFlag = apps.get_model("platform", "FeatureFlag")
    for code, name, description in FEATURE_FLAGS:
        if code == "ai":
            FeatureFlag.objects.filter(code=code).update(name=name, description=description)


class Migration(migrations.Migration):
    dependencies = [("platform", "0005_settings_overrides")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
