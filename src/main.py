"""
AI先知情报助手 - FastAPI 后端主服务
提供用户认证、审核、敏感词管理、资讯源配置、论文精析、文件下载等API
"""
import os
import json
import uuid
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import database
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")


# ========== Pydantic 模型 ==========

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ReviewAction(BaseModel):
    action: str = Field(..., description="approve/reject")
    comment: str = ""


class SensitiveWordRequest(BaseModel):
    word: str
    category: str = "general"


class NewsSourceRequest(BaseModel):
    name: str
    url: str
    source_type: str = "rss"
    category: str = "general"


class UserRoleUpdate(BaseModel):
    user_id: int
    role: str


# ========== 认证依赖 ==========

def get_current_user(request: Request) -> dict:
    """从cookie获取当前登录用户"""
    token = request.cookies.get("session_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    user = database.validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return user


def require_role(*roles: str):
    """角色检查依赖"""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return checker


# ========== Lifespan ==========

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库
    database.init_database()
    # 启动定时任务
    start_scheduler()
    logger.info("AI先知情报助手服务启动")
    yield
    stop_scheduler()
    logger.info("AI先知情报助手服务停止")


app = FastAPI(title="AI先知情报助手", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 健康检查 ==========

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ========== 认证API ==========

@app.post("/api/auth/login")
async def api_login(request: LoginRequest, response: Response):
    user = database.authenticate_user(request.username.strip(), request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = database.create_session(user["id"])
    response.set_cookie(
        key="session_token", value=token,
        max_age=7*24*3600, httponly=True, samesite="lax"
    )
    return {"success": True, "user": user}


@app.post("/api/auth/register")
async def api_register(request: RegisterRequest):
    username = request.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2个字符")
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    user = database.register_user(username, request.password, role="individual")
    if not user:
        raise HTTPException(status_code=409, detail="用户名已存在")
    return {"success": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


@app.post("/api/auth/logout")
async def api_logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie(key="session_token")
    return {"success": True}


@app.get("/api/auth/me")
async def api_me(user: dict = Depends(get_current_user)):
    return {"success": True, "user": user}


# ========== 看板统计 ==========

@app.get("/api/dashboard/stats")
async def api_dashboard_stats(user: dict = Depends(get_current_user)):
    return database.get_dashboard_stats()


# ========== 手动触发（管理员） ==========

@app.post("/api/admin/trigger/daily-news")
async def api_trigger_daily_news(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_role("admin", "super_admin")),
):
    """管理员手动触发一次早报推送（在后台异步执行，不阻塞请求）"""
    import scheduler as _scheduler

    def _run():
        try:
            _scheduler._do_daily_news()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"手动触发早报失败: {e}", exc_info=True)

    background_tasks.add_task(_run)
    return {
        "success": True,
        "message": "早报任务已加入后台队列，完成后可在看板/历史早报查看。",
        "triggered_by": user["username"],
    }


@app.post("/api/admin/trigger/incremental-collect")
async def api_trigger_incremental_collect(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_role("admin", "super_admin")),
):
    """管理员手动触发一次增量采集"""
    import scheduler as _scheduler

    def _run():
        try:
            _scheduler._do_incremental_collect()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"手动触发增量采集失败: {e}", exc_info=True)

    background_tasks.add_task(_run)
    return {
        "success": True,
        "message": "增量采集已加入后台队列。",
        "triggered_by": user["username"],
    }


# ========== 审核API ==========

@app.get("/api/reviews")
async def api_get_reviews(
    user: dict = Depends(require_role("reviewer", "admin", "super_admin"))
):
    return {"success": True, "items": database.get_pending_reviews(100)}


@app.get("/api/reviews/stats")
async def api_review_stats(user: dict = Depends(get_current_user)):
    return database.get_review_stats()


@app.post("/api/reviews/{review_id}/action")
async def api_review_action(
    review_id: int, action: ReviewAction,
    user: dict = Depends(require_role("reviewer", "admin", "super_admin"))
):
    if action.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="无效的操作类型")
    ok = database.review_action(review_id, action.action, action.comment, user["id"])
    if not ok:
        raise HTTPException(status_code=400, detail="审核失败（任务不存在或已处理）")
    return {"success": True}


# ========== 敏感词API ==========

@app.get("/api/sensitive-words")
async def api_get_sensitive_words(
    user: dict = Depends(require_role("admin", "super_admin"))
):
    return {"success": True, "items": database.get_sensitive_words()}


@app.post("/api/sensitive-words")
async def api_add_sensitive_word(
    req: SensitiveWordRequest,
    user: dict = Depends(require_role("admin", "super_admin"))
):
    ok = database.add_sensitive_word(req.word.strip(), req.category)
    if not ok:
        raise HTTPException(status_code=409, detail="敏感词已存在")
    return {"success": True}


@app.delete("/api/sensitive-words/{word_id}")
async def api_delete_sensitive_word(
    word_id: int,
    user: dict = Depends(require_role("admin", "super_admin"))
):
    ok = database.delete_sensitive_word(word_id)
    if not ok:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    return {"success": True}


# ========== 资讯源API ==========

@app.get("/api/news-sources")
async def api_get_news_sources(
    user: dict = Depends(require_role("admin", "super_admin"))
):
    return {"success": True, "items": database.get_news_sources()}


@app.post("/api/news-sources")
async def api_add_news_source(
    req: NewsSourceRequest,
    user: dict = Depends(require_role("admin", "super_admin"))
):
    ok = database.add_news_source(req.name.strip(), req.url.strip(), req.source_type, req.category)
    if not ok:
        raise HTTPException(status_code=400, detail="添加失败")
    return {"success": True}


@app.post("/api/news-sources/{source_id}/toggle")
async def api_toggle_news_source(
    source_id: int,
    user: dict = Depends(require_role("admin", "super_admin"))
):
    ok = database.toggle_news_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资讯源不存在")
    return {"success": True}


@app.delete("/api/news-sources/{source_id}")
async def api_delete_news_source(
    source_id: int,
    user: dict = Depends(require_role("admin", "super_admin"))
):
    ok = database.delete_news_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资讯源不存在")
    return {"success": True}


# ========== 用户管理API（超管） ==========

@app.get("/api/users")
async def api_get_users(
    user: dict = Depends(require_role("super_admin"))
):
    return {"success": True, "items": database.get_all_users()}


@app.post("/api/users/role")
async def api_update_user_role(
    req: UserRoleUpdate,
    user: dict = Depends(require_role("super_admin"))
):
    if req.role not in ("individual", "reviewer", "admin", "super_admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    if req.user_id == user["id"] and req.role != user["role"]:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    ok = database.update_user_role(req.user_id, req.role)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True}


# ========== 早报/资讯查询 ==========

@app.get("/api/news")
async def api_get_news(
    date: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    items = database.get_news_pool(100, date)
    return {"success": True, "items": items}


@app.get("/api/news/dates")
async def api_get_news_dates(user: dict = Depends(get_current_user)):
    return {"success": True, "dates": database.get_available_dates()}


# ========== 论文精析API ==========

@app.post("/api/papers/upload")
async def api_upload_paper(
    file: UploadFile = File(...),
    title: str = Form(""),
    user: dict = Depends(get_current_user)
):
    """上传论文PDF并创建分析任务"""
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="请上传PDF文件")
    
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过50MB")
    
    # 生成唯一文件名保存
    paper_id = uuid.uuid4().hex[:16]
    filename = f"{paper_id}.pdf"
    paper_dir = os.path.join(DATA_DIR, "papers")
    os.makedirs(paper_dir, exist_ok=True)
    paper_path = os.path.join(paper_dir, filename)
    
    with open(paper_path, "wb") as f:
        f.write(content)
    
    paper_title = title.strip() or os.path.splitext(file.filename)[0]
    
    task_id = database.create_paper_task(
        user_id=user["id"],
        username=user["username"],
        title=paper_title,
        filename=file.filename,
        paper_path=paper_path
    )
    
    return {"success": True, "task_id": task_id, "title": paper_title}


@app.get("/api/papers/tasks")
async def api_get_paper_tasks(user: dict = Depends(get_current_user)):
    """获取用户的论文任务列表"""
    # 超管可以看所有任务，其他人只能看自己的
    if user["role"] == "super_admin":
        tasks = database.get_paper_tasks(limit=50)
    else:
        tasks = database.get_paper_tasks(user_id=user["id"], limit=50)
    return {"success": True, "items": tasks}


@app.get("/api/papers/tasks/{task_id}")
async def api_get_paper_task(
    task_id: int, user: dict = Depends(get_current_user)
):
    """获取单个任务详情（含进度）"""
    task = database.get_paper_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"] and user["role"] not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="无权查看此任务")
    return {"success": True, "task": task}


# ========== 文件下载 ==========

@app.get("/files/{file_type}/{filename}")
async def api_download_file(file_type: str, filename: str, request: Request):
    """下载生成的报告文件"""
    if file_type == "reports":
        base_dir = os.path.join(DATA_DIR, "reports")
    elif file_type == "papers":
        base_dir = os.path.join(DATA_DIR, "papers")
    else:
        raise HTTPException(status_code=404, detail="无效的文件类型")
    
    # 安全检查：防止路径遍历
    safe_name = os.path.basename(filename)
    file_path = os.path.join(base_dir, safe_name)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        file_path,
        filename=safe_name,
        media_type="application/octet-stream"
    )


# ========== 前端静态文件挂载（开发用，生产用Nginx） ==========

# 静态文件查找路径（按优先级）
_STATIC_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static"),  # src/../static
    os.path.join(os.getcwd(), "static"),  # 当前工作目录/static
    "/app/static",  # Docker容器内
]
STATIC_DIR = None
for _d in _STATIC_CANDIDATES:
    if os.path.isdir(_d):
        STATIC_DIR = os.path.abspath(_d)
        break

if STATIC_DIR:
    logger.info(f"挂载静态文件目录: {STATIC_DIR}")

    # 显式登录页和控制台页面路由
    # HTML入口页禁止缓存：否则更新版本后浏览器可能继续用旧页面/旧JS引用
    _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/", include_in_schema=False)
    @app.get("/login", include_in_schema=False)
    async def _login_page():
        return FileResponse(os.path.join(STATIC_DIR, "login.html"), headers=_NO_CACHE)

    @app.get("/index.html", include_in_schema=False)
    async def _index_page():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=_NO_CACHE)

    # 挂载其余静态资源（/app.js 等），html=False 避免把根路径吞掉
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=False), name="static")
else:
    logger.warning("未找到static目录，静态文件服务未启用")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
