# AI先知情报智能体

企业级 AI 情报系统：每日自动采集 AI 前沿资讯（arXiv/Hacker News/量子位/36氪等），
大模型打分筛选、翻译并生成三段式中文摘要，敏感词+事实校验三级审核后生成 Word 早报，
定时推送企业微信；支持上传英文论文生成通俗中文精析报告（DOCX）。

## 快速开始（Docker 部署）

```bash
# 离线镜像（images.tar 为 amd64+arm64 双架构包，x86/ARM 服务器均可用）
docker load -i images.tar
docker compose up -d
# 浏览器打开 http://localhost:8080  默认账号 admin / admin123（登录后请立即修改）
```

完整部署说明（配置项、数据备份、常见问题）见 [DEPLOY.md](DEPLOY.md)。

## 本地开发运行

```bash
bash scripts/local_run.sh -m flow            # 运行完整工作流
bash scripts/local_run.sh -m node -n 节点名   # 运行单个节点
bash scripts/http_run.sh -m http -p 5000     # 启动HTTP服务
```

## 测试

三层测试体系，脚本在 `tests/` 目录，详细方案与人工抽查清单见 [tests/TEST_PLAN.md](tests/TEST_PLAN.md)。

### ① API 全需求回归（39 项，无额外依赖）

```bash
python3 tests/full_regression.py                              # 快速模式，约4分钟
python3 tests/full_regression.py --full                       # 含论文LLM分析完整验证，约8分钟
BASE_URL=http://服务器IP:8080 python3 tests/full_regression.py  # 测远程部署
```

### ② 前端 UI 自动点击测试（Playwright 机器人，20 项）

真实浏览器加载页面、执行前端 JS、模拟用户逐页点击，每步截图存 `tests/screenshots/`。

**首次准备（仅一次）：**

```bash
# 1. 安装 Playwright（国内清华源）
python3 -m pip install --user playwright==1.57.0 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 浏览器（二选一）
#    a) 机器上已装 Google Chrome（https://www.google.cn/chrome/）→ 无需操作，脚本自动使用
#    b) 无 Chrome → 用国内镜像下载 Playwright 内置 Chromium：
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright python3 -m playwright install chromium --no-shell
```

**运行：**

```bash
python3 tests/ui_click_test.py               # 无头模式（CI/日常回归）
HEADED=1 python3 tests/ui_click_test.py      # 弹出浏览器窗口，观看机器人点击全程（演示用）
BASE_URL=http://服务器IP:8080 python3 tests/ui_click_test.py   # 测远程部署
```

> 前置条件：应用已启动且 `admin/admin123` 可登录（改过密码用 `ADMIN_PASS=新密码` 传入）。
> 测试用 PDF 缺失时会自动从 arXiv 下载。

### ③ 人工抽查（约10分钟）

机器无法替代的项：企微双群收信确认（早报卡→主群、存疑告警→审核群）、DOCX 排版观感、
故障注入告警（改错 LLM Key 后触发采集）、x86 实机安装。步骤见 [tests/TEST_PLAN.md](tests/TEST_PLAN.md)。

## 需求覆盖矩阵（测试 ↔ 需求ID）

| 需求ID | 需求 | ①API回归 | ②UI点击 | ③人工 |
|--------|------|:---:|:---:|:---:|
| 1000072/1000073 | 资讯源订阅、定时采集与增量同步 | ✅ | — | 日志抽查 |
| 1000074 | 资讯智能筛选与排序（打分/阈值/筛除原因留档） | ✅ | — | 筛除文件抽查 |
| 1000082 | 摘要与关键词（三段式约100字+3-5关键词） | ✅ | — | 摘要质量 |
| 1000084 | 重复内容识别（V1基础去重） | ✅(链路内) | — | 日志抽查 |
| 1000092/1000110 | 敏感词维护/拦截规则（增删改查+CSV/TXT导入+模板） | ✅ | ✅ | — |
| 1000094/1000095 | 资讯源增删改启停+保存前连通性测试 | ✅ | ✅ | — |
| 1000096/1000091 | 早报生成与定时推送（时间/星期/间隔可配置） | ✅ | — | 企微收信 |
| 1000097 | 单篇论文深度解析（非PDF拦截/上传/进度/DOCX下载） | ✅ | ✅ | 报告质量 |
| 1000099 | 历史资讯检索（V1按日期） | ✅ | ✅ | — |
| 1000101/1000103 | 敏感拦截/有害预检（三级分类） | ✅ | — | 命中词演示 |
| 1000102 | 人工复核闭环（≥10字驳回校验/审核历史/通过写入待发池） | ✅ | ✅ | 企微收信 |
| 1000106 | 基础事实校验（LLM失败转待核实不放行） | 接口级 | — | 故障注入 |
| 1000085 | 安全基线（bcrypt/下载鉴权/会话Cookie） | ✅ | ✅ | — |
| 1000087 | 统一告警（采集/LLM/推送异常→企微，去重窗口） | — | — | 故障注入 |
| 1000088 | 健康监测（健康检查/自检） | ✅ | — | — |
| 1000089 | 全流程执行日志（task_runs/成功率/过滤查询） | ✅ | ✅ | — |
| 权限体系 | 四级角色隔离（401/403/角色变更） | ✅ | ✅ | — |
| 部署 | 双架构镜像 amd64+arm64 离线安装 | — | — | x86实机 |

**延后至 V1.1（本版不实现不测试）**：1000100 技术趋势周报、1000098 多篇论文对比、
1000083 个人关注主题、1000076/1000086 用量成本统计。

## 功能模块与角色

| 模块 | 说明 |
|------|------|
| 📊 数据看板 | 统计、管理员手动触发、执行记录与当日成功率 |
| 📰 每日早报 | 工作日定时采集→筛选→翻译→审核→Word早报→企微推送 |
| 📄 论文精析 | 上传PDF，AI 生成固定章节中文解读 DOCX |
| ✅ 人工审核 | 存疑内容复核（通过/驳回）+ 审核历史查询 |
| 🔒 敏感词库 | 增删改查、CSV/TXT 批量导入、模板下载 |
| 📡 资讯源配置 | 增删改启停、保存前连通性测试 |
| 👥 用户管理 | individual / reviewer / admin / super_admin 四级角色 |
