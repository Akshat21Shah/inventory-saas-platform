from rest_framework.pagination import CursorPagination


class DefaultCursorPagination(CursorPagination):
    """Cursor pagination ordered by UUIDv7 primary key (creation order), stable under inserts."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-id"
