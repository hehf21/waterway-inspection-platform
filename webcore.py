# -*- coding: utf-8 -*-
"""共享核心：配置常量、鉴权、渲染、限速 —— 路由模块（routes_*.py）统一从这里取用。

路由模块用 `from webcore import *` 获得全部非下划线符号；
带下划线的内部函数（_rate_limited 等）按需显式导入。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook

import pdfgen
import zipgen
from config import (ALLOWED_EXT, ALLOW_GOV_ENT_FEEDBACK, APP_NAME, ARCHIVE_DIR, CHECK_MODES, CHECK_TYPES,
                    GOV_ROLES, HOST, MAX_UPLOAD_MB, ORG_NAME, PORT, PROB_STATUS_CN, PUBLIC_RANDOM_NOTICE,
                    PUSH_TIME, REC_STATUS_CN, RESULT_NA, RESULT_NG, RESULT_OK, RESULT_UNCHECKED, ROLES,
                    SECRET_KEY, SESSION_DAYS, WEBHOOK_URL)
from db import audit, get_db, hash_password, init_db

BASE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

COOKIE = "slys_session"
CONCLUSIONS = ["未发现问题", "责发整改", "移送线索"]

# 登录失败限速（审计 P1-4）：滑动窗口计数 + 锁定绑定“账号+IP”，避免攻击者锁死他人账号
LOGIN_FAILS: dict = {}       # (username, ip) -> [失败次数, 窗口起始时间戳, 锁定到期时间戳]
IP_FAILS: dict = {}          # ip -> [失败次数, 窗口起始时间戳, 锁定到期时间戳]
LOGIN_MAX_FAIL = 5           # 同一账号+IP 在窗口内的允许失败次数
IP_MAX_FAIL = 50             # 同一 IP 在窗口内的允许失败次数（防同 IP 扫多账号）
LOGIN_LOCK_SEC = 300         # 锁定时长 / 计数窗口
LIMITER_MAX_ENTRIES = 5000   # 内存上限，超出时清理过期项


def _rate_limited(store: dict, key, now: float) -> int:
    """返回剩余锁定秒数；0 表示未锁定。窗口过期即清零，修复“计数只增不减导致永久锁定”。"""
    rec = store.get(key)
    if not rec:
        return 0
    if rec[2] > now:
        return int(rec[2] - now)
    if now - rec[1] > LOGIN_LOCK_SEC:
        store.pop(key, None)
    return 0


def _record_fail(store: dict, key, max_fail: int, now: float):
    rec = store.get(key)
    if not rec or now - rec[1] > LOGIN_LOCK_SEC:
        rec = [1, now, 0.0]
    else:
        rec[0] += 1
    if rec[0] >= max_fail:
        rec[2] = now + LOGIN_LOCK_SEC
    store[key] = rec
    if len(store) > LIMITER_MAX_ENTRIES:
        for k in [k for k, v in list(store.items()) if v[2] <= now and now - v[1] > LOGIN_LOCK_SEC]:
            store.pop(k, None)


def _clear_fails(username: str, ip: str):
    LOGIN_FAILS.pop((username, ip), None)
    IP_FAILS.pop(ip, None)


def csrf_token(uid: int) -> str:
    return _sign(f"csrf:{uid}")


def cookie_secure(request: Request) -> bool:
    """HTTPS（或反代 X-Forwarded-Proto=https）时给 Cookie 加 Secure 标志；
    纯 HTTP 内网部署不加——否则浏览器拒收 Cookie 导致全员掉线。"""
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or proto == "https"


def bad_csrf(user, token: str) -> bool:
    return not hmac.compare_digest(csrf_token(user["id"]).encode("utf-8"), (token or "").encode("utf-8"))


def dl_header(name: str) -> dict:
    """RFC 5987 附件文件名（UTF-8 百分号编码，纯 ASCII 头，兼容浏览器）"""
    from urllib.parse import quote
    return {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe="")}


def alloc_ins_code(conn, today8: str) -> str:
    """分配检查编号 JC-YYYYMMDD-XXX（数据库加固①）：COUNT+1 生成在并发下会撞号，
    调用方按 UNIQUE 约束 IntegrityError 重试；本函数每轮重取流水，并做存在性预检。"""
    for _ in range(30):
        seq = conn.execute("SELECT COUNT(*) c FROM inspections WHERE code LIKE ?",
                           (f"JC-{today8}-%",)).fetchone()["c"] + 1
        code = f"JC-{today8}-{seq:03d}"
        if not conn.execute("SELECT 1 FROM inspections WHERE code=?", (code,)).fetchone():
            return code
    row = conn.execute("SELECT code FROM inspections WHERE code LIKE ? ORDER BY code DESC LIMIT 1",
                       (f"JC-{today8}-%",)).fetchone()
    tail = int(row["code"].rsplit("-", 1)[1]) if row else 0
    return f"JC-{today8}-{tail + 1:03d}"


# ---------------- 认证 ----------------
def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(uid: int, rev: int) -> str:
    exp = (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y%m%d%H%M%S")
    payload = f"{uid}:{rev}:{exp}"
    raw = f"{payload}:{_sign(payload)}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def read_token(token: str):
    """返回 (uid, session_rev)；会话版本不匹配即失效——改密/重置后旧会话作废（审计 P2-5）。"""
    try:
        token = token.strip('"')
        raw = base64.urlsafe_b64decode((token + "=" * (-len(token) % 4)).encode()).decode()
        uid, rev, exp, sig = raw.split(":")
        if not hmac.compare_digest(_sign(f"{uid}:{rev}:{exp}"), sig):
            return None
        if datetime.strptime(exp, "%Y%m%d%H%M%S") < datetime.now():
            return None
        return int(uid), int(rev)
    except Exception:
        return None


def current_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    parsed = read_token(token) if token else None
    if not parsed:
        return None
    uid, rev = parsed
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    conn.close()
    if not row or row["session_rev"] != rev:
        return None
    return row


def require(request: Request, roles=None):
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    if user["must_change_pwd"] and not request.url.path.startswith(("/changepwd", "/logout", "/static")):
        return None, RedirectResponse("/changepwd?msg=首次登录请先修改初始密码", status_code=302)
    if roles and user["role"] not in roles:
        return None, HTMLResponse("<h3>无权访问该功能</h3><p><a href='/'>返回首页</a></p>", status_code=403)
    return user, None


def msg_count(conn, user) -> int:
    """待办提醒总数（逾期+待复核+未签字）——导航红点用，轻量单查询"""
    if not user:
        return 0
    today = date.today().isoformat()
    scope = " AND i.enterprise_id=?" if user["role"] == "enterprise" else ""
    args = [user["enterprise_id"]] if user["role"] == "enterprise" else []
    return conn.execute(
        "SELECT (SELECT COUNT(*) FROM problems p JOIN inspections i ON i.id=p.inspection_id"
        "  WHERE p.status IN ('pending','returned') AND p.deadline<>'' AND p.deadline<?" + scope + ")"
        " + (SELECT COUNT(*) FROM problems p JOIN inspections i ON i.id=p.inspection_id"
        "     WHERE p.status='submitted'" + scope + ")"
        " + (SELECT COUNT(*) FROM inspections i WHERE i.status IN ('closed','archived')"
        "     AND (NOT EXISTS(SELECT 1 FROM signatures s WHERE s.inspection_id=i.id AND s.sign_type='ent')"
        "      OR NOT EXISTS(SELECT 1 FROM signatures s WHERE s.inspection_id=i.id AND s.sign_type='insp'))" + scope + ")",
        [today] + args * 3).fetchone()[0]


def render(request: Request, name: str, ctx: dict, user=None):
    ctx.update({"request": request, "user": user, "APP_NAME": APP_NAME,
                "REC_STATUS_CN": REC_STATUS_CN, "PROB_STATUS_CN": PROB_STATUS_CN,
                "ROLES": ROLES, "msg": request.query_params.get("msg", ""),
                "csrf": csrf_token(user["id"]) if user else ""})
    if user and "msg_count" not in ctx:
        conn = get_db()
        ctx["msg_count"] = msg_count(conn, user)
        conn.close()
    return templates.TemplateResponse(request, name, ctx)
