## 项目概述
- **名称**: AI先知情报智能体 (AI Prophet Intelligence Agent)
- **功能**: 自动化AI情报采集+论文精析系统，支持Docker一键部署

## 系统架构
```
┌─────────────────────────────────────────┐
│             Docker Compose              │
│                                         │
│  ┌──────────┐  /api/*  ┌─────────────┐  │
│  │  Nginx   │─────────▶│   FastAPI   │  │
│  │ (前端)   │◀─────────│  (后端API)  │  │
│  │ :80      │ 静态文件 │  :8000      │  │
│  └──────────┘          └──────┬──────┘  │
│                               │         │
│                        ┌──────▼──────┐  │
│                        │ PostgreSQL  │  │
│                        │   :5432     │  │
│                        └─────────────┘  │
│                                         │
│  数据卷: ./data (论文、报告、数据库文件)   │
└─────────────────────────────────────────┘
```

### 节点清单
| 节点名 | 文件位置 | 类型 | 功能描述 |
|-------|---------|------|---------|
| news_collect_node | `graphs/nodes/news_collect_node.py` | task | RSS/API/WebSearch多通道资讯采集 |
| news_dedup_node | `graphs/nodes/news_dedup_node.py` | task | URL精确去重+标题相似度去重 |
| news_filter_node | `graphs/nodes/news_filter_node.py` | agent | LLM智能筛选排序 |
| news_translate_node | `graphs/nodes/news_translate_node.py` | agent | 英文标题翻译为中文 |
| sensitive_check_node | `graphs/nodes/sensitive_check_node.py` | task | 敏感词规则检测 |
| fact_check_node | `graphs/nodes/fact_check_node.py` | agent | LLM事实核查+审核分流 |
| daily_report_gen_node | `graphs/nodes/daily_report_gen_node.py` | task | DOCX早报生成 |
| paper_parse_node | `graphs/nodes/paper_parse_node.py` | task | PDF论文文本提取 |
| paper_analysis_node | `graphs/nodes/paper_analysis_node.py` | agent | LLM论文结构化分析 |
| paper_report_gen_node | `graphs/nodes/paper_report_gen_node.py` | task | DOCX论文报告生成 |
| wechat_receive_node | `graphs/nodes/wechat_receive_node.py` | task | 企微消息解析/路由 |
| wechat_push_node | `graphs/nodes/wechat_push_node.py` | task | 企微群推送（可跳过） |
| review_notify_node | `graphs/nodes/review_notify_node.py` | task | 审核通知 |
| review_process_node | `graphs/nodes/review_process_node.py` | task | 审核处理 |
| review_interact_node | `graphs/nodes/review_interact_node.py` | task | 审核交互 |
| ops_monitor_node | `graphs/nodes/ops_monitor_node.py` | task | 运维监控 |

## 关键文件说明
| 文件 | 说明 |
|------|------|
| `src/main.py` | FastAPI后端，所有API路由（认证/审核/管理/论文/文件下载） |
| `src/database.py` | PostgreSQL数据库层（SQLAlchemy Core），自动建表+初始管理员 |
| `src/scheduler.py` | 定时调度器：每日早报9:00 + 每60分钟采集 + 论文任务轮询 |
| `src/auth.py` | 认证模块（Session Cookie） |
| `static/login.html` | 登录/注册页（零CDN，原生JS） |
| `static/index.html` | 主看板SPA（零CDN，原生JS） |
| `static/app.js` | 前端逻辑（API调用/进度条/数据展示） |
| `Dockerfile` | 后端Python镜像构建 |
| `docker-compose.yml` | 三容器编排：nginx + api + postgres |
| `nginx.conf` | Nginx反向代理配置 |
| `init-db.sql` | PostgreSQL初始化（HSTORE扩展等） |
| `.env.example` | 环境变量模板 |
| `config/*.json` | LLM节点配置文件 |

## 部署方式

### Windows本地/服务器部署
```bash
# 1. 复制环境变量文件
cp .env.example .env
# 编辑 .env 设置必要参数

# 2. 启动所有服务
docker-compose up -d

# 3. 访问
http://localhost/login.html
# 默认账号: admin / admin123
```

### 数据持久化
- 数据库: `./data/postgres/`
- 上传论文: `./data/papers/`
- 生成报告: `./data/reports/`
- 备份: 打包 `./data/` 目录即可

## API列表
- `POST /api/auth/login` - 登录
- `POST /api/auth/register` - 注册
- `POST /api/auth/logout` - 登出
- `GET /api/auth/me` - 获取当前用户
- `GET /api/dashboard/stats` - 看板统计
- `GET/POST/DELETE /api/reviews` - 审核管理
- `GET/POST/DELETE /api/sensitive-words` - 敏感词管理
- `GET/POST/DELETE /api/news-sources` - 资讯源管理
- `GET/POST /api/users` - 用户管理
- `POST /api/papers/upload` - 论文上传
- `GET /api/papers/tasks` - 论文任务列表
- `GET /api/files/{type}/{filename}` - 文件下载