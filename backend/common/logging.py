import logging

from common.context import request_id_var, tenant_id_var, user_id_var


class RequestContextFilter(logging.Filter):
    """Attach request_id / tenant_id / user_id to every log record (structured JSON logs)."""

    def filter(self, record: logging.LogRecord) -> bool:
        tenant_id = tenant_id_var.get()
        record.request_id = request_id_var.get() or "-"
        record.tenant_id = str(tenant_id) if tenant_id else "-"
        record.user_id = user_id_var.get() or "-"
        return True
