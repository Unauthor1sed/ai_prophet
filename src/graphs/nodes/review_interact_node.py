"""审核交互节点 - 处理审核群 @机器人 通过/拒绝指令，更新审核状态并写入待发池"""
import os
import json
import re
import time
import datetime
import logging
from typing import List, Dict, Any, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import ReviewInteractInput, ReviewInteractOutput
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database import get_db
from sqlalchemy import text
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _push_result_card(webhook_url: str, action: str, item: Dict[str, Any], comment: str = "") -> bool:
    """推送审核结果到审核群"""
    import requests

    if not webhook_url:
        return False

    title: str = str(item.get("title_cn", item.get("title", "无标题")))
    now_str: str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: List[str] = []
    if action == "approved":
        lines.append("# ✅ 审核通过")
        lines.append("")
        lines.append(f"**{title[:80]}** 已通过审核，将进入当日早报排序。")
    else:
        lines.append("# ❌ 审核拒绝")
        lines.append("")
        lines.append(f"**{title[:80]}** 已被拒绝。")
        if comment:
            lines.append(f"> 原因: {comment}")

    lines.append("")
    lines.append(f"_{now_str} · 人工审核小助手_")

    try:
        resp = requests.post(
            webhook_url,
            json={"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        if resp.status_code == 200:
            resp_data: Dict[str, Any] = resp.json()
            return resp_data.get("errcode") == 0
    except Exception as e:
        logger.error(f"审核结果推送失败: {e}")
    return False


def review_interact_node(state: ReviewInteractInput, config: RunnableConfig, runtime: Runtime[Context]) -> ReviewInteractOutput:
    """
    title: 审核群交互处理
    desc: 处理审核群中 @机器人 的通过/拒绝指令，更新 review_queue 状态，通过内容写入 news_pool 待发池
    integrations: Supabase数据库, 企业微信机器人
    """
    ctx = runtime.context
    msg: Optional[Dict[str, Any]] = state.wechat_message
    review_webhook_url: str = state.review_webhook_url

    if msg is None:
        return ReviewInteractOutput(review_completed=False, wechat_push_result="无审核消息")

    # 解析文本消息
    msg_type: str = str(msg.get("msgtype", ""))
    if msg_type != "text":
        return ReviewInteractOutput(review_completed=False, wechat_push_result="非文本消息，跳过审核交互")

    text_content: str = ""
    if isinstance(msg.get("text"), dict):
        text_content = str(msg["text"].get("content", ""))

    if not text_content:
        return ReviewInteractOutput(review_completed=False, wechat_push_result="消息内容为空")

    logger.info(f"审核交互消息: {text_content}")

    # 解析指令：@AI先知 通过 123 或 @AI先知 拒绝 123 原因
    approve_match: Optional[re.Match[str]] = re.search(r'(?:通过|approve|同意)\s*(\d+)', text_content)
    reject_match: Optional[re.Match[str]] = re.search(r'(?:拒绝|reject|驳回)\s*(\d+)', text_content)

    action: str = ""
    item_id: int = 0
    comment: str = ""

    if approve_match:
        action = "approved"
        item_id = int(approve_match.group(1))
    elif reject_match:
        action = "rejected"
        item_id = int(reject_match.group(1))
        # 提取拒绝原因
        reason_match: Optional[re.Match[str]] = re.search(r'(?:拒绝|reject|驳回)\s*\d+\s*(.*)', text_content)
        if reason_match and reason_match.group(1).strip():
            comment = reason_match.group(1).strip()
    else:
        return ReviewInteractOutput(
            review_completed=False,
            wechat_push_result="未识别审核指令，请使用「通过/拒绝 + 编号」格式"
        )

    if item_id <= 0:
        return ReviewInteractOutput(review_completed=False, wechat_push_result="无效的审核编号")

    # 查询 review_queue
    try:
        with get_db() as db:
            result = db.execute(text("SELECT * FROM review_queue WHERE id = :id"), {"id": item_id})
            row = result.fetchone()
            if not row:
                return ReviewInteractOutput(
                    review_completed=False,
                    wechat_push_result=f"未找到审核编号 {item_id}"
                )

            # 转为字典
            col_names = list(result.keys())
            item: Dict[str, Any] = dict(zip(col_names, row))
            current_status: str = str(item.get("review_status", ""))

            if current_status != "pending":
                return ReviewInteractOutput(
                    review_completed=False,
                    wechat_push_result=f"审核编号 {item_id} 已处理（状态: {current_status}），无需重复操作"
                )

            now_utc = datetime.datetime.now(datetime.timezone.utc)

            # 更新审核状态
            db.execute(text(
                "UPDATE review_queue SET review_status = :status, reviewed_at = :reviewed_at, review_comment = :comment WHERE id = :id"
            ), {"status": action, "reviewed_at": now_utc.isoformat(), "comment": comment, "id": item_id})
            logger.info(f"审核编号 {item_id} 已更新为 {action}")

            # 如果通过 → 写入 news_pool
            if action == "approved":
                db.execute(text(
                    """INSERT INTO news_pool (news_url, title, title_cn, snippet, snippet_cn, site_name, importance, relevance_score, collected_at, approved_at, is_pushed)
                    VALUES (:news_url, :title, :title_cn, :snippet, :snippet_cn, :site_name, :importance, :relevance_score, :collected_at, :approved_at, :is_pushed)"""
                ), {
                    "news_url": str(item.get("news_url", "")),
                    "title": str(item.get("title", "")),
                    "title_cn": str(item.get("title_cn", "")),
                    "snippet": str(item.get("snippet", "")),
                    "snippet_cn": str(item.get("snippet_cn", "")),
                    "site_name": str(item.get("site_name", "")),
                    "importance": str(item.get("importance", "medium")),
                    "relevance_score": 0.5,
                    "collected_at": str(item.get("collected_at", now_utc.isoformat())),
                    "approved_at": now_utc.isoformat(),
                    "is_pushed": False,
                })
                logger.info(f"审核通过 {item_id} 已写入待发池")

        # 推送审核结果到审核群
        if review_webhook_url:
            _push_result_card(review_webhook_url, action, item, comment)

        result_msg: str = f"审核完成：编号 {item_id} 已{'通过' if action == 'approved' else '拒绝'}"
        return ReviewInteractOutput(review_completed=True, wechat_push_result=result_msg)

    except Exception as e:
        logger.error(f"审核交互处理失败: {e}")
        return ReviewInteractOutput(review_completed=False, wechat_push_result=f"处理失败: {str(e)}")
