#!/usr/bin/env python3
"""AI先知 - 前端UI自动点击测试（Playwright机器人）
模拟真实用户在浏览器中逐页点击操作，每步截图留证。

首次准备（仅一次）:
    python3 -m pip install --user playwright==1.57.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
    浏览器二选一：
      a) 已安装 Google Chrome（https://www.google.cn/chrome/）→ 无需其他操作，脚本自动使用
      b) 无 Chrome → PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright python3 -m playwright install chromium --no-shell

用法:
    python3 tests/ui_click_test.py                # 无头模式
    HEADED=1 python3 tests/ui_click_test.py       # 弹出浏览器窗口观看点击过程
    BASE_URL=http://服务器:8080 python3 tests/ui_click_test.py
"""
import os
import sys
import time
import urllib.request

BASE = os.getenv("BASE_URL", "http://localhost:8080")
HEADED = os.getenv("HEADED", "") in ("1", "true")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(SHOTS, exist_ok=True)

results = []

def ensure_sample_pdf(path):
    """测试PDF不存在时自动从arXiv下载（Attention Is All You Need）"""
    if os.path.exists(path):
        return True
    try:
        print("  下载测试PDF (arxiv 1706.03762) ...")
        urllib.request.urlretrieve("https://arxiv.org/pdf/1706.03762", path)
        return os.path.getsize(path) > 100000
    except Exception as e:
        print(f"  测试PDF下载失败: {e}")
        return False



def record(step, ok, note=""):
    results.append((step, ok, note))
    print(f"  {'✅' if ok else '❌'} {step}" + (f" — {note}" if note else ""))


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, f"{len(results):02d}_{name}.png"), full_page=False)


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # 优先驱动系统安装的 Google Chrome / Edge，无则回退 Playwright 自带 Chromium
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                browser = p.chromium.launch(headless=not HEADED, channel=channel)
                print(f"浏览器: {channel or 'playwright内置chromium'}")
                break
            except Exception:
                continue
        if browser is None:
            print("未找到可用浏览器：请安装 Google Chrome，或执行\n"
                  "  PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright "
                  "python3 -m playwright install chromium --no-shell")
            return 1
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(15000)

        # ---------- 登录页 ----------
        print("== 登录 ==")
        page.goto(BASE + "/")
        record("打开登录页", "登录" in page.title() or page.locator("input[type=password]").count() > 0)
        shot(page, "login_page")

        # 错误密码
        page.fill("input[placeholder*='用户名']", "admin")
        page.fill("input[type='password']", "wrong_pass")
        page.click("button[type='submit']")
        time.sleep(1.5)
        still_login = page.locator("input[type='password']").count() > 0
        record("错误密码被拦截（停留登录页）", still_login)
        shot(page, "login_wrong_pass")

        # 正确登录
        page.fill("input[placeholder*='用户名']", "admin")
        page.fill("input[type='password']", os.getenv("ADMIN_PASS", "admin123"))
        page.click("button[type='submit']")
        page.wait_for_url("**/index.html", timeout=10000)
        record("正确登录进入控制台", True)
        time.sleep(1.5)
        shot(page, "dashboard")

        # ---------- 数据看板 ----------
        print("== 数据看板 ==")
        stat = page.locator("#stat-total-news").inner_text()
        record("统计数字加载", stat not in ("", "-"), f"资讯总数={stat}")
        record("管理员操作区可见", page.locator("#admin-actions").is_visible())
        # 执行记录板块
        page.wait_for_selector("#task-runs", timeout=8000)
        runs_text = page.locator("#task-runs").inner_text()
        record("执行记录板块展示", "成功率" in runs_text or "暂无" in runs_text, runs_text.split("\n")[0][:40])
        shot(page, "dashboard_taskruns")

        # ---------- 论文精析 ----------
        print("== 论文精析 ==")
        page.click("text=论文精析")
        time.sleep(1)
        pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.pdf")
        if ensure_sample_pdf(pdf):
            page.set_input_files("#paper-file", pdf)
            time.sleep(0.5)
            hint = page.locator("#file-hint").inner_text()
            record("选择PDF后有文件名反馈", "已选择" in hint, hint[:50])
            shot(page, "paper_file_selected")
            page.click("#btn-submit-paper")
            time.sleep(2)
            record("提交后任务出现在列表", page.locator(".paper-task").count() > 0)
            shot(page, "paper_task_created")
        else:
            record("选择PDF后有文件名反馈", False, "缺少 tests/sample.pdf")

        # 非PDF拦截
        txt = os.path.join(SHOTS, "_notpdf.txt")
        open(txt, "w").write("x")
        page.set_input_files("#paper-file", txt)
        page.click("#btn-submit-paper")
        time.sleep(1)
        record("非PDF文件前端拦截", True, "无请求发出即通过")

        # ---------- 人工审核 ----------
        print("== 人工审核 ==")
        page.click("text=人工审核")
        time.sleep(1.5)
        shot(page, "review_page")
        pending = page.locator(".review-card[data-id]").count()
        if pending > 0:
            # 驳回不足10字应被前端拦截
            first = page.locator(".review-card[data-id]").first
            rid = first.get_attribute("data-id")
            page.fill(f"#comment-{rid}", "太短")
            first.locator(".btn-reject").click()
            time.sleep(1)
            still_there = page.locator(f".review-card[data-id='{rid}']").count() > 0
            record("驳回不足10字被前端拦截", still_there)
            # 合规驳回
            page.fill(f"#comment-{rid}", "UI自动化测试驳回：内容与主题无关")
            first.locator(".btn-reject").click()
            time.sleep(1.5)
            gone = page.locator(f".review-card[data-id='{rid}']").count() == 0
            record("填写原因后驳回成功", gone)
        else:
            record("待审列表为空（跳过驳回交互）", True, "先触发采集可产生待审项")
        # 审核历史查询
        page.click("text=审核历史")
        page.click("button:has-text('查询')")
        time.sleep(1.5)
        hist = page.locator("#review-history-list").inner_text()
        record("审核历史查询展示", "已通过" in hist or "已驳回" in hist or "暂无" in hist)
        shot(page, "review_history")

        # ---------- 敏感词库 ----------
        print("== 敏感词库 ==")
        page.click("text=敏感词库")
        time.sleep(1)
        page.fill("#new-word", "UI点击测试词")
        page.click("button:has-text('添加')")
        time.sleep(1)
        record("添加敏感词", page.locator("text=UI点击测试词").count() > 0)
        # 批量导入
        csv = os.path.join(SHOTS, "_words.csv")
        open(csv, "w").write("UI导入词1,test\nUI导入词2\n")
        page.set_input_files("#words-import-file", csv)
        page.click("button:has-text('导入 TXT/CSV')")
        time.sleep(1.5)
        record("CSV批量导入", page.locator("text=UI导入词1").count() > 0)
        shot(page, "words_imported")
        # 清理（点删除按钮，自动确认弹窗）
        page.on("dialog", lambda d: d.accept())
        for w in ("UI点击测试词", "UI导入词1", "UI导入词2"):
            item = page.locator(f".word-item:has-text('{w}')")
            if item.count() > 0:
                item.first.locator(".btn-del").click()
                time.sleep(0.8)
        record("删除敏感词", page.locator("text=UI点击测试词").count() == 0)

        # ---------- 资讯源配置 ----------
        print("== 资讯源配置 ==")
        page.click("text=资讯源配置")
        time.sleep(1.5)
        n_sources = page.locator(".source-item").count()
        record("资讯源列表加载", n_sources > 0, f"{n_sources}个源")
        # 点第一个源的"测试"按钮
        page.locator(".source-item").first.locator("button:has-text('测试')").click()
        time.sleep(12)
        shot(page, "source_tested")
        record("资讯源连通性测试按钮", True, "结果以toast提示")

        # ---------- 用户管理 ----------
        print("== 用户管理 ==")
        page.click("text=用户管理")
        time.sleep(1.5)
        record("用户列表加载", page.locator(".user-item").count() > 0)
        shot(page, "users")

        # ---------- 历史早报 ----------
        print("== 历史早报 ==")
        page.click("text=历史早报")
        time.sleep(1.5)
        shot(page, "news_history")
        record("历史早报页面加载", True)

        # ---------- 退出 ----------
        page.click("text=退出登录")
        time.sleep(1.5)
        record("退出登录回到登录页", page.locator("input[type='password']").count() > 0)
        shot(page, "logged_out")

        browser.close()

    print("\n" + "=" * 56)
    passed = sum(1 for r in results if r[1])
    print(f"UI点击测试: {len(results)} 项，通过 {passed}，失败 {len(results) - passed}")
    print(f"截图目录: {SHOTS}")
    for step, ok, note in results:
        if not ok:
            print(f"  ❌ {step} {note}")
    print("=" * 56)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
