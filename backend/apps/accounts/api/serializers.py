"""Auth API serializers: input validation and response shapes (documented in OpenAPI)."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import User
from common.phone import normalize_indian_mobile


class StaffLoginInputSerializer(serializers.Serializer[Any]):
    email = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class TenantChoiceSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class HandoffSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    tenant_slug = serializers.CharField()


class RetailerAccountChoiceSerializer(serializers.Serializer[Any]):
    """One of the verified phone owner's distributors (ADR-015)."""

    choice_id = serializers.UUIDField()
    distributor_name = serializers.CharField()
    shop_name = serializers.CharField()


class LoginResponseSerializer(serializers.Serializer[Any]):
    """One shape for every sign-in step; ``status`` says what the client does next."""

    status = serializers.ChoiceField(
        choices=[
            "authenticated",
            "handoff",
            "choose_tenant",
            "choose_account",
            "mfa_required",
            "mfa_setup_required",
        ]
    )
    user_type = serializers.ChoiceField(choices=User.UserType.choices, required=False)
    access = serializers.CharField(required=False)
    access_expires_at = serializers.DateTimeField(required=False)
    handoff = HandoffSerializer(required=False)
    choice_token = serializers.CharField(required=False)
    tenants = TenantChoiceSerializer(many=True, required=False)
    mfa_token = serializers.CharField(required=False)
    enrolment_token = serializers.CharField(required=False)
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Shown once, right after set-up."
    )
    accounts = RetailerAccountChoiceSerializer(many=True, required=False)


class MfaVerifyInputSerializer(serializers.Serializer[Any]):
    mfa_token = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    recovery_code = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("code") and not attrs.get("recovery_code"):
            raise serializers.ValidationError({"code": [_("Enter the code from your app.")]})
        return attrs


class EnrolmentTokenInputSerializer(serializers.Serializer[Any]):
    enrolment_token = serializers.CharField(max_length=200)


class EnrolmentConfirmInputSerializer(serializers.Serializer[Any]):
    enrolment_token = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=10)


class MfaSecretSerializer(serializers.Serializer[Any]):
    secret = serializers.CharField(help_text="Base32 secret, for manual entry.")
    otpauth_uri = serializers.CharField(help_text="Render as a QR code.")


class MfaSetupResponseSerializer(MfaSecretSerializer):
    setup_token = serializers.CharField()


class MfaSetupConfirmInputSerializer(serializers.Serializer[Any]):
    setup_token = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=10)


class RecoveryCodesSerializer(serializers.Serializer[Any]):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class PasswordAndFactorInputSerializer(serializers.Serializer[Any]):
    password = serializers.CharField(max_length=256, trim_whitespace=False)
    code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    recovery_code = serializers.CharField(max_length=40, required=False, allow_blank=True)


class PasswordForgotInputSerializer(serializers.Serializer[Any]):
    email = serializers.CharField(max_length=254)


class PasswordResetInputSerializer(serializers.Serializer[Any]):
    uid = serializers.CharField(max_length=100)
    token = serializers.CharField(max_length=100)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class PasswordChangeInputSerializer(serializers.Serializer[Any]):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class ChooseTenantInputSerializer(serializers.Serializer[Any]):
    choice_token = serializers.CharField(max_length=200)
    tenant_id = serializers.UUIDField()


class HandoffExchangeInputSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(max_length=200)


class RefreshInputSerializer(serializers.Serializer[Any]):
    refresh = serializers.CharField(required=False, max_length=2000)


class TokenResponseSerializer(serializers.Serializer[Any]):
    access = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh = serializers.CharField(required=False, help_text="Only when the request sent one.")


class MeTenantSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()


class MeRoleSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()


class MeImpersonationSerializer(serializers.Serializer[Any]):
    session_id = serializers.UUIDField()
    impersonator_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["READ_ONLY", "ACT"])
    expires_at = serializers.DateTimeField()


class ImpersonationReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=1000)


class MeRetailerSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    shop_name = serializers.CharField()
    code = serializers.CharField()
    # True while the distributor has put the shop on hold: the shop shows a notice and can't
    # order (ADR-036).
    on_hold = serializers.BooleanField()


class LanguageSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField(help_text="In English.")
    native = serializers.CharField(help_text="In its own script, for the language switcher.")


class MeSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    user_type = serializers.ChoiceField(choices=User.UserType.choices)
    email = serializers.EmailField(allow_null=True)
    phone = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_blank=True)
    preferred_language = serializers.CharField(help_text="As saved (may be unavailable now).")
    language = serializers.CharField(help_text="The language this person sees (ADR-060).")
    languages = LanguageSerializer(many=True, help_text="The languages they may choose.")
    tenant = MeTenantSerializer(allow_null=True)
    role = MeRoleSerializer(allow_null=True)
    retailer = MeRetailerSerializer(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())
    features = serializers.DictField(child=serializers.BooleanField())
    impersonation = MeImpersonationSerializer(allow_null=True)
    mfa_enabled = serializers.BooleanField()
    mfa_required = serializers.BooleanField(help_text="2FA can't be turned off for this account.")


class MeUpdateSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["full_name", "preferred_language"]


def _normalized_mobile(value: str) -> str:
    try:
        return normalize_indian_mobile(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc


class RetailerOtpRequestInputSerializer(serializers.Serializer[Any]):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value: str) -> str:
        return _normalized_mobile(value)


class RetailerOtpRequestResponseSerializer(serializers.Serializer[Any]):
    expires_in = serializers.IntegerField(help_text="Seconds the code stays valid.")
    resend_after = serializers.IntegerField(help_text="Seconds before offering 'send again'.")


class RetailerOtpVerifyInputSerializer(serializers.Serializer[Any]):
    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=10)

    def validate_phone(self, value: str) -> str:
        return _normalized_mobile(value)


class RetailerChooseAccountInputSerializer(serializers.Serializer[Any]):
    choice_token = serializers.CharField(max_length=200)
    choice_id = serializers.UUIDField()
