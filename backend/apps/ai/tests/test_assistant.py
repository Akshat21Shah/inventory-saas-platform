"""The data assistant (ADR-059): the tools are the person's reports (permissions, own shops,
costs), questions are answered in the background and logged, only the asker sees them, the
module flag, the monthly cap, the hourly limit, provider failures and runaway tool loops, and
nothing personal reaches the model."""

from datetime import date, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.ai.adapters import mock_chat
from apps.ai.adapters.chat import ChatTurn, ToolCall
from apps.ai.adapters.mock_chat import ScriptedChat
from apps.ai.assistant import periods, service
from apps.ai.assistant import tools as toolbox
from apps.ai.models import AiUsage, AssistantQuestion
from apps.ai.tests.assistant_world import build
from apps.ai.tests.test_semantic_search import switch
from apps.orders.tests.helpers import client_for, settings, shop_client
from apps.platform.services import set_platform_settings
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1/assistant"


@pytest.fixture
def world(tenant_a, tenant_b):
    data = build(tenant_a, tenant_b)
    yield data
    cache.clear()


def ask(client: Any, question: str, django_capture_on_commit_callbacks: Any) -> dict[str, Any]:
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{API}/questions/", {"question": question}, format="json")
    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "PENDING"
    body: dict[str, Any] = client.get(f"{API}/questions/{response.json()['id']}/").json()
    return body


def names(tool_list: list[toolbox.Tool]) -> set[str]:
    return {t.name for t in tool_list}


def test_periods_in_india_time():
    friday = date(2026, 10, 2)
    assert periods.dates("today", friday) == (friday, friday)
    assert periods.dates("this_week", friday) == (date(2026, 9, 28), friday)
    assert periods.dates("last_week", friday) == (date(2026, 9, 21), date(2026, 9, 27))
    assert periods.dates("last_30_days", friday) == (date(2026, 9, 3), friday)
    assert periods.dates("last_month", friday) == (date(2026, 9, 1), date(2026, 9, 30))
    assert periods.dates("this_quarter", friday) == (date(2026, 10, 1), friday)
    assert periods.dates("last_quarter", friday) == (date(2026, 7, 1), date(2026, 9, 30))
    assert periods.dates("this_financial_year", friday) == (date(2026, 4, 1), friday)
    assert periods.dates("last_financial_year", friday) == (date(2025, 4, 1), date(2026, 3, 31))
    assert periods.dates("last_month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    with pytest.raises(ValueError):
        periods.dates("next_month", friday)


def test_the_tools_are_the_persons_reports(world):
    with tenant_context(world["t"].pk):
        assert len(toolbox.tools_for(world["owner"])) == len(toolbox.TOOLS) == 11
        assert names(toolbox.tools_for(world["warehouse"])) == {
            "low_stock",
            "product_stock",
            "backorders",
        }
        sales = names(toolbox.tools_for(world["sales"]))
        assert "dues" in sales
        assert "low_stock" not in sales
        with pytest.raises(toolbox.ToolError):  # never offered, and refused if asked for
            toolbox.run(world["warehouse"], "dues", {})
        with pytest.raises(toolbox.ToolError):
            toolbox.run(world["owner"], "drop_table", {})


def test_arguments_are_checked(world):
    with tenant_context(world["t"].pk):
        owner = world["owner"]
        for bad in (
            {"period": "next_year"},
            {"limit": 50},
            {"limit": "lots"},
            {"sql": "select 1"},
        ):
            with pytest.raises(toolbox.ToolError):
                toolbox.run(owner, "top_products", bad)
        with pytest.raises(toolbox.ToolError):
            toolbox.run(owner, "product_stock", {})
        figures = toolbox.run(owner, "top_products", {"period": "today", "limit": 1})
    assert (figures.count, len(figures.rows)) == (2, 1)
    assert figures.rows[0]["name"] == "Glucose Biscuits 100g"


def test_sales_staff_see_their_own_shops_and_no_costs(world):
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    with tenant_context(world["t"].pk):
        mine = toolbox.run(world["sales"], "top_shops", {"period": "today"})
        everyone = toolbox.run(world["owner"], "top_shops", {"period": "today"})
        products = toolbox.run(world["sales"], "top_products", {"period": "today"})
        costed = toolbox.run(world["owner"], "top_products", {"period": "today"})
    assert [r["name"] for r in mine.rows] == ["Anand Stores"]
    assert mine.own_shops
    assert {r["name"] for r in everyone.rows} == {"Anand Stores", "Balaji Mart"}
    assert "margin" not in {c["key"] for c in products.columns}
    assert "margin" in {c["key"] for c in costed.columns}
    assert "only_the_askers_own_shops" in mine.for_model()


def test_nothing_personal_is_sent(world):
    with tenant_context(world["t"].pk):
        paid = toolbox.run(world["owner"], "collections", {"period": "today"})
        world["sales"].full_name = ""
        world["sales"].save(update_fields=["full_name"])
        shops = toolbox.run(world["owner"], "shops_not_ordering", {"days": 0 + 1})
    sent = str(paid.for_model()) + str(shops.for_model())
    assert "UTR998877" not in sent  # payment references aren't sent
    assert "@" not in sent  # emails never
    assert "98765" not in sent  # nor mobile numbers
    assert toolbox._scrub("name", "Call 98765 00171 or a@b.co") == "Call — or —"
    assert toolbox._scrub("code", "9876500171") == "9876500171"


@covers("assistant-questions", "assistant-question")
def test_asking_and_reading_answers_only_the_asker(world, django_capture_on_commit_callbacks):
    owner = client_for(world["t"], world["owner"])
    body = ask(owner, "Which shops haven't ordered in 30 days?", django_capture_on_commit_callbacks)
    assert body["status"] == "ANSWERED"
    assert "Durga Traders (45 days)" in body["answer"]
    assert "Chamunda Kirana" in body["answer"]
    [call] = body["tools"]
    assert (call["name"], call["args"], call["ok"]) == ("shops_not_ordering", {"days": 30}, True)
    assert [r["name"] for r in call["figures"]["rows"]] == ["Durga Traders", "Chamunda Kirana"]
    listed = owner.get(f"{API}/questions/").json()["results"]
    assert [q["id"] for q in listed] == [body["id"]]
    # Someone else in the business, and another distributor, can't see it.
    sales = client_for(world["t"], world["sales"])
    assert sales.get(f"{API}/questions/{body['id']}/").status_code == 404
    assert sales.get(f"{API}/questions/").json()["results"] == []
    from apps.accounts.tests.factories import make_staff_in

    switch(world["b"])
    other = client_for(world["b"], make_staff_in(world["b"], "OWNER"))
    assert other.get(f"{API}/questions/{body['id']}/").status_code == 404
    assert other.get(f"{API}/questions/").json()["results"] == []
    with tenant_context(world["t"].pk):
        assert AiUsage.objects.filter(feature="ASSISTANT").count() == 2  # the tool call, the answer


@covers("assistant-tools")
def test_tools_shops_and_the_module_switch(world):
    owner = client_for(world["t"], world["owner"])
    tools = owner.get(f"{API}/tools/").json()["tools"]
    assert len(tools) == 11
    assert tools[0] == {"name": "sales_summary", "report": "sales_summary"}
    warehouse = client_for(world["t"], world["warehouse"]).get(f"{API}/tools/").json()
    assert [t["name"] for t in warehouse["tools"]] == ["low_stock", "product_stock", "backorders"]
    shop = shop_client(world["t"], world["anand"])
    assert shop.get(f"{API}/tools/").status_code == 403
    assert shop.post(f"{API}/questions/", {"question": "sales today"}).status_code == 403
    switch(world["t"], on=False)
    refused = owner.post(f"{API}/questions/", {"question": "sales today"}, format="json")
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")
    assert owner.get(f"{API}/tools/").status_code == 403


def test_a_question_without_a_fitting_tool(world, django_capture_on_commit_callbacks):
    warehouse = client_for(world["t"], world["warehouse"])
    body = ask(warehouse, "Who owes us the most?", django_capture_on_commit_callbacks)
    assert body["status"] == "ANSWERED"
    assert body["tools"] == []
    assert "don't have access" in body["answer"]
    body = ask(warehouse, "Tell me a joke", django_capture_on_commit_callbacks)
    assert "I can answer questions" in body["answer"]


def test_the_monthly_cap(world, django_capture_on_commit_callbacks):
    with tenant_context(world["t"].pk):
        AiUsage.objects.create(feature="SEARCH_QUERY", provider="mock", units_in=5)
    set_platform_settings({"platform.ai_monthly_units": 1}, user=None)
    cache.clear()
    body = ask(
        client_for(world["t"], world["owner"]), "Sales today", django_capture_on_commit_callbacks
    )
    assert body["status"] == "LIMITED"
    assert body["answer"] == ""
    with tenant_context(world["t"].pk):
        assert not AiUsage.objects.filter(feature="ASSISTANT").exists()  # nothing was sent


def test_provider_failures_and_runaway_loops(
    world, monkeypatch, django_capture_on_commit_callbacks
):
    owner = client_for(world["t"], world["owner"])

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("took too long")

    monkeypatch.setattr(ScriptedChat, "chat", broken)
    body = ask(owner, "Sales today", django_capture_on_commit_callbacks)
    assert body["status"] == "FAILED"
    with tenant_context(world["t"].pk):
        failed = AiUsage.objects.get(feature="ASSISTANT")
        assert (failed.ok, failed.error) == (False, "took too long")

    def forever(self: Any, system: str, messages: list[Any], tools: list[Any], **kw: Any) -> Any:
        return ChatTurn("", (ToolCall("c", "sales_summary", {"period": "today"}),), 10, 1, "m")

    monkeypatch.setattr(ScriptedChat, "chat", forever)
    body = ask(owner, "Sales today", django_capture_on_commit_callbacks)
    assert body["status"] == "FAILED"
    assert len(body["tools"]) == service.MAX_ROUNDS
    with tenant_context(world["t"].pk):
        asked = AssistantQuestion.objects.get(pk=body["id"])
        assert (asked.rounds, asked.error, asked.units_in) == (4, "too_many_rounds", 40)


def test_bad_arguments_go_back_to_the_model(world, monkeypatch, django_capture_on_commit_callbacks):
    def wrong(self: Any, system: str, messages: list[Any], tools: list[Any], **kw: Any) -> Any:
        if messages[-1].tool_results:
            return ChatTurn("Sorry, I couldn't.", (), 1, 1, "m")
        return ChatTurn("", (ToolCall("c", "top_products", {"period": "someday"}),), 1, 1, "m")

    monkeypatch.setattr(ScriptedChat, "chat", wrong)
    body = ask(
        client_for(world["t"], world["owner"]), "Top products", django_capture_on_commit_callbacks
    )
    assert body["status"] == "ANSWERED"
    assert body["answer"] == "Sorry, I couldn't."
    [call] = body["tools"]
    assert call["ok"] is False
    assert "Unknown period" in call["error"]


def test_the_hourly_limit(world, monkeypatch):
    monkeypatch.setattr(service, "PER_HOUR", 2)
    owner = client_for(world["t"], world["owner"])
    for _ in range(2):
        asked = owner.post(f"{API}/questions/", {"question": "sales today"}, format="json")
        assert asked.status_code == 202
    refused = owner.post(f"{API}/questions/", {"question": "sales today"}, format="json")
    assert (refused.status_code, refused.json()["error"]["code"]) == (429, "ASSISTANT_RATE_LIMITED")
    short = owner.post(f"{API}/questions/", {"question": "hi"}, format="json")
    assert short.status_code == 400


def test_a_question_stuck_waiting_shows_as_failed(world):
    with tenant_context(world["t"].pk):
        asked = AssistantQuestion.objects.create(user=world["owner"], question="Sales today")
        AssistantQuestion.objects.filter(pk=asked.pk).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )
    body = client_for(world["t"], world["owner"]).get(f"{API}/questions/{asked.pk}/").json()
    assert body["status"] == "FAILED"


def test_the_mocks_wording_of_amounts():
    assert mock_chat.rupees("123456.5") == "₹1,23,456.50"
    assert mock_chat.rupees("-950") == "-₹950.00"
    rows = [{"name": "Gurukrupa Stores", "net": "950.00"}, {"name": "Ganesh", "net": "-1200.00"}]
    credit = mock_chat.write("dues", {"rows": rows, "totals": {"net": "-250.00"}}, {})
    assert credit == (
        "Owed the most: Gurukrupa Stores ₹950.00. Counting the credit shops hold, the balance "
        "is ₹250.00 in their favour."
    )
    owed = mock_chat.write("dues", {"rows": rows[:1], "totals": {"net": "950.00"}}, {})
    assert owed.endswith("shops owe ₹950.00 in all.")


def test_the_mock_offers_only_what_the_person_may_ask_and_says_when_costs_are_withheld(world):
    with tenant_context(world["t"].pk):
        sales = {t.name for t in toolbox.tools_for(world["sales"])}
        warehouse = {t.name for t in toolbox.tools_for(world["warehouse"])}
    assert "stock" not in mock_chat.can_answer(sales)
    assert mock_chat.can_answer(warehouse) == (
        "I can answer questions about low stock, a product's stock and backorders. "
        "Try “Which products are running low?”"
    )
    assert "no figures" in mock_chat.can_answer(set())
    without = {"columns": {"name": "Product", "total": "Total"}}
    with_margin = {"columns": {"name": "Product", "margin": "Margin"}}
    assert mock_chat.costs_note("What is our margin on top products?", without).startswith(
        "Costs and margins aren't shown to you"
    )
    assert mock_chat.costs_note("What is our margin on top products?", with_margin) == ""
    assert mock_chat.costs_note("Top products this month", without) == ""


def test_a_salesperson_asking_for_margins_is_told_they_are_not_shown(
    world, django_capture_on_commit_callbacks
):
    question = "What is our margin on the top products today?"
    sales = client_for(world["t"], world["sales"])
    body = ask(sales, question, django_capture_on_commit_callbacks)
    assert body["answer"].startswith("Costs and margins aren't shown to you")
    [call] = body["tools"]
    assert "margin" not in {c["key"] for c in call["figures"]["columns"]}
    owner = client_for(world["t"], world["owner"])
    body = ask(owner, question, django_capture_on_commit_callbacks)
    assert not body["answer"].startswith("Costs and margins")
    assert "margin" in {c["key"] for c in body["tools"][0]["figures"]["columns"]}
