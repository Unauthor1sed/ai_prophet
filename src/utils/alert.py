"""统一告警模块（需求1000087简版）
- 所有异常（采集全失败/LLM失败/推送失败/任务异常）通过统一入口发企微告警
- 同类告警在去重窗口内只发一次，避免刷屏
- 告警发送本身失败只记日志，绝不影响主流程
"""
import os
import time
import logging
import hashlib
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# 告警去重窗口（秒），默认30分钟
_DEDUP_WINDOW = int(os.getenv("ALERT_DEDUP_SECONDS", "1800"))
_sent_cache: dict = {}
_lock = threading.Lock()


def _alert_webhook() -> str:
    """告警通道：优先 ALERT_WEBHOOK_URL，缺省复用审核群"""
    return os.getenv("ALERT_WEBHOOK_URL", "") or os.getenv("REVIEW_WEBHOOK_URL", "")


def send_alert(alert_type: str, message: str, detail: str = "") -> bool:
    """发送统一告警。alert_type: collect_failed/llm_failed/push_failed/task_failed/service"""
    key = hashlib.md5(f"{alert_type}:{message}".encode()).hexdigest()
    now = time.time()
    with _lock:
        last = _sent_cache.get(key, 0)
        if now - last < _DEDUP_WINDOW:
            logger.info(f"告警去重窗口内已发送过，跳过: [{alert_type}] {message}")
            return False
        _sent_cache[key] = now
        # 清理过期缓存
        for k in [k for k, v in _sent_cache.items() if now - v > _DEDUP_WINDOW * 2]:
            _sent_cache.pop(k, None)

    logger.error(f"【统一告警】[{alert_type}] {message} {detail[:200]}")
    url = _alert_webhook()
    if not url:
        return False
    try:
        import requests
        content = (f"# 🚨 系统告警 · {alert_type}\n\n"
                   f"**{message}**\n\n")
        if detail:
            content += f"> {detail[:300]}\n\n"
        content += f"_请检查系统日志与运行状态_"
        resp = requests.post(url, json={"msgtype": "markdown", "markdown": {"content": content}},
                             timeout=10)
        ok = resp.status_code == 200 and resp.json().get("errcode") == 0
        if not ok:
            logger.error(f"告警企微推送失败: HTTP {resp.status_code} {resp.text[:100]}")
        return ok
    except Exception as e:
        logger.error(f"告警企微推送异常: {e}")
        return False
