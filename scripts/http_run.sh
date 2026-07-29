#!/bin/bash

set -e
# 导出环境变量

WORK_DIR="${COZE_WORKSPACE_PATH:-.}"
PORT="${DEPLOY_RUN_PORT:-5000}"

usage() {
  echo "用法: $0 -p <端口>"
}

while getopts "p:h" opt; do
  case "$opt" in
    p)
      PORT="$OPTARG"
      ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "无效选项: -$OPTARG"
      usage
      exit 1
      ;;
  esac
done

# 导出环境变量（优先使用系统环境变量，未设置时使用默认值）
export WECHAT_WEBHOOK_URL="${WECHAT_WEBHOOK_URL:-https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b15d6623-f7e6-43de-ab6e-3d1181b0122c}"
export REVIEW_WEBHOOK_URL="${REVIEW_WEBHOOK_URL:-https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=69a4158a-1654-4612-ac4c-95cd6164f4f9}"

# 激活 .venv（devbox 环境），deploy 无 .venv 则跳过
if [ -f "${WORK_DIR}/.venv/bin/activate" ]; then
  source "${WORK_DIR}/.venv/bin/activate"
fi

python ${WORK_DIR}/src/main.py -m http -p $PORT
