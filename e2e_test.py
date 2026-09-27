# -*- coding: utf-8 -*-
"""浏览器级 E2E 冒烟（Playwright）：驱动真实 Chromium 走通核心闭环，覆盖 smoke（HTTP 层）测不到的
JS 交互：CSP 事件委托、逐项点选、手写签字板、打印页、手机视口。

依赖：pip install playwright && playwright install chromium
运行：python e2e_test.py     （自动起隔离实例 :8099，跑完清理）
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 8099
URL = f"http://127.0.0.1:{PORT}"
DATA = os.path.join(BASE, "e2e_data")
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))


def wait_up(timeout=30):
    for _ in range(timeout * 2):
        try:
            if urllib.request.urlopen(URL + "/healthz", timeout=2).status == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def draw_sign(page, canvas_id):
    loc = page.locator("#" + canvas_id)
    loc.scroll_into_view_if_needed()          # 签字板常在页底，不滚入视口鼠标事件落不到 canvas
    box = loc.bounding_box()
    if box:
        x, y = box["x"] + 30, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 60, y + 12, steps=8)
        page.mouse.move(x + 120, y - 8, steps=8)
        page.mouse.up()


def wait_text(page, txt, timeout=8000):
    """等待跳转后的新内容出现（表单提交有导航竞态，不能读完即判）"""
    try:
        page.wait_for_selector("text=" + txt, timeout=timeout)
        return True
    except Exception:
        return False


def wait_sel(page, css, timeout=8000):
    try:
        page.wait_for_selector(css, timeout=timeout)
        return True
    except Exception:
        return False


def main():
    if os.path.exists(DATA):
        shutil.rmtree(DATA, ignore_errors=True)
    env = dict(os.environ, SLYS_DATA=DATA)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                            "--port", str(PORT)], cwd=BASE, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up():
            print("服务未启动"); srv.terminate(); sys.exit(1)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1366, "height": 768})
            page = ctx.new_page()
            js_errors = []
            page.on("console", lambda m: js_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: js_errors.append(str(e)))
            page.on("dialog", lambda d: d.accept())

            # 1. 政府登录 + 首次强制改密
            page.goto(URL + "/login")
            page.fill("#lg-user", "gov")
            page.fill("#lg-pw", "gov@123")
            page.click("#pw-toggle")                       # 密码可见切换（JS）
            ok("登录页密码可见切换", page.get_attribute("#lg-pw", "type") == "text")
            page.click("button[type=submit]")
            page.wait_for_load_state()
            ok("首次登录强制改密跳转", "/changepwd" in page.url, page.url)
            page.fill("input[name=new_password]", "e2eGov1!")
            page.fill("input[name=new_password2]", "e2eGov1!")
            page.click("text=确认修改")
            ok("改密后进工作台", "工作台" in page.content())
            ok("导航消息红点组件存在", "消息提醒" in page.content())

            # 2. 建企业
            page.goto(URL + "/enterprises")
            page.click("text=＋新增企业")                  # data-show 委托
            page.fill("input[name=name]", "E2E测试航运有限公司")
            page.fill("input[name=credit_code]", "91350128E2E0001X")
            page.click("#entform button")
            ok("新建企业（data-show 委托生效）", "E2E测试航运有限公司" in page.content())

            # 3. 登记检查：模板 + 逐项下拉点选 + 提交
            page.goto(URL + "/inspections/new")
            page.select_option("select[name=enterprise_id]", index=1)   # 首个企业（空库仅一家）
            page.select_option("#tpl_sel", index=1)
            selects = page.locator("select[data-res]")
            n = selects.count()
            for i in range(n):
                selects.nth(i).select_option(label="符合")   # data-res 变更委托
            cnt = page.locator("#item-count").inner_text()
            ok("逐项结果点选生效（委托 change）", n > 0 and "共 %d 项" % n in cnt, f"n={n} cnt={cnt}")
            # 造一个“不符合”项 → 自动带出问题卡（走真实 onResult 委托路径）
            selects.first.select_option(label="不符合")
            req = page.locator("textarea[data-pf$=':requirement']").first
            req.fill("E2E整改要求：限期整改到位")
            ok("不符合自动带出问题卡", page.locator("[data-pf$=':requirement']").count() >= 1)
            page.fill("input[name=inspectors]", "E2E检查员")
            page.fill("input[name=check_date]", time.strftime("%Y-%m-%d"))
            page.click("#btn-submit")
            page.wait_for_load_state()
            ok("保存登记并跳详情", "/inspections/" in page.url, page.url)
            ins_url = page.url.split("?")[0]

            # 4. 下发
            page.click("text=下发（企业可见）")
            ok("下发（data-confirm 委托）", wait_text(page, "整改中"))

            # 5. 建企业账号并登录 → 整改反馈
            page.goto(URL + "/users")
            page.fill("input[name=username]", "e2eent")
            page.fill("input[name=password]", "e2eEnt1!")
            page.fill("input[name=real_name]", "E2E企业")
            page.select_option("select[name=role]", "enterprise")
            page.select_option("select[name=enterprise_id]", label="E2E测试航运有限公司")
            page.click("#u-form button[type=submit]" if page.locator("#u-form").count() else "form[action='/users/save'] button")
            ok("创建企业账号", "e2eent" in page.content())
            page.goto(URL + "/logout")
            page.goto(URL + "/login")
            page.fill("#lg-user", "e2eent")
            page.fill("#lg-pw", "e2eEnt1!")
            page.click("button[type=submit]")
            page.wait_for_load_state()
            if "/changepwd" in page.url:
                page.fill("input[name=new_password]", "e2eEnt2!")
                page.fill("input[name=new_password2]", "e2eEnt2!")
                page.click("text=确认修改")
                page.wait_for_load_state()
            ok("企业工作台待办区", "待我整改" in page.content() and "工作台" in page.content())
            page.goto(ins_url)
            page.click("text=✎ 整改反馈")          # 子串匹配：按钮文案为“✎ 整改反馈（填写）”
            page.fill("textarea[name=measure]", "E2E整改措施：已整改到位")
            page.click("text=提交整改反馈")
            ok("企业整改反馈提交", wait_text(page, "待复核"))

            # 6. 政府复核 → 闭环
            page.goto(URL + "/logout")
            page.goto(URL + "/login")
            page.fill("#lg-user", "gov")
            page.fill("#lg-pw", "e2eGov1!")
            page.click("button[type=submit]")
            page.wait_for_load_state()
            page.goto(ins_url)
            page.select_option("select[name=result]", "pass")
            page.click("text=提交复核")
            ok("复核通过自动闭环", wait_text(page, "已闭环"))

            # 7. 双方手写签字（真实画一笔）
            page.click("text=\"✍ 手写签字确认\"")
            page.fill("#sign-insp input[name=signer_name]", "E2E检查员")
            draw_sign(page, "pad-insp")
            page.click("button[data-sign='sign-insp:pad-insp']")
            ok("检查人员手写签字成功", wait_sel(page, "img[alt='检查人员签名']"))
            page.click("text=\"✍ 手写签字确认\"", strict=False)
            page.fill("#sign-ent input[name=signer_name]", "E2E企业负责人")
            draw_sign(page, "pad-ent")
            page.click("button[data-sign='sign-ent:pad-ent']")
            ok("企业负责人手写签字成功", wait_sel(page, "img[alt='企业签名']"))

            # 8. 归档并锁定（该按钮是下载 ZIP，需回详情页看状态）→ 打印页含签名
            page.click("text=📦 归档并锁定")
            page.goto(ins_url)
            ok("归档并锁定", wait_text(page, "已归档"))
            page.goto(ins_url + "/print")
            txt = page.content()
            ok("打印页含检查表与签名", "打印本检查表" in txt and "签名" in txt)

            # 9. 手机视口现场登记
            m = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True,
                                    has_touch=True).new_page()
            m.goto(URL + "/login")
            m.fill("#lg-user", "gov")
            m.fill("#lg-pw", "e2eGov1!")
            m.click("button[type=submit]")
            m.goto(URL + "/onsite")
            m.select_option("#tpl_sel", index=1)
            nres = m.locator(".res-btns .res").count()
            ok("手机现场登记页结果大按钮渲染", nres > 0, f"按钮数={nres}")
            m.locator(".res-btns .res").first.tap()
            ok("手机点选结果（touch 委托）", m.locator(".res-btns .res.sel").count() == 1)

            # 10. CSP/JS 无错误
            real = [e for e in js_errors if "favicon" not in e.lower()]
            ok("全程无 JS/CSP 错误", not real, real[:3])

            browser.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
        shutil.rmtree(DATA, ignore_errors=True)

    n_fail = sum(1 for _, v in results if not v)
    print(f"\n=== E2E {len(results) - n_fail}/{len(results)} 通过 ===")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
