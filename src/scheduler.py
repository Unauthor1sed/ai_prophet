"""
定时任务调度器
- 每日9:00自动生成早报
- 每60分钟增量采集资讯
- 每15秒轮询论文精析任务队列
"""
import os
import time
import uuid
import logging
import threading
from datetime import datetime, date, timedelta
from typing import Optional

import database
from utils.file.file import File, FileOps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL", "")
REVIEW_WEBHOOK_URL = os.getenv("REVIEW_WEBHOOK_URL", "")

_scheduler = None
_running = False


def _do_daily_news():
    """执行每日早报任务"""
    logger.info("开始执行每日早报任务")
    try:
        from graphs.graph import main_graph
        result = main_graph.invoke({
            "workflow_mode": "daily_news",
            "wechat_webhook_url": WECHAT_WEBHOOK_URL,
            "review_webhook_url": REVIEW_WEBHOOK_URL,
            "trigger_source": "schedule",
            "skip_wechat_push": not bool(WECHAT_WEBHOOK_URL)
        })
        logger.info(f"每日早报任务完成: {result.get('daily_report_url', 'N/A')}")
    except Exception as e:
        logger.error(f"每日早报任务失败: {e}", exc_info=True)


def _do_incremental_collect():
    """增量采集资讯"""
    logger.info("开始增量采集资讯")
    try:
        from graphs.graph import main_graph
        result = main_graph.invoke({
            "workflow_mode": "daily_news",
            # 增量采集：不推早报摘要（wechat_push_node 按 trigger_source 判断），
            # 仅将存疑内容推送到审核群
            "wechat_webhook_url": "",
            "review_webhook_url": REVIEW_WEBHOOK_URL,
            "trigger_source": "incremental",
            "skip_wechat_push": not bool(REVIEW_WEBHOOK_URL)
        })
        logger.info("增量采集完成")
    except Exception as e:
        logger.error(f"增量采集失败: {e}", exc_info=True)


def _process_paper_task(task: dict):
    """处理单个论文任务"""
    task_id = task["id"]
    title = task.get("title", "")
    paper_path = task.get("paper_path", "")
    
    try:
        logger.info(f"开始处理论文任务 #{task_id}: {title}")
        
        # 更新进度：解析中
        database.update_paper_task(
            task_id, status="parsing", progress=20,
            progress_msg="正在解析PDF文档..."
        )
        
        # 构造File对象
        paper_file = File(url=paper_path, file_type="document")
        
        # 调用论文精析工作流
        from graphs.graph import main_graph
        result = main_graph.invoke({
            "workflow_mode": "paper_analysis",
            "paper_file": paper_file,
            "wechat_webhook_url": "",
            "skip_wechat_push": True,
            "trigger_source": "paper_task"
        })
        
        report_url = result.get("paper_report_url", "")
        
        # 如果返回的是URL，下载到本地reports目录
        report_path = ""
        if report_url:
            if report_url.startswith("http"):
                # 下载远程报告到本地
                import requests
                reports_dir = os.path.join(DATA_DIR, "reports")
                os.makedirs(reports_dir, exist_ok=True)
                safe_title = "".join(c for c in title[:50] if c.isalnum() or c in (' ', '-', '_')).strip()
                local_name = f"paper_{task_id}_{safe_title or 'report'}.docx"
                local_path = os.path.join(reports_dir, local_name)
                try:
                    resp = requests.get(report_url, timeout=60)
                    if resp.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
                        report_path = f"/files/reports/{local_name}"
                        logger.info(f"报告已下载到本地: {report_path}")
                except Exception as e:
                    logger.warning(f"下载报告失败，使用远程URL: {e}")
                    report_path = report_url
            else:
                report_path = report_url
        
        # 更新任务为完成
        database.update_paper_task(
            task_id, status="completed", progress=100,
            progress_msg="分析完成！",
            report_path=report_path,
            completed_at=datetime.now()
        )
        logger.info(f"论文任务 #{task_id} 处理完成")
        
    except Exception as e:
        logger.error(f"论文任务 #{task_id} 处理失败: {e}", exc_info=True)
        database.update_paper_task(
            task_id, status="failed", progress=0,
            progress_msg="处理失败",
            error_msg=str(e),
            completed_at=datetime.now()
        )


def _poll_paper_tasks():
    """轮询论文任务队列"""
    try:
        task = database.get_pending_paper_task()
        if task:
            _process_paper_task(task)
    except Exception as e:
        logger.error(f"轮询论文任务失败: {e}", exc_info=True)


def start_scheduler():
    """启动调度器"""
    global _scheduler, _running
    if _running:
        logger.warning("调度器已在运行")
        return
    
    try:
        _scheduler = BackgroundScheduler()
        
        # 每日9:00早报
        _scheduler.add_job(
            _do_daily_news,
            CronTrigger(hour=9, minute=0),
            id='daily_news',
            replace_existing=True
        )
        
        # 每60分钟增量采集
        _scheduler.add_job(
            _do_incremental_collect,
            IntervalTrigger(minutes=60),
            id='incremental_collect',
            replace_existing=True
        )
        
        # 每15秒轮询论文任务
        _scheduler.add_job(
            _poll_paper_tasks,
            IntervalTrigger(seconds=15),
            id='poll_paper_tasks',
            replace_existing=True
        )
        
        _scheduler.start()
        _running = True
        logger.info("调度器启动：每日9:00早报，每60分钟增量采集，论文任务每15秒轮询")
    except Exception as e:
        logger.error(f"调度器启动失败: {e}", exc_info=True)


def stop_scheduler():
    """停止调度器"""
    global _scheduler, _running
    _running = False
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
    logger.info("调度器已停止")
