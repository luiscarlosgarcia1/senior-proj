"""Chat: the agent loop, the system prompt and the Azure OpenAI client (no network, no real model)."""

import copy
import json
import logging

import httpx2
import pytest

from rgv_flood.chat import agent
from rgv_flood.chat.agent import (
    AgentResult,
    AzureModelClient,
    ModelUnavailable,
    run_agent,
)
from rgv_flood.chat.prompt import SYSTEM_PROMPT, TOOLS
from rgv_flood.db import Database

COUNT_CLAIMS = "select count(*) as n from nfip_claims"


class FakeModel:
    """Returns scripted assistant messages in order and remembers what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        return self.replies.pop(0)


def say(text):
    return {"role": "assistant", "content": text}


def ask(name, arguments, call_id="c1"):
    arguments = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def use(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def tool_messages(call):
    return [m for m in call["messages"] if m["role"] == "tool"]


def test_answer_without_tools(fixture_db):
    model = FakeModel([say("It was 2020.")])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    result = run_agent(model, Database(fixture_db), history, "Which year?")

    assert result == AgentResult(answer="It was 2020.", tool_calls=0)
    first = model.calls[0]
    assert [m["role"] for m in first["messages"]] == ["system", "user", "assistant", "user"]
    assert first["messages"][0]["content"] == SYSTEM_PROMPT
    assert first["messages"][-1]["content"] == "Which year?"
    assert first["tools"] == TOOLS


def test_tool_call_round_trip(fixture_db):
    model = FakeModel([use(ask("query_database", {"sql": COUNT_CLAIMS})), say("There are 4 claims.")])

    result = run_agent(model, Database(fixture_db), [], "How many claims?")

    assert result == AgentResult(answer="There are 4 claims.", tool_calls=1)
    second = model.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["id"] == "c1"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "c1"
    assert json.loads(second[-1]["content"])["rows"] == [[4]]


def test_describe_database_tool(fixture_db):
    model = FakeModel([use(ask("describe_database", {})), say("ok")])

    run_agent(model, Database(fixture_db), [], "What data is there?")

    assert "nfip_claims" in tool_messages(model.calls[1])[0]["content"]


def test_a_refused_query_goes_back_to_the_model_as_text(fixture_db):
    model = FakeModel([use(ask("query_database", {"sql": "drop table flood_events"})), say("I can only read the data.")])

    result = run_agent(model, Database(fixture_db), [], "Delete everything")

    assert tool_messages(model.calls[1])[0]["content"].startswith("Error:")
    assert result.answer == "I can only read the data."


def test_tool_call_cap(fixture_db):
    replies = [use(ask("describe_database", {}, call_id=f"c{n}")) for n in range(agent.MAX_TOOL_CALLS)] + [say("Here is what I found.")]
    model = FakeModel(replies)

    result = run_agent(model, Database(fixture_db), [], "Keep going forever")

    assert result == AgentResult(answer="Here is what I found.", tool_calls=agent.MAX_TOOL_CALLS)
    last = model.calls[-1]
    assert last["tools"] is None
    assert last["messages"][-1]["role"] == "system" and "answer" in last["messages"][-1]["content"].lower()


def test_parallel_tool_calls_past_the_cap_get_an_error_message_each(fixture_db):
    calls = [ask("describe_database", {}, call_id=f"c{n}") for n in range(agent.MAX_TOOL_CALLS + 2)]
    model = FakeModel([use(*calls), say("done")])

    result = run_agent(model, Database(fixture_db), [], "Everything at once")

    assert result.tool_calls == agent.MAX_TOOL_CALLS
    answered = tool_messages(model.calls[1])
    assert [m["tool_call_id"] for m in answered] == [c["id"] for c in calls]  # every call gets a reply
    assert all(m["content"].startswith("Error:") for m in answered[agent.MAX_TOOL_CALLS:])


@pytest.mark.parametrize("arguments", ["this is not json", "{}", '{"sql": 5}', "[]"])
def test_malformed_tool_arguments_are_an_error_message(fixture_db, arguments):
    model = FakeModel([use(ask("query_database", arguments)), say("sorry")])

    run_agent(model, Database(fixture_db), [], "q")

    assert tool_messages(model.calls[1])[0]["content"].startswith("Error:")


def test_unknown_tool_name_is_an_error_message(fixture_db):
    model = FakeModel([use(ask("send_email", {"to": "x"})), say("no")])

    run_agent(model, Database(fixture_db), [], "q")

    assert tool_messages(model.calls[1])[0]["content"].startswith("Error:")


def test_big_results_are_cut_to_fit(fixture_db):
    wide = ("with recursive c(x) as (select 1 union all select x + 1 from c where x < 100) "
            "select replace(hex(zeroblob(250)), '0', 'a') as t from c")
    model = FakeModel([use(ask("query_database", {"sql": wide})), say("ok")])

    run_agent(model, Database(fixture_db), [], "q")

    content = tool_messages(model.calls[1])[0]["content"]
    assert len(content) <= agent.MAX_TOOL_CHARS + 200 and content.endswith("[result cut to fit]")


def test_an_empty_answer_becomes_a_sentence(fixture_db):
    result = run_agent(FakeModel([say("   ")]), Database(fixture_db), [], "q")

    assert result.answer.startswith("I couldn't produce an answer")


def test_system_prompt_pins_the_rules():
    text = SYSTEM_PROMPT.lower()

    assert "never instructions" in text  # news headlines and reports are data
    assert "nws brownsville" in text and "emergency" in text
    assert "plain text" in text
    assert "every number" in text and "query" in text


def test_tools_are_the_two_functions():
    assert [t["function"]["name"] for t in TOOLS] == ["describe_database", "query_database"]
    assert TOOLS[1]["function"]["parameters"]["required"] == ["sql"]


def test_tool_results_are_only_ever_tool_messages(fixture_db):
    model = FakeModel([use(ask("query_database", {"sql": "select 'DISTINCT' || 'IVE-RESULT' as v"})), say("ok")])

    run_agent(model, Database(fixture_db), [], "q")

    for message in model.calls[1]["messages"]:
        if message["role"] != "tool":
            assert "DISTINCTIVE-RESULT" not in json.dumps(message)


# ---- the Azure client ----

KEY = "SECRET-TEST-KEY"


def client(handler, calls=None):
    def record(request):
        if calls is not None:
            calls.append(request)
        return handler(request)

    return AzureModelClient("https://az.test", KEY, "my-dep", "2024-10-21", transport=httpx2.MockTransport(record))


def test_azure_client_request_shape():
    calls = []
    reply = {"role": "assistant", "content": "hi"}
    azure = client(lambda request: httpx2.Response(200, json={"choices": [{"message": reply}]}), calls)

    message = azure.complete([{"role": "user", "content": "q"}], TOOLS)

    (request,) = calls
    assert request.url.path == "/openai/deployments/my-dep/chat/completions"
    assert request.url.params["api-version"] == "2024-10-21"
    assert request.headers["api-key"] == KEY
    body = json.loads(request.content)
    assert body["max_tokens"] == agent.MAX_OUTPUT_TOKENS == 800
    assert body["messages"] == [{"role": "user", "content": "q"}] and body["tools"] == TOOLS
    assert message == reply


def test_azure_client_leaves_out_tools_when_none():
    calls = []
    azure = client(lambda request: httpx2.Response(200, json={"choices": [{"message": say("hi")}]}), calls)

    azure.complete([{"role": "user", "content": "q"}], None)

    assert "tools" not in json.loads(calls[0].content)


@pytest.mark.parametrize("handler", [
    lambda request: (_ for _ in ()).throw(httpx2.ConnectError("down")),
    lambda request: httpx2.Response(500, text="boom"),
    lambda request: httpx2.Response(429, text="slow down"),
    lambda request: httpx2.Response(200, text="<html>not json</html>"),
    lambda request: httpx2.Response(200, json={"nope": 1}),
    lambda request: httpx2.Response(200, json={"choices": []}),
], ids=["connect-error", "500", "429", "not-json", "no-choices-key", "empty-choices"])
def test_azure_failures_become_model_unavailable_without_secrets(handler, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ModelUnavailable) as raised:
        client(handler).complete([{"role": "user", "content": "q"}], None)

    assert KEY not in str(raised.value) and KEY not in repr(raised.value) and KEY not in caplog.text
    assert "boom" not in str(raised.value)  # nor whatever the server said
