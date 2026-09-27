# -*- coding: utf-8 -*-
"""路由模块：消息提醒与群机器人推送 / 双随机结果公示（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 消息提醒中心（逾期/临期/待复核/未签字 + 群机器人定时推送） ----------------
def _reminders(conn, user):
    """按角色汇总待办提醒：政府=全部；企业=本企业。提醒不能只靠人肉盯台账。"""
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=7)).isoformat()
    ent_scope, ent_args = "", []
    if user["role"] == "enterprise":
        ent_scope = " AND i.enterprise_id=?"
        ent_args = [user["enterprise_id"]]
    out = {}
    out["overdue"] = conn.execute(
        "SELECT p.*, i.code ins_code, i.id iid, e.name ent_name FROM problems p"
        " JOIN inspections i ON i.id=p.inspection_id LEFT JOIN enterprises e ON e.id=i.enterprise_id"
        " WHERE p.status IN ('pending','returned') AND p.deadline<>'' AND p.deadline<?" + ent_scope +
        " ORDER BY p.deadline LIMIT 200", [today] + ent_args).fetchall()
    out["soon"] = conn.execute(
        "SELECT p.*, i.code ins_code, i.id iid, e.name ent_name FROM problems p"
        " JOIN inspections i ON i.id=p.inspection_id LEFT JOIN enterprises e ON e.id=i.enterprise_id"
        " WHERE p.status IN ('pending','returned') AND p.deadline>=? AND p.deadline<=?" + ent_scope +
        " ORDER BY p.deadline LIMIT 200", [today, soon] + ent_args).fetchall()
    out["wait_review"] = conn.execute(
        "SELECT p.*, i.code ins_code, i.id iid, e.name ent_name FROM problems p"
        " JOIN inspections i ON i.id=p.inspection_id LEFT JOIN enterprises e ON e.id=i.enterprise_id"
        " WHERE p.status='submitted'" + ent_scope + " ORDER BY p.id DESC LIMIT 200", ent_args).fetchall()
    out["unsigned"] = conn.execute(
        "SELECT i.id, i.code, i.check_date, e.name ent_name FROM inspections i"
        " LEFT JOIN enterprises e ON e.id=i.enterprise_id"
        " WHERE i.status IN ('closed','archived')"
        " AND (NOT EXISTS(SELECT 1 FROM signatures s WHERE s.inspection_id=i.id AND s.sign_type='ent')"
        "  OR NOT EXISTS(SELECT 1 FROM signatures s WHERE s.inspection_id=i.id AND s.sign_type='insp'))"
        + ent_scope + " ORDER BY i.id DESC LIMIT 20", ent_args).fetchall()
    return out


@router.get("/messages", response_class=HTMLResponse)
def messages_page(request: Request):
    user, err = require(request)
    if err: return err
    conn = get_db()
    r = _reminders(conn, user)
    conn.close()
    return render(request, "messages.html", {"r": r, "webhook_on": bool(WEBHOOK_URL)}, user)


def _push_webhook(text: str) -> bool:
    """企业微信群机器人推送（msgtype=text）；未配置地址返回 False"""
    if not WEBHOOK_URL:
        return False
    import urllib.request
    payload = json.dumps({"msgtype": "text", "text": {"content": text}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print("[提醒推送失败]", exc)
        return False


def _reminder_text() -> str:
    conn = get_db()
    r = _reminders(conn, {"role": "gov_admin", "enterprise_id": None})
    conn.close()
    lines = [f"【{APP_NAME} 每日提醒】{date.today().isoformat()}"]
    lines.append(f"逾期未整改 {len(r['overdue'])} 项；7天内到期 {len(r['soon'])} 项；"
                 f"待复核 {len(r['wait_review'])} 项；未完成签字 {len(r['unsigned'])} 条")
    for p in r["overdue"][:5]:
        days = (date.today() - date.fromisoformat(p["deadline"])).days
        lines.append(f"· 逾期{days}天：{p['ent_name']} {p['ins_code']}-P{p['seq']}（{(p['description'] or '')[:20]}）")
    if len(r["overdue"]) > 5:
        lines.append(f"· …另有 {len(r['overdue']) - 5} 项逾期")
    for p in r["soon"][:5]:
        lines.append(f"· 临期（{p['deadline']}）：{p['ent_name']} {p['ins_code']}-P{p['seq']}")
    lines.append("详见平台 → 消息提醒")
    return "\n".join(lines)


@router.post("/messages/push")
def messages_push(request: Request, csrf: str = Form("")):
    user, err = require(request, ("gov_admin",))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    ok = _push_webhook(_reminder_text())
    conn = get_db()
    audit(conn, user["username"], "手动推送提醒", "system", "", "推送成功" if ok else "推送失败（未配置或网络不通）")
    conn.commit(); conn.close()
    return RedirectResponse(f"/messages?msg={'提醒已推送到群机器人' if ok else '推送失败：请检查 SLYS_WEBHOOK_URL 配置与网络'}",
                            status_code=302)


def _daily_push_loop():
    """每日定时把逾期/临期提醒推到群机器人（SLYS_PUSH_TIME，默认 08:30）"""
    import time as _time
    while True:
        try:
            parts = (PUSH_TIME.split(":") + ["0", "0"])[:2]
            target = datetime.now().replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
            if target <= datetime.now():
                target += timedelta(days=1)
            _time.sleep(max(60.0, (target - datetime.now()).total_seconds()))
            if WEBHOOK_URL and _push_webhook(_reminder_text()):
                print(f"[定时提醒] {datetime.now():%Y-%m-%d %H:%M} 已推送每日提醒")
        except Exception as exc:
            print("[定时提醒] 异常：", exc)
            _time.sleep(60)


if WEBHOOK_URL:
    threading.Thread(target=_daily_push_loop, daemon=True).start()
    print(f"[定时提醒] 已启用：每日 {PUSH_TIME} 推送提醒到群机器人")


# ---------------- 双随机抽查结果公示（“一公开”，无需登录） ----------------
@router.get("/public/random", response_class=HTMLResponse)
def public_random(request: Request):
    if not PUBLIC_RANDOM_NOTICE:
        return render(request, "public_notice.html", {"batches": [], "closed": True, "org": ORG_NAME}, None)
    conn = get_db()
    batches = []
    for d in conn.execute("SELECT * FROM random_draws ORDER BY id DESC LIMIT 20").fetchall():
        info = json.loads(d["detail"] or "{}")
        dids = info.get("draft_ids", [])
        rows = []
        for e in info.get("ents", []):
            concl, cdate = "检查中", ""
            for iid in dids:
                rr = conn.execute("SELECT conclusion, check_date FROM inspections WHERE id=? AND enterprise_id=?",
                                  (iid, e["id"])).fetchone()
                if rr:
                    concl = rr["conclusion"] or "已检查"
                    cdate = rr["check_date"]
                    break
            rows.append({"name": e["name"], "conclusion": concl, "date": cdate})
        batches.append({"t": d["created_at"],
                        "type": "双随机（企业+检查员）" if d["draw_type"] == "double" else "随机抽取企业",
                        "seed": d["seed"], "ents": rows})
    conn.close()
    return render(request, "public_notice.html", {"batches": batches, "closed": False, "org": ORG_NAME}, None)


