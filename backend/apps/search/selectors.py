"""Global search (ADR-053, spec 5.17). A typed document number, GSTIN, mobile or barcode that names
exactly one record the person may see jumps straight to it; otherwise the matches come grouped by
kind of record, the best first. Pages and settings are matched in the browser from their translated
names, so only records come from here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Q

from apps.accounts.models import Membership, User
from apps.platform.models import Tenant
from apps.retailers.models import RetailerUser
from apps.search.sources import GSTIN, SOURCES, Hit, mobile_of
from common.permissions import user_has_permission
from common.platform_db import platform_db

MIN_LENGTH = 2
MAX_LENGTH = 100
PER_TYPE = 5


@dataclass(frozen=True)
class Group:
    type: str
    hits: list[Hit]
    more: bool  # more matches than shown: the app offers the full list


@dataclass(frozen=True)
class Results:
    query: str
    jump: Hit | None = None
    groups: list[Group] = field(default_factory=list)


def normalize(text: str) -> str:
    return " ".join(text.split())[:MAX_LENGTH]


def _grouped(found: dict[str, list[Hit]], jump: Hit | None, per_type: int) -> list[Group]:
    groups = []
    for kind, hits in found.items():
        if jump is not None and jump.type == kind:
            # A number typed without its padding isn't a substring of the stored one.
            hits = [jump, *(h for h in hits if h.id != jump.id)]
        if hits:
            groups.append(Group(kind, hits[:per_type], len(hits) > per_type))
    if jump is not None and jump.type not in found:
        groups.insert(0, Group(jump.type, [jump], False))
    return groups


def search(user: User, text: str, *, per_type: int = PER_TYPE) -> Results:
    """What a distributor's staff member finds for ``text``, within what their role may see."""
    text = normalize(text)
    if len(text) < MIN_LENGTH:
        return Results(text)
    sources = [s for s in SOURCES if user_has_permission(user, s.requirement)]
    exact = [hit for s in sources if s.exact is not None for hit in s.exact(user, text)]
    jump = exact[0] if len(exact) == 1 else None
    has_digit = any(ch.isdigit() for ch in text)
    found = {
        s.type: s.find(user, text, per_type + 1) for s in sources if has_digit or not s.numbers_only
    }
    return Results(text, jump, _grouped(found, jump, per_type))


# --- The super admin's search (across distributors, on the audited platform path) ----------------


def slug_of_address(text: str) -> str | None:
    """``https://sharma.example.com/manage`` or ``sharma.localhost:3000`` → ``sharma``."""
    if "." not in text and "://" not in text:
        return None
    host = urlsplit(text if "://" in text else f"//{text}").hostname or ""
    labels = host.split(".")
    return labels[0] if len(labels) > 1 and labels[0] else None


def _tenant_hit(t: Tenant) -> Hit:
    detail = " · ".join(x for x in (t.legal_name if t.legal_name != t.name else "", t.slug) if x)
    return Hit("tenant", t.pk, t.name, detail, status=t.status)


def search_tenants(text: str, *, limit: int = PER_TYPE) -> Results:
    """Distributors by name, legal name, GSTIN or web address. A GSTIN or a web address naming
    one distributor jumps to it."""
    text = normalize(text)
    if len(text) < MIN_LENGTH:
        return Results(text)
    tenants = Tenant.objects.using(platform_db("platform.search_tenants"))
    gstin = text.upper().replace(" ", "")
    slug = slug_of_address(text)
    jump = None
    if GSTIN.fullmatch(gstin):
        exact = list(tenants.filter(gstin=gstin)[:2])
        jump = _tenant_hit(exact[0]) if len(exact) == 1 else None
    elif slug:
        exact = list(tenants.filter(slug=slug.lower())[:2])
        jump = _tenant_hit(exact[0]) if len(exact) == 1 else None
    condition = (
        Q(name__icontains=text)
        | Q(legal_name__icontains=text)
        | Q(slug__icontains=text)
        | Q(name__trigram_word_similar=text)
    )
    if len(gstin) >= 5 and gstin.isalnum():
        condition |= Q(gstin__icontains=gstin)
    found = (
        tenants.filter(condition)
        .annotate(similarity=TrigramWordSimilarity(text, "name"))
        .order_by("-similarity", "name")
    )
    hits = [_tenant_hit(t) for t in found[: limit + 1]]
    return Results(text, jump, _grouped({"tenant": hits}, jump, limit))


@dataclass(frozen=True)
class UserHit:
    kind: str  # STAFF (a distributor's staff member) or SHOP (a shop's login)
    id: UUID  # the membership or the shop login
    name: str
    email: str
    phone: str
    tenant_id: UUID
    tenant_name: str
    shop_name: str
    is_active: bool


def users_matching(text: str, *, limit: int = 20) -> list[UserHit]:
    """People across every distributor by name, email or mobile, for the super admin. Only
    through ``services.search_users``, which audits every search (spec 5.17)."""
    text = normalize(text)
    if len(text) < MIN_LENGTH:
        return []
    alias = platform_db("platform.search_users")
    mobile = mobile_of(text)
    digits = re.sub(r"\D", "", text)

    def person(prefix: str) -> Q:
        condition = Q(**{f"{prefix}full_name__icontains": text}) | Q(
            **{f"{prefix}email__icontains": text}
        )
        if mobile:
            condition |= Q(**{f"{prefix}phone": mobile})
        elif len(digits) >= 4 and len(digits) == len(text.replace(" ", "")):
            condition |= Q(**{f"{prefix}phone__contains": digits})
        return condition

    staff = (
        Membership.objects.unscoped()
        .using(alias)
        .filter(person("user__"))
        .select_related("user", "tenant")
        .order_by("user__full_name", "pk")[:limit]
    )
    shops = (
        RetailerUser.objects.unscoped()
        .using(alias)
        .filter(person("user__") | Q(retailer__shop_name__icontains=text))
        .select_related("user", "retailer", "tenant")
        .order_by("retailer__shop_name", "pk")[:limit]
    )
    hits = [
        UserHit(
            "STAFF",
            m.pk,
            m.user.full_name,
            m.user.email or "",
            m.user.phone or "",
            m.tenant_id,
            m.tenant.name,
            "",
            m.is_active and m.user.is_active,
        )
        for m in staff
    ] + [
        UserHit(
            "SHOP",
            r.pk,
            r.user.full_name or r.retailer.owner_name,
            r.user.email or "",
            r.user.phone or "",
            r.tenant_id,
            r.tenant.name,
            r.retailer.shop_name,
            r.user.is_active,
        )
        for r in shops
    ]
    return hits
