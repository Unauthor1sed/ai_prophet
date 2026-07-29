"""敏感词检测节点 - 基于内置敏感词库检测资讯内容"""
import os
import json
import re
import time
import datetime
import logging
from typing import List, Dict, Any
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import SensitiveCheckInput, SensitiveCheckOutput

logger = logging.getLogger(__name__)

# 内置敏感词库
SENSITIVE_WORDS: List[str] = [
    "违禁", "非法", "赌博", "色情", "暴力恐怖",
    "颠覆国家", "分裂国家", "邪教", "毒品", "枪支",
    "诈骗", "传销", "洗钱", "盗版", "侵权",
]


def _check_sensitive(text: str) -> Dict[str, Any]:
    """检查文本是否包含敏感词"""
    if not text:
        return {"has_sensitive": False, "matched_words": [], "level": "通过"}

    matched: List[str] = []
    text_lower: str = text.lower()
    for word in SENSITIVE_WORDS:
        if word.lower() in text_lower:
            matched.append(word)

    if not matched:
        return {"has_sensitive": False, "matched_words": [], "level": "通过"}

    level: str = "存疑"
    high_risk: List[str] = ["违禁", "非法", "颠覆国家", "分裂国家", "邪教", "毒品", "枪支", "暴力恐怖"]
    for w in matched:
        if w in high_risk:
            level = "有害"
            break

    return {"has_sensitive": True, "matched_words": matched, "level": level}


def sensitive_check_node(state: SensitiveCheckInput, config: RunnableConfig, runtime: Runtime[Context]) -> SensitiveCheckOutput:
    """
    title: 敏感词检测
    desc: 基于内置敏感词库对筛选后的资讯进行敏感词筛查，标记通过/存疑/有害
    """
    translated_news: List[Dict[str, Any]] = state.translated_news
    audit_results: List[Dict[str, Any]] = []

    for item in translated_news:
        title: str = item.get("title", "")
        snippet: str = item.get("snippet", "")
        combined_text: str = f"{title} {snippet}"

        result: Dict[str, Any] = _check_sensitive(combined_text)
        audit_item: Dict[str, Any] = {
            "title": title,
            "url": item.get("url", ""),
            "snippet": snippet,
            "audit_level": result["level"],
            "matched_words": result["matched_words"],
            "has_sensitive": result["has_sensitive"],
        }
        audit_results.append(audit_item)

    logger.info(f"敏感词检测完成：共 {len(audit_results)} 条")
    return SensitiveCheckOutput(audit_results=audit_results)
