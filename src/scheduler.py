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

# 调度时间可配置（需求1000091）：
# DAILY_REPORT_TIME=HH:MM 每日早报时间（默认09:00）
# DAILY_REPORT_DAYS=cron星期表达式（默认mon-fri工作日；每天用 mon-sun 或 *）
# COLLECT_INTERVAL_MINUTES=增量采集间隔分钟（默认60，最小5）
def _parse_report_time() -> tuple:
    raw = os.getenv("DAILY_REPORT_TIME", "09:00").strip()
    try:
        h, m = raw.split(":")
        h, m = int(h), int(m)
        assert 0 <= h <= 23 and 0 <= m <= 59
        return h, m
    except Exception:
        logger.warning(f"DAILY_REPORT_TIME 配置无效（{raw}），使用默认 09:00")
        return 9, 0

DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE = _parse_report_time()
DAILY_REPORT_DAYS = os.getenv("DAILY_REPORT_DAYS", "mon-fri").strip() or "mon-fri"
try:
    COLLECT_INTERVAL_MINUTES = max(5, int(os.getenv("COLLECT_INTERVAL_MINUTES", "60")))
except ValueError:
    COLLECT_INTERVAL_MINUTES = 60

_scheduler = None
_running = False


def _run_news_task(task_type: str, invoke_args: dict):
    """统一任务执行器：执行记录（task_runs）+ 采集全失败/任务异常统一告警"""
    from utils.alert import send_alert
    run_id = 0
    try:
        run_id = database.create_task_run(task_type, invoke_args.get("trigger_source", ""))
    except Exception as e:
        logger.warning(f"创建执行记录失败: {e}")
    try:
        from graphs.graph import main_graph
        result = main_graph.invoke(invoke_args)
        collected = len(result.get("raw_news") or [])
        filtered = len(result.get("filtered_news") or [])
        if collected == 0:
            # 采集全失败：告警 + 记为failed
            send_alert("collect_failed", f"{task_type}: 所有资讯源采集失败（0条）",
                       "请检查网络与资讯源配置")
            if run_id:
                database.finish_task_run(run_id, "failed", 0, 0, "采集0条")
        else:
            status = "success" if filtered > 0 else "partial"
            if run_id:
                database.finish_task_run(run_id, status, collected, filtered)
        return result
    except Exception as e:
        logger.error(f"{task_type}任务失败: {e}", exc_info=True)
        send_alert("task_failed", f"{task_type} 任务执行异常", str(e))
        if run_id:
            try:
                database.finish_task_run(run_id, "failed", 0, 0, str(e))
            except Exception:
                pass
        return None


def _do_daily_news():
    """执行每日早报任务"""
    logger.info("开始执行每日早报任务")
    result = _run_news_task("daily_news", {
        "workflow_mode": "daily_news",
        "wechat_webhook_url": WECHAT_WEBHOOK_URL,
        "review_webhook_url": REVIEW_WEBHOOK_URL,
        "trigger_source": "schedule",
        "skip_wechat_push": not bool(WECHAT_WEBHOOK_URL)
    })
    if result:
        logger.info(f"每日早报任务完成: {result.get('daily_report_url', 'N/A')}")


def _do_incremental_collect():
    """增量采集资讯"""
    logger.info("开始增量采集资讯")
    result = _run_news_task("incremental_collect", {
        "workflow_mode": "daily_news",
        # 增量采集：不推早报摘要（wechat_push_node 按 trigger_source 判断），
        # 仅将存疑内容推送到审核群
        "wechat_webhook_url": "",
        "review_webhook_url": REVIEW_WEBHOOK_URL,
        "trigger_source": "incremental",
        "skip_wechat_push": not bool(REVIEW_WEBHOOK_URL)
    })
    if result:
        logger.info("增量采集完成")


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
    
    # 启动时清理上次进程中断遗留的 running 记录
    try:
        from sqlalchemy import text as _text
        with database.get_db() as _db:
            _db.execute(_text(
                "UPDATE task_runs SET status='failed', error_msg='进程重启中断' WHERE status='running'"))
    except Exception as e:
        logger.warning(f"清理遗留执行记录失败: {e}")

    try:
        _scheduler = BackgroundScheduler()
        
        # 每日早报（时间/星期可配置）
        _scheduler.add_job(
            _do_daily_news,
            CronTrigger(hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE,
                        day_of_week=DAILY_REPORT_DAYS),
            id='daily_news',
            replace_existing=True
        )

        # 增量采集（间隔可配置）
        _scheduler.add_job(
            _do_incremental_collect,
            IntervalTrigger(minutes=COLLECT_INTERVAL_MINUTES),
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
        logger.info(
            f"调度器启动：早报 {DAILY_REPORT_DAYS} {DAILY_REPORT_HOUR:02d}:{DAILY_REPORT_MINUTE:02d}，"
            f"每{COLLECT_INTERVAL_MINUTES}分钟增量采集，论文任务每15秒轮询")
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
