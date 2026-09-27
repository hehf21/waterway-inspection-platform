# -*- coding: utf-8 -*-
"""路由模块：登录 / 登出 / 修改密码（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403
from webcore import _clear_fails, _rate_limited, _record_fail  # noqa: F401

router = APIRouter()

# ---------------- 登录 ----------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", {})


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else ""
    now = datetime.now().timestamp()
    wait = max(_rate_limited(LOGIN_FAILS, (username, ip), now), _rate_limited(IP_FAILS, ip, now))
    if wait:
        return RedirectResponse(f"/login?msg=尝试次数过多，请{wait}秒后再试", status_code=302)
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    if not row or hash_password(password, row["salt"]) != row["password_hash"]:
        _record_fail(LOGIN_FAILS, (username, ip), LOGIN_MAX_FAIL, now)
        _record_fail(IP_FAILS, ip, IP_MAX_FAIL, now)
        n = LOGIN_FAILS[(username, ip)][0]
        audit(conn, username, "登录失败", ip=ip, detail=f"第{n}次失败（账号+IP 维度）")
        conn.commit(); conn.close()
        return RedirectResponse("/login?msg=" + "账号或密码错误", status_code=302)
    _clear_fails(username, ip)
    audit(conn, username, "登录系统", ip=ip)
    conn.commit(); conn.close()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, make_token(row["id"], row["session_rev"]), httponly=True,
                    max_age=SESSION_DAYS * 86400, samesite="lax")
    return resp


@router.get("/logout")
def logout(request: Request):
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


@router.get("/changepwd", response_class=HTMLResponse)
def changepwd_page(request: Request):
    user, err = require(request)
    if err: return err
    return render(request, "changepwd.html", {}, user)


@router.post("/changepwd")
def changepwd(request: Request, csrf: str = Form(""), old_password: str = Form(""),
              new_password: str = Form(...), new_password2: str = Form(...)):
    user, err = require(request)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not user["must_change_pwd"] and hash_password(old_password, row["salt"]) != row["password_hash"]:
        conn.close()
        return RedirectResponse("/changepwd?msg=原密码不正确", status_code=302)
    if len(new_password) < 6:
        conn.close()
        return RedirectResponse("/changepwd?msg=新密码至少6位", status_code=302)
    if new_password != new_password2:
        conn.close()
        return RedirectResponse("/changepwd?msg=两次输入的新密码不一致", status_code=302)
    salt = secrets.token_hex(8)
    # 会话版本+1：改密后其他终端的旧会话立即失效（审计 P2-5）；当前终端换发新会话保持在线
    conn.execute("UPDATE users SET password_hash=?, salt=?, must_change_pwd=0, session_rev=session_rev+1 WHERE id=?",
                 (hash_password(new_password, salt), salt, user["id"]))
    new_rev = conn.execute("SELECT session_rev FROM users WHERE id=?", (user["id"],)).fetchone()["session_rev"]
    audit(conn, user["username"], "修改密码", "user", user["id"])
    conn.commit(); conn.close()
    resp = RedirectResponse("/?msg=密码修改成功，其他终端的旧登录已失效", status_code=302)
    resp.set_cookie(COOKIE, make_token(user["id"], new_rev), httponly=True,
                    max_age=SESSION_DAYS * 86400, samesite="lax")
    return resp


