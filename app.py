# -*- coding: utf-8 -*-
"""水路运输企业检查记录管理平台 — 应用装配入口。

路由按业务模块拆分在 routes_*.py（APIRouter）；共享鉴权/渲染/限速在 webcore.py。
本文件只负责：应用创建、静态目录、中间件（安全响应头/CSP）、健康检查、
全局异常兜底、路由装配、启动参数。
"""
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from config import APP_NAME, HOST, PORT
from db import init_db, get_db
from webcore import IP_FAILS, LIMITER_MAX_ENTRIES, LOGIN_FAILS, templates  # noqa: F401  供测试/运维引用

import routes_admin
import routes_auth
import routes_dash
import routes_enterprise
import routes_inspection
import routes_item
import routes_notify
import routes_plan
import routes_random
import routes_stats

app = FastAPI(title=APP_NAME)
BASE = os.path.dirname(os.path.abspath(__file__))
app.add_middleware(GZipMiddleware, minimum_size=1024)   # HTML/JSON 压缩传输（内网/手机访问更顺）
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
init_db()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """安全响应头（审计 P3-5 + CSP 收紧）：每请求生成 nonce，内联脚本按 nonce 放行，
    其余脚本仅同源——模板已迁离内联事件处理器，不再需要 unsafe-inline。"""
    nonce = secrets.token_urlsafe(16)
    request.state.nonce = nonce
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'nonce-%s'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'" % nonce)
    return response


@app.get("/healthz")
def healthz():
    """健康检查（Docker/运维探活）：确认数据库可读"""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception:
        return Response('{"status":"error"}', status_code=500, media_type="application/json")


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """全局兜底：未捕获异常返回友好错误页并记服务端日志，不向用户暴露堆栈"""
    import traceback
    print("[ERROR] %s %s -> %s\n%s" % (request.method, request.url.path, exc, traceback.format_exc()))
    try:
        return templates.TemplateResponse(
            request, "error.html",
            {"code": 500, "msg": "服务器内部错误，请稍后重试或联系管理员（错误已记入服务端日志）"},
            status_code=500)
    except Exception:
        return HTMLResponse("<h3>500 服务器内部错误</h3>", status_code=500)


for _r in (routes_auth.router, routes_dash.router, routes_enterprise.router, routes_item.router,
           routes_inspection.router, routes_notify.router, routes_plan.router, routes_random.router,
           routes_stats.router, routes_admin.router):
    app.include_router(_r)


def _setup_file_log():
    """运行日志落盘 data\\logs\\app.log（超 5MB 轮转一代）：stdout/stderr 同时写控制台与文件，
    双击启动日志不丢。仅 python app.py 直启时启用，测试/CI 导入模块不受影响。"""
    import sys
    log_dir = os.path.join(BASE, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "app.log")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
            os.replace(path, path + ".1")
    except OSError:
        pass
    fp = open(path, "a", encoding="utf-8", buffering=1)

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, s):
            for st in self.streams:
                try:
                    st.write(s)
                except Exception:
                    pass

        def flush(self):
            for st in self.streams:
                try:
                    st.flush()
                except Exception:
                    pass

    sys.stdout = _Tee(sys.__stdout__, fp)
    sys.stderr = _Tee(sys.__stderr__, fp)


if __name__ == "__main__":
    _setup_file_log()
    import uvicorn
    print(f"[启动] {APP_NAME} http://{HOST}:{PORT}  运行日志：data\\logs\\app.log")
    uvicorn.run(app, host=HOST, port=PORT)
