"""资讯去重节点 - 基于URL和标题相似度去重，支持跨天历史去重"""
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
from graphs.state import NewsDedupInput, NewsDedupOutput
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database import get_db
import logging
from typing import List, Dict, Any, Tuple
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _title_similarity(title1: str, title2: str) -> float:
    """计算两个标题的简单相似度"""
    if not title1 or not title2:
        return 0.0
    words1: set = set(title1.lower().split())
    words2: set = set(title2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection: set = words1 & words2
    union: set = words1 | words2
    return len(intersection) / len(union)


def _get_historical_urls_and_titles() -> Tuple[set, List[str]]:
    """从 news_pool 获取最近7天的历史URL和标题，用于跨天去重"""
    historical_urls: set = set()
    historical_titles: List[str] = []
    try:
        seven_days_ago: str = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        with get_db() as db:
            result = db.execute(text(
                "SELECT news_url, title FROM news_pool WHERE collected_at >= :days_ago"
            ), {"days_ago": seven_days_ago})
            for row in result.fetchall():
                url: str = str(row[0] or "")
                title: str = str(row[1] or "")
                if url:
                    historical_urls.add(url)
                if title:
                    historical_titles.append(title)
    except Exception as e:
        logger.warning(f"获取历史资讯失败: {e}")
    return historical_urls, historical_titles


def news_dedup_node(state: NewsDedupInput, config: RunnableConfig, runtime: Runtime[Context]) -> NewsDedupOutput:
    """
    title: 资讯去重
    desc: 基于URL精确匹配和标题相似度对采集的资讯进行去重，同时与历史7天内的资讯做跨天去重
    """
    raw_news: List[Dict[str, Any]] = state.raw_news
    if not raw_news:
        return NewsDedupOutput(deduped_news=[])

    # 获取历史数据用于跨天去重
    historical_urls, historical_titles = _get_historical_urls_and_titles()

    deduped: List[Dict[str, Any]] = []
    seen_urls: set = set(historical_urls)  # 初始化时包含历史URL

    for item in raw_news:
        url: str = item.get("url", "")
        if not url:
            continue
        if url in seen_urls:
            logger.info(f"URL重复（含历史），跳过: {url[:80]}")
            continue

        title: str = item.get("title", "")
        is_dup: bool = False

        # 与本次已去重的标题比较
        for existing in deduped:
            existing_title: str = existing.get("title", "")
            sim: float = _title_similarity(title, existing_title)
            if sim > 0.8:
                is_dup = True
                break

        # 与历史标题比较
        if not is_dup:
            for hist_title in historical_titles:
                sim = _title_similarity(title, hist_title)
                if sim > 0.8:
                    is_dup = True
                    logger.info(f"标题相似（与历史），跳过: {title[:60]}")
                    break

        if not is_dup:
            seen_urls.add(url)
            deduped.append(item)

    logger.info(f"去重完成：{len(raw_news)} → {len(deduped)} 条（含跨天去重）")
    return NewsDedupOutput(deduped_news=deduped)
