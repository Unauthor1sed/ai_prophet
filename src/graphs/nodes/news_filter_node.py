"""资讯筛选节点 - 大模型智能筛选和排序资讯"""
import os
import json
import re
import time
import datetime
import logging
from typing import List, Dict, Any
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from llm_client import chat_completion_with_json
from graphs.state import NewsFilterInput, NewsFilterOutput

logger = logging.getLogger(__name__)


def news_filter_node(state: NewsFilterInput, config: RunnableConfig, runtime: Runtime[Context]) -> NewsFilterOutput:
    """
    title: 资讯筛选
    desc: 使用大模型对去重后的资讯进行智能筛选和排序，保留高质量AI前沿资讯
    integrations: 大语言模型
    """
    deduped_news: List[Dict[str, Any]] = state.deduped_news

    if not deduped_news:
        return NewsFilterOutput(filtered_news=[])

    # 读取配置文件
    cfg_file: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "..", "config", "news_filter_llm_cfg.json")
    with open(cfg_file, 'r', encoding='utf-8') as fd:
        _cfg: Dict[str, Any] = json.load(fd)

    llm_config: Dict[str, Any] = _cfg.get("config", {})
    sp: str = _cfg.get("sp", "")
    up: str = _cfg.get("up", "")

    # 渲染用户提示词
    news_json: str = json.dumps(deduped_news, ensure_ascii=False)
    up_tpl = Template(up)
    user_prompt: str = up_tpl.render({"news_list": news_json})

    temperature: float = float(llm_config.get("temperature", 0.3))
    max_tokens: int = int(llm_config.get("max_completion_tokens", 4096))

    # 调用大模型（使用通用LLM客户端）
    try:
        result = chat_completion_with_json(
            system_prompt=sp,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if isinstance(result, list):
            filtered_news: List[Dict[str, Any]] = result
        elif isinstance(result, dict) and "news" in result:
            filtered_news = result["news"]
        else:
            filtered_news = deduped_news[:10]
    except Exception as e:
        logger.warning(f"LLM调用或解析失败，使用原始数据: {e}")
        filtered_news = deduped_news[:10]

    logger.info(f"资讯筛选完成：{len(deduped_news)} → {len(filtered_news)} 条")
    return NewsFilterOutput(filtered_news=filtered_news)
