"""ADR-053 item 4: a goods receipt's supplier. A posted receipt still never changes, except that
cost-pending lines gain their cost once (ADR-041) and, once, a past receipt is linked to the
supplier staff confirmed for its typed name."""

import django.db.models.deletion
from django.db import migrations, models

GUARD = """
CREATE OR REPLACE FUNCTION inventory_inward_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'posted goods receipt % cannot be deleted', OLD.number
            USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'POSTED' AND (
        (to_jsonb(NEW) - 'total_cost' - 'cost_pending_lines' - 'updated_at' - 'supplier_id')
        IS DISTINCT FROM
        (to_jsonb(OLD) - 'total_cost' - 'cost_pending_lines' - 'updated_at' - 'supplier_id')
        OR (OLD.supplier_id IS NOT NULL AND NEW.supplier_id IS DISTINCT FROM OLD.supplier_id)
    ) THEN
        RAISE EXCEPTION 'posted goods receipt % cannot be changed', OLD.number
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
"""

GUARD_BEFORE = """
CREATE OR REPLACE FUNCTION inventory_inward_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'posted goods receipt % cannot be deleted', OLD.number
            USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'POSTED' AND
       (to_jsonb(NEW) - 'total_cost' - 'cost_pending_lines' - 'updated_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'total_cost' - 'cost_pending_lines' - 'updated_at') THEN
        RAISE EXCEPTION 'posted goods receipt % cannot be changed', OLD.number
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_inventory_models"),
        ("purchasing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockinward",
            name="supplier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipts",
                to="purchasing.supplier",
            ),
        ),
        migrations.RunSQL(GUARD, GUARD_BEFORE),
    ]
