"""资讯翻译节点 - 将英文AI资讯翻译为专业中文"""
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
from graphs.state import NewsTranslateInput, NewsTranslateOutput

logger = logging.getLogger(__name__)


def news_translate_node(state: NewsTranslateInput, config: RunnableConfig, runtime: Runtime[Context]) -> NewsTranslateOutput:
    """
    title: 专业翻译
    desc: 将英文AI资讯翻译为专业中文，技术术语首次出现时附英文原词，同时将翻译结果回填到filtered_news中
    integrations: 大语言模型
    """
    filtered_news: List[Dict[str, Any]] = state.filtered_news

    if not filtered_news:
        return NewsTranslateOutput(translated_news=[], filtered_news=[])

    # 读取配置文件
    cfg_file: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "..", "config", "news_translate_llm_cfg.json")
    with open(cfg_file, 'r', encoding='utf-8') as fd:
        _cfg: Dict[str, Any] = json.load(fd)

    llm_config: Dict[str, Any] = _cfg.get("config", {})
    sp: str = _cfg.get("sp", "")
    up: str = _cfg.get("up", "")

    # 渲染用户提示词
    news_json: str = json.dumps(filtered_news, ensure_ascii=False)
    up_tpl = Template(up)
    user_prompt: str = up_tpl.render({"filtered_news": news_json})

    temperature: float = float(llm_config.get("temperature", 0.2))
    max_tokens: int = int(llm_config.get("max_completion_tokens", 8192))

    # 调用大模型
    translated_news: List[Dict[str, Any]] = []
    try:
        result = chat_completion_with_json(
            system_prompt=sp,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if isinstance(result, list):
            translated_news = result
        elif isinstance(result, dict) and "items" in result:
            translated_news = result["items"]
    except Exception as e:
        logger.warning(f"翻译LLM调用失败，使用原文: {e}")

    # 如果LLM返回为空，回填原文
    if not translated_news:
        for item in filtered_news:
            translated_news.append({
                "title": item.get("title", ""),
                "title_en": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "snippet_en": item.get("snippet", ""),
                "url": item.get("url", ""),
                "site_name": item.get("site_name", ""),
                "importance": item.get("importance", "medium"),
            })

    # 将翻译结果回填到filtered_news中
    enriched_news: List[Dict[str, Any]] = []
    for i, item in enumerate(filtered_news):
        enriched_item: Dict[str, Any] = dict(item)
        if i < len(translated_news):
            t_item: Dict[str, Any] = translated_news[i]
            trans_title: str = t_item.get("title", "")
            orig_title: str = item.get("title", "")
            enriched_item["title_cn"] = trans_title if trans_title else orig_title

            trans_snippet: str = t_item.get("snippet", "")
            orig_snippet: str = item.get("snippet", "")
            enriched_item["snippet_cn"] = trans_snippet if trans_snippet else orig_snippet
        else:
            enriched_item["title_cn"] = item.get("title", "")
            enriched_item["snippet_cn"] = item.get("snippet", "")
        enriched_news.append(enriched_item)

    logger.info(f"翻译完成，共 {len(translated_news)} 条资讯")
    return NewsTranslateOutput(translated_news=translated_news, filtered_news=enriched_news)
