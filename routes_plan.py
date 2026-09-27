# -*- coding: utf-8 -*-
"""路由模块：检查计划（制定→下达→执行跟踪）（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 检查计划（制定→下达→执行跟踪→自动核销） ----------------
PLAN_STATUS_CN = {"draft": "草稿", "issued": "已下达"}


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request):
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    # 一次聚合取全量进度，避免每个计划 2 次查询（N+1 优化）
    stat = {}
    for s in conn.execute(
            "SELECT pi.plan_id, COUNT(*) items, COALESCE(SUM(pi.count_plan),0) plan_total,"
            " COALESCE(SUM((SELECT COUNT(*) FROM inspections i WHERE i.plan_item_id=pi.id"
            "   AND i.status<>'draft')),0) done FROM plan_items pi GROUP BY pi.plan_id").fetchall():
        stat[s["plan_id"]] = (s["items"], s["plan_total"], s["done"])
    rows = []
    for p in conn.execute("SELECT * FROM plans ORDER BY id DESC").fetchall():
        d = dict(p)
        d["item_cnt"], d["plan_total"], d["done"] = stat.get(p["id"], (0, 0, 0))
        rows.append(d)
    conn.close()
    return render(request, "plans.html", {"rows": rows, "PLAN_STATUS_CN": PLAN_STATUS_CN}, user)


@router.get("/plans/{pid}", response_class=HTMLResponse)
def plan_edit(request: Request, pid: int = 0):
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone() if pid else None
    if pid and not plan:
        conn.close(); return HTMLResponse("计划不存在", status_code=404)
    items = []
    if plan:
        # 一次联表取企业名与已核销数（N+1 优化）
        for r in conn.execute(
                "SELECT pi.*, e.name ent_name,"
                " (SELECT COUNT(*) FROM inspections i WHERE i.plan_item_id=pi.id AND i.status<>'draft') done"
                " FROM plan_items pi LEFT JOIN enterprises e ON e.id=pi.enterprise_id"
                " WHERE pi.plan_id=? ORDER BY pi.id", (pid,)).fetchall():
            d = dict(r)
            d["ent_name"] = d["ent_name"] or (d["ent_scope"] or "不限定企业")
            items.append(d)
    ents = conn.execute("SELECT id, name FROM enterprises ORDER BY name").fetchall()
    conn.close()
    return render(request, "plan_edit.html",
                  {"plan": plan, "items": items, "ents": ents,
                   "CHECK_TYPES": CHECK_TYPES, "PLAN_STATUS_CN": PLAN_STATUS_CN}, user)


@router.post("/plans/save")
async def plan_save(request: Request, csrf: str = Form(""), pid: int = Form(0),
                    title: str = Form(...), year: int = Form(0), period: str = Form(""),
                    note: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if not title.strip():
        return HTMLResponse("计划名称不能为空", status_code=400)
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if pid:
        old = conn.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()
        if not old:
            conn.close(); return HTMLResponse("计划不存在", status_code=404)
        conn.execute("UPDATE plans SET title=?,year=?,period=?,note=? WHERE id=?",
                     (title.strip(), year, period, note, pid))
        audit(conn, user["username"], "修改检查计划", "plan", pid, title.strip(),
              before=json.dumps({"title": old["title"], "year": old["year"], "period": old["period"],
                                 "note": old["note"]}, ensure_ascii=False),
              after=json.dumps({"title": title.strip(), "year": year, "period": period, "note": note},
                               ensure_ascii=False))
        new_id = pid
    else:
        cur = conn.execute("INSERT INTO plans(title,year,period,status,note,created_by,created_at)"
                           " VALUES(?,?,?,'draft',?,?,?)",
                           (title.strip(), year, period, note, user["username"], now))
        new_id = cur.lastrowid
        audit(conn, user["username"], "新建检查计划", "plan", new_id, title.strip())
    conn.commit(); conn.close()
    return RedirectResponse(f"/plans/{new_id}?msg=计划已保存，请继续添加计划项", status_code=302)


@router.post("/plans/{pid}/items/save")
async def plan_item_save(request: Request, pid: int, piid: int = Form(0), csrf: str = Form(""),
                         enterprise_id: int = Form(0), ent_scope: str = Form(""),
                         check_type: str = Form(...), count_plan: int = Form(1),
                         period: str = Form(""), inspectors: str = Form(""), note: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()
    if not plan:
        conn.close(); return HTMLResponse("计划不存在", status_code=404)
    if plan["status"] != "draft":
        conn.close()
        return HTMLResponse("计划已下达，不能再调整计划项（如需变更请先与管理员沟通）", status_code=400)
    if check_type not in CHECK_TYPES:
        conn.close(); return HTMLResponse("检查类型不合法", status_code=400)
    vals = (enterprise_id or 0, ent_scope.strip(), check_type, max(1, min(count_plan, 999)),
            period.strip(), inspectors.strip(), note)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if piid:
        old = conn.execute("SELECT * FROM plan_items WHERE id=? AND plan_id=?", (piid, pid)).fetchone()
        if not old:
            conn.close(); return HTMLResponse("计划项不存在", status_code=404)
        conn.execute("UPDATE plan_items SET enterprise_id=?,ent_scope=?,check_type=?,count_plan=?,period=?,"
                     "inspectors=?,note=? WHERE id=?", vals + (piid,))
        audit(conn, user["username"], "修改计划项", "plan_item", piid, f"计划#{pid}",
              before=json.dumps(dict(old), ensure_ascii=False), after=json.dumps(dict(vals), ensure_ascii=False))
    else:
        cur = conn.execute("INSERT INTO plan_items(plan_id,enterprise_id,ent_scope,check_type,count_plan,"
                           "period,inspectors,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (pid,) + vals + (now,))
        audit(conn, user["username"], "新增计划项", "plan_item", cur.lastrowid,
              f"计划#{pid} {check_type} {vals[3]}家次")
    conn.commit(); conn.close()
    return RedirectResponse(f"/plans/{pid}?msg=计划项已保存", status_code=302)


@router.post("/plan_items/{piid}/delete")
def plan_item_delete(request: Request, piid: int, csrf: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    pi = conn.execute("SELECT * FROM plan_items WHERE id=?", (piid,)).fetchone()
    if not pi:
        conn.close(); return HTMLResponse("计划项不存在", status_code=404)
    plan = conn.execute("SELECT status FROM plans WHERE id=?", (pi["plan_id"],)).fetchone()
    if plan and plan["status"] != "draft":
        conn.close(); return HTMLResponse("计划已下达，不能删除计划项", status_code=400)
    conn.execute("DELETE FROM plan_items WHERE id=?", (piid,))
    audit(conn, user["username"], "删除计划项", "plan_item", piid, f"计划#{pi['plan_id']}")
    conn.commit(); conn.close()
    return RedirectResponse(f"/plans/{pi['plan_id']}?msg=计划项已删除", status_code=302)


@router.post("/plans/{pid}/issue")
def plan_issue(request: Request, pid: int, csrf: str = Form("")):
    """下达计划：草稿→已下达（下达后计划项锁定，开始执行跟踪）"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()
    if not plan:
        conn.close(); return HTMLResponse("计划不存在", status_code=404)
    n = conn.execute("SELECT COUNT(*) c FROM plan_items WHERE plan_id=?", (pid,)).fetchone()["c"]
    if n == 0:
        conn.close(); return RedirectResponse(f"/plans/{pid}?msg=请先添加计划项再下达", status_code=302)
    if plan["status"] == "issued":
        conn.close(); return RedirectResponse(f"/plans/{pid}?msg=该计划已下达", status_code=302)
    conn.execute("UPDATE plans SET status='issued', issued_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pid))
    audit(conn, user["username"], "下达检查计划", "plan", pid, f"{plan['title']}（{n} 个计划项）")
    conn.commit(); conn.close()
    return RedirectResponse(f"/plans/{pid}?msg=计划已下达，开始执行跟踪", status_code=302)


@router.get("/plans/{pid}/export")
def plan_export(request: Request, pid: int):
    """导出检查计划表（Excel：计划信息 + 计划项与执行进度），可打印作为正式计划文件"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()
    if not plan:
        conn.close(); return HTMLResponse("计划不存在", status_code=404)
    wb = Workbook()
    ws = wb.active
    ws.title = "计划信息"
    ws.append(["计划名称", plan["title"]])
    ws.append(["年度", plan["year"]])
    ws.append(["计划时段", plan["period"]])
    ws.append(["状态", PLAN_STATUS_CN.get(plan["status"], plan["status"])])
    ws.append(["制定人", plan["created_by"]])
    ws.append(["制定时间", plan["created_at"]])
    ws.append(["下达时间", plan["issued_at"] or "（未下达）"])
    ws.append(["说明", plan["note"]])
    ws2 = wb.create_sheet("计划项与执行")
    ws2.append(["序号", "检查对象/适用范围", "检查类型", "计划家次", "计划时段", "计划检查人员",
                "已完成", "完成率", "备注"])
    i, plan_total, done_total = 0, 0, 0
    for pi in conn.execute("SELECT * FROM plan_items WHERE plan_id=? ORDER BY id", (pid,)).fetchall():
        i += 1
        ent = (conn.execute("SELECT name FROM enterprises WHERE id=?", (pi["enterprise_id"],)).fetchone()
               if pi["enterprise_id"] else None)
        done = conn.execute("SELECT COUNT(*) c FROM inspections WHERE plan_item_id=? AND status<>'draft'",
                            (pi["id"],)).fetchone()["c"]
        plan_total += pi["count_plan"]
        done_total += done
        ws2.append([i, ent["name"] if ent else (pi["ent_scope"] or "不限定企业"), pi["check_type"],
                    pi["count_plan"], pi["period"], pi["inspectors"], done,
                    f"{min(done / pi['count_plan'] * 100, 100):.0f}%" if pi["count_plan"] else "-", pi["note"]])
    ws2.append([])
    ws2.append(["合计", "", "", plan_total, "", "", done_total,
                f"{min(done_total / plan_total * 100, 100):.0f}%" if plan_total else "-", ""])
    audit(conn, user["username"], "导出检查计划", "plan", pid, plan["title"])
    conn.commit(); conn.close()
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=dl_header(f"{plan['title']}.xlsx"))


