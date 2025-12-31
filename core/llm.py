"""LLM 提供商抽象层。

提供统一的 LLM 接口，包含用于测试的 mock 实现。
"""

from typing import Any, Dict, List, Optional
from core.config import LLMConfig


class LLMProvider:
    """LLM 提供商统一接口。"""
    
    def __init__(self, config: LLMConfig):
        """初始化 LLM 提供商。"""
        self.config = config
        self.provider = config.provider
        self.model = config.model
    
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """生成 LLM 响应。"""
        if self.provider == "mock":
            return await self._mock_generate(prompt, **kwargs)
        elif self.provider == "openai":
            return await self._openai_generate(prompt, **kwargs)
        elif self.provider == "deepseek":
            return await self._deepseek_generate(prompt, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
    
    async def _mock_generate(self, prompt: str, **kwargs: Any) -> str:
        """Mock LLM 实现（用于测试）。"""
        prompt_lower = prompt.lower()
        
        # Pattern matching for different types of prompts
        if "focus" in prompt_lower or "prioritize" in prompt_lower or "which files" in prompt_lower:
            # Manager node asking which files to review
            return """{
            "focus_files": [
                "src/main.py",
                "src/utils/helpers.py"
            ],
            "reasoning": "These files contain the core logic changes and should be reviewed first."
            }"""
        
        elif "review" in prompt_lower or "issue" in prompt_lower or "comment" in prompt_lower:
            # Reviewer node generating review comments
            return """[
            {
                "file": "src/main.py",
                "line": 42,
                "severity": "warning",
                "message": "Consider adding error handling for this operation.",
                "suggestion": "Wrap this in a try-except block to handle potential exceptions."
            },
            {
                "file": "src/utils/helpers.py",
                "line": 15,
                "severity": "info",
                "message": "Function could benefit from type hints.",
                "suggestion": "Add type annotations to improve code clarity."
            }
            ]"""
        
        elif "summary" in prompt_lower or "analyze" in prompt_lower:
            # General analysis request
            return "This is a mock analysis summary. In production, this would contain detailed insights from the LLM."
        
        else:
            # Default mock response
            return "Mock LLM response: I understand your request. This is a placeholder response for testing purposes."
    
    async def _openai_generate(self, prompt: str, **kwargs: Any) -> str:
        """OpenAI LLM 实现。
        
        Raises:
            ValueError: API 密钥未配置。
            Exception: API 调用失败。
        """
        try:
            import openai
            
            if not self.config.api_key:
                raise ValueError("OpenAI API key is required but not configured")
            
            client = openai.AsyncOpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
            
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", 2000)
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content or ""
        except ImportError:
            raise ImportError("openai package is required for OpenAI provider. Install with: pip install openai")
        except Exception as e:
            raise Exception(f"OpenAI API call failed: {str(e)}")
    
    async def _deepseek_generate(self, prompt: str, **kwargs: Any) -> str:
        """DeepSeek LLM 实现（使用 OpenAI 兼容 API）。
        
        Raises:
            ValueError: API 密钥未配置。
            Exception: API 调用失败。
        """
        try:
            import openai
            
            if not self.config.api_key:
                raise ValueError("DeepSeek API key is required but not configured. Set DEEPSEEK_API_KEY environment variable or configure in config file.")
            
            # DeepSeek uses OpenAI-compatible API
            base_url = self.config.base_url or "https://api.deepseek.com"
            client = openai.AsyncOpenAI(api_key=self.config.api_key, base_url=base_url)
            
            temperature = kwargs.get("temperature", self.config.temperature)
            max_tokens = kwargs.get("max_tokens", 2000)
            
            # Default model for DeepSeek if not specified
            model = self.model if self.model != "gpt-4" else "deepseek-chat"
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content or ""
        except ImportError:
            raise ImportError("openai package is required for DeepSeek provider. Install with: pip install openai")
        except Exception as e:
            raise Exception(f"DeepSeek API call failed: {str(e)}")
    
    async def generate_structured(self, prompt: str, response_format: str = "json", **kwargs: Any) -> Dict[str, Any]:
        """生成结构化响应（如 JSON）。"""
        response = await self.generate(prompt, **kwargs)
        
        if response_format == "json":
            try:
                import json
                # Try to extract JSON from the response (in case it's wrapped in markdown)
                response_clean = response.strip()
                if response_clean.startswith("```json"):
                    response_clean = response_clean[7:]
                if response_clean.startswith("```"):
                    response_clean = response_clean[3:]
                if response_clean.endswith("```"):
                    response_clean = response_clean[:-3]
                response_clean = response_clean.strip()
                
                return json.loads(response_clean)
            except json.JSONDecodeError as e:
                return {
                    "raw": response,
                    "error": f"Failed to parse JSON response: {str(e)}"
                }
        else:
            return {"raw": response}

