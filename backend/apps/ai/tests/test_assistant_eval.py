"""The assistant's evaluation set (ADR-059 item 7) with the scripted mock: each realistic
question reaches the right tool with the right arguments, and its answer carries the figures the
same report gives when run directly; Hindi and Marathi questions are answered in their language."""

import pytest
from django.core.cache import cache

from apps.ai.assistant.evaluation import CASES, run_case
from apps.ai.tests.assistant_world import build
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def test_every_question_of_the_evaluation_set(tenant_a, tenant_b):
    world = build(tenant_a, tenant_b)
    with tenant_context(tenant_a.pk):
        outcomes = [run_case(case, world["owner"], product="Glucose Biscuits") for case in CASES]
    cache.clear()
    failed = [
        f"{o.question}: {'; '.join(o.problems)} (answer: {o.answer!r})"
        for o in outcomes
        if not o.ok
    ]
    assert not failed, "\n".join(failed)
    assert len(outcomes) == 24  # 16 in English, 4 in Hindi, 4 in Marathi
