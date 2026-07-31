#!/bin/sh
set -e

echo "======================================"
echo "  AI Prophet Intelligence Agent"
echo "======================================"

export PYTHONPATH=/app/src:$PYTHONPATH

# 兼容旧配置文件字段名：WECHAT_REVIEW_URL -> REVIEW_WEBHOOK_URL（代码读取的是后者）
if [ -z "${REVIEW_WEBHOOK_URL:-}" ] && [ -n "${WECHAT_REVIEW_URL:-}" ]; then
    export REVIEW_WEBHOOK_URL="$WECHAT_REVIEW_URL"
fi

# 确保数据目录存在
mkdir -p "${DATA_DIR:-/data}/papers" "${DATA_DIR:-/data}/reports"

# 网络自检：DNS 解析失败时给出明确提示（不阻塞启动）
python - <<'PYEOF' || true
import socket
try:
    socket.gethostbyname("api.deepseek.com")
    print("网络自检: DNS 解析正常")
except Exception as e:
    print("=" * 50)
    print(f"警告: 容器内 DNS 解析失败({e})，LLM/资讯采集/企微推送将不可用。")
    print("请确认 docker-compose.yml 中 dns: 配置存在，或检查宿主机网络。")
    print("=" * 50)
PYEOF

echo "初始化数据库..."
cd /app
python -c "
import sys
sys.path.insert(0, 'src')
import database
database.init_db()
print('数据库初始化完成')
"

echo "启动服务 (容器内 0.0.0.0:8000)..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers ${API_WORKERS:-1} \
    --app-dir /app/src \
    --proxy-headers \
    --forwarded-allow-ips='*'
