"""
数据库连接与操作模块
默认使用 SQLite（单容器部署零依赖），可通过 DATABASE_URL 环境变量切换 PostgreSQL
"""
import os
import json
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text, inspect, bindparam
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

# 数据库配置 - 默认SQLite单文件
DATA_DIR = os.getenv("DATA_DIR", "/data")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/aiprophet.db")

# 密码盐值
PASSWORD_SALT = "ai_prophet_salt_2024"
SESSION_EXPIRE_DAYS = 7

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "papers"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "reports"), exist_ok=True)


def get_database_url() -> str:
    """获取数据库连接URL"""
    return DATABASE_URL


# 创建引擎（SQLite需要check_same_thread=False以支持多线程）
_db_url = get_database_url()
_connect_args: Dict[str, Any] = {}
if _db_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    _db_url,
    connect_args=_connect_args,
    pool_pre_ping=not _db_url.startswith("sqlite"),
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """获取数据库会话的上下文管理器"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def hash_password(password: str) -> str:
    """密码哈希（SHA256 + 盐值）"""
    return hashlib.sha256((password + PASSWORD_SALT).encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return hash_password(password) == password_hash


def create_session_token() -> str:
    """生成会话token"""
    return secrets.token_urlsafe(32)


# ========== 初始化数据库 ==========

def init_db():
    """初始化数据库（别名，供外部调用）"""
    init_database()

def init_database():
    """初始化数据库表结构"""
    db_path = get_database_url()
    
    if "sqlite" in db_path:
        _init_sqlite()
    else:
        _init_postgres()
    
    # 确保有默认admin账号
    _ensure_default_admin()
    # 确保有默认敏感词库（仅首次创建时 seed）
    _ensure_default_sensitive_words()
    # 确保有默认资讯源（仅首次创建时 seed）
    _ensure_default_news_sources()
    logger.info("数据库初始化完成")


def _init_sqlite():
    """初始化SQLite数据库"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'individual',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login TEXT
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                translated_title TEXT,
                content TEXT,
                summary TEXT,
                url TEXT NOT NULL,
                source TEXT,
                relevance_score REAL DEFAULT 0.5,
                fact_check_result TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER,
                review_comment TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                translated_title TEXT,
                content TEXT,
                summary TEXT,
                url TEXT NOT NULL UNIQUE,
                source TEXT,
                relevance_score REAL DEFAULT 0.5,
                news_date TEXT NOT NULL DEFAULT (date('now')),
                published_at TEXT DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                is_pushed INTEGER NOT NULL DEFAULT 0
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sensitive_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT 'general',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by INTEGER
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'rss',
                category TEXT DEFAULT 'general',
                weight REAL DEFAULT 1.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_fetched TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                original_filename TEXT,
                paper_path TEXT NOT NULL,
                paper_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                progress_msg TEXT DEFAULT '等待处理',
                analysis_result TEXT,
                report_path TEXT,
                error_msg TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                description TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        
        # 创建索引
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status)",
            "CREATE INDEX IF NOT EXISTS idx_review_queue_created ON review_queue(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_news_pool_date ON news_pool(news_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_paper_tasks_user ON paper_tasks(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_paper_tasks_status ON paper_tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_paper_tasks_created ON paper_tasks(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token)",
        ]:
            conn.execute(text(idx_sql))

        # 兼容已有库：补齐新加的列（SQLite 不支持 IF NOT EXISTS for ADD COLUMN）
        try:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(news_pool)")).fetchall()}
            if "is_pushed" not in cols:
                conn.execute(text("ALTER TABLE news_pool ADD COLUMN is_pushed INTEGER NOT NULL DEFAULT 0"))
                logger.info("为 news_pool 表补充 is_pushed 列")
        except Exception as e:
            logger.warning(f"检查/补充 news_pool 列失败（可忽略）: {e}")

        conn.commit()


def _init_postgres():
    """PostgreSQL初始化建表（双重保险）"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(128) NOT NULL UNIQUE,
                password_hash VARCHAR(256) NOT NULL,
                role VARCHAR(32) NOT NULL DEFAULT 'individual',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS review_queue (
                id SERIAL PRIMARY KEY,
                news_id INTEGER DEFAULT 0,
                title VARCHAR(512) NOT NULL DEFAULT '',
                summary TEXT DEFAULT '',
                source VARCHAR(512) DEFAULT '',
                source_url TEXT DEFAULT '',
                translated_title VARCHAR(512) DEFAULT '',
                translated_content TEXT DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER DEFAULT NULL,
                review_comment TEXT DEFAULT '',
                review_time TIMESTAMPTZ DEFAULT NULL,
                facts JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_pool (
                id SERIAL PRIMARY KEY,
                title VARCHAR(512) NOT NULL DEFAULT '',
                summary TEXT DEFAULT '',
                source VARCHAR(512) DEFAULT '',
                source_url TEXT DEFAULT '',
                translated_title VARCHAR(512) DEFAULT '',
                translated_content TEXT DEFAULT '',
                published_date VARCHAR(32) DEFAULT '',
                relevance_score FLOAT DEFAULT 0.0,
                status VARCHAR(32) DEFAULT 'pending',
                news_date VARCHAR(20) DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sensitive_words (
                id SERIAL PRIMARY KEY,
                word VARCHAR(256) NOT NULL UNIQUE,
                category VARCHAR(64) DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_sources (
                id SERIAL PRIMARY KEY,
                name VARCHAR(256) NOT NULL,
                url VARCHAR(512) NOT NULL,
                source_type VARCHAR(32) DEFAULT 'rss',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_crawled TIMESTAMPTZ DEFAULT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_tasks (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                username VARCHAR(128) NOT NULL,
                title VARCHAR(512) NOT NULL DEFAULT '',
                paper_url TEXT NOT NULL,
                local_path TEXT DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                progress_msg TEXT DEFAULT '等待处理',
                analysis_result TEXT DEFAULT NULL,
                report_path TEXT DEFAULT NULL,
                error_msg TEXT DEFAULT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ DEFAULT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_pool_date ON news_pool(news_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_paper_tasks_user ON paper_tasks(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_paper_tasks_status ON paper_tasks(status)"))
        conn.commit()


def _ensure_default_admin():
    """确保默认管理员账号存在"""
    with get_db() as db:
        result = db.execute(text("SELECT id FROM users WHERE username = 'admin'")).fetchone()
        if not result:
            db.execute(text(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (:username, :password_hash, :role, :now, :now)"
            ), {"username": "admin", "password_hash": hash_password("admin123"), "role": "super_admin", "now": datetime.now()})


# 默认敏感词库（首次启动时 seed 一次；之后用户在前端增删的不受影响）
DEFAULT_SENSITIVE_WORDS: List[tuple] = [
    ("违禁", "politics"),
    ("非法", "politics"),
    ("赌博", "vice"),
    ("色情", "vice"),
    ("暴力恐怖", "violence"),
    ("颠覆国家", "politics"),
    ("分裂国家", "politics"),
    ("邪教", "politics"),
    ("毒品", "vice"),
    ("枪支", "violence"),
    ("诈骗", "vice"),
    ("传销", "vice"),
    ("洗钱", "vice"),
    ("盗版", "ip"),
    ("侵权", "ip"),
]


def _ensure_default_sensitive_words():
    """首次启动时 seed 默认敏感词库（用户后续可自行增删）"""
    with get_db() as db:
        count = db.execute(text("SELECT COUNT(*) FROM sensitive_words")).fetchone()[0]
        if count == 0:
            for word, category in DEFAULT_SENSITIVE_WORDS:
                try:
                    db.execute(text(
                        "INSERT INTO sensitive_words (word, category, is_active) VALUES (:w, :c, 1)"
                    ), {"w": word, "c": category})
                except Exception as e:
                    logger.warning(f"seed 敏感词 '{word}' 失败: {e}")
            logger.info(f"已 seed {len(DEFAULT_SENSITIVE_WORDS)} 个默认敏感词")


# 默认资讯源（首次启动 seed；用户后续可自行增删/启停）
# Reddit 类目前在国内网络环境下不可达（GFW 屏蔽 + 所有镜像同步屏蔽）；
# 用国内可访问的 AI 资讯源作为替代。
# 注意: 机器之心的 RSS URL 已失效（网站改版），已替换为 InfoQ 中文。
DEFAULT_NEWS_SOURCES: List[tuple] = [
    # 学术
    ("arXiv CS.AI", "http://export.arxiv.org/rss/cs.AI", "rss", "research"),
    ("arXiv CS.CL", "http://export.arxiv.org/rss/cs.CL", "rss", "research"),
    # 海外社区
    ("Hacker News", "https://hacker-news.firebaseio.com/v0/topstories.json", "api", "tech"),
    # 国内 AI/技术资讯站（替代 Reddit）
    ("量子位", "https://www.qbitai.com/feed", "rss", "media-cn"),
    ("36氪", "https://36kr.com/feed", "rss", "media-cn"),
    ("InfoQ中文", "https://www.infoq.cn/feed.xml", "rss", "media-cn"),
    # Reddit 类（当前网络不可达，仅作占位；用户有代理时可启用）
    ("Reddit r/MachineLearning",
     "https://www.reddit.com/r/MachineLearning/top.rss?t=day", "rss", "reddit"),
    ("Reddit r/LocalLLaMA",
     "https://www.reddit.com/r/LocalLLaMA/top.rss?t=day", "rss", "reddit"),
]


def _ensure_default_news_sources():
    """首次启动时 seed 默认资讯源（用户后续可自行增删/启停）"""
    with get_db() as db:
        count = db.execute(text("SELECT COUNT(*) FROM news_sources")).fetchone()[0]
        if count == 0:
            for name, url, source_type, category in DEFAULT_NEWS_SOURCES:
                try:
                    db.execute(text(
                        "INSERT INTO news_sources (name, url, source_type, category, is_active) "
                        "VALUES (:n, :u, :st, :c, 1)"
                    ), {"n": name, "u": url, "st": source_type, "c": category})
                except Exception as e:
                    logger.warning(f"seed 资讯源 '{name}' 失败: {e}")
            logger.info(f"已 seed {len(DEFAULT_NEWS_SOURCES)} 个默认资讯源")


# ========== 用户相关操作 ==========

def register_user(username: str, password: str, role: str = "individual") -> Optional[Dict[str, Any]]:
    """注册用户"""
    with get_db() as db:
        existing = db.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).fetchone()
        if existing:
            return None
        db.execute(text(
            "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (:u, :p, :r, :now, :now)"
        ), {"u": username, "p": hash_password(password), "r": role, "now": datetime.now()})
        db.commit()
        user = db.execute(text("SELECT id, username, role, created_at FROM users WHERE username = :u"), {"u": username}).fetchone()
        return dict(user._mapping) if user else None


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """验证用户登录"""
    with get_db() as db:
        user = db.execute(text(
            "SELECT id, username, password_hash, role, is_active FROM users WHERE username = :u"
        ), {"u": username}).fetchone()
        if not user:
            return None
        user_dict = dict(user._mapping)
        if not user_dict.get("is_active"):
            return None
        if not verify_password(password, user_dict["password_hash"]):
            return None
        # 更新最后登录时间
        db.execute(text("UPDATE users SET last_login = :now WHERE id = :id"), {
            "now": datetime.now(), "id": user_dict["id"]
        })
        return {
            "id": user_dict["id"],
            "username": user_dict["username"],
            "role": user_dict["role"]
        }


def create_session(user_id: int) -> str:
    """创建会话"""
    token = create_session_token()
    expires = datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)
    with get_db() as db:
        db.execute(text(
            "INSERT INTO sessions (session_token, user_id, expires_at) VALUES (:t, :uid, :exp)"
        ), {"t": token, "uid": user_id, "exp": expires})
    return token


def validate_session(token: str) -> Optional[Dict[str, Any]]:
    """验证会话token"""
    if not token:
        return None
    with get_db() as db:
        row = db.execute(text("""
            SELECT u.id, u.username, u.role, s.expires_at 
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.session_token = :t AND s.expires_at > :now AND u.is_active = 1
        """), {"t": token, "now": datetime.now()}).fetchone()
        return dict(row._mapping) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    """获取所有用户"""
    with get_db() as db:
        rows = db.execute(text("""
            SELECT id, username, role, is_active, created_at, last_login 
            FROM users ORDER BY created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


def update_user_role(user_id: int, role: str) -> bool:
    """更新用户角色"""
    with get_db() as db:
        result = db.execute(text("UPDATE users SET role = :r, updated_at = :now WHERE id = :id"), {
            "r": role, "now": datetime.now(), "id": user_id
        })
        return result.rowcount > 0


# ========== 审核队列操作 ==========

def get_pending_reviews(limit: int = 50) -> List[Dict[str, Any]]:
    """获取待审核列表"""
    with get_db() as db:
        rows = db.execute(text("""
            SELECT id, title, translated_title, summary, url, source, relevance_score, created_at, status
            FROM review_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]


def get_review_stats() -> Dict[str, Any]:
    """获取审核统计"""
    with get_db() as db:
        pending = db.execute(text("SELECT COUNT(*) as cnt FROM review_queue WHERE status='pending'")).fetchone()[0]
        approved = db.execute(text("SELECT COUNT(*) as cnt FROM review_queue WHERE status='approved'")).fetchone()[0]
        rejected = db.execute(text("SELECT COUNT(*) as cnt FROM review_queue WHERE status='rejected'")).fetchone()[0]
        today = date.today()
        today_total = db.execute(text("SELECT COUNT(*) as cnt FROM review_queue WHERE DATE(created_at) = :d"), {"d": today}).fetchone()[0]
        return {
            "pending": pending, "approved": approved, "rejected": rejected,
            "total": pending + approved + rejected, "today_total": today_total
        }


def review_action(review_id: int, action: str, comment: str, reviewer_id: int) -> bool:
    """审核操作"""
    status = "approved" if action == "approve" else "rejected"
    with get_db() as db:
        # 先检查是否已审核
        existing = db.execute(text("SELECT status FROM review_queue WHERE id = :id"), {"id": review_id}).fetchone()
        if not existing or existing[0] != "pending":
            return False
        db.execute(text("""
            UPDATE review_queue SET status = :s, review_comment = :c, reviewer_id = :rid, reviewed_at = :now
            WHERE id = :id
        """), {"s": status, "c": comment, "rid": reviewer_id, "now": datetime.now(), "id": review_id})

        # 审核通过 → 写入待发池，下次早报作为"历史审核通过资讯"收录（完成人工复核闭环）
        if status == "approved":
            row = db.execute(text(
                "SELECT title, url, source, summary FROM review_queue WHERE id = :id"
            ), {"id": review_id}).fetchone()
            if row and row[1]:
                existing_news = db.execute(
                    text("SELECT id FROM news_pool WHERE url = :u"), {"u": row[1]}).fetchone()
                if not existing_news:
                    db.execute(text("""
                        INSERT INTO news_pool (title, summary, url, source, news_date, relevance_score, created_at)
                        VALUES (:title, :summary, :url, :source, :news_date, 0.5, :now)
                    """), {
                        "title": row[0], "summary": row[3] or "", "url": row[1],
                        "source": row[2] or "", "news_date": date.today().isoformat(),
                        "now": datetime.now(),
                    })
        return True


# ========== 敏感词操作 ==========

def get_sensitive_words() -> List[Dict[str, Any]]:
    """获取敏感词列表"""
    with get_db() as db:
        rows = db.execute(text("SELECT id, word, category, is_active, created_at FROM sensitive_words ORDER BY created_at DESC")).fetchall()
        return [dict(r._mapping) for r in rows]


def add_sensitive_word(word: str, category: str = "general") -> bool:
    """添加敏感词"""
    try:
        with get_db() as db:
            db.execute(text("INSERT INTO sensitive_words (word, category) VALUES (:w, :c)"), {"w": word, "c": category})
        return True
    except Exception:
        return False


def delete_sensitive_word(word_id: int) -> bool:
    """删除敏感词"""
    with get_db() as db:
        result = db.execute(text("DELETE FROM sensitive_words WHERE id = :id"), {"id": word_id})
        return result.rowcount > 0


# ========== 资讯源操作 ==========

def get_news_sources() -> List[Dict[str, Any]]:
    """获取资讯源列表"""
    with get_db() as db:
        rows = db.execute(text("""
            SELECT id, name, url, source_type, category, weight, is_active, last_fetched 
            FROM news_sources ORDER BY created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


def add_news_source(name: str, url: str, source_type: str = "rss", category: str = "general") -> bool:
    """添加资讯源"""
    try:
        with get_db() as db:
            db.execute(text("""
                INSERT INTO news_sources (name, url, source_type, category) VALUES (:n, :u, :t, :c)
            """), {"n": name, "u": url, "t": source_type, "c": category})
        return True
    except Exception:
        return False


def toggle_news_source(source_id: int) -> bool:
    """切换资讯源启用状态"""
    with get_db() as db:
        row = db.execute(text("SELECT is_active FROM news_sources WHERE id = :id"), {"id": source_id}).fetchone()
        if not row:
            return False
        new_state = 0 if row[0] else 1
        db.execute(text("UPDATE news_sources SET is_active = :s, updated_at = :now WHERE id = :id"), {
            "s": new_state, "now": datetime.now(), "id": source_id
        })
        return True


def delete_news_source(source_id: int) -> bool:
    """删除资讯源"""
    with get_db() as db:
        result = db.execute(text("DELETE FROM news_sources WHERE id = :id"), {"id": source_id})
        return result.rowcount > 0


# ========== 早报/资讯操作 ==========

def get_news_pool(limit: int = 100, news_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取资讯池"""
    with get_db() as db:
        if news_date:
            rows = db.execute(text("""
                SELECT id, title, translated_title, summary, url, source, relevance_score, news_date, created_at
                FROM news_pool WHERE news_date = :d ORDER BY relevance_score DESC, created_at DESC LIMIT :lim
            """), {"d": news_date, "lim": limit}).fetchall()
        else:
            rows = db.execute(text("""
                SELECT id, title, translated_title, summary, url, source, relevance_score, news_date, created_at
                FROM news_pool ORDER BY news_date DESC, relevance_score DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]


def insert_news_pool(item: Dict[str, Any]) -> int:
    """插入一条新闻到新闻池，若URL已存在则跳过。返回新记录ID或已存在的ID"""
    with get_db() as db:
        url = item.get("url", "").strip()
        if url:
            existing = db.execute(text("SELECT id FROM news_pool WHERE url = :u"), {"u": url}).fetchone()
            if existing:
                return int(existing[0])
        title = item.get("title", "")
        source = item.get("source", "")
        summary = item.get("summary", "")
        news_date = item.get("news_date") or date.today().isoformat()
        result = db.execute(text("""
            INSERT INTO news_pool (title, summary, url, source, news_date, relevance_score, created_at)
            VALUES (:title, :summary, :url, :source, :news_date, :score, :now)
        """), {
            "title": title, "summary": summary, "url": url, "source": source,
            "news_date": news_date, "score": float(item.get("relevance_score") or 0.5),
            "now": datetime.now()
        })
        return int(result.lastrowid or 0)


def insert_review_queue(news_id: int, item_type: str, content_snapshot: Dict[str, Any],
                        trigger_reason: str = "") -> int:
    """插入审核队列（使用现有 SQLite schema 列）"""
    with get_db() as db:
        url: str = str(content_snapshot.get("news_url", "") or content_snapshot.get("url", ""))
        if url:
            existing = db.execute(text(
                "SELECT id FROM review_queue WHERE url = :u AND status = 'pending' LIMIT 1"
            ), {"u": url}).fetchone()
            if existing:
                return int(existing[0])
        result = db.execute(text("""
            INSERT INTO review_queue (title, url, source, summary, status, fact_check_result, created_at)
            VALUES (:title, :url, :source, :summary, 'pending', :snapshot, :now)
        """), {
            "title": str(content_snapshot.get("title", ""))[:500] or "(无标题)",
            "url": url,
            "source": str(content_snapshot.get("site_name", "") or content_snapshot.get("source", ""))[:200],
            "summary": str(content_snapshot.get("audit_reason", trigger_reason or ""))[:2000],
            "snapshot": json.dumps(content_snapshot, ensure_ascii=False),
            "now": datetime.now(),
        })
        return int(result.lastrowid or 0)


def get_review_queue_by_url(url: str) -> Optional[Dict[str, Any]]:
    """根据URL查询审核队列中对应的新闻"""
    if not url:
        return None
    with get_db() as db:
        row = db.execute(text(
            "SELECT * FROM review_queue WHERE url = :u AND status = 'pending' LIMIT 1"
        ), {"u": url}).fetchone()
        return dict(row._mapping) if row else None


def news_pool_mark_pushed(news_ids) -> None:
    """标记新闻已推送到早报（接受单个 int 或 int 列表）"""
    if isinstance(news_ids, (int, str)):
        news_ids = [news_ids]
    if not news_ids:
        return
    with get_db() as db:
        db.execute(
            text("UPDATE news_pool SET is_pushed = 1 WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(news_ids)},
        )


def get_available_dates() -> List[str]:
    """获取可查询的早报日期"""
    with get_db() as db:
        rows = db.execute(text("""
            SELECT DISTINCT news_date FROM news_pool ORDER BY news_date DESC LIMIT 30
        """)).fetchall()
        return [str(r[0]) for r in rows]


def get_dashboard_stats() -> Dict[str, Any]:
    """获取看板统计"""
    with get_db() as db:
        total_news = db.execute(text("SELECT COUNT(*) FROM news_pool")).fetchone()[0]
        total_reviews = db.execute(text("SELECT COUNT(*) FROM review_queue")).fetchone()[0]
        total_users = db.execute(text("SELECT COUNT(*) FROM users WHERE is_active = 1")).fetchone()[0]
        total_sources = db.execute(text("SELECT COUNT(*) FROM news_sources WHERE is_active = 1")).fetchone()[0]
        today = date.today()
        today_news = db.execute(text("SELECT COUNT(*) FROM news_pool WHERE news_date = :d"), {"d": today}).fetchone()[0]
        return {
            "total_news": total_news,
            "total_reviews": total_reviews,
            "total_users": total_users,
            "total_sources": total_sources,
            "today_news": today_news
        }


# ========== 论文任务操作 ==========

def create_paper_task(user_id: int, username: str, title: str, filename: str, paper_path: str) -> int:
    """创建论文分析任务"""
    with get_db() as db:
        result = db.execute(text("""
            INSERT INTO paper_tasks (user_id, username, title, original_filename, paper_path, status, progress, progress_msg, created_at, updated_at)
            VALUES (:uid, :un, :t, :fn, :pp, 'pending', 0, '等待处理', :now, :now)
            RETURNING id
        """), {"uid": user_id, "un": username, "t": title, "fn": filename, "pp": paper_path,
               "now": datetime.now()})
        task_id = result.fetchone()[0]
        db.commit()
        return task_id


def get_paper_tasks(user_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """获取论文任务列表"""
    with get_db() as db:
        if user_id:
            rows = db.execute(text("""
                SELECT id, title, original_filename, status, progress, progress_msg,
                       analysis_result, report_path, error_msg, created_at, completed_at
                FROM paper_tasks WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim
            """), {"uid": user_id, "lim": limit}).fetchall()
        else:
            # 超级管理员视图：也读 report_path（之前漏了，导致 download 按钮不显示）
            rows = db.execute(text("""
                SELECT id, user_id, username, title, original_filename, status, progress, progress_msg,
                       report_path, error_msg, created_at, completed_at
                FROM paper_tasks ORDER BY created_at DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        tasks = []
        for r in rows:
            t = dict(r._mapping)
            # 将 report_path 转为下载 URL（与 main.py @app.get("/files/{file_type}/{filename}") 一致）
            if t.get("report_path"):
                fname = os.path.basename(t["report_path"])
                t["report_url"] = f"/files/reports/{fname}"
            tasks.append(t)
        return tasks


def get_paper_task(task_id: int) -> Optional[Dict[str, Any]]:
    """获取单个论文任务"""
    with get_db() as db:
        row = db.execute(text("SELECT * FROM paper_tasks WHERE id = :id"), {"id": task_id}).fetchone()
        return dict(row._mapping) if row else None


def update_paper_task(task_id: int, **kwargs) -> bool:
    """更新论文任务"""
    if not kwargs:
        return False
    allowed_fields = {"status", "progress", "progress_msg", "analysis_result", "report_path", "error_msg", "completed_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return False
    updates["updated_at"] = datetime.now()
    
    set_clause = ", ".join([f"{k} = :{k}" for k in updates])
    updates["id"] = task_id
    
    with get_db() as db:
        db.execute(text(f"UPDATE paper_tasks SET {set_clause} WHERE id = :id"), updates)
        return True


def get_pending_paper_task() -> Optional[Dict[str, Any]]:
    """获取一个待处理的论文任务（scheduler轮询用）"""
    with get_db() as db:
        row = db.execute(text("""
            SELECT * FROM paper_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1
        """)).fetchone()
        return dict(row._mapping) if row else None
