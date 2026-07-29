"""论文解析节点 - 解析PDF论文文件提取文本内容"""
import os
import json
import re
import time
import datetime
import logging
from typing import Optional
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from utils.file.file import File, FileOps
from graphs.state import PaperParseInput, PaperParseOutput

logger = logging.getLogger(__name__)


def paper_parse_node(state: PaperParseInput, config: RunnableConfig, runtime: Runtime[Context]) -> PaperParseOutput:
    """
    title: 论文解析
    desc: 解析上传的SCI论文PDF文件，提取全文文本内容
    """
    paper_file: Optional[File] = state.paper_file

    if paper_file is None:
        logger.warning("未提供论文文件")
        return PaperParseOutput(paper_text="")

    try:
        content: str = FileOps.extract_text(paper_file)
        if not content:
            logger.warning("论文文件内容为空")
            return PaperParseOutput(paper_text="")

        # 清理文本
        content = content.strip()
        logger.info(f"论文解析完成，共 {len(content)} 字符")
        return PaperParseOutput(paper_text=content)

    except Exception as e:
        logger.error(f"论文解析失败: {e}")
        return PaperParseOutput(paper_text=f"[解析失败] {str(e)}")
