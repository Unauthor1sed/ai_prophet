"""AI先知情报智能体 - 状态定义"""
import os
import json
import re
import time
import datetime
import math
import logging
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from utils.file.file import File


# ============================================================
# 全局状态
# ============================================================
class GlobalState(BaseModel):
    """全局状态定义，贯穿整个工作流"""
    workflow_mode: str = Field(default="", description="工作流模式：daily_news/paper_analysis/manual_review/ops_monitor/review_interact/hourly_collect")
    run_id: str = Field(default="", description="运行ID")

    # 每日早报相关
    search_keywords: List[str] = Field(default=[], description="搜索关键词列表")
    news_sources_config: Optional[dict] = Field(default=None, description="自定义资讯源配置")
    raw_news: List[dict] = Field(default=[], description="原始采集资讯列表")
    deduped_news: List[dict] = Field(default=[], description="去重后资讯列表")
    filtered_news: List[dict] = Field(default=[], description="筛选排序后资讯列表")
    translated_news: List[dict] = Field(default=[], description="翻译后的资讯列表（中文标题+摘要）")
    audit_results: List[dict] = Field(default=[], description="审核结果列表")
    audit_status: str = Field(default="", description="审核分类结果：通过/存疑/有害")
    daily_report_url: str = Field(default="", description="每日早报Word文档下载URL")

    # 待发池（从DB读取）
    news_pool: List[dict] = Field(default=[], description="待发池：已通过审核的资讯列表")

    # 论文精析相关
    paper_file: Optional[File] = Field(default=None, description="上传的论文PDF文件")
    paper_text: str = Field(default="", description="论文解析后的文本内容")
    paper_analysis: str = Field(default="", description="论文分析结果")
    paper_report_url: str = Field(default="", description="论文分析报告下载URL")

    # 人工复核相关
    review_items: List[dict] = Field(default=[], description="待人工复核的条目列表")
    review_completed: bool = Field(default=False, description="人工复核是否完成")
    review_action: str = Field(default="", description="审核交互动作：approve/reject")
    review_item_id: int = Field(default=0, description="审核交互的条目ID")
    review_comment: str = Field(default="", description="审核备注/拒绝原因")

    # 运维监控相关
    monitor_report: str = Field(default="", description="运维监控报告")

    # 企业微信相关
    wechat_webhook_url: str = Field(default="", description="企业微信机器人Webhook地址（早报推送群）")
    review_webhook_url: str = Field(default="", description="审核群企业微信机器人Webhook地址")
    wechat_push_result: str = Field(default="", description="企微推送结果")
    wechat_message: Optional[dict] = Field(default=None, description="企微接收到的消息")
    skip_wechat_push: bool = Field(default=False, description="是否跳过企微推送（前端论文精析时为True）")

    # 触发来源
    trigger_source: str = Field(default="manual", description="触发来源：scheduled/manual/wechat")


# ============================================================
# 图输入/输出
# ============================================================
class GraphInput(BaseModel):
    """工作流入口输入"""
    workflow_mode: str = Field(default="daily_news", description="工作流模式：daily_news/paper_analysis/manual_review/ops_monitor/review_interact/hourly_collect")
    search_keywords: List[str] = Field(default=[], description="搜索关键词（daily_news/hourly_collect模式）")
    news_sources_config: Optional[dict] = Field(default=None, description="自定义资讯源配置")
    paper_file: Optional[File] = Field(default=None, description="论文文件（paper_analysis模式）")
    review_items: List[dict] = Field(default=[], description="待复核条目（manual_review模式）")
    wechat_webhook_url: str = Field(default="", description="企业微信机器人Webhook地址")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")
    wechat_message: Optional[dict] = Field(default=None, description="企业微信接收到的消息")
    trigger_source: str = Field(default="manual", description="触发来源：scheduled/manual/wechat/paper_task")
    skip_wechat_push: bool = Field(default=False, description="是否跳过企微推送")


class GraphOutput(BaseModel):
    """工作流出口输出"""
    daily_report_url: str = Field(default="", description="每日早报下载URL")
    paper_report_url: str = Field(default="", description="论文分析报告下载URL")
    review_completed: bool = Field(default=False, description="人工复核是否完成")
    monitor_report: str = Field(default="", description="运维监控报告")
    wechat_push_result: str = Field(default="", description="企微推送结果")
    # 供执行日志（task_runs）统计采集/入选条数
    raw_news: List[dict] = Field(default=[], description="原始采集资讯列表")
    filtered_news: List[dict] = Field(default=[], description="筛选后资讯列表")


# ============================================================
# 工作流路由节点
# ============================================================
class WorkflowRouteInput(BaseModel):
    """工作流路由输入"""
    workflow_mode: str = Field(default="", description="工作流模式")


# ============================================================
# 每日早报工作流节点
# ============================================================
class NewsCollectInput(BaseModel):
    """资讯采集节点输入"""
    search_keywords: List[str] = Field(default=[], description="搜索关键词列表")
    news_sources_config: Optional[dict] = Field(default=None, description="自定义资讯源配置")


class NewsCollectOutput(BaseModel):
    """资讯采集节点输出"""
    raw_news: List[dict] = Field(default=[], description="原始采集资讯列表")


class NewsDedupInput(BaseModel):
    """资讯去重节点输入"""
    raw_news: List[dict] = Field(default=[], description="原始资讯列表")


class NewsDedupOutput(BaseModel):
    """资讯去重节点输出"""
    deduped_news: List[dict] = Field(default=[], description="去重后资讯列表")


class NewsFilterInput(BaseModel):
    """资讯筛选节点输入"""
    deduped_news: List[dict] = Field(default=[], description="去重后资讯列表")


class NewsFilterOutput(BaseModel):
    """资讯筛选节点输出"""
    filtered_news: List[dict] = Field(default=[], description="筛选排序后资讯列表")


class NewsTranslateInput(BaseModel):
    """资讯翻译节点输入"""
    filtered_news: List[dict] = Field(default=[], description="筛选后英文资讯列表")


class NewsTranslateOutput(BaseModel):
    """资讯翻译节点输出"""
    translated_news: List[dict] = Field(default=[], description="翻译后中文资讯列表")
    filtered_news: List[dict] = Field(default=[], description="回填翻译后的筛选资讯列表（含title_cn/snippet_cn）")


class SensitiveCheckInput(BaseModel):
    """敏感词检测节点输入"""
    translated_news: List[dict] = Field(default=[], description="翻译后资讯列表")


class SensitiveCheckOutput(BaseModel):
    """敏感词检测节点输出"""
    audit_results: List[dict] = Field(default=[], description="审核结果列表")


class FactCheckInput(BaseModel):
    """事实校验节点输入"""
    audit_results: List[dict] = Field(default=[], description="审核结果列表")
    filtered_news: List[dict] = Field(default=[], description="筛选后资讯列表（含翻译）")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")


class FactCheckOutput(BaseModel):
    """事实校验节点输出"""
    audit_results: List[dict] = Field(default=[], description="审核结果列表")
    audit_status: str = Field(default="", description="审核分类：通过/存疑/有害")
    review_items: List[dict] = Field(default=[], description="推送到审核群的存疑条目")


class ClassifyRouteInput(BaseModel):
    """审核分类路由输入"""
    audit_status: str = Field(default="", description="审核分类：通过/存疑/有害")
    workflow_mode: str = Field(default="daily_news", description="工作流模式")


class DailyReportGenInput(BaseModel):
    """早报生成节点输入"""
    news_pool: List[dict] = Field(default=[], description="待发池：已通过审核的资讯列表")


class DailyReportGenOutput(BaseModel):
    """早报生成节点输出"""
    daily_report_url: str = Field(default="", description="每日早报下载URL")


# ============================================================
# 论文精析工作流节点
# ============================================================
class PaperParseInput(BaseModel):
    """论文解析节点输入"""
    paper_file: Optional[File] = Field(default=None, description="论文PDF文件")


class PaperParseOutput(BaseModel):
    """论文解析节点输出"""
    paper_text: str = Field(default="", description="论文解析文本")


class PaperAnalysisInput(BaseModel):
    """论文分析节点输入"""
    paper_text: str = Field(default="", description="论文解析文本")


class PaperAnalysisOutput(BaseModel):
    """论文分析节点输出"""
    paper_analysis: str = Field(default="", description="论文分析结果")


class PaperReportGenInput(BaseModel):
    """论文报告生成节点输入"""
    paper_analysis: str = Field(default="", description="论文分析结果")


class PaperReportGenOutput(BaseModel):
    """论文报告生成节点输出"""
    paper_report_url: str = Field(default="", description="论文分析报告下载URL")


# ============================================================
# 人工复核工作流节点
# ============================================================
class ReviewNotifyInput(BaseModel):
    """复核通知节点输入"""
    review_items: List[dict] = Field(default=[], description="存疑条目列表")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")
    audit_results: List[dict] = Field(default=[], description="审核结果列表")


class ReviewNotifyOutput(BaseModel):
    """复核通知节点输出"""
    review_completed: bool = Field(default=False, description="通知是否发送成功")


class ReviewProcessInput(BaseModel):
    """复核处理节点输入"""
    review_items: List[dict] = Field(default=[], description="待复核条目列表")


class ReviewProcessOutput(BaseModel):
    """复核处理节点输出"""
    review_completed: bool = Field(default=False, description="复核是否完成")


# ============================================================
# 审核交互节点（审核群 @机器人 通过/拒绝）
# ============================================================
class ReviewInteractInput(BaseModel):
    """审核交互节点输入"""
    wechat_message: Optional[dict] = Field(default=None, description="企微消息（含@机器人指令）")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")


class ReviewInteractOutput(BaseModel):
    """审核交互节点输出"""
    review_completed: bool = Field(default=False, description="审核交互是否完成")
    wechat_push_result: str = Field(default="", description="审核结果推送消息")


# ============================================================
# 运维监控工作流节点
# ============================================================
class OpsMonitorInput(BaseModel):
    """运维监控节点输入"""
    pass


class OpsMonitorOutput(BaseModel):
    """运维监控节点输出"""
    monitor_report: str = Field(default="", description="运维监控报告")


# ============================================================
# 企业微信相关节点
# ============================================================
class WechatPushInput(BaseModel):
    """企微推送节点输入"""
    daily_report_url: str = Field(default="", description="每日早报下载URL")
    paper_report_url: str = Field(default="", description="论文分析报告下载URL")
    wechat_webhook_url: str = Field(default="", description="企业微信机器人Webhook地址")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")
    audit_results: List[dict] = Field(default=[], description="审核结果列表")
    filtered_news: List[dict] = Field(default=[], description="筛选后资讯列表（含翻译）")
    review_items: List[dict] = Field(default=[], description="待审核条目列表")
    paper_analysis: str = Field(default="", description="论文分析结果")
    skip_wechat_push: bool = Field(default=False, description="是否跳过企微推送")
    trigger_source: str = Field(default="", description="触发来源：schedule/incremental/manual等，incremental时不推早报摘要")


class WechatPushOutput(BaseModel):
    """企微推送节点输出"""
    wechat_push_result: str = Field(default="", description="企微推送结果")


class WechatReceiveInput(BaseModel):
    """企微消息接收节点输入"""
    wechat_message: Optional[dict] = Field(default=None, description="企业微信接收到的消息")
    wechat_webhook_url: str = Field(default="", description="企业微信机器人Webhook地址")
    review_webhook_url: str = Field(default="", description="审核群Webhook地址")
    workflow_mode: str = Field(default="", description="上游预设的工作流模式（manual触发时传入）")
    paper_file: Optional[File] = Field(default=None, description="上游传入的论文文件（manual触发时传入）")
    search_keywords: List[str] = Field(default=[], description="上游传入的搜索关键词")
    skip_wechat_push: bool = Field(default=False, description="是否跳过企微推送")
    trigger_source: str = Field(default="", description="上游传入的触发来源（schedule/incremental/manual），需透传")


class WechatReceiveOutput(BaseModel):
    """企微消息接收节点输出"""
    workflow_mode: str = Field(default="", description="解析后的工作流模式")
    paper_file: Optional[File] = Field(default=None, description="从企微消息中提取的论文文件")
    search_keywords: List[str] = Field(default=[], description="从企微消息中提取的搜索关键词")
    trigger_source: str = Field(default="wechat", description="触发来源")
    review_action: str = Field(default="", description="审核交互动作：approve/reject")
    review_item_id: int = Field(default=0, description="审核交互条目ID")
    review_comment: str = Field(default="", description="审核备注")
    skip_wechat_push: bool = Field(default=False, description="是否跳过企微推送")
