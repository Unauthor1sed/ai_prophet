"""复核处理节点 - 处理审核员的人工复核操作"""
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
from graphs.state import ReviewProcessInput, ReviewProcessOutput

logger = logging.getLogger(__name__)


def review_process_node(state: ReviewProcessInput, config: RunnableConfig, runtime: Runtime[Context]) -> ReviewProcessOutput:
    """
    title: 复核处理
    desc: 处理内容审核员的人工复核操作，更新审核状态
    """
    review_items: List[Dict[str, Any]] = state.review_items

    if not review_items:
        logger.info("无待复核条目")
        return ReviewProcessOutput(review_completed=True)

    processed_count: int = 0
    for item in review_items:
        title: str = item.get("title", "")
        action: str = item.get("action", "通过")
        logger.info(f"复核处理: [{action}] {title}")
        processed_count += 1

    logger.info(f"复核处理完成，共处理 {processed_count} 条")
    return ReviewProcessOutput(review_completed=True)
