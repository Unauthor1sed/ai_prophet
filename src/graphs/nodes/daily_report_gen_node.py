"""每日早报生成节点 - 从待发池读取当日已通过资讯，按优先级排序生成精美Word文档"""
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
from graphs.state import DailyReportGenInput, DailyReportGenOutput
from database import get_db, news_pool_mark_pushed

logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    """转义Markdown特殊字符"""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("*", "\\*").replace("_", "\\_")


def _get_importance_order(importance: str) -> int:
    """重要性排序权重"""
    order_map: Dict[str, int] = {"high": 0, "medium": 1, "low": 2}
    return order_map.get(importance, 1)


def daily_report_gen_node(state: DailyReportGenInput, config: RunnableConfig, runtime: Runtime[Context]) -> DailyReportGenOutput:
    """
    title: 早报生成
    desc: 从待发池读取当日已通过审核的资讯，按优先级排序后生成格式精美的Word每日早报文档，跨日资讯标注原始采集日期
    integrations: 本地文件存储, PostgreSQL数据库
    """
    ctx = runtime.context
    news_pool: List[Dict[str, Any]] = state.news_pool

    # 如果 state 中没有传入 news_pool，从数据库读取
    if not news_pool:
        try:
            db = get_db()
            rows = db.execute(
                """SELECT * FROM news_pool WHERE is_pushed = %s ORDER BY importance ASC, approved_at DESC""",
                (False,)
            ).fetchall()
            col_names = [desc[0] for desc in db.description]
            news_pool = [dict(zip(col_names, row)) for row in rows]
            logger.info(f"从数据库读取待发池: {len(news_pool)} 条")
        except Exception as e:
            logger.error(f"读取待发池失败: {e}")

    if not news_pool:
        return DailyReportGenOutput(daily_report_url="")

    # 按重要性 + 评分排序
    def _safe_score(item: Dict[str, Any]) -> float:
        raw = item.get("relevance_score", 0.5)
        if raw is None:
            return 0.5
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.5

    news_pool.sort(key=lambda x: (_get_importance_order(str(x.get("importance", "medium"))), -_safe_score(x)))

    now_dt = datetime.datetime.now()
    today_date: datetime.date = now_dt.date()
    now_str: str = now_dt.strftime("%Y年%m月%d日")
    weekday: str = ["一", "二", "三", "四", "五", "六", "日"][now_dt.weekday()]
    now_ts: str = now_dt.strftime("%Y%m%d_%H%M%S")

    # 统计
    total_count: int = len(news_pool)
    today_count: int = 0
    cross_day_count: int = 0
    high_count: int = 0

    for news in news_pool:
        importance: str = str(news.get("importance", "medium"))
        if importance == "high":
            high_count += 1

        collected = news.get("collected_at")
        if collected:
            try:
                if hasattr(collected, 'date'):
                    cdate = collected.date()
                else:
                    collected_str = str(collected).replace("Z", "+00:00")
                    cdate = datetime.datetime.fromisoformat(collected_str).date()
                if cdate == today_date:
                    today_count += 1
                else:
                    cross_day_count += 1
            except (ValueError, TypeError):
                today_count += 1
        else:
            today_count += 1

    # ===== 构建精美Markdown内容 =====
    lines: List[str] = []

    # 头部Banner
    lines.append("# 🤖 AI先知 · 每日技术早报")
    lines.append("")
    lines.append(f"> 📅 **{now_str}** 星期{weekday}  |  📰 共收录 **{total_count}** 条资讯  |  🔥 重点 **{high_count}** 条")
    if cross_day_count > 0:
        lines.append(f"> 📌 含 **{cross_day_count}** 条历史审核通过资讯（已标注原始日期）")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 目录索引
    lines.append("## 📋 本期速览")
    lines.append("")
    for i, news in enumerate(news_pool, 1):
        title_cn: str = str(news.get("title_cn", news.get("title", "无标题")))
        importance: str = str(news.get("importance", "medium"))
        icon: str = "🔥" if importance == "high" else ("📌" if importance == "medium" else "💡")
        lines.append(f"{i}. {icon} {_escape_md(title_cn[:80])}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 详细内容
    lines.append("## 📰 今日AI前沿资讯")
    lines.append("")

    for i, news in enumerate(news_pool, 1):
        title: str = str(news.get("title", "无标题"))
        title_cn: str = str(news.get("title_cn", ""))
        url: str = str(news.get("news_url", news.get("url", "")))
        snippet: str = str(news.get("snippet", ""))
        snippet_cn: str = str(news.get("snippet_cn", ""))
        site_name: str = str(news.get("site_name", ""))
        importance: str = str(news.get("importance", "medium"))
        collected = news.get("collected_at")

        # 跨日标注
        cross_day_note: str = ""
        if collected:
            try:
                if hasattr(collected, 'date'):
                    cdate = collected.date()
                else:
                    collected_str = str(collected).replace("Z", "+00:00")
                    cdt = datetime.datetime.fromisoformat(collected_str)
                    cdate = cdt.date()
                    collected = cdt
                if cdate != today_date:
                    cross_day_note = f" 📅（{cdate.strftime('%m月%d日')}收录）"
            except (ValueError, TypeError):
                pass

        # 标题
        display_title: str = title_cn if title_cn else title
        importance_icon: str = "🔥" if importance == "high" else ("📌" if importance == "medium" else "💡")
        lines.append(f"### {i}. {importance_icon} {display_title}{cross_day_note}")
        lines.append("")

        # 原标题（如果有翻译）
        if title_cn and title != title_cn:
            lines.append(f"> 📝 原标题: *{_escape_md(title[:120])}*")
            lines.append("")

        # 内容摘要
        display_snippet: str = snippet_cn if snippet_cn else snippet
        if display_snippet:
            snip: str = display_snippet[:300]
            if len(display_snippet) > 300:
                snip += "..."
            lines.append(f"{snip}")
            lines.append("")

        # 元信息
        meta_parts: List[str] = []
        if site_name:
            meta_parts.append(f"🏷️ 来源: {site_name}")
        if collected:
            try:
                if hasattr(collected, 'strftime'):
                    meta_parts.append(f"🕐 {collected.strftime('%Y-%m-%d %H:%M')}")
            except (ValueError, TypeError):
                pass
        if url:
            meta_parts.append(f"🔗 查看原文: {url}")
        lines.append(" | ".join(meta_parts))
        lines.append("")
        lines.append("---")
        lines.append("")

    # 统计信息
    lines.append("## 📊 统计信息")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 收录资讯数 | {total_count} |")
    lines.append(f"| 今日新收录 | {today_count} |")
    if cross_day_count > 0:
        lines.append(f"| 历史审核通过 | {cross_day_count} |")
    lines.append(f"| 重点资讯 (🔥) | {high_count} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*🤖 本早报由 **AI先知情报智能体** 自动采集、翻译、审核并生成*")
    lines.append("")
    lines.append(f"*生成时间: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}*")

    markdown_content: str = "\n".join(lines)

    try:
        from doc_gen import generate_docx_from_markdown
        from storage import save_file_to_local

        title_str: str = f"AI_Daily_Report_{now_ts}"
        local_path: str = generate_docx_from_markdown(markdown_content, title_str)
        
        # 保存到文件存储
        url_path: str = save_file_to_local(local_path, "reports")
        report_url: str = f"/files/reports/{os.path.basename(local_path)}"

        # 标记已推送
        try:
            ids_to_mark: List[int] = []
            for news in news_pool:
                nid = news.get("id", 0)
                if nid and int(nid) > 0:
                    ids_to_mark.append(int(nid))
            if ids_to_mark:
                news_pool_mark_pushed(ids_to_mark)
            logger.info(f"已标记 {len(ids_to_mark)} 条资讯为已推送")
        except Exception as e:
            logger.warning(f"标记已推送失败: {e}")

        logger.info(f"每日早报已生成: {report_url}")
        return DailyReportGenOutput(daily_report_url=report_url)

    except Exception as e:
        logger.error(f"早报生成失败: {e}", exc_info=True)
        return DailyReportGenOutput(daily_report_url="")
