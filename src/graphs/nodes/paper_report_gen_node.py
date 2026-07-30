"""论文报告生成节点 - 将分析结果生成Word文档"""
import os
import datetime
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import PaperReportGenInput, PaperReportGenOutput
from doc_gen import generate_docx_from_markdown
from storage import save_file_to_local

logger = logging.getLogger(__name__)


def paper_report_gen_node(state: PaperReportGenInput, config: RunnableConfig, runtime: Runtime[Context]) -> PaperReportGenOutput:
    """
    title: 论文报告生成
    desc: 将论文分析结果生成格式规范的Word文档，保存到本地文件存储并返回下载路径
    integrations: 本地文件存储
    """
    analysis: str = state.paper_analysis

    if not analysis:
        return PaperReportGenOutput(paper_report_url="")

    # 剥离LLM可能带的开场白：若正文前500字符内出现首个Markdown标题，则从标题开始
    first_heading = analysis.find("## ")
    if 0 < first_heading < 500:
        analysis = analysis[first_heading:]

    now_str: str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    markdown_content: str = f"""# SCI论文精析报告

**生成时间**: {now_str}

---

{analysis}

---

*本报告由AI先知情报智能体自动生成*
"""

    try:
        timestamp: str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        title: str = f"Paper_Analysis_{timestamp}"
        local_path: str = generate_docx_from_markdown(markdown_content, title)
        
        url_path: str = save_file_to_local(local_path, "reports")
        report_url: str = f"/files/reports/{os.path.basename(local_path)}"

        logger.info(f"论文分析报告已生成: {report_url}")
        return PaperReportGenOutput(paper_report_url=report_url)

    except Exception as e:
        logger.error(f"论文报告生成失败: {e}", exc_info=True)
        return PaperReportGenOutput(paper_report_url="")
