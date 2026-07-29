"""论文分析节点 - 大模型深度分析论文内容"""
import os
import json
import re
import time
import datetime
import logging
from typing import Any, Dict, List
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from llm_client import chat_completion
from graphs.state import PaperAnalysisInput, PaperAnalysisOutput

logger = logging.getLogger(__name__)


def paper_analysis_node(state: PaperAnalysisInput, config: RunnableConfig, runtime: Runtime[Context]) -> PaperAnalysisOutput:
    """
    title: 论文分析
    desc: 使用大模型对SCI论文进行深度分析，拆解研究方法、创新点与落地价值
    integrations: 大语言模型
    """
    paper_text: str = state.paper_text

    if not paper_text:
        return PaperAnalysisOutput(paper_analysis="")

    # 读取配置文件
    cfg_file: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "..", "config", "paper_analysis_llm_cfg.json")
    with open(cfg_file, 'r', encoding='utf-8') as fd:
        _cfg: Dict[str, Any] = json.load(fd)

    llm_config: Dict[str, Any] = _cfg.get("config", {})
    sp: str = _cfg.get("sp", "")
    up: str = _cfg.get("up", "")

    # 渲染用户提示词（截取前8000字符避免超token）
    truncated_text: str = paper_text[:8000]
    up_tpl = Template(up)
    user_prompt: str = up_tpl.render({"paper_text": truncated_text})

    temperature: float = float(llm_config.get("temperature", 0.3))
    max_tokens: int = int(llm_config.get("max_completion_tokens", 8192))

    # 调用大模型（使用通用LLM客户端，从环境变量读取模型配置）
    analysis: str = chat_completion(
        system_prompt=sp,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    logger.info(f"论文分析完成，共 {len(analysis)} 字符")
    return PaperAnalysisOutput(paper_analysis=analysis)
