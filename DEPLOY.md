# AI先知情报智能体 - 部署说明

## 一、系统架构（单容器版）

```
┌────────────────────────────────────────┐
│          Docker 容器（单容器）           │
│                                        │
│  FastAPI (:8000)                       │
│    ├── 静态前端（static/）              │
│    ├── API 接口（/api/*）               │
│    ├── 文件下载（/files/*）             │
│    └── 定时任务（APScheduler）          │
│                                        │
│  SQLite 文件数据库（/data/*.db）         │
│  文件存储（/data/papers、/data/reports） │
└────────────────────────────────────────┘
              ↓ 端口80（可改）
          浏览器访问
```

- **零外部依赖**：不需要 PostgreSQL、Nginx、Redis 等。
- **国内网络可直接构建**：使用阿里云 Docker 镜像 + 清华 PyPI 源。

---

## 二、准备工作

### 1. 安装 Docker Desktop（Windows）
下载地址：https://www.docker.com/products/docker-desktop/
安装完成后启动 Docker Desktop，确认 `docker -v` 和 `docker compose version` 可正常输出。

### 2. 获取 DeepSeek API Key（必须）
1. 打开 https://platform.deepseek.com/
2. 注册账号（新用户送 500 万 tokens 免费额度）
3. 进入「API Keys」页面，点击「创建 API Key」，复制保存。

> 如果要用其他模型（如豆包、Kimi、通义千问等兼容 OpenAI 协议的模型），只需修改 `.env` 中的 `LLM_BASE_URL` 和 `LLM_MODEL` 即可。

---

## 三、部署步骤

### 1. 解压项目文件
将项目文件解压到任意目录，例如 `D:\ai-prophet\`，确保目录下有 `Dockerfile`、`docker-compose.yml`、`.env.example`、`src/`、`static/` 等文件。

### 2. 创建配置文件
将 `.env.example` 复制为 `.env`：
- Windows PowerShell：`copy .env.example .env`
- CMD：`copy .env.example .env`
- Linux/Mac：`cp .env.example .env`

编辑 `.env` 文件，**必须修改**：
```env
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx   # 替换为你的 DeepSeek API Key
JWT_SECRET=改成一段随机字符串        # 建议用 openssl rand -hex 32 生成
```
其他配置通常保持默认即可。

### 3. 启动

**方式 A：离线镜像（推荐，交付包中含 `images.tar`）**

无需联网构建，直接导入镜像后启动：
```bash
docker load -i images.tar
docker compose up -d
```

**方式 B：本地构建**（需要能拉取 python:3.11-slim 基础镜像，约 3-5 分钟）：
```bash
docker compose up -d --build
```

启动成功后查看日志：
```bash
docker compose logs -f
```
看到 `Uvicorn running on http://0.0.0.0:8000` 和 `数据库初始化完成` 即成功。

### 4. 访问系统
浏览器打开：http://localhost:8080/（默认端口 8080，可在 `.env` 中用 `PORT` 修改）

**默认超级管理员账号**：
- 用户名：`admin`
- 密码：`admin123`

首次登录后请立刻进入"用户管理"修改密码。

### 5. 常用命令
```bash
docker compose ps          # 查看容器状态
docker compose logs -f     # 查看实时日志
docker compose restart     # 重启
docker compose down        # 停止并删除容器（数据在 ./data 中，不会丢）
docker compose pull        # 更新镜像（一般用不到）
```

---

## 四、数据持久化

所有数据都挂载在当前目录下的 `./data/` 文件夹中：
- `data/ai_prophet.db`：SQLite 数据库（用户、新闻、论文任务、审核记录等）
- `data/papers/`：上传的论文原文
- `data/reports/`：生成的早报/论文报告 DOCX 文件

**备份**：直接复制整个 `./data/` 目录即可。
**迁移**：把项目目录 + `./data/` 目录一起复制到新机器，重新 `docker compose up -d` 即可。

---

## 五、常见问题

### Q0: 容器启动后 LLM 调用 / 资讯采集 / 企微推送全部失败（域名解析失败）？
部分环境下（尤其 Docker Desktop 配置过代理、或宿主机 DNS 探测失败时），
compose 自定义网络的容器内置 DNS 没有上游服务器，容器内所有域名都无法解析。
本项目 `docker-compose.yml` 已通过给服务显式配置 `dns:`（223.5.5.5 等公共 DNS）修复。
容器启动日志里会打印「网络自检: DNS 解析正常」；若看到 DNS 失败警告：
1. 确认使用的是本项目自带的 `docker-compose.yml`（含 `dns:` 配置）；
2. 检查 Docker Desktop → Settings → Resources → Proxies 中是否配置了已失效的代理，如有请清除后重启 Docker。

### Q1: `docker compose up --build` 卡在拉取镜像？
本项目 Dockerfile 已使用阿里云镜像源 `registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim`，理论上国内直连。若仍卡住，请检查 Docker Desktop 的网络代理设置，或配置 Docker 镜像加速器：
在 Docker Desktop → Settings → Docker Engine 中添加：
```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
```
保存后重启 Docker Desktop。

### Q2: 大模型调用报 401/认证失败？
检查 `.env` 中的 `LLM_API_KEY` 是否正确、是否有余额。

### Q3: 如何修改对外端口？
修改 `.env` 中的 `PORT=80`，例如改成 `PORT=8080`，然后 `docker compose up -d`，访问 http://localhost:8080 。

### Q4: 如何推送到企业微信群？
在企业微信群里添加「群机器人」，复制 Webhook URL，填入 `.env` 的 `WECHAT_WEBHOOK_URL=` 即可。每日早报会自动推送到群里。

### Q5: 想切换到 PostgreSQL？
将 `.env` 中的 `DATABASE_URL` 改成 PostgreSQL 连接串即可（例如 `postgresql+psycopg2://user:pass@host:5432/db`），并确保容器能访问到数据库；默认内置 SQLite，一般无需切换。

---

## 六、功能模块

| 模块 | 说明 |
|------|------|
| 📊 数据看板 | 每日早报、论文精析数量统计 |
| 📰 每日早报 | 定时采集 AI 领域新闻，自动生成早报 DOCX 并推送企微 |
| 📄 论文精析 | 前端上传 PDF 论文，AI 深度分析并生成报告，支持进度条 |
| ✅ 审核台 | 审核员/管理员审核早报/论文报告（敏感词、事实核查） |
| ⚙️ 运维监控 | 监控系统运行状态、错误日志 |
| 👥 用户管理 | 管理员可添加/删除用户、修改角色 |

角色权限：
- `individual`（个人用户）：看板、论文上传与下载
- `reviewer`（审核员）：+审核台
- `admin`（管理员）：+用户管理、敏感词、新闻源管理
- `super_admin`（超级管理员）：所有权限 + 运维监控
