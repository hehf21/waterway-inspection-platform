# -*- coding: utf-8 -*-
"""路由模块：工作台看板（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 首页看板 ----------------
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user, err = require(request)
    if err: return err
    conn = get_db()
    today = date.today().isoformat()
    ctx = {}
    if user["role"] in GOV_ROLES:
        soon_day = (date.today() + timedelta(days=7)).isoformat()
        ctx["stats"] = {
            "ent": conn.execute("SELECT COUNT(*) c FROM enterprises").fetchone()["c"],
            "ins": conn.execute("SELECT COUNT(*) c FROM inspections").fetchone()["c"],
            "prob_open": conn.execute("SELECT COUNT(*) c FROM problems WHERE status IN ('pending','returned','submitted')").fetchone()["c"],
            "prob_review": conn.execute("SELECT COUNT(*) c FROM problems WHERE status='submitted'").fetchone()["c"],
            "overdue": conn.execute("SELECT COUNT(*) c FROM problems WHERE status IN ('pending','returned') AND deadline<>'' AND deadline<?", (today,)).fetchone()["c"],
            "soon": conn.execute("SELECT COUNT(*) c FROM problems WHERE status IN ('pending','returned') AND deadline>=? AND deadline<=?", (today, soon_day)).fetchone()["c"],
            "closed": conn.execute("SELECT COUNT(*) c FROM inspections WHERE status IN ('closed','archived')").fetchone()["c"],
        }
        ctx["recent"] = conn.execute(
            "SELECT i.*, e.name ent_name FROM inspections i LEFT JOIN enterprises e ON e.id=i.enterprise_id"
            " ORDER BY i.id DESC LIMIT 8").fetchall()
        ctx["wait_review"] = conn.execute(
            "SELECT p.*, i.code ins_code, e.name ent_name FROM problems p"
            " JOIN inspections i ON i.id=p.inspection_id LEFT JOIN enterprises e ON e.id=i.enterprise_id"
            " WHERE p.status='submitted' ORDER BY p.id DESC LIMIT 8").fetchall()
        # 本月态势 + 逾期企业排行（管理视角一眼看家底）
        m0 = date.today().strftime("%Y-%m-01")
        ctx["month"] = conn.execute(
            "SELECT (SELECT COUNT(*) FROM inspections WHERE check_date>=? AND status<>'draft') ins,"
            " (SELECT COUNT(*) FROM problems p JOIN inspections i2 ON i2.id=p.inspection_id"
            "  WHERE i2.check_date>=? AND p.status='passed') passed,"
            " (SELECT COUNT(*) FROM problems p JOIN inspections i2 ON i2.id=p.inspection_id"
            "  WHERE i2.check_date>=?) total",
            (m0, m0, m0)).fetchone()
        ctx["top_overdue"] = conn.execute(
            "SELECT e.name, COUNT(*) c FROM problems p JOIN inspections i ON i.id=p.inspection_id"
            " LEFT JOIN enterprises e ON e.id=i.enterprise_id"
            " WHERE p.status IN ('pending','returned') AND p.deadline<>'' AND p.deadline<?"
            " GROUP BY e.name ORDER BY c DESC LIMIT 3", (today,)).fetchall()
    else:
        eid = user["enterprise_id"]
        soon_day = (date.today() + timedelta(days=7)).isoformat()
        ctx["stats"] = {
            "ins": conn.execute("SELECT COUNT(*) c FROM inspections WHERE enterprise_id=?", (eid,)).fetchone()["c"],
            "prob_open": conn.execute(
                "SELECT COUNT(*) c FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                " WHERE i.enterprise_id=? AND p.status IN ('pending','returned')", (eid,)).fetchone()["c"],
            "prob_review": conn.execute(
                "SELECT COUNT(*) c FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                " WHERE i.enterprise_id=? AND p.status='submitted'", (eid,)).fetchone()["c"],
            "overdue": conn.execute(
                "SELECT COUNT(*) c FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                " WHERE i.enterprise_id=? AND p.status IN ('pending','returned') AND p.deadline<>'' AND p.deadline<?",
                (eid, today)).fetchone()["c"],
            "soon": conn.execute(
                "SELECT COUNT(*) c FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                " WHERE i.enterprise_id=? AND p.status IN ('pending','returned') AND p.deadline>=? AND p.deadline<=?",
                (eid, today, soon_day)).fetchone()["c"],
        }
        ctx["recent"] = conn.execute(
            "SELECT i.*, e.name ent_name FROM inspections i LEFT JOIN enterprises e ON e.id=i.enterprise_id"
            " WHERE i.enterprise_id=? ORDER BY i.id DESC LIMIT 8", (eid,)).fetchall()
        # 企业端“待我整改”直达清单：登录第一屏就能看到该干什么
        ctx["my_todos"] = conn.execute(
            "SELECT p.*, i.code ins_code, i.id iid FROM problems p JOIN inspections i ON i.id=p.inspection_id"
            " WHERE i.enterprise_id=? AND p.status IN ('pending','returned')"
            " ORDER BY CASE WHEN p.deadline='' THEN 1 ELSE 0 END, p.deadline", (eid,)).fetchall()
        ctx["wait_review"] = []
    conn.close()
    return render(request, "dashboard.html", ctx, user)


