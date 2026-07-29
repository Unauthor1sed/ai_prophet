"""复核通知节点 - 将存疑内容通知审核员"""
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
from graphs.state import ReviewNotifyInput, ReviewNotifyOutput

logger = logging.getLogger(__name__)


def review_notify_node(state: ReviewNotifyInput, config: RunnableConfig, runtime: Runtime[Context]) -> ReviewNotifyOutput:
    """
    title: 复核通知
    desc: 将存疑内容整理为通知消息，发送给内容审核员进行人工复核
    """
    audit_results: List[Dict[str, Any]] = state.audit_results

    if not audit_results:
        logger.info("无存疑内容，跳过复核通知")
        return ReviewNotifyOutput(review_completed=True)

    # 筛选存疑条目
    flagged_items: List[Dict[str, Any]] = [
        item for item in audit_results
        if item.get("audit_level") in ("存疑", "有害")
    ]

    if not flagged_items:
        logger.info("无存疑条目需要复核")
        return ReviewNotifyOutput(review_completed=True)

    # 构造通知消息
    notify_lines: List[str] = [
        "## AI先知 · 内容复核通知",
        "",
        f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**待复核条目数**: {len(flagged_items)}",
        "",
        "### 待复核内容",
        "",
    ]

    for i, item in enumerate(flagged_items, 1):
        title: str = item.get("title", "无标题")
        level: str = item.get("audit_level", "存疑")
        matched: List[str] = item.get("matched_words", [])
        notify_lines.append(f"**{i}. {title}**")
        notify_lines.append(f"   - 审核级别: {level}")
        notify_lines.append(f"   - 匹配敏感词: {', '.join(matched) if matched else '无'}")
        notify_lines.append("")

    notify_message: str = "\n".join(notify_lines)
    logger.info(f"复核通知已生成:\n{notify_message}")

    return ReviewNotifyOutput(review_completed=True)
