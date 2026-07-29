#!/bin/bash
set -e

echo "======================================"
echo "  AI Prophet Intelligence Agent"
echo "======================================"

export PYTHONPATH=/app/src:$PYTHONPATH

# 确保数据目录存在
mkdir -p "${DATA_DIR:-/data}/papers" "${DATA_DIR:-/data}/reports"

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
