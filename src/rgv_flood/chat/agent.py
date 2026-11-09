"""The agent loop: the model asks for queries, we run them read-only, it answers.

The model sits behind `ModelClient`, so tests use a scripted fake and nothing
here talks to Azure unless an `AzureModelClient` is built with real settings.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx2

from rgv_flood.chat.prompt import FINAL_INSTRUCTION, SYSTEM_PROMPT, TOOLS
from rgv_flood.chat.sqltool import QueryRefused, describe_database, run_select
from rgv_flood.db import Database

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_OUTPUT_TOKENS = 800
MAX_TOOL_CHARS = 12000  # a tool result is cut to this many characters before the model sees it
UNAVAILABLE = "The assistant is unavailable right now."
NO_ANSWER = "I couldn't produce an answer to that. Please try rephrasing the question."


class ModelUnavailable(Exception):
    """The model could not be reached or answered badly. The message is safe to show."""


class ModelClient(Protocol):
    def complete(self, messages: list[dict], tools: list[dict] | None) -> dict:
        """The assistant's reply message (`role`, `content`, optionally `tool_calls`)."""


class AzureModelClient:
    """Azure OpenAI chat completions. The key stays in a header and out of every error."""

    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str, *, transport=None, timeout: float = 60.0):
        self.url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
        self.api_version = api_version
        self.client = httpx2.Client(transport=transport, timeout=timeout, headers={"api-key": api_key})

    def complete(self, messages: list[dict], tools: list[dict] | None) -> dict:
        body: dict = {"messages": messages, "max_tokens": MAX_OUTPUT_TOKENS, "temperature": 0.2}
        if tools:
            body["tools"] = tools
        try:
            response = self.client.post(self.url, params={"api-version": self.api_version}, json=body)
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError("message is not an object")
            return message
        except (httpx2.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise ModelUnavailable(UNAVAILABLE) from None


@dataclass
class AgentResult:
    answer: str
    tool_calls: int


def _fit(text: str) -> str:
    return text if len(text) <= MAX_TOOL_CHARS else text[:MAX_TOOL_CHARS] + "\n[result cut to fit]"


def _run_tool(db: Database, name: str, arguments: str) -> str:
    """One tool call's result as the text the model reads; problems come back as `Error: ...`."""
    try:
        parsed = json.loads(arguments or "{}")
        if not isinstance(parsed, dict):
            return "Error: the arguments must be a JSON object."
        if name == "describe_database":
            return _fit(json.dumps(describe_database(db), default=str))
        if name == "query_database":
            sql = parsed.get("sql")
            if not isinstance(sql, str):
                return 'Error: query_database needs a string argument "sql".'
            return _fit(json.dumps(run_select(db, sql), default=str))
        return f"Error: there is no tool named {name}."
    except json.JSONDecodeError:
        return "Error: the arguments were not valid JSON."
    except QueryRefused as refused:
        return f"Error: {refused}"
    except Exception:
        logger.exception("chat tool failed")
        return "Error: that could not be run."


def run_agent(model: ModelClient, db: Database, history: list[dict], message: str) -> AgentResult:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": message}]
    used = 0
    while True:
        capped = used >= MAX_TOOL_CALLS
        if capped:
            messages.append({"role": "system", "content": FINAL_INSTRUCTION})
        reply = model.complete(messages, None if capped else TOOLS)
        calls = None if capped else reply.get("tool_calls")
        if not calls:
            return AgentResult(answer=(reply.get("content") or "").strip() or NO_ANSWER, tool_calls=used)
        messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": calls})
        for call in calls:
            if used >= MAX_TOOL_CALLS:
                result = "Error: the tool-call limit was reached; answer with what you have."
            else:
                used += 1
                function = call.get("function") or {}
                result = _run_tool(db, function.get("name", ""), function.get("arguments", ""))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
