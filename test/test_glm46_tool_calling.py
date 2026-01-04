"""Manual capability test for GLM-4.6 tool-calling (and thus web-search integration).

This test does NOT prove the model has built-in web browsing.
It verifies that GLM-4.6 can emit tool calls when tools are provided, which is
how this repo should implement "联网搜索": provide a `web_search` tool and optionally
an URL fetch/extract tool.

Run:
  ZHIPUAI_API_KEY=... python test/test_glm46_tool_calling.py

Optional:
  ZHIPUAI_MODEL=glm-4.6 python test/test_glm46_tool_calling.py

Exit codes:
  0: pass (or skipped when no API key)
  2: failed assertions
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional, Tuple

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from core.zhipuai_compat import ChatZhipuAICompat


@tool
def web_search(query: str) -> str:
    """Mock web search tool.

    In real usage, replace this implementation with a call to SearxNG
    (e.g., GET /search?q=...&format=json) and return compact JSON.
    """

    payload = {
        "query": query,
        "results": [
            {
                "title": "SearxNG (example)",
                "url": "https://example.com/searxng",
                "snippet": "Example snippet for testing tool-calling.",
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_first_tool_call(ai_message: Any) -> Tuple[str, str, Dict[str, Any]]:
    """Return (tool_call_id, tool_name, args_dict) from the first tool call."""

    tool_calls = getattr(ai_message, "tool_calls", None) or (ai_message.additional_kwargs or {}).get("tool_calls")
    if not tool_calls:
        raise AssertionError("Expected at least one tool call, got none")

    first = tool_calls[0]

    # ZhipuAI / OpenAI-like schema
    if isinstance(first, dict) and isinstance(first.get("function"), dict) and isinstance(first.get("id"), str):
        tool_call_id = first["id"]
        tool_name = first["function"].get("name")
        arguments = first["function"].get("arguments")
        if not isinstance(tool_name, str) or not tool_name:
            raise AssertionError(f"Malformed tool call (missing function.name): {first}")
        if isinstance(arguments, str) and arguments.strip():
            try:
                args = json.loads(arguments)
            except Exception as e:
                raise AssertionError(f"Failed to parse function.arguments JSON: {e}: {arguments}")
        else:
            args = {}
        return tool_call_id, tool_name, args

    # LangChain simplified schema
    if isinstance(first, dict):
        tool_call_id = first.get("id") or first.get("tool_call_id")
        tool_name = first.get("name")
        args = first.get("args")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise AssertionError(f"Malformed tool call (missing id): {first}")
        if not isinstance(tool_name, str) or not tool_name:
            raise AssertionError(f"Malformed tool call (missing name): {first}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise AssertionError(f"Malformed tool call (args is not dict): {first}")
        return tool_call_id, tool_name, args

    raise AssertionError(f"Unknown tool call schema: {type(first).__name__}: {first}")


async def _run() -> None:
    api_key = os.environ.get("ZHIPUAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("SKIP: set ZHIPUAI_API_KEY (or LLM_API_KEY) to run the live test")
        return

    model = os.environ.get("ZHIPUAI_MODEL") or "glm-4.6"

    llm = ChatZhipuAICompat(
        model=model,
        api_key=api_key,
        temperature=0,
    )

    llm_with_tools = llm.bind_tools([web_search])

    prompt = (
        "你是一个严格的测试代理。\n"
        "你必须调用一次 web_search 工具来查询: 'Django QuerySet negative slicing behavior'。\n"
        "拿到工具返回的 JSON 后，只输出 results[0].url（不要输出任何解释）。"
    )

    user_msg = HumanMessage(content=prompt)

    # Round 1: expect a tool call
    ai_msg = await llm_with_tools.ainvoke([user_msg])
    tool_call_id, tool_name, tool_args = _extract_first_tool_call(ai_msg)

    if tool_name != "web_search":
        raise AssertionError(f"Expected tool 'web_search', got: {tool_name}")

    # Execute tool
    tool_output = web_search.invoke(tool_args)
    tool_msg = ToolMessage(content=tool_output, tool_call_id=tool_call_id, name=tool_name)

    # Round 2: ensure compatibility wrapper can serialize tool_calls + tool message
    final_msg = await llm_with_tools.ainvoke([user_msg, ai_msg, tool_msg])

    content = (final_msg.content or "").strip()
    if "example.com" not in content:
        raise AssertionError(f"Expected final answer to contain example.com, got: {content!r}")

    print("PASS")
    print(f"model={model}")
    print(f"final={content}")


def main() -> int:
    try:
        asyncio.run(_run())
        return 0
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
