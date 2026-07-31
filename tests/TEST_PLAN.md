# AI先知 - 全需求测试方案

三层测试，按顺序执行：

| 层 | 工具 | 覆盖 | 耗时 |
|----|------|------|------|
| ① API 全需求回归 | `tests/full_regression.py` | 所有后端验收点（按需求ID输出矩阵） | ~4分钟（`--full` 论文完整验证 ~8分钟） |
| ② 前端 UI 自动点击 | `tests/ui_click_test.py`（Playwright机器人） | 页面交互、表单校验、点击流，每步截图 | ~2分钟 |
| ③ 人工抽查 | 浏览器 + 企微群 | 机器无法替代的观感/收信确认 | ~10分钟 |

## 运行方式

```bash
# 前置：应用已启动（docker compose up -d，healthy）

# ① API 回归（无额外依赖）
python3 tests/full_regression.py            # 快速模式
python3 tests/full_regression.py --full     # 含论文分析完整等待

# ② UI 点击测试（首次需装 Playwright，见下）
python3 tests/ui_click_test.py              # 无头运行
HEADED=1 python3 tests/ui_click_test.py     # 弹窗观看机器人点击

# 测远程服务器
BASE_URL=http://服务器IP:8080 python3 tests/full_regression.py
```

**Playwright 首次安装**（国内镜像）：
```bash
python3 -m pip install --user playwright==1.57.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
```
浏览器二选一：
- 机器上已装 **Google Chrome**（https://www.google.cn/chrome/ 可直连下载）→ 无需其他操作，脚本自动驱动它；
- 没有 Chrome → 下载 Playwright 内置 Chromium：
  ```bash
  PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright python3 -m playwright install chromium --no-shell
  ```

> UI 点击测试就是"机器人做前端测试"：Playwright 驱动真实 Chromium 浏览器，
> 像人一样填表单、点按钮、断言页面变化，失败时有截图（tests/screenshots/）可回溯。

## 需求覆盖矩阵

| 需求ID | 需求 | ①API | ②UI | ③人工 |
|--------|------|------|-----|-------|
| 1000072/1000073 | 资讯源订阅、定时采集与增量 | 触发采集→task_runs有数据 | — | 日志看8源采集条数 |
| 1000074 | 智能筛选与排序（打分/阈值/筛除原因） | 入选≤采集；筛除文件 | — | `docker exec ai-prophet head /data/reports/filter_excluded_*.jsonl` |
| 1000082 | 摘要与关键词（三段式100字+3-5词） | 资讯summary含"关键词:" | — | 看板资讯页读摘要质量 |
| 1000084 | 去重聚合（V1基础去重） | 覆盖于采集链路 | — | 日志"去重完成：N→M" |
| 1000092/1000110 | 敏感词维护/拦截规则（增删改+导入+模板） | 全覆盖 | 添加/导入/删除点击 | — |
| 1000094/1000095 | 资讯源增删改启停+连通性测试 | 全覆盖 | 列表/测试按钮点击 | — |
| 1000096/1000091 | 早报生成与定时推送（可配置） | task_runs+触发 | — | 企微主群收到早报卡；改`DAILY_REPORT_TIME`验证 |
| 1000097 | 单篇论文深度解析 | 非PDF拦截+上传+（--full完成/下载） | 选文件反馈+提交+任务出现 | 打开DOCX看章节质量 |
| 1000099 | 历史资讯检索（V1日期过滤） | /api/news/dates | 历史早报页 | — |
| 1000101/1000103 | 敏感拦截/有害预检（三级分类） | 分类统计接口 | — | 加敏感词触发采集→审核台见命中词+位置 |
| 1000102 | 人工复核闭环（10字驳回+历史+写池） | 全覆盖 | 驳回校验+历史查询点击 | 企微审核群收到存疑卡片 |
| 1000106 | 基础事实校验（失败转待核实） | 接口在（LLM失败场景需断网模拟） | — | 断网/错Key启动→日志"全部转待核实" |
| 1000085 | 安全基线（bcrypt/下载鉴权/Cookie） | 401验证+Cookie | 退出登录后被拦 | — |
| 1000087 | 统一告警 | —（需故障注入） | — | 错误Key触发采集→审核群收到🚨告警卡 |
| 1000089 | 全流程执行日志 | 查询+过滤+成功率 | 看板执行记录板块 | — |
| 1000088 | 健康探测 | /api/health | — | — |
| 权限体系 | 角色隔离 | 401/403+改角色 | 登录/退出流 | — |
| 双架构部署 | amd64+arm64 | — | — | x86机器 `docker load && compose up` |

**延后至V1.1（不测）**：1000100 趋势周报、1000098 多篇对比、1000083 主题配置、1000076/1000086 用量成本。

## 人工抽查清单（③）

1. 触发一次「立即推送今日早报」→ **企微主群**收到早报卡片、**审核群**只收存疑告警
2. 添加必命中敏感词（如"模型"）→ 触发采集 → 审核台显示命中词与位置 → 测完删除
3. 打开下载的早报/论文 DOCX，检查排版与内容
4. 把 `.env` 的 `LLM_API_KEY` 改错重启 → 触发采集 → 审核群收到🚨告警 + 日志"全部转待核实" → 改回
5. x86 机器上完整走一遍 `docker load -i images.tar && docker compose up -d`
