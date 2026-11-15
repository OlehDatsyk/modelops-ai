"""AI Analyst: a tool-using LLM loop (OpenAI or Anthropic) over the controlled analytics tools."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.base import extract_error_message
from app.providers.registry import get_http_client
from app.services.analyst_tools import TOOLS, ToolContext, run_tool

logger = logging.getLogger("modelops.analyst")

MAX_TOOL_ROUNDS = 6
MAX_RESULT_CHARS = 12_000

SYSTEM_PROMPT = """You are the ModelOps AI Analyst, an assistant that explains a customer's AI API usage and costs.

Rules:
- Base every number you state on tool results from this conversation. Never invent figures.
- Call tools to gather data before answering. Prefer few, targeted calls.
- All costs are ESTIMATES derived from a configurable pricing table; say so when discussing money.
  If tool results show unpriced requests, mention that costs for those requests are unknown.
- If there is too little data to answer (e.g. zero requests in the period), say so plainly and
  suggest what data would be needed.
- Times are UTC.
- Be concise: lead with the direct answer, then 2-5 supporting bullet points with metrics, then
  (when relevant) concrete recommendations.
- You cannot see prompts or responses, only metadata (tokens, cost, latency, status).
"""


@dataclass
class AnalystResult:
    answer: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)


def _truncate(data: dict[str, Any]) -> str:
    text = json.dumps(data, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '..."(truncated)"'


async def ask(ctx: ToolContext, history: list[dict[str, str]], question: str) -> AnalystResult:
    settings = get_settings()
    if not settings.analyst_configured:
        raise AppError(503, "analyst_not_configured", "The AI Analyst is not configured on this server.")
    try:
        if settings.ai_analyst_provider == "anthropic":
            return await _ask_anthropic(ctx, history, question)
        return await _ask_openai(ctx, history, question)
    except httpx.TimeoutException:
        raise AppError(504, "analyst_timeout", "The AI Analyst timed out. Please try again.") from None
    except httpx.HTTPError:
        raise AppError(502, "analyst_unreachable", "Could not reach the AI Analyst provider.") from None


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        logger.warning("Analyst provider returned HTTP %s", resp.status_code)
        message = extract_error_message(resp.content)
        raise AppError(502, "analyst_provider_error", f"AI Analyst provider error (HTTP {resp.status_code}): {message}")


async def _ask_openai(ctx: ToolContext, history: list[dict[str, str]], question: str) -> AnalystResult:
    settings = get_settings()
    url = settings.openai_base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.ai_analyst_api_key}"}
    tools = [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.json_schema()},
        }
        for t in TOOLS.values()
    ]
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append({"role": "user", "content": question})
    evidence: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_ROUNDS + 1):
        resp = await get_http_client().post(
            url,
            headers=headers,
            timeout=httpx.Timeout(90.0, connect=10.0),
            json={"model": settings.ai_analyst_model, "messages": messages, "tools": tools},
        )
        _raise_for_status(resp)
        message = (resp.json().get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            return AnalystResult((message.get("content") or "").strip() or "No answer was produced.", evidence)
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            result = await run_in_threadpool(run_tool, ctx, fn.get("name", ""), args if isinstance(args, dict) else {})
            evidence.append({"tool": fn.get("name"), "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _truncate(result)})
    return AnalystResult("I could not complete the analysis within the allowed number of steps.", evidence)


async def _ask_anthropic(ctx: ToolContext, history: list[dict[str, str]], question: str) -> AnalystResult:
    settings = get_settings()
    url = settings.anthropic_base_url.rstrip("/") + "/v1/messages"
    headers = {"x-api-key": settings.ai_analyst_api_key, "anthropic-version": settings.anthropic_version}
    tools = [{"name": t.name, "description": t.description, "input_schema": t.json_schema()} for t in TOOLS.values()]
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    evidence: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_ROUNDS + 1):
        resp = await get_http_client().post(
            url,
            headers=headers,
            timeout=httpx.Timeout(90.0, connect=10.0),
            json={
                "model": settings.ai_analyst_model,
                "max_tokens": 1500,
                "system": SYSTEM_PROMPT,
                "messages": messages,
                "tools": tools,
            },
        )
        _raise_for_status(resp)
        data = resp.json()
        content = data.get("content") or []
        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not tool_uses:
            text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            return AnalystResult(text.strip() or "No answer was produced.", evidence)
        messages.append({"role": "assistant", "content": content})
        results = []
        for block in tool_uses:
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            result = await run_in_threadpool(run_tool, ctx, block.get("name", ""), args)
            evidence.append({"tool": block.get("name"), "args": args, "result": result})
            results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": _truncate(result)})
        messages.append({"role": "user", "content": results})
    return AnalystResult("I could not complete the analysis within the allowed number of steps.", evidence)
