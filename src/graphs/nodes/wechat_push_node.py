"""企业微信推送节点 - 将早报/报告推送到企微群，支持审核群交互式卡片"""
import os
import json
import logging
import datetime
import requests
from typing import Any, List, Dict
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import WechatPushInput, WechatPushOutput

logger = logging.getLogger(__name__)


def _get_current_time() -> str:
    """获取当前时间字符串"""
    return datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")


def _build_morning_report_card(daily_report_url: str, filtered_news: List[Dict[str, Any]]) -> str:
    """构建早报推送卡片（Markdown格式）"""
    now_dt = datetime.datetime.now()
    now_str: str = now_dt.strftime("%Y年%m月%d日")
    weekday: str = ["一", "二", "三", "四", "五", "六", "日"][now_dt.weekday()]

    lines: List[str] = []
    lines.append(f"# 🤖 AI先知 · 每日技术早报")
    lines.append(f"**{now_str}** 星期{weekday}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 资讯速览（前5条）
    lines.append("## 📋 今日速览")
    for i, news in enumerate(filtered_news[:5], 1):
        title_cn: str = str(news.get("title_cn", news.get("title", "无标题")))
        importance: str = str(news.get("importance", "medium"))
        icon: str = "🔥" if importance == "high" else ("📌" if importance == "medium" else "💡")
        lines.append(f"{i}. {icon} {title_cn[:60]}")
    lines.append("")

    if len(filtered_news) > 5:
        lines.append(f"> 共 **{len(filtered_news)}** 条资讯，更多详情请下载完整早报")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"📥 [**点击下载完整早报 (Word)**]({daily_report_url})")
    lines.append("")
    lines.append(f"_{_get_current_time()} · 由AI先知智能体自动生成_")

    return "\n".join(lines)


def _build_paper_report_card(paper_report_url: str, paper_analysis: str) -> str:
    """构建论文报告推送卡片"""
    lines: List[str] = []
    lines.append(f"# 📄 AI先知 · 论文精析报告")
    lines.append("")

    if paper_analysis:
        preview: str = paper_analysis[:200]
        if len(paper_analysis) > 200:
            preview += "..."
        lines.append(f"> {preview}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"📥 [**点击下载完整报告 (Word)**]({paper_report_url})")
    lines.append("")
    lines.append(f"_{_get_current_time()} · 由AI先知智能体自动生成_")

    return "\n".join(lines)


def _build_review_alert_card(item: Dict[str, Any]) -> str:
    """构建单条审核提醒卡片（推送到审核群，引导审核员使用Bot命令操作）"""
    title: str = str(item.get("title_cn", item.get("title", "无标题")))
    reason: str = str(item.get("audit_reason", item.get("fact_reason", "内容存疑")))
    item_id: int = int(item.get("id", 0))
    snippet: str = str(item.get("snippet_cn", item.get("snippet", "")))
    site_name: str = str(item.get("site_name", "未知来源"))
    source: str = str(item.get("source", site_name))
    importance: str = str(item.get("importance", "medium"))
    icon: str = "🔥" if importance == "high" else ("📌" if importance == "medium" else "💡")

    lines: List[str] = []
    lines.append(f"# ⚠️ 人工审核小助手 · 内容审核通知")
    lines.append("")
    lines.append(f"{icon} **{title}**")
    lines.append("")
    if snippet:
        lines.append(f"> {snippet[:200]}")
        lines.append("")
    lines.append(f"**来源**: {source}")
    lines.append(f"**存疑原因**: {reason}")
    lines.append(f"**编号**: #{item_id}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🤖 使用 Bot 命令操作")
    lines.append("")
    lines.append("在 Coze 平台 Bot 对话中输入以下命令：")
    lines.append("")
    lines.append(f"- `通过 #{item_id}` — 通过审核，加入早报")
    lines.append(f"- `拒绝 #{item_id} [原因]` — 拒绝此条")
    lines.append(f"- `查看审核` — 查看所有待审列表")
    lines.append("")
    lines.append("---")
    lines.append(f"_{_get_current_time()} · 由人工审核小助手自动生成_")

    return "\n".join(lines)


def wechat_push_node(state: WechatPushInput, config: RunnableConfig, runtime: Runtime[Context]) -> WechatPushOutput:
    """
    title: 企微消息推送
    desc: 将每日早报推送到早报群，存疑内容推送到审核群（交互式卡片），论文报告推送到指定群
    integrations: 企业微信机器人
    """
    ctx = runtime.context
    webhook_url: str = state.wechat_webhook_url
    review_webhook_url: str = state.review_webhook_url

    # 如果标记跳过企微推送（前端论文精析场景），直接返回
    if state.skip_wechat_push:
        logger.info("skip_wechat_push=True，跳过企微推送")
        return WechatPushOutput(wechat_push_result="已跳过企微推送（前端模式）")

    if not webhook_url:
        webhook_url = os.getenv("WECHAT_WEBHOOK_URL", "")

    push_messages: list[dict[str, Any]] = []

    # 每日早报推送（推送到早报群）
    if state.daily_report_url and webhook_url:
        filtered_news: List[Dict[str, Any]] = state.filtered_news
        msg_content: str = _build_morning_report_card(state.daily_report_url, filtered_news)
        push_messages.append({
            "target": "main",
            "webhook_url": webhook_url,
            "payload": {"msgtype": "markdown", "markdown": {"content": msg_content}}
        })

    # 论文分析报告推送
    if state.paper_report_url and webhook_url:
        paper_analysis: str = state.paper_analysis
        msg_content = _build_paper_report_card(state.paper_report_url, paper_analysis)
        push_messages.append({
            "target": "main",
            "webhook_url": webhook_url,
            "payload": {"msgtype": "markdown", "markdown": {"content": msg_content}}
        })

    # 审核存疑通知 → 推送到审核群（逐条推送）
    review_items: List[Dict[str, Any]] = state.review_items
    if not review_items:
        review_items = [
            item for item in state.audit_results
            if isinstance(item, dict) and (item.get("audit_level") == "存疑" or item.get("fact_check") == "存疑")
        ]

    if review_items and review_webhook_url:
        for item in review_items:
            item_id: int = int(item.get("id", 0))
            msg_content = _build_review_alert_card(item)
            push_messages.append({
                "target": "review",
                "webhook_url": review_webhook_url,
                "payload": {"msgtype": "markdown", "markdown": {"content": msg_content}},
                "item_id": item_id,
            })

    if not push_messages:
        return WechatPushOutput(wechat_push_result="无推送内容")

    # 发送消息
    success_count: int = 0
    fail_count: int = 0
    for msg in push_messages:
        target_url: str = str(msg.get("webhook_url", ""))
        payload: Dict[str, Any] = msg.get("payload", {})
        target: str = str(msg.get("target", "main"))

        if not target_url:
            fail_count += 1
            logger.warning(f"推送目标 {target} 缺少Webhook地址")
            continue

        try:
            resp = requests.post(
                target_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if resp.status_code == 200:
                resp_data: Dict[str, Any] = resp.json()
                if resp_data.get("errcode") == 0:
                    success_count += 1
                    logger.info(f"企微消息推送成功 ({target})")
                else:
                    fail_count += 1
                    logger.error(f"企微消息推送失败 ({target}): {resp_data.get('errmsg')}")
            else:
                fail_count += 1
                logger.error(f"企微消息推送HTTP错误 ({target}): {resp.status_code}")
        except Exception as e:
            fail_count += 1
            logger.error(f"企微消息推送异常 ({target}): {e}")

    result_msg: str = f"推送完成：成功{success_count}条，失败{fail_count}条"
    return WechatPushOutput(wechat_push_result=result_msg)
