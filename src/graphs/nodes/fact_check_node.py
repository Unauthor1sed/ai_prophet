"""事实校验节点 - 大模型校验资讯标题与内容一致性，存疑写入审核队列，通过写入待发池"""
import os
import json
import re
import time
import datetime
import logging
from typing import List, Dict, Any, Optional
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from llm_client import chat_completion_with_json
from graphs.state import FactCheckInput, FactCheckOutput
from database import insert_news_pool, insert_review_queue, get_review_queue_by_url

logger = logging.getLogger(__name__)


def _parse_json_list(text: str) -> Optional[List[Dict[str, Any]]]:
    """增强JSON解析：处理Markdown代码块包裹、前后缀文本等情况"""
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    code_block_patterns = [
        r'```json\s*\n?(.*?)```',
        r'```\s*\n?(.*?)```',
    ]
    for pattern in code_block_patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            inner = m.group(1).strip()
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue
    array_match = re.search(r'\[[\s\S]*\]', text)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def fact_check_node(state: FactCheckInput, config: RunnableConfig, runtime: Runtime[Context]) -> FactCheckOutput:
    """
    title: 事实校验与审核分流
    desc: 使用大模型校验资讯事实一致性，存疑内容写入审核队列，通过内容写入待发池
    integrations: 大语言模型, 数据库
    """
    audit_results: List[Dict[str, Any]] = state.audit_results
    filtered_news: List[Dict[str, Any]] = state.filtered_news

    if not audit_results:
        return FactCheckOutput(audit_results=[], audit_status="通过", review_items=[])

    # 读取配置文件
    cfg_file: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "..", "config", "fact_check_llm_cfg.json")
    with open(cfg_file, 'r', encoding='utf-8') as fd:
        _cfg: Dict[str, Any] = json.load(fd)

    llm_config: Dict[str, Any] = _cfg.get("config", {})
    sp: str = _cfg.get("sp", "")
    up: str = _cfg.get("up", "")

    check_items: List[Dict[str, Any]] = [
        item for item in audit_results
        if item.get("audit_level") != "有害"
    ]

    if not check_items:
        return FactCheckOutput(audit_results=audit_results, audit_status="有害", review_items=[])

    items_json: str = json.dumps(check_items, ensure_ascii=False)
    up_tpl = Template(up)
    user_prompt: str = up_tpl.render({"audit_items": items_json})

    temperature: float = float(llm_config.get("temperature", 0.3))
    max_tokens: int = int(llm_config.get("max_completion_tokens", 4096))

    # 调用大模型
    fact_results: List[Dict[str, Any]] = []
    try:
        result = chat_completion_with_json(
            system_prompt=sp,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if isinstance(result, list):
            fact_results = result
        elif isinstance(result, dict) and "items" in result:
            fact_results = result["items"]
    except Exception as e:
        logger.warning(f"事实校验LLM调用失败，默认通过: {e}")

    if fact_results:
        for i, item in enumerate(audit_results):
            if i < len(fact_results):
                fc: Dict[str, Any] = fact_results[i]
                item["fact_check"] = fc.get("fact_check", "通过")
                item["fact_reason"] = fc.get("reason", "")
    else:
        logger.warning("事实校验LLM返回为空，已按默认'通过'处理")

    # 构建 news 索引
    news_index: Dict[str, Dict[str, Any]] = {}
    for news in filtered_news:
        url: str = news.get("url", "")
        if url:
            news_index[url] = news

    passed_items: List[Dict[str, Any]] = []
    flagged_items: List[Dict[str, Any]] = []
    harmful_items: List[Dict[str, Any]] = []

    for item in audit_results:
        level: str = item.get("audit_level", "通过")
        fact: str = item.get("fact_check", "通过")
        if level == "有害":
            harmful_items.append(item)
        elif level == "存疑" or fact == "存疑":
            flagged_items.append(item)
        else:
            passed_items.append(item)

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 写入数据库
    try:
        for item in passed_items:
            url: str = item.get("url", "")
            news: Dict[str, Any] = news_index.get(url, {})
            try:
                rel_score = float(news.get("relevance_score", 0.5) or 0.5)
            except (ValueError, TypeError):
                rel_score = 0.5
            pool_data: Dict[str, Any] = {
                "news_url": url,
                "title": str(news.get("title", item.get("title", ""))),
                "title_cn": str(news.get("title_cn", "")),
                "snippet": str(news.get("snippet", "")),
                "snippet_cn": str(news.get("snippet_cn", "")),
                "site_name": str(news.get("site_name", "")),
                "importance": str(news.get("importance", "medium")),
                "relevance_score": rel_score,
                "is_pushed": False,
            }
            try:
                insert_news_pool(pool_data)
                logger.info(f"已写入待发池: {url[:80]}")
            except Exception as e:
                logger.warning(f"写入待发池失败: {e}")

        for item in flagged_items:
            url: str = item.get("url", "")
            news = news_index.get(url, {})
            try:
                existing = get_review_queue_by_url(url)
                if existing:
                    item["id"] = existing.get("id", 0)
                    logger.info(f"审核队列已存在，跳过: {url[:80]}")
                    continue
            except Exception as e:
                logger.warning(f"审核队列查重失败: {e}")

            source_name: str = str(news.get("site_name", item.get("site_name", "")))
            review_data: Dict[str, Any] = {
                "news_url": url,
                "title": str(news.get("title", item.get("title", ""))),
                "title_cn": str(news.get("title_cn", "")),
                "snippet": str(news.get("snippet", "")),
                "snippet_cn": str(news.get("snippet_cn", "")),
                "site_name": source_name,
                "source": source_name,
                "importance": str(news.get("importance", "medium")),
                "audit_level": str(item.get("audit_level", "存疑")),
                "audit_reason": str(item.get("audit_reason", item.get("fact_reason", ""))),
                "review_status": "pending",
            }
            try:
                new_id = insert_review_queue(review_data)
                item["id"] = new_id
                logger.info(f"已写入审核队列: {url[:80]}")
            except Exception as e:
                logger.warning(f"写入审核队列失败: {e}")

    except Exception as e:
        logger.error(f"数据库操作失败: {e}")

    review_items: List[Dict[str, Any]] = flagged_items

    if harmful_items:
        audit_status: str = "有害"
    elif flagged_items:
        audit_status = "存疑"
    else:
        audit_status = "通过"

    logger.info(f"事实校验完成: 通过{len(passed_items)}条, 存疑{len(flagged_items)}条, 有害{len(harmful_items)}条")
    return FactCheckOutput(
        audit_results=audit_results,
        audit_status=audit_status,
        review_items=review_items
    )
