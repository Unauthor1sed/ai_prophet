"""资讯采集节点 - 支持 RSS 订阅 + API 调用 + DuckDuckGo搜索混合采集"""
import os
import json
import re
import time
import datetime
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import NewsCollectInput, NewsCollectOutput

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_SOURCES_CFG = os.path.join(os.getenv("COZE_WORKSPACE_PATH", ""), "assets", "news_sources_cfg.json")


class _MLStripper(HTMLParser):
    """简单HTML标签剥离器"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []
    def handle_data(self, d):
        self.fed.append(d)
    def get_data(self):
        return ''.join(self.fed)


def _strip_html(html: str) -> str:
    """去除HTML标签"""
    s = _MLStripper()
    try:
        s.feed(html)
        return s.get_data()
    except Exception:
        return re.sub(r'<[^>]+>', '', html)


def _load_sources_config(custom_config: Optional[dict]) -> dict:
    """加载资讯源配置，按优先级：
    1. 显式传入的 custom_config
    2. 配置文件 assets/news_sources_cfg.json
    3. 数据库 news_sources 表（用户在 UI 加的源）
    4. 内置兜底
    """
    if custom_config and isinstance(custom_config, dict):
        sources: Optional[list] = custom_config.get("sources")
        if sources and isinstance(sources, list) and len(sources) > 0:
            logger.info("使用自定义资讯源配置")
            return custom_config
    try:
        with open(DEFAULT_SOURCES_CFG, "r", encoding="utf-8") as f:
            cfg: dict = json.load(f)
        logger.info(f"加载默认资讯源配置: {DEFAULT_SOURCES_CFG}")
        return cfg
    except Exception:
        # 文件不存在/解析失败 → fallback 到数据库
        try:
            from database import get_news_sources as _get_db_sources
            db_sources = _get_db_sources()
            if db_sources:
                logger.info(f"从数据库加载 {len(db_sources)} 个资讯源")
                return {
                    "sources": [
                        {
                            "name": s["name"],
                            "type": s.get("source_type", "rss"),
                            "url": s["url"],
                            "enabled": bool(int(s.get("is_active", 1))),
                            "max_items": 10,
                            "description": f"DB source ({s.get('category', 'general')})",
                        }
                        for s in db_sources
                    ],
                    "global": {"max_total_items": 50, "request_timeout": 15},
                }
        except Exception as e:
            logger.warning(f"从数据库加载资讯源失败: {e}")

    logger.warning("加载默认配置失败，使用内置默认源")
    return _get_builtin_defaults()


def _get_builtin_defaults() -> dict:
    """内置兜底配置"""
    return {
        "sources": [
            {
                "name": "arXiv CS.AI",
                "type": "rss",
                "url": "http://export.arxiv.org/rss/cs.AI",
                "enabled": True,
                "max_items": 10,
                "description": "arXiv 人工智能领域最新论文",
            },
            {
                "name": "arXiv CS.CL",
                "type": "rss",
                "url": "http://export.arxiv.org/rss/cs.CL",
                "enabled": True,
                "max_items": 10,
                "description": "arXiv 计算语言学/LLM领域最新论文",
            },
            {
                "name": "Hacker News",
                "type": "api",
                "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
                "enabled": True,
                "max_items": 10,
                "description": "Hacker News 热门资讯",
            },
            {
                "name": "AI前沿搜索",
                "type": "web_search",
                "keywords": [
                    "AI latest breakthroughs research 2025",
                    "large language model LLM new research",
                ],
                "enabled": False,
                "max_items": 5,
                "description": "通过DuckDuckGo获取AI前沿资讯",
            },
        ],
        "global": {"max_total_items": 50, "request_timeout": 15},
    }


def _http_get(url: str, timeout: int = 15, headers: Optional[dict] = None) -> Optional[str]:
    """简单HTTP GET请求"""
    if headers is None:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-Prophet/1.0)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug(f"HTTP GET {url} failed: {e}")
        return None


def _parse_rss_xml(xml_text: str, source_name: str, max_items: int) -> List[Dict[str, Any]]:
    """解析RSS XML"""
    items: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        # 支持RSS 2.0和Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        
        # RSS 2.0 items
        for item in root.findall(".//item")[:max_items]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            
            title = title_el.text if title_el is not None and title_el.text else ""
            link = link_el.text if link_el is not None and link_el.text else ""
            desc = _strip_html(desc_el.text or "") if desc_el is not None and desc_el.text else ""
            pub = pub_el.text if pub_el is not None and pub_el.text else ""
            
            # 解析时间
            pub_time = ""
            if pub:
                from email.utils import parsedate_to_datetime
                try:
                    dt = parsedate_to_datetime(pub)
                    pub_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pub_time = pub
            
            if title and link:
                items.append({
                    "title": title.strip(),
                    "url": link.strip(),
                    "snippet": desc[:300],
                    "site_name": source_name,
                    "publish_time": pub_time,
                    "summary": desc,
                    "source_type": "rss",
                    "source_name": source_name,
                })
        
        # Atom entries
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                summary_el = entry.find("atom:summary", ns)
                updated_el = entry.find("atom:updated", ns)
                
                title = title_el.text if title_el is not None and title_el.text else ""
                link = link_el.get("href", "") if link_el is not None else ""
                desc = _strip_html(summary_el.text or "") if summary_el is not None and summary_el.text else ""
                updated = updated_el.text if updated_el is not None and updated_el.text else ""
                
                pub_time = ""
                if updated:
                    try:
                        dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        pub_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pub_time = updated
                
                if title and link:
                    items.append({
                        "title": title.strip(),
                        "url": link.strip(),
                        "snippet": desc[:300],
                        "site_name": source_name,
                        "publish_time": pub_time,
                        "summary": desc,
                        "source_type": "rss",
                        "source_name": source_name,
                    })
    except Exception as e:
        logger.warning(f"RSS [{source_name}] 解析失败: {e}")
    
    return items


def _fetch_rss_source(source: dict, timeout: int) -> List[Dict[str, Any]]:
    """从 RSS 源采集资讯"""
    url: str = source.get("url", "")
    max_items: int = source.get("max_items", 10)
    source_name: str = source.get("name", url)
    
    xml_text = _http_get(url, timeout)
    if not xml_text:
        logger.warning(f"RSS源 [{source_name}] 请求失败")
        return []
    
    items = _parse_rss_xml(xml_text, source_name, max_items)
    logger.info(f"RSS源 [{source_name}] 采集 {len(items)} 条")
    return items


def _fetch_api_source(source: dict, timeout: int) -> List[Dict[str, Any]]:
    """从 API 源采集资讯（支持Hacker News等）"""
    url: str = source.get("url", "")
    max_items: int = source.get("max_items", 10)
    source_name: str = source.get("name", url)
    items: List[Dict[str, Any]] = []

    try:
        resp_text = _http_get(url, timeout)
        if not resp_text:
            return items
        data: Any = json.loads(resp_text)

        if isinstance(data, list):
            item_ids = data[:max_items]
            for item_id in item_ids:
                try:
                    detail_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                    detail_text = _http_get(detail_url, timeout)
                    if not detail_text:
                        continue
                    detail: dict = json.loads(detail_text)
                    news_item: Dict[str, Any] = {
                        "title": detail.get("title", ""),
                        "url": detail.get("url", f"https://news.ycombinator.com/item?id={item_id}"),
                        "snippet": (detail.get("text", "") or "")[:300],
                        "site_name": source_name,
                        "publish_time": datetime.datetime.fromtimestamp(
                            detail.get("time", 0)
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                        "summary": detail.get("text", "") or "",
                        "source_type": "api",
                        "source_name": source_name,
                    }
                    items.append(news_item)
                except Exception:
                    continue

        logger.info(f"API源 [{source_name}] 采集 {len(items)} 条")
    except Exception as e:
        logger.warning(f"API源 [{source_name}] 采集失败: {e}")

    return items


def _duckduckgo_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """使用DuckDuckGo HTML搜索"""
    items: List[Dict[str, Any]] = []
    try:
        encoded_q = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        html = _http_get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if not html:
            return items
        
        # 简单正则解析DuckDuckGo HTML结果
        # 结果格式: <a class="result__a" href="...">title</a> ... <a class="result__snippet">snippet</a>
        result_blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        
        for href, title_html, snippet_html in result_blocks[:max_results]:
            title = _strip_html(title_html).strip()
            snippet = _strip_html(snippet_html).strip()
            # DuckDuckGo使用uddg参数传递真实URL
            if "uddg=" in href:
                try:
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    real_url = qs.get("uddg", [href])[0]
                    href = urllib.parse.unquote(real_url)
                except Exception:
                    pass
            
            if title and href:
                items.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet[:300],
                    "site_name": urllib.parse.urlparse(href).netloc or "DuckDuckGo",
                    "publish_time": "",
                    "summary": snippet,
                    "source_type": "web_search",
                    "source_name": "Web搜索",
                })
    except Exception as e:
        logger.warning(f"DuckDuckGo搜索 '{query}' 失败: {e}")
    
    return items


def _fetch_web_search_source(source: dict) -> List[Dict[str, Any]]:
    """从 Web 搜索采集资讯（使用DuckDuckGo）"""
    keywords: List[str] = source.get("keywords", [])
    max_items: int = source.get("max_items", 5)
    source_name: str = source.get("name", "Web搜索")
    items: List[Dict[str, Any]] = []
    seen_urls: set = set()

    if not keywords:
        return items

    for keyword in keywords:
        try:
            results = _duckduckgo_search(keyword, max_items)
            for item in results:
                url: str = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    item["source_keyword"] = keyword
                    items.append(item)
        except Exception as e:
            logger.warning(f"Web搜索关键词 '{keyword}' 失败: {e}")

    logger.info(f"Web搜索源 [{source_name}] 采集 {len(items)} 条")
    return items


def news_collect_node(
    state: NewsCollectInput, config: RunnableConfig, runtime: Runtime[Context]
) -> NewsCollectOutput:
    """
    title: 资讯采集
    desc: 通过RSS订阅、API调用和DuckDuckGo搜索从arXiv、Hacker News等公开渠道采集AI前沿资讯，支持自定义资讯源配置
    integrations: Web搜索(DuckDuckGo)
    """
    # 加载资讯源配置
    sources_cfg: dict = _load_sources_config(state.news_sources_config)
    sources: list = sources_cfg.get("sources", [])
    global_cfg: dict = sources_cfg.get("global", {})
    max_total: int = global_cfg.get("max_total_items", 50)
    timeout: int = global_cfg.get("request_timeout", 15)

    # 过滤启用的源
    enabled_sources: list = [s for s in sources if s.get("enabled", True)]
    logger.info(f"开始采集，共 {len(enabled_sources)} 个启用的资讯源")

    all_news: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for source in enabled_sources:
        source_type: str = source.get("type", "")
        source_items: List[Dict[str, Any]] = []

        if source_type == "rss":
            source_items = _fetch_rss_source(source, timeout)
        elif source_type == "api":
            source_items = _fetch_api_source(source, timeout)
        elif source_type == "web_search":
            source_items = _fetch_web_search_source(source)
        else:
            logger.warning(f"未知资讯源类型: {source_type}，跳过 [{source.get('name', 'unknown')}]")

        # 去重
        for item in source_items:
            url: str = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_news.append(item)

        if len(all_news) >= max_total:
            all_news = all_news[:max_total]
            break

    # 如果用户额外传了 search_keywords，追加 Web 搜索
    extra_keywords: List[str] = state.search_keywords
    if extra_keywords:
        extra_source = {
            "name": "自定义搜索",
            "type": "web_search",
            "keywords": extra_keywords,
            "max_items": 5,
            "enabled": True,
        }
        extra_items = _fetch_web_search_source(extra_source)
        for item in extra_items:
            url: str = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_news.append(item)

    logger.info(f"资讯采集完成，共获取 {len(all_news)} 条资讯（来自 {len(enabled_sources)} 个源）")
    return NewsCollectOutput(raw_news=all_news)
