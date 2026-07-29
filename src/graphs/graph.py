"""AI先知情报智能体 - 主图编排

五条工作流：
1. daily_news: 企微接收→资讯采集→去重→筛选→翻译→敏感词检测→事实校验→分类路由→早报生成/审核通知→企微推送
2. hourly_collect: 定时触发→资讯采集→去重→筛选→翻译→敏感词检测→事实校验→写入DB/审核群推送
3. paper_analysis: 企微接收→论文解析→论文分析→报告生成→企微推送
4. review_interact: 企微接收(审核指令)→审核交互处理→企微推送
5. ops_monitor: 企微接收→运维监控→企微推送
"""
import os
import json
import re
import time
import datetime
import logging
from typing import Literal
from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context

from graphs.state import (
    GlobalState,
    GraphInput,
    GraphOutput,
    WorkflowRouteInput,
    ClassifyRouteInput,
)

from graphs.nodes.wechat_receive_node import wechat_receive_node
from graphs.nodes.news_collect_node import news_collect_node
from graphs.nodes.news_dedup_node import news_dedup_node
from graphs.nodes.news_filter_node import news_filter_node
from graphs.nodes.sensitive_check_node import sensitive_check_node
from graphs.nodes.news_translate_node import news_translate_node
from graphs.nodes.fact_check_node import fact_check_node
from graphs.nodes.daily_report_gen_node import daily_report_gen_node
from graphs.nodes.paper_parse_node import paper_parse_node
from graphs.nodes.paper_analysis_node import paper_analysis_node
from graphs.nodes.paper_report_gen_node import paper_report_gen_node
from graphs.nodes.review_notify_node import review_notify_node
from graphs.nodes.review_process_node import review_process_node
from graphs.nodes.review_interact_node import review_interact_node
from graphs.nodes.ops_monitor_node import ops_monitor_node
from graphs.nodes.wechat_push_node import wechat_push_node

logger = logging.getLogger(__name__)


# ============================================================
# 条件路由函数
# ============================================================
def route_workflow(state: WorkflowRouteInput) -> str:
    """
    title: 工作流路由
    desc: 根据workflow_mode将请求路由到对应的工作流分支
    """
    mode: str = state.workflow_mode
    if mode == "paper_analysis":
        return "论文精析"
    elif mode == "review_interact":
        return "审核交互"
    elif mode == "ops_monitor":
        return "运维监控"
    elif mode == "hourly_collect":
        return "增量采集"
    else:
        return "每日早报"


def classify_audit(state: ClassifyRouteInput) -> str:
    """
    title: 审核分类路由
    desc: daily_news模式：存疑仅标记不拦截，仍生成早报；hourly_collect模式：存疑推审核群
    """
    status: str = state.audit_status
    mode: str = state.workflow_mode
    if status == "有害":
        return "拦截结束"
    elif status == "存疑" and mode == "hourly_collect":
        return "转审核通知"
    else:
        return "生成早报"


# ============================================================
# 构建主图
# ============================================================
builder = StateGraph(GlobalState, input_schema=GraphInput, output_schema=GraphOutput)

# ---- 添加所有节点 ----
# 企业微信交互节点
builder.add_node("wechat_receive", wechat_receive_node)
builder.add_node("wechat_push", wechat_push_node)

# 每日早报/增量采集工作流节点
builder.add_node("news_collect", news_collect_node)
builder.add_node("news_dedup", news_dedup_node)
builder.add_node("news_filter", news_filter_node, metadata={"type": "agent", "llm_cfg": "config/news_filter_llm_cfg.json"})
builder.add_node("news_translate", news_translate_node, metadata={"type": "agent", "llm_cfg": "config/news_translate_llm_cfg.json"})
builder.add_node("sensitive_check", sensitive_check_node)
builder.add_node("fact_check", fact_check_node, metadata={"type": "agent", "llm_cfg": "config/fact_check_llm_cfg.json"})
builder.add_node("daily_report_gen", daily_report_gen_node)

# 论文精析工作流节点
builder.add_node("paper_parse", paper_parse_node)
builder.add_node("paper_analysis", paper_analysis_node, metadata={"type": "agent", "llm_cfg": "config/paper_analysis_llm_cfg.json"})
builder.add_node("paper_report_gen", paper_report_gen_node)

# 审核相关节点
builder.add_node("review_notify", review_notify_node)
builder.add_node("review_process", review_process_node)
builder.add_node("review_interact", review_interact_node)

# 运维监控工作流节点
builder.add_node("ops_monitor", ops_monitor_node)

# ---- 设置入口点：企微消息接收 ----
builder.set_entry_point("wechat_receive")

# ---- 企微接收 → 工作流路由 ----
builder.add_conditional_edges(
    source="wechat_receive",
    path=route_workflow,
    path_map={
        "每日早报": "news_collect",
        "增量采集": "news_collect",
        "论文精析": "paper_parse",
        "审核交互": "review_interact",
        "运维监控": "ops_monitor",
    }
)

# ---- 每日早报/增量采集工作流边 ----
builder.add_edge("news_collect", "news_dedup")
builder.add_edge("news_dedup", "news_filter")
builder.add_edge("news_filter", "news_translate")
builder.add_edge("news_translate", "sensitive_check")
builder.add_edge("sensitive_check", "fact_check")

# 审核分类路由
builder.add_conditional_edges(
    source="fact_check",
    path=classify_audit,
    path_map={
        "生成早报": "daily_report_gen",
        "转审核通知": "review_notify",
        "拦截结束": "wechat_push",
    }
)

builder.add_edge("daily_report_gen", "wechat_push")
builder.add_edge("review_notify", "wechat_push")

# ---- 论文精析工作流边 ----
builder.add_edge("paper_parse", "paper_analysis")
builder.add_edge("paper_analysis", "paper_report_gen")
builder.add_edge("paper_report_gen", "wechat_push")

# ---- 审核交互工作流边 ----
builder.add_edge("review_interact", END)

# ---- 运维监控工作流边 ----
builder.add_edge("ops_monitor", "wechat_push")

# ---- 企微推送 → 结束 ----
builder.add_edge("wechat_push", END)

# ---- 编译图 ----
main_graph = builder.compile()
