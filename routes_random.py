# -*- coding: utf-8 -*-
"""路由模块：双随机抽查（随机抽企业 + 随机派检查员）（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 双随机抽查（随机抽取检查对象 + 随机选派检查人员） ----------------
@router.get("/random", response_class=HTMLResponse)
def random_page(request: Request):
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    ent_cnt = conn.execute("SELECT COUNT(*) c FROM enterprises").fetchone()["c"]
    inspectors = conn.execute("SELECT id, username, real_name, role FROM users"
                              " WHERE active=1 AND role IN ('gov_staff','gov_admin') ORDER BY id").fetchall()
    rows = []
    for d in conn.execute("SELECT * FROM random_draws ORDER BY id DESC LIMIT 50").fetchall():
        r = dict(d)
        info = json.loads(d["detail"] or "{}")
        r["ent_names"] = [e["name"] for e in info.get("ents", [])]
        r["insp_names"] = [i["name"] for i in info.get("insps", [])]
        r["draft_ids"] = info.get("draft_ids", [])
        rows.append(r)
    conn.close()
    return render(request, "random.html",
                  {"draws": rows, "ent_cnt": ent_cnt, "inspectors": inspectors}, user)


@router.post("/random/draw")
async def random_draw(request: Request, csrf: str = Form(""), draw_type: str = Form("double"),
                      ent_count: int = Form(5), insp_count: int = Form(2),
                      exclude_days: int = Form(90), make_drafts: int = Form(0), note: str = Form("")):
    """双随机抽取：企业与检查员均随机选派；随机种子入档，抽取过程可按种子复现复核。"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if draw_type not in ("single", "double"):
        return HTMLResponse("抽查类型不合法", status_code=400)
    ent_count = max(1, min(ent_count, 200))
    insp_count = max(1, min(insp_count, 5))
    exclude_days = max(0, min(exclude_days, 365))
    conn = get_db()
    if exclude_days:
        since = (date.today() - timedelta(days=exclude_days)).isoformat()
        pool = conn.execute("SELECT * FROM enterprises WHERE id NOT IN"
                            " (SELECT DISTINCT enterprise_id FROM inspections WHERE check_date>=?)"
                            " ORDER BY id", (since,)).fetchall()
    else:
        pool = conn.execute("SELECT * FROM enterprises ORDER BY id").fetchall()
    if len(pool) < ent_count:
        conn.close()
        return RedirectResponse(f"/random?msg=可抽企业仅{len(pool)}家（排除近{exclude_days}天已检查后），少于要抽的{ent_count}家",
                                status_code=302)
    insp_pool = conn.execute("SELECT id, username, real_name, role FROM users"
                             " WHERE active=1 AND role IN ('gov_staff','gov_admin') ORDER BY id").fetchall()
    if draw_type == "double" and len(insp_pool) < insp_count:
        conn.close()
        return RedirectResponse(f"/random?msg=可派检查员仅{len(insp_pool)}人，少于要派的{insp_count}人", status_code=302)
    # 用随机种子抽样：种子入库，任何人可用同一池子按种子复现结果，验证抽样公正
    seed = secrets.token_hex(8)
    rng = random.Random(seed)
    ents = rng.sample(list(pool), ent_count)
    insps = rng.sample(list(insp_pool), insp_count) if draw_type == "double" else []
    insp_names = "、".join(i["real_name"] for i in insps)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    draft_ids = []
    if make_drafts:
        today = date.today().isoformat()
        today8 = datetime.now().strftime("%Y%m%d")
        for e in ents:
            cur = None
            for _ in range(30):   # 批量生成草稿编号，撞号（UNIQUE）时重取流水
                code = alloc_ins_code(conn, today8)
                try:
                    cur = conn.execute(
                        "INSERT INTO inspections(code,enterprise_id,template_id,parent_id,check_type,check_mode,check_date,"
                        "location,inspectors,conclusion,conclusion_note,status,deadline,created_by,created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',?,?,?)",
                        (code, e["id"], 0, 0, "双随机抽查", "现场检查", today, "", insp_names, "", "", "",
                         user["username"], now))
                    break
                except sqlite3.IntegrityError:
                    continue
            if cur is not None:
                draft_ids.append(cur.lastrowid)
    detail = json.dumps({
        "ents": [{"id": e["id"], "name": e["name"], "license_type": e["license_type"]} for e in ents],
        "insps": [{"id": i["id"], "name": i["real_name"], "role": i["role"]} for i in insps],
        "draft_ids": draft_ids,
    }, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO random_draws(draw_type,ent_count,insp_count,exclude_days,seed,ent_ids,insp_ids,detail,note,"
        "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (draw_type, ent_count, len(insps), exclude_days, seed,
         ",".join(str(e["id"]) for e in ents), ",".join(str(i["id"]) for i in insps),
         detail, note, user["username"], now))
    audit(conn, user["username"], "双随机抽查抽取", "random_draw", cur.lastrowid,
          f"抽取企业{len(ents)}家" + (f"、选派检查员{insp_names}" if insps else "（仅抽企业）")
          + f"；随机种子{seed}" + (f"；生成检查草稿{len(draft_ids)}条" if draft_ids else ""))
    conn.commit(); conn.close()
    return RedirectResponse(f"/random?msg=抽取完成：企业{len(ents)}家"
                            + (f"、检查员{insp_names}" if insps else ""), status_code=302)


@router.get("/random/{did}/export")
def random_export(request: Request, did: int):
    """导出双随机抽查结果表（Excel：抽取信息/抽中企业/选派检查员/生成草稿）"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    d = conn.execute("SELECT * FROM random_draws WHERE id=?", (did,)).fetchone()
    if not d:
        conn.close(); return HTMLResponse("抽取记录不存在", status_code=404)
    info = json.loads(d["detail"] or "{}")
    wb = Workbook()
    ws = wb.active
    ws.title = "抽取信息"
    ws.append(["抽取时间", d["created_at"]])
    ws.append(["抽取类型", "双随机（企业+检查员）" if d["draw_type"] == "double" else "随机抽取企业"])
    ws.append(["抽取企业数", d["ent_count"]])
    ws.append(["选派检查员数", d["insp_count"]])
    ws.append(["排除近N天已检查", d["exclude_days"]])
    ws.append(["随机种子", d["seed"]])
    ws.append(["备注", d["note"]])
    ws.append(["抽取人", d["created_by"]])
    ws.append(["说明", "同一企业池按本随机种子可复现本次抽取结果，用于验证抽样公正"])
    ws2 = wb.create_sheet("抽中企业")
    ws2.append(["序号", "企业名称", "经营类别"])
    for i, e in enumerate(info.get("ents", []), 1):
        ws2.append([i, e["name"], e.get("license_type", "")])
    ws3 = wb.create_sheet("选派检查员")
    ws3.append(["序号", "姓名", "角色"])
    for i, p in enumerate(info.get("insps", []), 1):
        ws3.append([i, p["name"], ROLES.get(p.get("role", ""), p.get("role", ""))])
    ws4 = wb.create_sheet("生成检查草稿")
    ws4.append(["草稿ID", "检查编号", "企业", "状态"])
    for did2 in info.get("draft_ids", []):
        r = conn.execute("SELECT i.id, i.code, e.name ent, i.status FROM inspections i"
                         " LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE i.id=?", (did2,)).fetchone()
        if r:
            ws4.append([r["id"], r["code"], r["ent"], REC_STATUS_CN.get(r["status"], r["status"])])
    audit(conn, user["username"], "导出双随机抽查结果", "random_draw", did, f"抽取批次#{did}")
    conn.commit(); conn.close()
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=dl_header(f"双随机抽查结果_{d['created_at'][:10]}_批次{did}.xlsx"))


