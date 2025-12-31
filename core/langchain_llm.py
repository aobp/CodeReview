"""LangChain LLM 适配器。

将现有的 LLMProvider 包装成 LangChain 的 LLM 接口。
支持 LCEL (LangChain Expression Language) 语法：prompt | llm | parser。
"""

from typing import Any, Optional, List, Dict
from pydantic import PrivateAttr
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.outputs import ChatGeneration, ChatResult
from core.llm import LLMProvider
from core.config import LLMConfig


class LangChainLLMAdapter(BaseChatModel):
    """将 LLMProvider 适配为 LangChain 的 BaseChatModel。
    
    此类将现有的 LLMProvider 包装成 LangChain 兼容的接口。
    允许使用 LCEL 语法：prompt | llm | parser。
    支持工具绑定：llm.bind_tools(tools)。
    """
    
    _llm_provider: LLMProvider = PrivateAttr()
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        **kwargs: Any
    ):
        """初始化适配器。"""
        super().__init__(**kwargs)
        self._llm_provider = llm_provider
    
    @property
    def _llm_type(self) -> str:
        """返回 LLM 类型标识符。"""
        return f"adapter_{self._llm_provider.provider}"
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """生成聊天响应（同步版本）。
        
        注意：此方法应该被 _agenerate 覆盖，因为 LLMProvider 是异步的。
        这里提供同步版本是为了兼容性，但实际应该使用异步版本。
        """
        import asyncio
        return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))
    
    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """生成聊天响应（异步版本）。
        
        将 LangChain 的 BaseMessage 列表转换为字符串提示，
        调用底层的 LLMProvider.generate() 方法，
        将响应包装为 ChatResult 对象。
        """
        # 将消息列表转换为提示字符串
        prompt_parts = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                prompt_parts.append(f"System: {msg.content}")
            elif isinstance(msg, HumanMessage):
                prompt_parts.append(f"Human: {msg.content}")
            elif isinstance(msg, AIMessage):
                prompt_parts.append(f"Assistant: {msg.content}")
            else:
                prompt_parts.append(str(msg.content))
        
        prompt = "\n\n".join(prompt_parts)
        
        # 从 kwargs 中提取参数
        temperature = kwargs.get("temperature", 0.7)
        
        # 调用底层的 LLMProvider
        response_text = await self._llm_provider.generate(
            prompt,
            temperature=temperature,
            **{k: v for k, v in kwargs.items() if k != "temperature"}
        )
        
        # 创建 AIMessage
        ai_message = AIMessage(content=response_text)
        
        # 创建 ChatGeneration
        generation = ChatGeneration(message=ai_message)
        
        # 返回 ChatResult
        return ChatResult(generations=[generation])
    
    @classmethod
    def from_config(cls, config: LLMConfig) -> "LangChainLLMAdapter":
        """从配置创建适配器实例。"""
        llm_provider = LLMProvider(config)
        return cls(llm_provider=llm_provider)
