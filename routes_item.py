# -*- coding: utf-8 -*-
"""路由模块：检查项目库 / 检查表模板设计（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 检查项目库 ----------------
@router.get("/items", response_class=HTMLResponse)
def item_list(request: Request, category: str = ""):
    user, err = require(request, GOV_ROLES + ("sysadmin",))
    if err: return err
    conn = get_db()
    sql = "SELECT * FROM check_items"
    args = ()
    if category:
        sql += " WHERE category=?"; args = (category,)
    rows = conn.execute(sql + " ORDER BY code", args).fetchall()
    cats = [r["category"] for r in conn.execute("SELECT DISTINCT category FROM check_items ORDER BY category")]
    conn.close()
    return render(request, "items.html", {"rows": rows, "cats": cats, "category": category}, user)


@router.post("/items/save")
async def item_save(request: Request, iid: int = Form(0), code: str = Form(...), category: str = Form(...),
                    name: str = Form(...), content: str = Form(...), legal_basis: str = Form(...),
                    legal_note: str = Form(""),
                    method: str = Form(...), criteria: str = Form(...), is_key: int = Form(0),
                    is_veto: int = Form(0), score: int = Form(3), scope: str = Form(""), note: str = Form(""),
                    csrf: str = Form("")):
    user, err = require(request, ("gov_admin",))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    vals = (code, category, name, content, legal_basis, legal_note, method, criteria, is_key, is_veto, score, scope, note)
    if iid:
        old = conn.execute("SELECT * FROM check_items WHERE id=?", (iid,)).fetchone()
        if not old:
            conn.close(); return HTMLResponse("检查项不存在", status_code=404)
        # 修改前版本存档（条款库版本历史）：旧文本入库可追溯；历史检查记录另有登记时快照，互不影响
        conn.execute("INSERT INTO check_item_history(item_id,code,category,name,content,legal_basis,legal_note,method,criteria,"
                     "is_key,is_veto,score,scope,note,active,changed_by,changed_at,change_note)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (iid, old["code"], old["category"], old["name"], old["content"], old["legal_basis"],
                      old["legal_note"],
                      old["method"], old["criteria"], old["is_key"], old["is_veto"], old["score"],
                      old["scope"], old["note"], old["active"], user["username"],
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "修改前版本存档"))
        conn.execute("UPDATE check_items SET code=?,category=?,name=?,content=?,legal_basis=?,legal_note=?,method=?,criteria=?,"
                     "is_key=?,is_veto=?,score=?,scope=?,note=? WHERE id=?", vals + (iid,))
        fields = ["code", "category", "name", "content", "legal_basis", "method", "criteria", "is_key",
                  "is_veto", "score", "scope", "note"]
        audit(conn, user["username"], "修改检查项", "check_item", iid, code,
              before=json.dumps({f: old[f] for f in fields}, ensure_ascii=False),
              after=json.dumps(dict(zip(fields, vals)), ensure_ascii=False))
    else:
        cur = conn.execute("INSERT INTO check_items(code,category,name,content,legal_basis,legal_note,method,criteria,"
                           "is_key,is_veto,score,scope,note,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                           vals + (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        audit(conn, user["username"], "新增检查项", "check_item", cur.lastrowid, code)
    conn.commit(); conn.close()
    return RedirectResponse("/items?msg=保存成功", status_code=302)


@router.get("/items/{iid}/history", response_class=HTMLResponse)
def item_history(request: Request, iid: int):
    user, err = require(request, GOV_ROLES + ("sysadmin",))
    if err: return err
    conn = get_db()
    item = conn.execute("SELECT * FROM check_items WHERE id=?", (iid,)).fetchone()
    if not item:
        conn.close(); return HTMLResponse("检查项不存在", status_code=404)
    rows = conn.execute("SELECT * FROM check_item_history WHERE item_id=? ORDER BY id DESC", (iid,)).fetchall()
    conn.close()
    return render(request, "item_history.html", {"item": item, "rows": rows}, user)


@router.post("/items/{iid}/toggle")
def item_toggle(request: Request, iid: int, csrf: str = Form("")):
    user, err = require(request, ("gov_admin",))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    old = conn.execute("SELECT * FROM check_items WHERE id=?", (iid,)).fetchone()
    if old:
        conn.execute("INSERT INTO check_item_history(item_id,code,category,name,content,legal_basis,legal_note,method,criteria,"
                     "is_key,is_veto,score,scope,note,active,changed_by,changed_at,change_note)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (iid, old["code"], old["category"], old["name"], old["content"], old["legal_basis"],
                      old["legal_note"],
                      old["method"], old["criteria"], old["is_key"], old["is_veto"], old["score"],
                      old["scope"], old["note"], old["active"], user["username"],
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "启停前版本存档"))
    conn.execute("UPDATE check_items SET active=1-active WHERE id=?", (iid,))
    audit(conn, user["username"], "启停检查项", "check_item", iid)
    conn.commit(); conn.close()
    return RedirectResponse("/items?msg=已切换状态", status_code=302)


# ---------------- 检查表模板设计 ----------------
@router.get("/templates", response_class=HTMLResponse)
def tpl_list(request: Request):
    user, err = require(request, GOV_ROLES + ("sysadmin",))
    if err: return err
    conn = get_db()
    rows = conn.execute("SELECT t.*, (SELECT COUNT(*) FROM template_items ti WHERE ti.template_id=t.id) cnt"
                        " FROM check_templates t ORDER BY t.id").fetchall()
    conn.close()
    return render(request, "templates.html", {"rows": rows}, user)


@router.get("/templates/{tid}", response_class=HTMLResponse)
def tpl_edit(request: Request, tid: int = 0):
    user, err = require(request, ("gov_admin",) + GOV_ROLES)
    if err: return err
    conn = get_db()
    tpl = conn.execute("SELECT * FROM check_templates WHERE id=?", (tid,)).fetchone() if tid else None
    items = conn.execute("SELECT * FROM check_items WHERE active=1 ORDER BY code").fetchall()
    chosen = set()
    if tpl:
        chosen = {r["item_id"] for r in conn.execute("SELECT item_id FROM template_items WHERE template_id=?", (tid,))}
    conn.close()
    return render(request, "template_edit.html", {"tpl": tpl, "items": items, "chosen": chosen}, user)


@router.post("/templates/save")
async def tpl_save(request: Request, tid: int = Form(0), name: str = Form(...), description: str = Form(""),
                   item_ids: str = Form(""), csrf: str = Form("")):
    user, err = require(request, ("gov_admin",))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    ids = [int(x) for x in item_ids.split(",") if x.strip().isdigit()]
    conn = get_db()
    if tid:
        old = conn.execute("SELECT * FROM check_templates WHERE id=?", (tid,)).fetchone()
        conn.execute("UPDATE check_templates SET name=?,description=?,version=version+1 WHERE id=?",
                     (name, description, tid))
        conn.execute("DELETE FROM template_items WHERE template_id=?", (tid,))
        audit(conn, user["username"], "修改检查表", "template", tid,
              f"{old['name']} → {name}", before=old["description"], after=description)
    else:
        cur = conn.execute("INSERT INTO check_templates(name,description,version,active,created_by,created_at)"
                           " VALUES(?,?,1,1,?,?)",
                           (name, description, user["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        tid = cur.lastrowid
        audit(conn, user["username"], "新建检查表", "template", tid, name)
    for i, iid in enumerate(ids):
        conn.execute("INSERT OR IGNORE INTO template_items(template_id,item_id,sort_order) VALUES(?,?,?)",
                     (tid, iid, i))
    conn.commit(); conn.close()
    return RedirectResponse("/templates?msg=保存成功（版本已递增，历史检查记录保留原版本内容）", status_code=302)


@router.post("/templates/{tid}/toggle")
def tpl_toggle(request: Request, tid: int, csrf: str = Form("")):
    user, err = require(request, ("gov_admin",))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    conn.execute("UPDATE check_templates SET active=1-active WHERE id=?", (tid,))
    audit(conn, user["username"], "启停检查表", "template", tid)
    conn.commit(); conn.close()
    return RedirectResponse("/templates?msg=已切换检查表状态", status_code=302)


