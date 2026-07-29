"""企业微信消息接收节点 - 解析企微消息触发对应工作流，支持审核交互指令"""
import os
import json
import re
import logging
from typing import Optional, Any
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from utils.file.file import File
from graphs.state import WechatReceiveInput, WechatReceiveOutput

logger = logging.getLogger(__name__)


def wechat_receive_node(state: WechatReceiveInput, config: RunnableConfig, runtime: Runtime[Context]) -> WechatReceiveOutput:
    """
    title: 企微消息接收
    desc: 接收企业微信机器人消息，智能解析用户意图：早报触发/论文精析/审核交互/运维监控
    integrations: 企业微信机器人
    """
    ctx = runtime.context
    msg: Optional[dict[str, Any]] = state.wechat_message

    if msg is None:
        logger.info("无企微消息，使用传入参数或默认模式")
        # 尊重上游传入的workflow_mode（manual/test_run触发时）
        preset_mode: str = state.workflow_mode if state.workflow_mode else "daily_news"
        return WechatReceiveOutput(
            workflow_mode=preset_mode,
            paper_file=state.paper_file,
            search_keywords=state.search_keywords if state.search_keywords else [],
            trigger_source="manual" if state.workflow_mode else "manual",
            skip_wechat_push=state.skip_wechat_push,
        )

    msg_type: str = str(msg.get("msgtype", ""))
    logger.info(f"收到企微消息，类型: {msg_type}")

    # 文本消息：解析用户意图
    if msg_type == "text":
        return _handle_text_message(msg)

    # 文件消息：处理上传的文件
    if msg_type == "file":
        return _handle_file_message(msg)

    # 图片消息
    if msg_type == "image":
        return _handle_image_message(msg)

    logger.info(f"未识别的消息类型 {msg_type}，使用默认模式")
    return WechatReceiveOutput(
        workflow_mode="daily_news",
        paper_file=None,
        search_keywords=[],
        trigger_source="wechat"
    )


def _handle_text_message(msg: dict[str, Any]) -> WechatReceiveOutput:
    """处理文本消息，解析用户意图"""
    text_content: str = ""
    if isinstance(msg.get("text"), dict):
        text_content = str(msg["text"].get("content", ""))

    if not text_content:
        return WechatReceiveOutput(
            workflow_mode="daily_news",
            paper_file=None,
            search_keywords=[],
            trigger_source="wechat"
        )

    logger.info(f"解析文本消息: {text_content}")

    # 优先检测审核交互指令
    review_keywords: list[str] = ["通过", "拒绝", "approve", "reject", "驳回", "同意"]
    if any(kw in text_content for kw in review_keywords):
        # 尝试提取审核编号
        review_match: Optional[re.Match[str]] = re.search(r'(?:通过|拒绝|approve|reject|驳回|同意)\s*(\d+)', text_content)
        if review_match:
            item_id: int = int(review_match.group(1))
            action: str = "approve" if any(kw in text_content for kw in ["通过", "approve", "同意"]) else "reject"
            comment: str = ""
            reason_match: Optional[re.Match[str]] = re.search(r'(?:拒绝|reject|驳回)\s*\d+\s*(.*)', text_content)
            if reason_match and reason_match.group(1).strip():
                comment = reason_match.group(1).strip()

            logger.info(f"检测到审核交互指令: {action} {item_id}")
            return WechatReceiveOutput(
                workflow_mode="review_interact",
                paper_file=None,
                search_keywords=[],
                trigger_source="wechat",
                review_action=action,
                review_item_id=item_id,
                review_comment=comment
            )

    # 论文精析意图
    paper_keywords: list[str] = ["论文", "paper", "精析", "分析论文", "解析", "SCI"]
    if any(kw in text_content.lower() for kw in paper_keywords):
        url_match: Optional[re.Match[str]] = re.search(r'(https?://\S+\.pdf)', text_content)
        if url_match:
            pdf_url: str = url_match.group(1)
            logger.info(f"检测到论文PDF链接: {pdf_url}")
            return WechatReceiveOutput(
                workflow_mode="paper_analysis",
                paper_file=File(url=pdf_url, file_type="document"),
                search_keywords=[],
                trigger_source="wechat"
            )
        else:
            logger.info("论文意图但未提供PDF链接")
            return WechatReceiveOutput(
                workflow_mode="paper_analysis",
                paper_file=None,
                search_keywords=[],
                trigger_source="wechat"
            )

    # 运维监控意图
    monitor_keywords: list[str] = ["运维", "监控", "统计", "状态", "健康"]
    if any(kw in text_content for kw in monitor_keywords):
        return WechatReceiveOutput(
            workflow_mode="ops_monitor",
            paper_file=None,
            search_keywords=[],
            trigger_source="wechat"
        )

    # 早报意图（含触发词）
    news_keywords: list[str] = ["早报", "资讯", "日报", "新闻", "AI动态", "前沿", "立即推送", "测试推送", "测试"]
    if any(kw in text_content for kw in news_keywords):
        keywords: list[str] = _extract_keywords(text_content)
        return WechatReceiveOutput(
            workflow_mode="daily_news",
            paper_file=None,
            search_keywords=keywords,
            trigger_source="wechat"
        )

    # 默认识别为早报请求
    keywords = _extract_keywords(text_content)
    if not keywords:
        keywords = ["AI前沿资讯"]
    return WechatReceiveOutput(
        workflow_mode="daily_news",
        paper_file=None,
        search_keywords=keywords,
        trigger_source="wechat"
    )


def _handle_file_message(msg: dict[str, Any]) -> WechatReceiveOutput:
    """处理文件消息"""
    file_url: str = ""
    file_name: str = ""

    if isinstance(msg.get("file"), dict):
        file_url = str(msg["file"].get("url", ""))
        file_name = str(msg["file"].get("file_name", ""))

    logger.info(f"收到文件: {file_name}, URL: {file_url}")

    if not file_url:
        return WechatReceiveOutput(
            workflow_mode="daily_news",
            paper_file=None,
            search_keywords=[],
            trigger_source="wechat"
        )

    file_name_lower: str = file_name.lower()
    if file_name_lower.endswith(".pdf"):
        logger.info("检测到PDF文件，触发论文精析")
        return WechatReceiveOutput(
            workflow_mode="paper_analysis",
            paper_file=File(url=file_url, file_type="document"),
            search_keywords=[],
            trigger_source="wechat"
        )
    else:
        logger.info(f"非PDF文件类型: {file_name}，默认触发早报")
        return WechatReceiveOutput(
            workflow_mode="daily_news",
            paper_file=None,
            search_keywords=[],
            trigger_source="wechat"
        )


def _handle_image_message(msg: dict[str, Any]) -> WechatReceiveOutput:
    """处理图片消息"""
    image_url: str = ""
    if isinstance(msg.get("image"), dict):
        image_url = str(msg["image"].get("url", ""))

    if image_url:
        logger.info("收到图片消息，暂不处理")

    return WechatReceiveOutput(
        workflow_mode="daily_news",
        paper_file=None,
        search_keywords=[],
        trigger_source="wechat"
    )


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取搜索关键词"""
    # 移除常见触发词
    trigger_words: list[str] = ["早报", "资讯", "日报", "新闻", "AI动态", "前沿", "立即推送", "测试推送", "测试", "论文", "paper", "精析", "运维", "监控", "通过", "拒绝", "approve", "reject"]
    cleaned: str = text
    for word in trigger_words:
        cleaned = cleaned.replace(word, " ")

    # 提取剩余关键词
    words: list[str] = [w.strip() for w in cleaned.split() if len(w.strip()) > 1]
    return words[:5] if words else ["AI前沿资讯"]
