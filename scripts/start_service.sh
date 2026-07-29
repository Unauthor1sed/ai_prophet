#!/bin/bash
export WECHAT_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b15d6623-f7e6-43de-ab6e-3d1181b0122c"
export REVIEW_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=69a4158a-1654-4612-ac4c-95cd6164f4f9"
cd /workspace/projects
exec python src/main.py
