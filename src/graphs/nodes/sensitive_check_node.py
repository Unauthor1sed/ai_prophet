"""敏感词检测节点 - 从数据库读取词库进行匹配，支持位置定位"""
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

# 高风险敏感词分类（命中即标"有害"，而不是"存疑"）
HIGH_RISK_WORDS: set = {
    "违禁", "非法", "颠覆国家", "分裂国家", "邪教", "毒品", "枪支", "暴力恐怖",
}


def _load_active_words() -> List[Dict[str, Any]]:
    """从数据库加载所有启用的敏感词（带分类）"""
    try:
        from database import get_sensitive_words
        all_words: List[Dict[str, Any]] = get_sensitive_words()
        return [w for w in all_words if int(w.get("is_active", 1)) == 1]
    except Exception as e:
        logger.error(f"加载敏感词库失败: {e}")
        return []


def _check_sensitive(text: str, words: List[Dict[str, Any]]) -> Dict[str, Any]:
    """检查文本中是否包含敏感词（返回命中词 + 字符位置）

    返回:
      {
        "has_sensitive": bool,
        "matched_words": [str, ...],   # 命中的词（去重）
        "matches": [{                   # 每个命中位置的详情
          "word": str,
          "start": int,                # 起始字符下标
          "end": int,                  # 结束字符下标（开区间）
          "category": str
        }, ...],
        "level": "通过" | "存疑" | "有害"
      }
    """
    if not text or not words:
        return {"has_sensitive": False, "matched_words": [], "matches": [], "level": "通过"}

    matched_set: set = set()
    matches: List[Dict[str, Any]] = []
    text_lower: str = text.lower()

    for w in words:
        word: str = str(w.get("word", "")).strip()
        if not word:
            continue
        word_lower: str = word.lower()
        start: int = 0
        while True:
            idx: int = text_lower.find(word_lower, start)
            if idx < 0:
                break
            matched_set.add(word)
            matches.append({
                "word": word,
                "start": idx,
                "end": idx + len(word),
                "category": str(w.get("category", "general")),
            })
            start = idx + len(word)  # 允许重叠命中

    if not matched_set:
        return {"has_sensitive": False, "matched_words": [], "matches": [], "level": "通过"}

    level: str = "存疑"
    for hit_word in matched_set:
        if hit_word in HIGH_RISK_WORDS:
            level = "有害"
            break

    return {
        "has_sensitive": True,
        "matched_words": sorted(matched_set),
        "matches": matches,
        "level": level,
    }


def sensitive_check_node(state: SensitiveCheckInput, config: RunnableConfig, runtime: Runtime[Context]) -> SensitiveCheckOutput:
    """
    title: 敏感词检测
    desc: 从数据库加载敏感词库，对筛选后的资讯进行敏感词筛查，标记通过/存疑/有害（含命中位置）
    """
    translated_news: List[Dict[str, Any]] = state.translated_news
    words: List[Dict[str, Any]] = _load_active_words()
    logger.info(f"敏感词检测：当前词库 {len(words)} 个词")

    audit_results: List[Dict[str, Any]] = []

    for item in translated_news:
        title: str = item.get("title", "")
        snippet: str = item.get("snippet", "")
        combined_text: str = f"{title} {snippet}"

        result: Dict[str, Any] = _check_sensitive(combined_text, words)
        audit_item: Dict[str, Any] = {
            "title": title,
            "url": item.get("url", ""),
            "snippet": snippet,
            "audit_level": result["level"],
            "matched_words": result["matched_words"],
            "matches": result["matches"],
            "has_sensitive": result["has_sensitive"],
        }
        audit_results.append(audit_item)

    flagged: int = sum(1 for r in audit_results if r["has_sensitive"])
    logger.info(f"敏感词检测完成：共 {len(audit_results)} 条，命中 {flagged} 条")
    return SensitiveCheckOutput(audit_results=audit_results)
