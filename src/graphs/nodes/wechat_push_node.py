"""企业微信推送节点 - 将早报/报告推送到企微群，支持审核群交互式卡片"""
import os
import json
import time
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
    """构建单条审核提醒卡片（推送到审核群，引导审核员到Web审核台处理。
    企微群机器人为单向推送通道，审核操作在系统审核台完成闭环）"""
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
    # 企微群机器人是单向推送，审核操作请前往Web审核台完成
    base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        lines.append(f"请前往 [审核台]({base_url}/index.html) 处理该条目（编号 #{item_id}）：")
    else:
        lines.append(f"请登录系统进入「人工审核」页面处理该条目（编号 #{item_id}）：")
    lines.append("")
    lines.append("- **通过** — 加入早报")
    lines.append("- **驳回** — 不进早报（可填写原因）")
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
    # 审核群Webhook同样支持环境变量兜底（否则存疑通知永远发不出去）
    if not review_webhook_url:
        review_webhook_url = os.getenv("REVIEW_WEBHOOK_URL", "")

    push_messages: list[dict[str, Any]] = []

    # 每日早报推送（只发早报主群；增量采集不发摘要，避免每小时打扰主群，
    # 增量场景只把存疑内容推到审核群）
    is_incremental: bool = state.trigger_source == "incremental"
    if state.daily_report_url and webhook_url and not is_incremental:
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

        # 失败重试3次（间隔2s/4s/6s），全部失败后记录告警
        max_attempts: int = 3
        pushed: bool = False
        last_error: str = ""
        for attempt in range(1, max_attempts + 1):
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
                        pushed = True
                        logger.info(f"企微消息推送成功 ({target}, 第{attempt}次尝试)")
                        break
                    last_error = f"errcode={resp_data.get('errcode')} {resp_data.get('errmsg')}"
                else:
                    last_error = f"HTTP {resp.status_code}"
            except Exception as e:
                last_error = str(e)
            if attempt < max_attempts:
                logger.warning(f"企微推送失败 ({target}, 第{attempt}次): {last_error}，{attempt * 2}s后重试")
                time.sleep(attempt * 2)

        if pushed:
            success_count += 1
        else:
            fail_count += 1
            logger.error(
                f"【告警】企微消息推送失败 ({target})：已重试{max_attempts}次仍失败，"
                f"最后错误: {last_error}，请检查Webhook配置和网络")
            try:
                from utils.alert import send_alert
                send_alert("push_failed", f"企微推送失败（{target}通道，重试{max_attempts}次）", last_error)
            except Exception:
                pass

    result_msg: str = f"推送完成：成功{success_count}条，失败{fail_count}条"
    return WechatPushOutput(wechat_push_result=result_msg)
