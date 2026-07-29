"""
通用LLM客户端 - 使用OpenAI兼容协议调用大模型
支持 DeepSeek / 豆包(火山引擎) / Kimi / GLM 等所有OpenAI兼容API
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI

logger = logging.getLogger(__name__)

# 默认配置（支持通过环境变量覆盖）
DEFAULT_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
DEFAULT_LLM_API_KEY = os.getenv("LLM_API_KEY", "")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
DEFAULT_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))


def get_llm_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_LLM_TIMEOUT
) -> OpenAI:
    """获取OpenAI兼容客户端"""
    return OpenAI(
        base_url=base_url or DEFAULT_LLM_BASE_URL,
        api_key=api_key or DEFAULT_LLM_API_KEY,
        timeout=timeout
    )


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    response_json: bool = False,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_LLM_TIMEOUT
) -> str:
    """
    调用大模型获取回复
    
    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大输出token数
        response_json: 是否要求返回JSON格式
        base_url: API基础URL
        api_key: API密钥
        timeout: 超时时间(秒)
    
    Returns:
        模型回复文本
    """
    client = get_llm_client(base_url=base_url, api_key=api_key, timeout=timeout)
    model_name = model or DEFAULT_LLM_MODEL
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    kwargs: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    
    # 如果要求JSON输出
    if response_json:
        # DeepSeek和豆包支持response_format
        kwargs["response_format"] = {"type": "json_object"}
    
    try:
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if content is None:
            content = ""
        return content.strip()
    except Exception as e:
        logger.error(f"LLM调用失败 (model={model_name}): {e}", exc_info=True)
        raise RuntimeError(f"大模型调用失败: {e}") from e


def chat_completion_with_json(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_LLM_TIMEOUT
) -> Any:
    """
    调用大模型并解析JSON回复
    支持多种JSON格式包裹（裸JSON、```json```代码块等）
    """
    # 在system prompt中强制要求JSON
    json_enhanced_sp = system_prompt.strip() + "\n\n重要：请严格以JSON格式返回结果，不要包含任何其他说明文字、Markdown格式或代码块标记。"
    
    content = chat_completion(
        system_prompt=json_enhanced_sp,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_json=True,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout
    )
    
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # 尝试提取JSON代码块
    import re
    # 匹配 ```json ... ``` 或 ``` ... ```
    patterns = [
        r'```json\s*\n?(.*?)\n?```',
        r'```\s*\n?(.*?)\n?```',
        r'\{.*\}',  # 裸JSON对象
        r'\[.*\]',  # 裸JSON数组
    ]
    for pattern in patterns:
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
    
    logger.error(f"LLM返回内容无法解析为JSON: {content[:500]}")
    raise ValueError(f"大模型返回内容无法解析为JSON: {content[:200]}")
