"""Why a 2FA code was refused (logged, never shown): replay, clock skew or invalid. And the
dev-only command the E2E helper uses to read the backend's clock and replay state."""

import json
import logging
import types

import pyotp
import pytest
from django.core.management import CommandError, call_command

from apps.accounts import mfa
from apps.accounts.models import User

SECRET = pyotp.random_base32()
TOTP = pyotp.TOTP(SECRET, interval=mfa.TOTP_INTERVAL, digits=mfa.TOTP_DIGITS)


NOW = 1_800_000_010.0  # mid-step, so nothing straddles a 30-second boundary


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("apps.accounts.mfa.time", types.SimpleNamespace(time=lambda: NOW))


def _code(offset: int) -> tuple[str, int]:
    step = int(NOW) // mfa.TOTP_INTERVAL + offset
    return TOTP.at(step * mfa.TOTP_INTERVAL), step


def test_replay_is_named():
    code, step = _code(0)
    assert mfa.refusal_reason(SECRET, code, last_step=step) == "replay"


@pytest.mark.parametrize("offset", [-10, -3, 2, 5, 10])
def test_clock_skew_is_named_with_its_size(offset):
    code, _ = _code(offset)
    assert mfa.refusal_reason(SECRET, code, last_step=None) == f"clock_skew:{offset:+d}"


@pytest.mark.parametrize("code", ["", "12345", "abcdef"])
def test_malformed_codes_are_invalid(code):
    assert mfa.refusal_reason(SECRET, code, last_step=None) == "invalid"


def test_a_wrong_key_is_invalid():
    other = pyotp.TOTP(pyotp.random_base32(), interval=mfa.TOTP_INTERVAL).at(int(NOW))
    # A random key's code may happen to equal ours in a nearby step; usually it matches nothing.
    reason = mfa.refusal_reason(SECRET, other, last_step=None)
    assert reason == "invalid" or reason.startswith("clock_skew")


@pytest.mark.django_db
def test_a_refused_code_is_logged_with_its_reason(caplog):
    user = User.objects.create_user("mfa@example.com", "a-strong-password", user_type="STAFF")
    user.totp_secret, user.totp_enabled = SECRET, True
    user.save()
    code, _ = _code(0)
    assert mfa.verify_user_totp(user, code) is True
    with caplog.at_level(logging.WARNING, logger="apps.accounts.mfa"):
        assert mfa.verify_user_totp(user, code) is False  # the same step again
    assert "mfa: code refused (replay)" in caplog.text
    assert code not in caplog.text  # the code itself is never logged


@pytest.mark.django_db
def test_e2e_totp_state(settings, capsys):
    settings.DEBUG = True
    user = User.objects.create_user("state@example.com", "a-strong-password", user_type="STAFF")
    User.objects.filter(pk=user.pk).update(totp_last_step=123)
    call_command("e2e_totp_state", "--email", "STATE@example.com")
    state = json.loads(capsys.readouterr().out)
    assert state["last_step"] == 123
    assert state["server_step"] == int(state["server_time"]) // 30
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("e2e_totp_state", "--email", "state@example.com")
