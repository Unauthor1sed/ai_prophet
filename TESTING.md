# AI先知情报智能体 - 完整测试流程

> 测试口径：全新安装（删除全部镜像 → docker load → docker compose up -d），
> 然后按模块过一遍前端功能。每项后面的【预期】就是通过标准，测完在表格里记录结果。

## 第零步：全新安装

在终端整块执行：

```bash
docker rm -f ai-prophet 2>/dev/null
docker rmi -f ai-prophet:latest ai_prophet-api:latest
docker images | grep prophet || echo "== 镜像已删干净 =="
docker load -i ~/Desktop/ai-prophet-deploy/images.tar
cd ~/Desktop/ai-prophet-deploy
docker compose up -d
sleep 25
echo "== 健康检查 ==" && curl -s http://localhost:8080/api/health && echo
echo "== 容器内DNS ==" && docker exec ai-prophet python3 -c "import socket; print('DNS OK:', socket.gethostbyname('api.deepseek.com'))"
echo "== 容器健康状态 ==" && docker inspect ai-prophet --format '{{.State.Health.Status}}'
```

【预期】依次输出 `{"status":"ok",...}`、`DNS OK: ...`、`healthy`。

> 想彻底从零测（连历史数据都清掉），在 `docker compose up -d` 前多执行一步：
> `rm -rf ~/Desktop/ai-prophet-deploy/data`（会重建数据库，之前采集的资讯/账号会清空）。

---

## 第一步：登录与账号（前端）

浏览器打开 http://localhost:8080/

| # | 操作 | 预期 |
|---|------|------|
| 1.1 | 打开首页 | 显示登录页 |
| 1.2 | 错误密码登录 admin / 123456 | 提示用户名或密码错误 |
| 1.3 | 正确登录 admin / admin123 | 进入控制台，右上角显示 admin（超级管理员） |
| 1.4 | 注册一个新用户（如 test01 / test123456）并登录 | 注册成功，登录后只能看到看板和论文精析（个人用户权限） |
| 1.5 | 退出登录 | 回到登录页，直接访问控制台被拦截 |

## 第二步：数据看板 + 手动触发采集

用 admin 登录：

| # | 操作 | 预期 |
|---|------|------|
| 2.1 | 查看数据看板 | 显示早报/论文统计数字，不报错 |
| 2.2 | 点「手动触发增量采集」 | 提示已加入后台队列 |
| 2.3 | 等约 1-2 分钟后刷新「每日早报/资讯」 | 出现新采集的资讯，**中文标题+摘要** |

同时在终端看流水线日志：

```bash
docker logs ai-prophet --since 5m 2>&1 | grep -E "采集|筛选|筛除|翻译|推送|告警"
```

【预期】能看到：`资讯采集完成，共获取 N 条`（多个源）→ `筛除 [标题] 原因: xxx`（逐条筛除原因）→ `资讯筛选完成：N → M 条（阈值 0.6，筛除 X 条，原因已保留）` → `翻译完成` → `企微消息推送成功`。

筛除原因留档文件：

```bash
docker exec ai-prophet sh -c 'head -5 /data/reports/filter_excluded_*.jsonl'
```

【预期】每行一条 JSON，含 title / relevance_score / reason。

## 第三步：企业微信推送

| # | 操作 | 预期 |
|---|------|------|
| 3.1 | 触发采集后查看配置的企微群 | 收到早报卡片消息（标题+摘要+链接） |

## 第四步：论文精析

准备一份英文论文 PDF（可用命令下载经典论文）：

```bash
curl -sL -o ~/Desktop/attention.pdf https://arxiv.org/pdf/1706.03762 && ls -lh ~/Desktop/attention.pdf
```

| # | 操作 | 预期 |
|---|------|------|
| 4.1 | 前端「论文精析」上传该 PDF | 创建任务，出现进度条 |
| 4.2 | 等待 2-5 分钟（看 LLM 速度） | 进度推进：解析中 → 分析中 → 完成 |
| 4.3 | 任务完成后点下载 | 下载 DOCX，打开后是固定章节的中文解读（研究方法/创新点/落地价值），术语附英文 |
| 4.4 | 上传一个非 PDF 文件 | 前端/接口拒绝，提示请上传 PDF |

## 第五步：内容审核（审核台）

| # | 操作 | 预期 |
|---|------|------|
| 5.1 | 「敏感词库」添加一个测试词（选一个大概率出现在资讯里的词，如 "AI"，测完删掉） | 添加成功，列表可见 |
| 5.2 | 再触发一次增量采集 | 命中敏感词的内容进入审核队列 |
| 5.3 | 打开审核台 | 待审条目显示命中词和**命中位置** |
| 5.4 | 对一条执行「通过」、另一条执行「驳回」 | 状态变化正确，驳回的不进早报 |
| 5.5 | 删除测试敏感词 | 列表移除 |

## 第六步：资讯源管理

| # | 操作 | 预期 |
|---|------|------|
| 6.1 | 查看资讯源列表 | 显示默认的 8 个源 |
| 6.2 | 新增一个 RSS 源（如 `https://www.jiqizhixin.com/rss`） | 添加成功 |
| 6.3 | 停用某个源后触发采集 | 日志中该源不再出现 |
| 6.4 | 恢复启用 + 删除测试源 | 状态正确 |

## 第七步：用户管理与权限（超管）

| # | 操作 | 预期 |
|---|------|------|
| 7.1 | 用户管理中把 test01 角色改为 reviewer | test01 重新登录后能看到审核台 |
| 7.2 | 尝试修改自己的角色 | 被拒绝（不能修改自己的角色） |
| 7.3 | 用 test01（reviewer）访问用户管理接口 | 403 权限不足 |

## 第八步：稳定性

| # | 操作 | 预期 |
|---|------|------|
| 8.1 | `docker compose restart` 后刷新页面 | 服务恢复，登录态/数据都在 |
| 8.2 | `docker compose down && docker compose up -d` | 数据不丢（早报、论文任务还在） |
| 8.3 | `docker logs ai-prophet 2>&1 \| grep 自检` | 显示「网络自检: DNS 解析正常」 |

---

## 测试记录表

| 模块 | 结果(✓/✗) | 备注 |
|------|-----------|------|
| 全新安装（load+up） | | |
| 登录/注册/权限 | | |
| 看板+手动触发 | | |
| 采集→筛选(打分/筛除原因)→翻译 | | |
| 早报生成+企微推送 | | |
| 论文精析全流程 | | |
| 敏感词+审核台闭环 | | |
| 资讯源管理 | | |
| 用户管理 | | |
| 重启/数据持久化 | | |

## 全部通过后：提交并推送到 fork

```bash
cd ~/Desktop/ai_prophet
git add -A
git commit -m "fix(deploy): Docker容器DNS修复+离线交付包; feat: 筛选打分阈值/推送重试告警/采集重试"
git push -u fork fix/runtime-bugs-2026-07
```
