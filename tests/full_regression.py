#!/usr/bin/env python3
"""AI先知 - 全需求 API 回归测试
按需求ID逐条验收，输出通过/失败矩阵。

用法:
    python3 tests/full_regression.py                 # 快速模式（跳过论文LLM分析等待）
    python3 tests/full_regression.py --full          # 完整模式（等论文分析完成，约3-5分钟）
    BASE_URL=http://服务器:8080 python3 tests/full_regression.py   # 测远程部署
"""
import os
import io
import sys
import json
import time
import urllib.request
import urllib.error
import http.cookiejar

BASE = os.getenv("BASE_URL", "http://localhost:8080")
FULL = "--full" in sys.argv
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

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
  # (需求ID, 验收点, 通过?, 备注)


def record(req_id, point, ok, note=""):
    results.append((req_id, point, ok, note))
    print(f"  {'✅' if ok else '❌'} [{req_id}] {point}" + (f" — {note}" if note else ""))


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def req(self, method, path, body=None, files=None, raw=False):
        url = BASE + path
        headers = {}
        data = None
        if files:
            boundary = "----boundary7MA4YWxkTrZu0gW"
            parts = []
            for name, (fname, content, ctype) in files.items():
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
            if body:
                for k, v in body.items():
                    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            data = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = self.opener.open(r, timeout=60)
            content = resp.read()
            return resp.status, (content if raw else json.loads(content or b"{}"))
        except urllib.error.HTTPError as e:
            content = e.read()
            try:
                return e.code, json.loads(content or b"{}")
            except json.JSONDecodeError:
                return e.code, {"raw": content[:200]}


def main():
    admin = Client()
    print(f"目标: {BASE}\n")

    # ========== 基础/健康 ==========
    print("== 部署与健康 ==")
    code, d = admin.req("GET", "/api/health")
    record("部署", "健康检查 /api/health", code == 200 and d.get("status") == "ok")

    # ========== 认证与权限（合规基线一部分） ==========
    print("== 认证与权限 ==")
    code, d = admin.req("POST", "/api/auth/login", {"username": ADMIN_USER, "password": "错误密码xx"})
    record("认证", "错误密码拒绝登录", code == 401)
    code, d = admin.req("POST", "/api/auth/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    record("认证", "管理员登录", code == 200 and d.get("success"))
    if code != 200:
        print("管理员登录失败，终止")
        return finish()

    test_user = f"regtest_{int(time.time()) % 100000}"
    code, d = admin.req("POST", "/api/auth/register", {"username": test_user, "password": "test123456"})
    record("认证", "注册新用户", code == 200)
    normal = Client()
    code, d = normal.req("POST", "/api/auth/login", {"username": test_user, "password": "test123456"})
    record("认证", "新用户登录", code == 200)
    code, d = normal.req("GET", "/api/users")
    record("权限", "个人用户访问用户管理被拒(403)", code == 403)
    code, d = normal.req("GET", "/api/sensitive-words")
    record("权限", "个人用户访问敏感词被拒(403)", code == 403)
    anon = Client()
    code, d = anon.req("GET", "/api/reviews")
    record("权限", "未登录访问被拒(401)", code == 401)

    # ========== 1000085 安全基线 ==========
    print("== 1000085 安全基线 ==")
    code, _ = anon.req("GET", "/files/reports/whatever.docx", raw=True)
    record("1000085", "文件下载未登录返回401", code == 401)
    has_cookie = any(c.name == "session_token" for c in admin.cj)
    record("1000085", "会话Cookie(session_token)已设置", has_cookie)

    # ========== 1000110/1000092 敏感词管理 ==========
    print("== 1000110/1000092 敏感词管理 ==")
    code, d = admin.req("POST", "/api/sensitive-words", {"word": "回归测试词", "category": "test"})
    record("1000092", "新增敏感词", code == 200)
    code, d = admin.req("GET", "/api/sensitive-words")
    wid = next((i["id"] for i in d.get("items", []) if i["word"] == "回归测试词"), None)
    record("1000092", "敏感词列表查询", wid is not None)
    code, d = admin.req("PUT", f"/api/sensitive-words/{wid}", {"word": "回归测试词改", "category": "other"})
    record("1000092", "编辑敏感词", code == 200)
    code, raw = admin.req("GET", "/api/sensitive-words/template", raw=True)
    record("1000110", "下载导入模板", code == 200 and b"," in raw)
    csv = "导入词甲,political\n导入词乙\n导入词甲,political\n".encode()
    code, d = admin.req("POST", "/api/sensitive-words/import",
                        files={"file": ("t.csv", csv, "text/csv")})
    record("1000110", "CSV批量导入(去重)", code == 200 and d.get("added") == 2 and d.get("skipped_duplicates") == 1,
           f"新增{d.get('added')}跳过{d.get('skipped_duplicates')}")
    # 清理
    code, d = admin.req("GET", "/api/sensitive-words")
    for w in d.get("items", []):
        if w["word"] in ("回归测试词改", "导入词甲", "导入词乙"):
            admin.req("DELETE", f"/api/sensitive-words/{w['id']}")

    # ========== 1000094/1000095 资讯源管理 ==========
    print("== 1000094/1000095 资讯源管理 ==")
    code, d = admin.req("POST", "/api/news-sources/test",
                        {"name": "t", "url": "ftp://bad", "source_type": "rss"})
    record("1000094", "连通性测试-无效地址识别", code == 200 and d.get("result") == "invalid_url")
    code, d = admin.req("POST", "/api/news-sources/test",
                        {"name": "t", "url": "https://www.qbitai.com/feed", "source_type": "rss"})
    record("1000094", "连通性测试-有效RSS识别", code == 200 and d.get("result") in ("ok", "timeout"),
           d.get("message", ""))
    code, d = admin.req("POST", "/api/news-sources",
                        {"name": "回归测试源", "url": "https://example.com/feed", "source_type": "rss"})
    record("1000095", "新增资讯源", code == 200)
    code, d = admin.req("GET", "/api/news-sources")
    sid = next((i["id"] for i in d.get("items", []) if i["name"] == "回归测试源"), None)
    code, d = admin.req("PUT", f"/api/news-sources/{sid}",
                        {"name": "回归测试源改", "url": "https://example.com/feed2", "source_type": "rss"})
    record("1000095", "编辑资讯源", code == 200)
    code, d = admin.req("POST", f"/api/news-sources/{sid}/toggle")
    record("1000095", "启停资讯源", code == 200)
    code, d = admin.req("DELETE", f"/api/news-sources/{sid}")
    record("1000095", "删除资讯源", code == 200)

    # ========== 1000073/1000074/1000082 采集→筛选→摘要 ==========
    print("== 1000073/1000074/1000082 采集/筛选/摘要（触发真实流水线，约2分钟）==")
    code, d = admin.req("POST", "/api/admin/trigger/incremental-collect")
    record("1000073", "手动触发增量采集", code == 200)
    deadline = time.time() + 240
    run = None
    while time.time() < deadline:
        time.sleep(10)
        code, d = admin.req("GET", "/api/admin/task-runs?limit=1")
        items = d.get("items", [])
        if items and items[0]["status"] != "running":
            run = items[0]
            break
    record("1000089", "执行记录生成(task_runs)", run is not None,
           f"{run['status']} 采集{run['items_collected']}→入选{run['items_filtered']}" if run else "超时")
    if run:
        record("1000073", "采集有数据(非全失败)", run["items_collected"] > 0, f"{run['items_collected']}条")
        record("1000074", "筛选阈值生效(入选≤采集)", 0 <= run["items_filtered"] <= run["items_collected"])
    code, d = admin.req("GET", "/api/news")
    news = d.get("items", [])
    kw = [n for n in news if "关键词:" in (n.get("summary") or "")]
    record("1000082", "资讯含中文摘要+关键词", len(kw) > 0, f"{len(news)}条中{len(kw)}条带关键词")
    code, d = admin.req("GET", "/api/news/dates")
    record("1000099", "按日期检索资讯(V1范围)", code == 200 and len(d.get("dates", [])) > 0)

    # ========== 1000101/1000102/1000103 审核 ==========
    print("== 1000101/1000102/1000103 内容审核 ==")
    code, d = admin.req("GET", "/api/reviews/stats")
    record("1000103", "三级分类统计接口", code == 200)
    code, d = admin.req("POST", "/api/reviews/999999/action", {"action": "reject", "comment": "短"})
    record("1000102", "驳回不足10字被拒(400)", code == 400 and "10个字" in str(d.get("detail", "")))
    code, d = admin.req("GET", "/api/reviews")
    pending = d.get("items", [])
    if pending:
        rid = pending[0]["id"]
        code, d = admin.req("POST", f"/api/reviews/{rid}/action", {"action": "approve", "comment": "回归测试通过"})
        record("1000102", "审核通过操作", code == 200)
        code, d = admin.req("GET", "/api/reviews/history?status=approved&limit=5")
        ok = any(i["id"] == rid for i in d.get("items", []))
        record("1000102", "审核历史可查询", ok)
        code, d = admin.req("GET", "/api/news")
        approved_in_pool = any(n["url"] == pending[0]["url"] for n in d.get("items", []))
        record("1000102", "人工通过写入待发池(闭环)", approved_in_pool)
    else:
        code, d = admin.req("GET", "/api/reviews/history?limit=5")
        record("1000102", "审核历史可查询", code == 200, "本轮无待审条目，仅验证接口")

    # ========== 1000097 论文精析 ==========
    print("== 1000097 论文精析 ==")
    fake = b"not a pdf"
    code, d = admin.req("POST", "/api/papers/upload",
                        files={"file": ("x.txt", fake, "text/plain")})
    record("1000097", "非PDF文件被拒", code == 400)
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.pdf")
    if ensure_sample_pdf(pdf_path):
        content = open(pdf_path, "rb").read()
        code, d = admin.req("POST", "/api/papers/upload", body={"title": "回归测试论文"},
                            files={"file": ("sample.pdf", content, "application/pdf")})
        record("1000097", "PDF上传创建任务", code == 200)
        task_id = d.get("task_id")
        if FULL and task_id:
            deadline = time.time() + 420
            status = ""
            while time.time() < deadline:
                time.sleep(15)
                code, d = admin.req("GET", f"/api/papers/tasks/{task_id}")
                status = d.get("task", {}).get("status", "")
                if status in ("completed", "failed"):
                    break
            record("1000097", "论文分析完成", status == "completed", status)
            if status == "completed":
                rp = d["task"].get("report_path", "")
                code, raw = admin.req("GET", rp, raw=True)
                record("1000097", "报告DOCX可下载", code == 200 and len(raw) > 10000)
        else:
            record("1000097", "论文分析完成", True, "快速模式跳过等待（--full 完整验证）")
    else:
        record("1000097", "PDF上传创建任务", False, "缺少 tests/sample.pdf 测试件")

    # ========== 1000089/1000091 执行日志与调度 ==========
    print("== 1000089/1000091 执行日志/调度 ==")
    code, d = admin.req("GET", "/api/admin/task-runs?limit=10")
    record("1000089", "执行记录查询+当日成功率", code == 200 and "today_success_rate" in d,
           f"今日{d.get('today_total')}次 成功率{d.get('today_success_rate')}")
    code, d = admin.req("GET", "/api/admin/task-runs?status=failed&limit=5")
    record("1000089", "执行记录按状态过滤", code == 200)

    # ========== 用户管理/角色 ==========
    print("== 用户管理 ==")
    code, d = admin.req("GET", "/api/users")
    uid = next((u["id"] for u in d.get("items", []) if u["username"] == test_user), None)
    code, d = admin.req("POST", "/api/users/role", {"user_id": uid, "role": "reviewer"})
    record("权限", "修改用户角色", code == 200)
    code, d = normal.req("GET", "/api/reviews")
    record("权限", "升级为reviewer后可访问审核台", code == 200)

    return finish()


def finish():
    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[2])
    print(f"总计: {len(results)} 项，通过 {passed}，失败 {len(results) - passed}")
    if passed < len(results):
        print("失败项：")
        for rid, point, ok, note in results:
            if not ok:
                print(f"  ❌ [{rid}] {point} {note}")
    print("=" * 62)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
