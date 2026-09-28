"""Platform (super admin) API serializers, and the settings-registry shape shared with tenants."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.platform import registry
from apps.platform.models import CessType, FeatureFlag, HsnRateHint, Plan, State, TaxRate, Tenant


class StateSerializer(serializers.ModelSerializer[State]):
    class Meta:
        model = State
        fields = ["code", "name", "is_union_territory"]


class PlanRefSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_null=True)


class TenantListSerializer(serializers.ModelSerializer[Tenant]):
    plan = serializers.SerializerMethodField()
    state_code = serializers.CharField(source="state_id", read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "gstin",
            "state_code",
            "city",
            "plan",
            "created_at",
        ]
        read_only_fields = fields  # output only: every field is always present

    @extend_schema_field(PlanRefSerializer)
    def get_plan(self, obj: Tenant) -> dict[str, Any]:
        return {"code": getattr(obj, "plan_code", None), "name": getattr(obj, "plan_name", None)}


class TenantUsageSerializer(serializers.Serializer[Any]):
    staff = serializers.IntegerField()
    retailers = serializers.IntegerField()
    pending_invitations = serializers.IntegerField()


class TenantOwnerSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField()
    full_name = serializers.CharField(allow_blank=True)
    status = serializers.CharField()


class TenantDetailSerializer(TenantListSerializer):
    usage = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()
    gst_identity_locked = serializers.SerializerMethodField()

    class Meta(TenantListSerializer.Meta):
        fields = [
            *TenantListSerializer.Meta.fields,
            "gst_identity_locked",
            "legal_name",
            "pan",
            "registration_type",
            "address_line1",
            "address_line2",
            "pincode",
            "email",
            "phone",
            "suspended_reason",
            "suspended_at",
            "usage",
            "owner",
            "features",
        ]
        read_only_fields = fields

    @extend_schema_field(TenantUsageSerializer)
    def get_usage(self, obj: Tenant) -> dict[str, int]:
        return dict(self.context["usage"])

    @extend_schema_field(TenantOwnerSerializer(allow_null=True))
    def get_owner(self, obj: Tenant) -> dict[str, Any] | None:
        owner: dict[str, Any] | None = self.context["owner"]
        return owner

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    def get_features(self, obj: Tenant) -> dict[str, bool]:
        return dict(self.context["features"])

    def get_gst_identity_locked(self, obj: Tenant) -> bool:
        """After the first invoice, GSTIN, legal name and state change only through the separate
        GST identity action."""
        return bool(self.context["gst_identity_locked"])


class GstIdentityChangeSerializer(serializers.Serializer[Any]):
    legal_name = serializers.CharField(max_length=200, required=False)
    gstin = serializers.CharField(max_length=30, required=False)
    state_code = serializers.CharField(max_length=2, required=False)
    reason = serializers.CharField(max_length=1000)


class OnboardingSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    legal_name = serializers.CharField(max_length=200)
    gstin = serializers.CharField(max_length=30)  # spaces are removed by the service
    state_code = serializers.CharField(max_length=2)
    address_line1 = serializers.CharField(max_length=200)
    address_line2 = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    city = serializers.CharField(max_length=100)
    pincode = serializers.CharField(max_length=6)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=16)
    slug = serializers.CharField(max_length=30)
    owner_email = serializers.EmailField()
    owner_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    plan_code = serializers.CharField(max_length=40, required=False, allow_null=True, default=None)
    primary_color = serializers.CharField(
        max_length=7, required=False, allow_null=True, default=None
    )


class TenantUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200, required=False)
    legal_name = serializers.CharField(max_length=200, required=False)
    gstin = serializers.CharField(max_length=30, required=False)  # spaces removed later
    state_code = serializers.CharField(max_length=2, required=False)
    address_line1 = serializers.CharField(max_length=200, required=False)
    address_line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False)
    pincode = serializers.CharField(max_length=6, required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=16, required=False)
    slug = serializers.CharField(max_length=30, required=False)
    confirm_slug_change = serializers.BooleanField(required=False, default=False)


class ReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=1000)


class FeatureToggleSerializer(serializers.Serializer[Any]):
    enabled = serializers.BooleanField()


class SubscriptionSerializer(serializers.Serializer[Any]):
    plan = PlanRefSerializer()
    status = serializers.CharField()
    starts_at = serializers.DateTimeField()


class ChangePlanSerializer(serializers.Serializer[Any]):
    plan_code = serializers.CharField(max_length=40)


class PlanSerializer(serializers.ModelSerializer[Plan]):
    class Meta:
        model = Plan
        fields = [
            "id",
            "code",
            "name",
            "price_monthly",
            "max_retailers",
            "max_staff",
            "max_products",
            "features",
            "is_default",
            "is_active",
        ]
        read_only_fields = ["id"]
        # The service moves the default flag between plans; DRF's generated checks for the
        # conditional unique constraint would refuse the switch before the service runs.
        validators: list[Any] = []
        extra_kwargs: dict[str, Any] = {"is_default": {"validators": []}}


class PlanUpdateSerializer(PlanSerializer):
    class Meta(PlanSerializer.Meta):
        read_only_fields = ["id", "code"]
        extra_kwargs = {
            **{f: {"required": False} for f in PlanSerializer.Meta.fields},
            "is_default": {"required": False, "validators": []},
        }
        validators: list[Any] = []


class FeatureFlagSerializer(serializers.ModelSerializer[FeatureFlag]):
    class Meta:
        model = FeatureFlag
        fields = ["code", "name", "description", "default_enabled", "tenant_toggleable"]
        read_only_fields = ["code"]
        extra_kwargs = {f: {"required": False} for f in fields}


class TaxRateSerializer(serializers.ModelSerializer[TaxRate]):
    class Meta:
        model = TaxRate
        fields = ["id", "rate", "label", "is_active", "notes"]
        read_only_fields = ["id"]


class TaxRateUpdateSerializer(serializers.Serializer[Any]):
    label = serializers.CharField(max_length=40, required=False)  # type: ignore[assignment]
    notes = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


class CessTypeSerializer(serializers.ModelSerializer[CessType]):
    class Meta:
        model = CessType
        fields = ["id", "code", "name", "calc_method", "is_active"]
        read_only_fields = ["id"]


class CessTypeUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120, required=False)
    calc_method = serializers.ChoiceField(choices=CessType.CalcMethod.choices, required=False)
    is_active = serializers.BooleanField(required=False)


class HsnHintSerializer(serializers.ModelSerializer[HsnRateHint]):
    class Meta:
        model = HsnRateHint
        fields = ["id", "hsn_prefix", "gst_rate", "effective_from", "description"]
        read_only_fields = ["id"]


class HsnHintUpdateSerializer(serializers.Serializer[Any]):
    gst_rate = serializers.DecimalField(max_digits=6, decimal_places=3, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)


class HsnImportSerializer(serializers.Serializer[Any]):
    file = serializers.FileField()


class HsnImportResultSerializer(serializers.Serializer[Any]):
    created = serializers.IntegerField()
    updated = serializers.IntegerField()


class DashboardSerializer(serializers.Serializer[Any]):
    total = serializers.IntegerField()
    active = serializers.IntegerField()
    onboarding = serializers.IntegerField()
    suspended = serializers.IntegerField()


class SlugAvailabilitySerializer(serializers.Serializer[Any]):
    slug = serializers.CharField()
    available = serializers.BooleanField()


# --- Settings registry (shared by platform and tenant endpoints) --------------------------------


class DependsOnSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    equals = serializers.JSONField(allow_null=True)
    not_null = serializers.BooleanField()


class SettingSerializer(serializers.Serializer[Any]):
    """A registry definition with the current value; the settings UI is generated from this."""

    key = serializers.CharField()
    group = serializers.CharField()
    type = serializers.CharField()
    default = serializers.JSONField(allow_null=True)
    value = serializers.JSONField(allow_null=True)
    is_default = serializers.BooleanField()
    allowed = serializers.ListField(child=serializers.JSONField())
    reserved_values = serializers.ListField(child=serializers.JSONField())
    min_value = serializers.JSONField(allow_null=True)
    max_value = serializers.JSONField(allow_null=True)
    pattern = serializers.CharField(allow_null=True)
    nullable = serializers.BooleanField()
    description = serializers.CharField()
    i18n_key = serializers.CharField()
    edit_permission = serializers.CharField()
    can_edit = serializers.BooleanField()
    snapshot_on = serializers.ListField(child=serializers.CharField())
    depends_on = DependsOnSerializer(allow_null=True)
    status = serializers.CharField()


def setting_rows(
    values: dict[str, Any], scope: registry.Scope, permissions: frozenset[str]
) -> list[dict[str, Any]]:
    rows = []
    for defn in registry.definitions(scope):
        value = values[defn.key]
        rows.append(
            {
                "key": defn.key,
                "group": defn.group.value,
                "type": defn.type.value,
                "default": registry.to_json(defn, defn.default),
                "value": registry.to_json(defn, value),
                "is_default": value == defn.default,
                "allowed": list(defn.allowed),
                "reserved_values": list(defn.reserved_values),
                "min_value": registry.to_json(defn, defn.min_value)
                if defn.min_value is not None
                else None,
                "max_value": registry.to_json(defn, defn.max_value)
                if defn.max_value is not None
                else None,
                "pattern": defn.pattern,
                "nullable": defn.nullable,
                "description": defn.description,
                "i18n_key": defn.i18n_key,
                "edit_permission": defn.required_permission,
                "can_edit": defn.required_permission in permissions
                and defn.status is registry.Status.ACTIVE,
                "snapshot_on": sorted(s.value for s in defn.snapshot_on),
                "depends_on": (
                    {
                        "key": defn.depends_on.key,
                        "equals": defn.depends_on.equals,
                        "not_null": defn.depends_on.not_null,
                    }
                    if defn.depends_on
                    else None
                ),
                "status": defn.status.value,
            }
        )
    return rows


class SettingValuesSerializer(serializers.Serializer[Any]):
    values = serializers.DictField(child=serializers.JSONField(allow_null=True))


# --- Impersonation (ADR-029) --------------------------------------------------------------------


class ImpersonationStartSerializer(serializers.Serializer[Any]):
    tenant_id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000)


class ImpersonationStartedSerializer(serializers.Serializer[Any]):
    session_id = serializers.UUIDField()
    tenant_slug = serializers.CharField()
    handoff_code = serializers.CharField(help_text="Exchange on the tenant subdomain within 60 s.")
    target_type = serializers.CharField(help_text="STAFF opens /manage; RETAILER opens /shop.")
    expires_at = serializers.DateTimeField()


class SessionTenantSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class SessionPersonSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    phone = serializers.CharField(allow_null=True, required=False)
    user_type = serializers.CharField(required=False)


class ImpersonationSessionSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    tenant = serializers.SerializerMethodField()
    impersonator = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    reason = serializers.CharField()
    mode = serializers.CharField()
    act_reason = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField()

    @extend_schema_field(SessionTenantSerializer)
    def get_tenant(self, obj: Any) -> dict[str, Any]:
        return {"id": obj.tenant_id, "name": obj.tenant.name, "slug": obj.tenant.slug}

    @extend_schema_field(SessionPersonSerializer)
    def get_impersonator(self, obj: Any) -> dict[str, Any]:
        return {
            "id": obj.impersonator_id,
            "full_name": obj.impersonator.full_name,
            "email": obj.impersonator.email,
        }

    @extend_schema_field(SessionPersonSerializer)
    def get_target(self, obj: Any) -> dict[str, Any]:
        t = obj.target_user
        return {
            "id": t.pk,
            "full_name": t.full_name,
            "email": t.email,
            "phone": t.phone,
            "user_type": t.user_type,
        }
