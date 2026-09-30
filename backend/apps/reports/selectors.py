from django.db.models import QuerySet

from apps.accounts.models import User
from apps.reports.models import ReportRun


def runs_of(user: User) -> QuerySet[ReportRun]:
    """A person's own exports only (the files hold what they were allowed to see)."""
    return ReportRun.objects.filter(requested_by=user)
