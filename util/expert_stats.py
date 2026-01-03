"""Expert analysis statistics helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from langchain_core.messages import AIMessage, ToolMessage


def count_tool_messages(messages: Iterable[Any]) -> int:
    return sum(1 for m in messages if isinstance(m, ToolMessage))


def count_ai_rounds(messages: Iterable[Any]) -> int:
    return sum(1 for m in messages if isinstance(m, AIMessage))


def build_tool_call_stats(records: Iterable[Tuple[int, int]]) -> Dict[str, Any]:
    """records: iterable of (tool_calls_used, ai_rounds_used) per risk."""
    tool_calls = [int(a) for a, _ in records]
    rounds = [int(b) for _, b in records]
    n = len(tool_calls)
    hist = dict(sorted(Counter(tool_calls).items(), key=lambda kv: kv[0]))
    avg = (sum(tool_calls) / n) if n else 0.0
    max_calls = max(tool_calls) if n else 0
    avg_rounds = (sum(rounds) / n) if n else 0.0
    max_rounds = max(rounds) if n else 0
    return {
        "total_risks": n,
        "tool_calls_hist": hist,
        "tool_calls_avg": avg,
        "tool_calls_max": max_calls,
        "ai_rounds_avg": avg_rounds,
        "ai_rounds_max": max_rounds,
    }


def format_tool_call_summary(stats: Mapping[str, Any]) -> str:
    total = int(stats.get("total_risks", 0) or 0)
    hist = stats.get("tool_calls_hist") or {}
    avg = float(stats.get("tool_calls_avg", 0.0) or 0.0)
    max_calls = int(stats.get("tool_calls_max", 0) or 0)
    avg_rounds = float(stats.get("ai_rounds_avg", 0.0) or 0.0)
    max_rounds = int(stats.get("ai_rounds_max", 0) or 0)

    parts: List[str] = []
    parts.append("\n" + "=" * 80)
    parts.append("🧮 Expert tool-call stats")
    parts.append("=" * 80)
    parts.append(f"Total risks: {total}")
    parts.append(f"Tool calls: avg={avg:.2f}, max={max_calls}")
    parts.append(f"AI rounds: avg={avg_rounds:.2f}, max={max_rounds}")

    if isinstance(hist, dict) and hist:
        items = sorted(((int(k), int(v)) for k, v in hist.items()), key=lambda kv: kv[0])
        hist_str = ", ".join(f"{k}次={v}个" for k, v in items)
        parts.append(f"Histogram: {hist_str}")
    else:
        parts.append("Histogram: <empty>")

    parts.append("=" * 80)
    return "\n".join(parts)

