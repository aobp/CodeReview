"""专家分析子图。
使用 LangGraph 子图模式实现专家智能体的工具调用循环。
"""

import logging
from typing import List, Optional, Any, Dict
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from core.state import RiskItem, ExpertState
from core.config import Config
from langchain_core.tools import BaseTool
from util.json_utils import extract_json_from_text
from agents.expert_graph_runtime import ExpertGraphRuntime

logger = logging.getLogger(__name__)


def create_langchain_tools(
    workspace_root: Optional[str] = None,
    asset_key: Optional[str] = None
) -> List[BaseTool]:
    """创建 LangChain 工具列表。
    
    统一使用 langchain_tools.create_tools_with_context 创建标准工具。
    
    Args:
        workspace_root: 工作区根目录（用于工具上下文）。
        asset_key: 仓库映射的资产键（用于 fetch_repo_map）。
    
    Returns:
        LangChain 工具列表：fetch_repo_map, read_file, run_grep。
    """
    from tools.langchain_tools import create_tools_with_context
    from pathlib import Path
    
    if workspace_root:
        workspace_path = Path(workspace_root)
        return create_tools_with_context(
            workspace_root=workspace_path,
            asset_key=asset_key
        )
    else:
        # 如果没有 workspace_root，仍然创建工具（使用默认值）
        return create_tools_with_context(
            workspace_root=None,
            asset_key=asset_key
        )


def tools_condition(state: ExpertState) -> str:
    """条件路由函数：根据最后一条消息是否包含工具调用来决定路由。
    
    Args:
        state: 专家子图状态。
    
    Returns:
        "tools" 如果最后一条消息包含工具调用，否则 "end"。
    """
    messages = state.get("messages", [])
    if not messages:
        return "end"
    
    last_message = messages[-1]
    # 检查最后一条消息是否包含工具调用
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    return "end"


def build_expert_graph(
    llm: BaseChatModel,
    tools: List[BaseTool],
    config: Optional[Config] = None,
) -> Any:
    """构建专家分析子图。
    
    子图结构：
    1. reasoner 节点：调用 LLM 进行分析
    2. tools 节点：执行工具调用（如果 LLM 返回工具调用）
    3. 条件路由：根据是否有工具调用决定继续或结束
    
    Args:
        llm: LangChain 标准 ChatModel。
        tools: LangChain 工具列表。
        config: 配置对象（可选），用于获取最大轮次限制。
    
    Returns:
        编译后的 LangGraph 子图。
    """
    # 工具开关：当 max_expert_tool_calls=0 时，物理上不绑定工具，避免模型产生 tool_calls 后进入 tools 节点。
    max_tool_calls_config = config.system.max_expert_tool_calls if config else 6
    tools_enabled = int(max_tool_calls_config) > 0
    llm_for_reasoner = llm.bind_tools(tools) if tools_enabled else llm
    
    # 创建工具节点
    tool_node = ToolNode(tools)
    
    # 创建 Pydantic 解析器
    parser = PydanticOutputParser(pydantic_object=RiskItem)
    format_instructions = parser.get_format_instructions()
    
    # 格式化可用工具描述
    tool_descriptions = []
    for tool in tools:
        desc = getattr(tool, 'description', f'Tool: {tool.name}')
        tool_descriptions.append(f"- **{tool.name}**: {desc}")
    available_tools_text = "\n".join(tool_descriptions)

    runtime = ExpertGraphRuntime(
        llm_raw=llm,
        llm_for_reasoner=llm_for_reasoner,
        config=config,
        tools_enabled=tools_enabled,
        available_tools_text=available_tools_text,
        format_instructions=format_instructions,
    )
    
    # 构建图
    graph = StateGraph(ExpertState)
    
    # 添加节点
    graph.add_node("reasoner", runtime.reasoner)
    graph.add_node("tools", tool_node)
    
    # 设置入口点
    graph.set_entry_point("reasoner")
    
    # 添加条件边
    def _tools_condition(state: ExpertState) -> str:
        if not tools_enabled:
            return "end"
        return tools_condition(state)

    graph.add_conditional_edges(
        "reasoner",
        _tools_condition,
        {
            "tools": "tools",
            "end": END
        }
    )
    
    # 工具执行后回到 reasoner
    graph.add_edge("tools", "reasoner")
    
    # 编译图
    return graph.compile()


async def run_expert_analysis(
    graph: Any,
    risk_item: RiskItem,
    diff_context: Optional[str] = None,
    file_content: Optional[str] = None,
    recursion_limit: Optional[int] = None,
) -> Optional[dict]:
    """运行专家分析子图。
    
    Args:
        graph: 编译后的专家子图。
        risk_item: 待分析的风险项。
        risk_type_str: 风险类型字符串（用于渲染提示词模板）。
        diff_context: 文件的 diff 上下文（可选）。
        file_content: 文件的完整内容（可选）。
    
    Returns:
        包含 'result' 和 'messages' 的字典，如果失败则返回 None。
        - result: 最终验证结果（RiskItem 对象）
        - messages: 对话历史（消息列表）
    """
    try:
        # 创建 Pydantic 解析器
        parser = PydanticOutputParser(pydantic_object=RiskItem)
        
        # 初始化状态
        initial_state: ExpertState = {
            "messages": [],
            "risk_context": risk_item,
            "final_result": None,
            "diff_context": diff_context,
            "file_content": file_content
        }
        
        # 运行子图
        invoke_kwargs: Dict[str, Any] = {}
        if recursion_limit is not None:
            invoke_kwargs["config"] = {"recursion_limit": int(recursion_limit)}
        final_state = await graph.ainvoke(initial_state, **invoke_kwargs)
        
        # 从消息中提取最后一条消息的文本内容
        messages = final_state.get("messages", [])
        if not messages:
            logger.warning("No messages in final state")
            return None
        
        # 获取最后一条消息的文本内容
        last_message = messages[-1]
        response_text = last_message.content if hasattr(last_message, "content") else str(last_message)
        
        # 从响应文本中提取 JSON
        json_text = extract_json_from_text(response_text)
        if not json_text:
            logger.warning("Could not extract JSON from response")
            logger.warning(f"Response text (first 500 chars): {response_text[:500]}")
            return None
        
        # 使用 PydanticOutputParser 解析提取的 JSON
        try:
            result: RiskItem = parser.parse(json_text)
        except Exception as e:
            logger.warning(f"PydanticOutputParser failed to parse extracted JSON: {e}")
            logger.warning(f"Extracted JSON (first 500 chars): {json_text[:500]}")
            logger.warning(f"Original response (first 500 chars): {response_text[:500]}")
            return None
        
        return {
            "result": result,
            "messages": messages
        }
        
    except Exception as e:
        import traceback
        error_msg = str(e) if str(e) else type(e).__name__
        error_traceback = traceback.format_exception(type(e), e, e.__traceback__)
        logger.error(f"Error running expert analysis: {error_msg}")
        logger.error(f"Traceback:\n{''.join(error_traceback)}")
        return None
