"""Asking the assistant (ADR-059 items 3 and 6): a question is saved and answered in the
background; the model calls the person's tools for up to ``MAX_ROUNDS`` rounds; every provider call
is an ``AiUsage`` row; the monthly cap and an hourly limit per person apply."""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.ai import services
from apps.ai.adapters.base import AiProviderError
from apps.ai.adapters.chat import ChatProvider, ChatTurn, Message, ToolResult, ToolSpec
from apps.ai.adapters.mock_chat import ScriptedChat
from apps.ai.assistant import tools as toolbox
from apps.ai.models import AiUsage, AssistantQuestion
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.tenancy import require_tenant_id

log = logging.getLogger(__name__)

MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3
PER_HOUR = 30  # questions per person per hour [assumed]
STALE_AFTER = timedelta(minutes=3)  # a question still waiting by then is shown as failed
MAX_QUESTION = 500
MAX_ANSWER = 4000


class AssistantRateLimited(DomainError):
    status_code = 429
    code = ErrorCode.ASSISTANT_RATE_LIMITED
    default_message = "You've asked a lot of questions in the last hour. Try again a little later."


class AssistantUnavailable(DomainError):
    status_code = 403
    code = ErrorCode.ASSISTANT_NOT_AVAILABLE
    default_message = "There are no figures the assistant may show you."


def chat_provider() -> ChatProvider:
    """The configured provider (``AI_ASSISTANT_PROVIDER``; ``mock`` unless set)."""
    name = getattr(settings, "AI_ASSISTANT_PROVIDER", "mock")
    if name == "mock":
        return ScriptedChat()
    if name == "anthropic":
        from apps.ai.adapters.anthropic import AnthropicChat

        return AnthropicChat(
            getattr(settings, "ANTHROPIC_API_KEY", ""),
            getattr(settings, "AI_ASSISTANT_MODEL", "claude-sonnet-5"),
        )
    raise AiProviderError(f"assistant provider {name!r} isn't set up")


def system_prompt(tenant: Tenant) -> str:
    return (
        f"You answer questions from the staff of {tenant.name}, a distributor in India, about "
        f"their own business. Today is {today_ist():%d %B %Y} (India time).\n"
        "Rules:\n"
        "- Use only the tools to get figures. Never guess or invent a number, a name or a date.\n"
        "- If the tools can't answer the question, say so plainly and suggest what they can "
        "answer.\n"
        "- Amounts are in rupees (₹), with Indian digit grouping (₹1,23,456.00).\n"
        "- Keep answers short: one to four sentences, or a short numbered list. No tables: the "
        "app shows the figures under your answer.\n"
        "- If the figures cover only the person's own shops, say so.\n"
        "- Answer in the language of the question."
    )


# --- Asking ---------------------------------------------------------------------------------


def _within_rate(user: User) -> bool:
    key = f"ai-ask:{user.pk}:{timezone.now():%Y%m%d%H}"
    cache.add(key, 0, 3600)
    try:
        count = cache.incr(key)
    except ValueError:  # the key expired between add and incr
        cache.set(key, 1, 3600)
        count = 1
    return count <= PER_HOUR


def ask(user: User, question: str) -> AssistantQuestion:
    """Save the question and answer it in the background (after the commit)."""
    tenant = require_tenant_id()
    if not toolbox.tools_for(user):
        raise AssistantUnavailable()
    text = " ".join(question.split())[:MAX_QUESTION]
    if not _within_rate(user):
        raise AssistantRateLimited()
    asked: AssistantQuestion = AssistantQuestion.objects.create(user=user, question=text)

    def send() -> None:
        from apps.ai.tasks import answer_question

        answer_question.delay(tenant_id=str(tenant), question_id=str(asked.pk))

    transaction.on_commit(send)
    return asked


# --- Answering ------------------------------------------------------------------------------


def _chat(
    provider: ChatProvider,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec],
    *,
    timeout: float,
) -> ChatTurn | None:
    """One provider call, recorded in ``AiUsage``; ``None`` when it failed."""
    started = time.monotonic()
    try:
        turn = provider.chat(system, messages, tools, timeout=timeout)
    except Exception as exc:  # any provider trouble: record it and stop
        AiUsage.objects.create(
            feature=AiUsage.Feature.ASSISTANT,
            provider=provider.name,
            duration_ms=int((time.monotonic() - started) * 1000),
            ok=False,
            error=str(exc)[:200],
        )
        log.warning("assistant provider failed", extra={"error": str(exc)[:200]})
        return None
    AiUsage.objects.create(
        feature=AiUsage.Feature.ASSISTANT,
        provider=provider.name,
        model=turn.model[:60],
        units_in=turn.units_in,
        units_out=turn.units_out,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return turn


def _finish(asked: AssistantQuestion, status: str, *, answer: str = "", error: str = "") -> None:
    asked.status = status
    asked.answer = answer[:MAX_ANSWER]
    asked.error = error[:200]
    asked.answered_at = timezone.now()
    asked.duration_ms = int((asked.answered_at - asked.created_at).total_seconds() * 1000)
    asked.save()


def answer(question_id: UUID) -> AssistantQuestion:
    """Answer a waiting question in the active distributor (the Celery task's work)."""
    tenant_id = require_tenant_id()
    asked: AssistantQuestion = AssistantQuestion.objects.select_related("user").get(pk=question_id)
    if asked.status != AssistantQuestion.Status.PENDING:
        return asked
    if not services.enabled(tenant_id):
        _finish(asked, AssistantQuestion.Status.FAILED, error="ai_off")
        return asked
    user = asked.user
    offered = toolbox.tools_for(user)
    specs = [t.spec() for t in offered]
    system = system_prompt(Tenant.objects.get(pk=tenant_id))
    timeout = float(get_platform_setting("platform.ai_assistant_timeout_seconds") or 30)
    try:
        provider = chat_provider()
    except AiProviderError as exc:
        _finish(asked, AssistantQuestion.Status.FAILED, error=str(exc))
        return asked
    messages = [Message("user", text=asked.question)]
    calls: list[dict[str, object]] = []
    for _ in range(MAX_ROUNDS):
        if not services.within_limit(tenant_id):
            asked.tools = calls
            _finish(asked, AssistantQuestion.Status.LIMITED, error="monthly_limit")
            return asked
        turn = _chat(provider, system, messages, specs, timeout=timeout)
        if turn is None:
            asked.tools = calls
            _finish(asked, AssistantQuestion.Status.FAILED, error="provider")
            return asked
        asked.units_in += turn.units_in
        asked.units_out += turn.units_out
        asked.rounds += 1
        if not turn.tool_calls:
            asked.tools = calls
            _finish(asked, AssistantQuestion.Status.ANSWERED, answer=turn.text.strip())
            return asked
        messages.append(Message("assistant", text=turn.text, tool_calls=turn.tool_calls))
        results = []
        for call in turn.tool_calls[:MAX_CALLS_PER_ROUND]:
            try:
                figures = toolbox.run(user, call.name, call.args)
            except toolbox.ToolError as exc:
                calls.append({"name": call.name, "args": call.args, "ok": False, "error": str(exc)})
                results.append(ToolResult(call.id, json.dumps({"error": str(exc)}), error=True))
                continue
            calls.append(
                {"name": call.name, "args": call.args, "ok": True, "figures": figures.as_json()}
            )
            results.append(ToolResult(call.id, json.dumps(figures.for_model(), default=str)))
        for call in turn.tool_calls[MAX_CALLS_PER_ROUND:]:
            results.append(
                ToolResult(call.id, json.dumps({"error": "Too many at once."}), error=True)
            )
        messages.append(Message("user", tool_results=tuple(results)))
    asked.tools = calls
    _finish(asked, AssistantQuestion.Status.FAILED, error="too_many_rounds")
    return asked


def shown_status(asked: AssistantQuestion) -> str:
    """A question still waiting after ``STALE_AFTER`` is shown as failed (a stuck worker)."""
    if (
        asked.status == AssistantQuestion.Status.PENDING
        and timezone.now() - asked.created_at > STALE_AFTER
    ):
        return AssistantQuestion.Status.FAILED
    return asked.status
