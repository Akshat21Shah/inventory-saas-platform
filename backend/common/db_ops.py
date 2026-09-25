"""Custom migration operations: Row-Level Security and append-only tables (ADR-002)."""

from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import ProjectState

TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _table(
    app_label: str, model_name: str, state: ProjectState, editor: BaseDatabaseSchemaEditor
) -> str:
    model = state.apps.get_model(app_label, model_name)
    return str(editor.quote_name(model._meta.db_table))


class EnableRLS(migrations.operations.base.Operation):
    """Enable RLS on a tenant table with a policy matching ``app.current_tenant``.

    Usage in a migration: ``EnableRLS("Widget")`` right after the model is created.
    """

    reversible = True

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def state_forwards(self, app_label: str, state: ProjectState) -> None:
        pass

    def database_forwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        table = _table(app_label, self.model_name, to_state, schema_editor)
        schema_editor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        schema_editor.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})"
        )

    def database_backwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        table = _table(app_label, self.model_name, from_state, schema_editor)
        schema_editor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        schema_editor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    def describe(self) -> str:
        return f"Enable row-level security on {self.model_name}"

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        return (self.__class__.__qualname__, [self.model_name], {})


APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION common_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only table %: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


class MakeAppendOnly(migrations.operations.base.Operation):
    """Reject UPDATE and DELETE at the database level (ledger, stock movements, audit)."""

    reversible = True

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def state_forwards(self, app_label: str, state: ProjectState) -> None:
        pass

    def database_forwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        table = _table(app_label, self.model_name, to_state, schema_editor)
        schema_editor.execute(APPEND_ONLY_FUNCTION, params=None)
        schema_editor.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION common_reject_mutation()"
        )

    def database_backwards(
        self,
        app_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        table = _table(app_label, self.model_name, from_state, schema_editor)
        schema_editor.execute(f"DROP TRIGGER IF EXISTS append_only ON {table}")

    def describe(self) -> str:
        return f"Make {self.model_name} append-only"

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        return (self.__class__.__qualname__, [self.model_name], {})
