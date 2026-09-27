# -*- coding: utf-8 -*-
"""界面截图生成：起隔离实例 + 造演示数据 + Playwright 截图到 docs/screenshots/，供 README 使用。
用法：python make_screenshots.py   （输出 PNG；幂等覆盖）"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 8097
URL = f"http://127.0.0.1:{PORT}"
DATA = os.path.join(BASE, "shot_data")
OUT = os.path.join(BASE, "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)


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
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        x, y = box["x"] + 30, box["y"] + box["height"] / 2
        page.mouse.move(x, y); page.mouse.down()
        page.mouse.move(x + 60, y + 12, steps=8)
        page.mouse.move(x + 120, y - 8, steps=8)
        page.mouse.up()


def shot(page, name, full=False):
    page.screenshot(path=os.path.join(OUT, name), full_page=full)
    print("  ✓", name)


def main():
    if os.path.exists(DATA):
        shutil.rmtree(DATA, ignore_errors=True)
    env = dict(os.environ, SLYS_DATA=DATA)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                            "--port", str(PORT)], cwd=BASE, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up():
            print("服务未启动"); sys.exit(1)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(viewport={"width": 1366, "height": 768}).new_page()
            page.on("dialog", lambda d: d.accept())

            # --- 造演示数据 ---
            page.goto(URL + "/login")
            page.fill("#lg-user", "gov"); page.fill("#lg-pw", "gov@123")
            page.click("button[type=submit]"); page.wait_for_load_state()
            page.fill("input[name=new_password]", "ShotGov1!")
            page.fill("input[name=new_password2]", "ShotGov1!")
            page.click("text=确认修改"); page.wait_for_load_state()
            page.goto(URL + "/enterprises")
            for nm, cc in (("平潭兴海航运有限公司", "91350128SHOT001X"), ("平潭蓝鳍轮渡有限公司", "91350128SHOT002X")):
                page.click("text=＋新增企业")
                page.fill("#entform input[name=name]", nm)
                page.fill("#entform input[name=credit_code]", cc)
                page.select_option("#f-type", "普通货物运输")
                page.click("#entform button")
                page.wait_for_load_state()
            page.goto(URL + "/inspections/new")
            page.select_option("select[name=enterprise_id]", index=1)
            page.select_option("#tpl_sel", index=1)
            sels = page.locator("select[data-res]")
            n = sels.count()
            for i in range(n):
                sels.nth(i).select_option(label="符合")
            sels.first.select_option(label="不符合")
            page.locator("textarea[data-pf$=':requirement']").first.fill("限期配齐专职海务机务管理人员并备案")
            page.fill("input[name=inspectors]", "李检查员、王检查员")
            page.fill("input[name=location]", "企业经营场所")
            page.fill("input[name=check_date]", time.strftime("%Y-%m-%d"))
            page.fill("textarea[name=conclusion_note]", "安全管理台账基本健全，人员配备不足，责令限期整改。")

            # --- 截图 2：登记检查（填写完成态） ---
            shot(page, "02-inspection-new.png")
            page.click("#btn-submit"); page.wait_for_load_state()
            ins_url = page.url.split("?")[0]
            page.click("text=下发（企业可见）")
            page.wait_for_selector("text=整改中")

            # --- 截图 3：详情页（含逐项结果/问题/签字入口） ---
            shot(page, "03-detail.png", full=True)

            # 双方签字（截图打印页时签名可见）
            page.click("text=\"✍ 手写签字确认\"")
            page.fill("#sign-insp input[name=signer_name]", "李检查员")
            draw_sign(page, "pad-insp")
            page.click("button[data-sign='sign-insp:pad-insp']")
            page.wait_for_selector("img[alt='检查人员签名']")
            page.click("text=\"✍ 手写签字确认\"", strict=False)
            page.fill("#sign-ent input[name=signer_name]", "王船长")
            draw_sign(page, "pad-ent")
            page.click("button[data-sign='sign-ent:pad-ent']")
            page.wait_for_selector("img[alt='企业签名']")

            # --- 截图 5：打印检查表（含手写签名） ---
            page.goto(ins_url + "/print")
            page.wait_for_load_state()
            shot(page, "05-print.png", full=True)

            # --- 截图 1：工作台（有统计与待办） ---
            page.goto(URL + "/")
            page.wait_for_load_state()
            shot(page, "01-dashboard.png")

            # --- 截图 6：消息提醒 ---
            page.goto(URL + "/messages")
            shot(page, "06-messages.png")

            # --- 截图 4：手机现场登记 ---
            m = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True,
                                    has_touch=True).new_page()
            m.goto(URL + "/login")
            m.fill("#lg-user", "gov"); m.fill("#lg-pw", "ShotGov1!")
            m.click("button[type=submit]"); m.wait_for_load_state()
            m.goto(URL + "/onsite")
            m.select_option("#tpl_sel", index=1)
            m.locator(".res-btns .res").nth(0).tap()
            m.locator(".res-btns .res").nth(3).tap()
            shot(m, "04-onsite-mobile.png")
            browser.close()
        print("\n截图完成：", OUT)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == "__main__":
    main()
