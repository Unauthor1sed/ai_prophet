"""本地文件存储模块 - 替代S3对象存储"""
import os
import shutil
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/data")


def ensure_dirs() -> None:
    """确保必要目录存在"""
    for subdir in ["papers", "reports", "tmp"]:
        os.makedirs(os.path.join(DATA_DIR, subdir), exist_ok=True)


def save_file_to_local(source_path: str, category: str = "reports") -> str:
    """
    将文件保存到本地存储目录
    :param source_path: 源文件路径
    :param category: 分类目录 (papers/reports)
    :return: 相对URL路径
    """
    ensure_dirs()
    target_dir: str = os.path.join(DATA_DIR, category)
    os.makedirs(target_dir, exist_ok=True)
    
    filename: str = os.path.basename(source_path)
    target_path: str = os.path.join(target_dir, filename)
    
    if source_path != target_path:
        shutil.copy2(source_path, target_path)
    
    return f"/files/{category}/{filename}"


def save_uploaded_file(file_content: bytes, original_filename: str, category: str = "papers") -> str:
    """
    保存上传的文件内容
    :param file_content: 文件二进制内容
    :param original_filename: 原始文件名
    :param category: 分类目录
    :return: 本地文件路径
    """
    ensure_dirs()
    target_dir: str = os.path.join(DATA_DIR, category)
    os.makedirs(target_dir, exist_ok=True)
    
    # 生成唯一文件名
    ext: str = os.path.splitext(original_filename)[1] if "." in original_filename else ""
    unique_name: str = f"{uuid.uuid4().hex[:8]}_{original_filename}"
    target_path: str = os.path.join(target_dir, unique_name)
    
    with open(target_path, "wb") as f:
        f.write(file_content)
    
    logger.info(f"文件已保存: {target_path}")
    return target_path


def get_file_path(relative_url: str) -> Optional[str]:
    """
    根据URL路径获取本地文件路径
    :param relative_url: 如 /files/reports/xxx.docx
    :return: 本地绝对路径
    """
    if not relative_url:
        return None
    
    # 去掉 /files/ 前缀
    if relative_url.startswith("/files/"):
        relative_url = relative_url[len("/files/"):]
    elif relative_url.startswith("files/"):
        relative_url = relative_url[len("files/"):]
    
    local_path: str = os.path.join(DATA_DIR, relative_url)
    
    if os.path.exists(local_path) and os.path.isfile(local_path):
        return local_path
    
    # 兼容旧格式：直接传文件名
    for category in ["reports", "papers", "tmp"]:
        candidate: str = os.path.join(DATA_DIR, category, os.path.basename(relative_url))
        if os.path.exists(candidate):
            return candidate
    
    return None


def save_tmp_file(file_content: bytes, suffix: str = ".pdf") -> str:
    """
    保存临时文件
    :param file_content: 文件内容
    :param suffix: 文件后缀
    :return: 临时文件路径
    """
    ensure_dirs()
    tmp_dir: str = os.path.join(DATA_DIR, "tmp")
    tmp_path: str = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{suffix}")
    with open(tmp_path, "wb") as f:
        f.write(file_content)
    return tmp_path


def cleanup_tmp_file(filepath: str) -> None:
    """清理临时文件"""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.warning(f"清理临时文件失败: {e}")
