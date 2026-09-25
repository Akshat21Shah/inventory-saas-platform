"""OpenAPI extensions: document our JWT authenticators as bearer JWT (drf-spectacular)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class SessionJWTScheme(SimpleJWTScheme):  # type: ignore[misc]
    target_class = "apps.accounts.authentication.SessionJWTAuthentication"
    match_subclasses = True
    name = "jwtAuth"
