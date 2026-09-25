"""The platform alias is a separate database connection in production: it cannot see rows the
current request has not committed yet. Tests mirror it onto the default connection, so they cannot
show such a bug; this test finds it statically instead.

Every function that reads through ``platform_db(...)``, directly or through other module-level
functions, is a platform read. A view whose write handler (POST/PUT/PATCH/DELETE) reaches a platform
read must not run inside the request-wide transaction (``atomic_request = False``): it commits its
write in its own ``atomic()`` block before reading (``CommitThenReadView``), or manages its own
transactions (the sign-in views)."""

import ast
import inspect
import textwrap
from pathlib import Path

from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver

WRITE_METHODS = ("post", "put", "patch", "delete")
ROOT = Path(settings.BASE_DIR)


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                names.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                names.add(call.func.attr)
    return names


def _module_functions() -> dict[str, set[str]]:
    """Module-level function name -> names it calls, for all application code."""
    functions: dict[str, set[str]] = {}
    for path in [*ROOT.glob("apps/**/*.py"), *ROOT.glob("common/**/*.py")]:
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                functions.setdefault(node.name, set()).update(_called_names(node))
    return functions


def platform_readers() -> set[str]:
    functions = _module_functions()
    readers = {"platform_db"}
    while True:
        more = {name for name, calls in functions.items() if calls & readers} - readers
        if not more:
            return readers
        readers |= more


def _views() -> set[type]:
    found: set[type] = set()

    def walk(patterns: list[URLPattern | URLResolver]) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns)
            else:
                view_class = getattr(pattern.callback, "view_class", None)
                if view_class is not None:
                    found.add(view_class)

    walk(get_resolver().url_patterns)
    return found


def views_reading_after_writes() -> dict[str, list[str]]:
    readers = platform_readers()
    flagged: dict[str, list[str]] = {}
    for view in _views():
        for method in WRITE_METHODS:
            handler = getattr(view, method, None)
            if handler is None or not view.__module__.startswith(("apps.", "common.")):
                continue
            tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
            reached = sorted(_called_names(tree) & readers)
            if reached:
                flagged.setdefault(f"{view.__module__}.{view.__qualname__}", []).append(
                    f"{method}: {', '.join(reached)}"
                )
    return flagged


def test_the_detector_finds_the_tenant_write_views():
    flagged = views_reading_after_writes()
    for name in ("TenantListCreateView", "TenantDetailView", "TenantSuspendView"):
        assert any(key.endswith(f".{name}") for key in flagged), flagged


def test_views_that_read_through_the_platform_alias_after_a_write_commit_first():
    offenders = {
        view: calls
        for view, calls in views_reading_after_writes().items()
        if getattr(_class(view), "atomic_request", True)
    }
    assert offenders == {}, (
        "These write handlers read through the platform alias inside the request transaction; "
        "make them commit first (CommitThenReadView): " + repr(offenders)
    )


def _class(dotted: str) -> type:
    module_name, _, qualname = dotted.rpartition(".")
    module = __import__(module_name, fromlist=[qualname])
    view_class: type = getattr(module, qualname)
    return view_class
