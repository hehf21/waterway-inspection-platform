# -*- coding: utf-8 -*-
"""路由模块：操作日志 / 用户管理 / 一键备份（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 审计日志 / 用户管理 ----------------
@router.get("/audit", response_class=HTMLResponse)
def audit_list(request: Request, q: str = "", p: int = 1):
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    conn = get_db()
    page_size = 100
    p = max(1, p)
    where, args = "", []
    if q:
        where = " WHERE username LIKE ? OR action LIKE ? OR detail LIKE ?"
        args = [f"%{q}%"] * 3
    total = conn.execute("SELECT COUNT(*) c FROM audit_logs" + where, args).fetchone()["c"]
    rows = conn.execute("SELECT * FROM audit_logs" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                        args + [page_size, (p - 1) * page_size]).fetchall()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return render(request, "audit.html",
                  {"rows": rows, "q": q, "p": p, "pages": pages, "total": total}, user)


@router.get("/users", response_class=HTMLResponse)
def user_list(request: Request):
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    conn = get_db()
    rows = conn.execute("SELECT u.*, e.name ent_name FROM users u LEFT JOIN enterprises e ON e.id=u.enterprise_id"
                        " ORDER BY u.id").fetchall()
    ents = conn.execute("SELECT * FROM enterprises ORDER BY name").fetchall()
    conn.close()
    return render(request, "users.html", {"rows": rows, "ents": ents}, user)


def _can_manage_role(actor, target_role: str) -> bool:
    """仅 sysadmin 可创建/维护 sysadmin 账号，防止 gov_admin 越权提权（审计 P1-6）。"""
    return actor["role"] == "sysadmin" or target_role != "sysadmin"


@router.post("/users/save")
async def user_save(request: Request, uid: int = Form(0), username: str = Form(...), password: str = Form(""),
                    real_name: str = Form(...), role: str = Form(...), enterprise_id: int = Form(0),
                    phone: str = Form(""), csrf: str = Form("")):
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if role not in ROLES:
        return HTMLResponse("角色不合法", status_code=400)
    if not _can_manage_role(user, role):
        return HTMLResponse("无权创建或修改系统管理员账号", status_code=403)
    conn = get_db()
    eid = enterprise_id if role == "enterprise" and enterprise_id else None
    if uid:
        target = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not target:
            conn.close(); return HTMLResponse("用户不存在", status_code=404)
        if not _can_manage_role(user, target["role"]):
            conn.close(); return HTMLResponse("无权修改系统管理员账号", status_code=403)
        if password:
            salt = secrets.token_hex(8)
            # session_rev+1：管理员重置密码后该用户所有旧会话立即失效（审计 P2-5）
            conn.execute("UPDATE users SET username=?,password_hash=?,salt=?,real_name=?,role=?,enterprise_id=?,phone=?,"
                         "must_change_pwd=1, session_rev=session_rev+1 WHERE id=?",
                         (username, hash_password(password, salt), salt, real_name, role, eid, phone, uid))
        else:
            conn.execute("UPDATE users SET username=?,real_name=?,role=?,enterprise_id=?,phone=? WHERE id=?",
                         (username, real_name, role, eid, phone, uid))
        audit(conn, user["username"], "修改用户", "user", uid, username,
              before=json.dumps({"username": target["username"], "real_name": target["real_name"],
                                 "role": target["role"], "enterprise_id": target["enterprise_id"],
                                 "phone": target["phone"], "active": target["active"]}, ensure_ascii=False),
              after=json.dumps({"username": username, "real_name": real_name, "role": role,
                                "enterprise_id": eid, "phone": phone}, ensure_ascii=False))
    else:
        salt = secrets.token_hex(8)
        conn.execute("INSERT INTO users(username,password_hash,salt,real_name,role,enterprise_id,phone,active,must_change_pwd,created_at)"
                     " VALUES(?,?,?,?,?,?,?,1,1,?)",
                     (username, hash_password(password or "123456", salt), salt, real_name, role, eid, phone,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        audit(conn, user["username"], "新增用户", "user", 0, username)
    conn.commit(); conn.close()
    return RedirectResponse("/users?msg=保存成功", status_code=302)


@router.post("/users/{uid}/toggle")
def user_toggle(request: Request, uid: int, csrf: str = Form("")):
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    target = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        conn.close(); return HTMLResponse("用户不存在", status_code=404)
    if target["id"] == user["id"]:
        conn.close(); return HTMLResponse("不能停用当前登录的账号", status_code=400)
    if not _can_manage_role(user, target["role"]):
        conn.close(); return HTMLResponse("无权操作系统管理员账号", status_code=403)
    conn.execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
    audit(conn, user["username"], "启停用户", "user", uid, target["username"])
    conn.commit(); conn.close()
    return RedirectResponse("/users?msg=已切换状态", status_code=302)


@router.post("/admin/backup")
def admin_backup(request: Request, csrf: str = Form("")):
    """一键备份：数据库热备份 + 全部附件，打包下载"""
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    import sqlite3
    import zipfile
    from config import DB_PATH, UPLOAD_DIR
    # SQLite 热备份（在线一致性拷贝，不影响使用）
    src = sqlite3.connect(DB_PATH)
    mem = sqlite3.connect(":memory:")
    src.backup(mem)
    db_bytes = mem.serialize()
    src.close(); mem.close()
    buf = io.BytesIO()
    n_att = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("app.db", db_bytes)
        if os.path.isdir(UPLOAD_DIR):
            for root, _dirs, files in os.walk(UPLOAD_DIR):
                for f in files:
                    full = os.path.join(root, f)
                    arc = "uploads/" + os.path.relpath(full, UPLOAD_DIR).replace("\\", "/")
                    z.write(full, arc)
                    n_att += 1
        z.writestr("备份说明.txt",
                   (f"水路运输企业检查记录管理平台 数据备份\n{'=' * 40}\n"
                    f"备份时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"备份人：{user['username']}\n"
                    f"内容：app.db（数据库，含检查记录/检查项目库/用户/日志）+ uploads\\（全部附件，{n_att} 件）\n"
                    f"恢复方法：停止平台 → 将 app.db 覆盖到 data\\app.db、uploads\\ 覆盖到 data\\uploads\\ → 重新启动。\n"
                    f"建议：定期备份 data\\ 目录，重要归档包另行离线保存。\n").encode("utf-8"))
    conn = get_db()
    audit(conn, user["username"], "一键备份数据", "system", "",
          f"备份包含附件{n_att}件")
    conn.commit(); conn.close()
    name = f"水路运输检查平台备份_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(buf.getvalue(), media_type="application/zip", headers=dl_header(name))


