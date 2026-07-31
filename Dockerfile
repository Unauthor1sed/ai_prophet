# ============================================================
# AI先知情报智能体 - 单容器镜像（FastAPI + SQLite + 静态前端）
# 构建说明：
#   1. 请先在 Docker Desktop -> Settings -> Docker Engine 中
#      配置 registry-mirrors 镜像加速器（见 DEPLOY.md）
#   2. FROM 使用官方镜像名 python:3.11-slim，Docker 会走加速器拉取
#   3. pip 走清华源，国内构建顺畅
# ============================================================
# 基础镜像可通过 --build-arg 覆盖（离线双架构构建时用：
#   amd64: --platform linux/amd64 --build-arg BASE_IMAGE=python-amd64:3.11-slim）
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

LABEL maintainer="AI Prophet"
LABEL description="AI先知情报智能体 - 单容器部署版（SQLite+FastAPI静态托管）"

# 工作目录
WORKDIR /app

# 环境变量：关闭 pyc、关闭缓冲、设置时区、配置清华 pip 源
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    TZ=Asia/Shanghai

# 设置时区（slim 镜像自带 tzdata 无需 apt）
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone || true

# 先复制 requirements.txt 利用 Docker 缓存层
COPY requirements.txt /app/requirements.txt

# 安装 Python 依赖
# --verbose 方便出错时看到是哪个包装不上
RUN pip install --verbose --upgrade pip setuptools wheel && \
    pip install --verbose -r /app/requirements.txt && \
    pip install --verbose uvicorn[standard] gunicorn

# 复制应用代码
COPY src/ /app/src/
COPY static/ /app/static/
COPY config/ /app/config/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh

# 启动脚本权限 + 数据目录
RUN chmod +x /app/docker-entrypoint.sh && \
    mkdir -p /data/papers /data/reports

# 端口
EXPOSE 8000

# 数据卷
VOLUME ["/data"]

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3); \
        print('ok')" || exit 1

# 入口
ENTRYPOINT ["/app/docker-entrypoint.sh"]
