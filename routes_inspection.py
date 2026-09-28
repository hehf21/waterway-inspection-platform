# -*- coding: utf-8 -*-
"""路由模块：检查记录登记 / 现场登记 / 整改与复核 / 签字 / 打印与归档打包（由 app.py 拆分生成）"""
from fastapi import APIRouter, File, Form, Request, UploadFile

from webcore import *  # noqa: F401,F403

router = APIRouter()

# ---------------- 检查记录登记 ----------------
@router.get("/inspections", response_class=HTMLResponse)
def ins_list(request: Request, q: str = "", status: str = "", enterprise_id: int = 0,
             check_type: str = "", check_mode: str = "", conclusion: str = "",
             date_from: str = "", date_to: str = "", p: int = 1):
    user, err = require(request)
    if err: return err
    conn = get_db()
    sql = ("SELECT i.*, e.name ent_name FROM inspections i LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE 1=1")
    args = []
    if user["role"] == "enterprise":
        sql += " AND i.enterprise_id=?"; args.append(user["enterprise_id"])
        # 草稿是企业尚未收到的在办记录，未下发不应对企业可见（审计 P1-5）
        sql += " AND i.status<>'draft'"
    if q:  # 关键字：企业名称/检查编号/检查人员/检查地点/结论说明
        sql += (" AND (e.name LIKE ? OR i.code LIKE ? OR i.inspectors LIKE ? OR i.location LIKE ?"
                " OR i.conclusion_note LIKE ?)")
        args += [f"%{q}%"] * 5
    if status:
        sql += " AND i.status=?"; args.append(status)
    if enterprise_id:
        sql += " AND i.enterprise_id=?"; args.append(enterprise_id)
    if check_type:
        sql += " AND i.check_type=?"; args.append(check_type)
    if check_mode:
        sql += " AND i.check_mode=?"; args.append(check_mode)
    if conclusion:
        sql += " AND i.conclusion=?"; args.append(conclusion)
    if date_from:
        sql += " AND i.check_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND i.check_date<=?"; args.append(date_to)
    # 分页（每页50条）：记录多了之后列表不再一次性全量渲染
    page_size = 50
    p = max(1, p)
    total = conn.execute(f"SELECT COUNT(*) c FROM ({sql})", args).fetchone()["c"]
    rows = conn.execute(sql + " ORDER BY i.id DESC LIMIT ? OFFSET ?",
                        args + [page_size, (p - 1) * page_size]).fetchall()
    ents = conn.execute("SELECT id, name FROM enterprises ORDER BY name").fetchall()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in {"q": q, "status": status, "enterprise_id": enterprise_id or "",
                                      "check_type": check_type, "check_mode": check_mode,
                                      "conclusion": conclusion, "date_from": date_from,
                                      "date_to": date_to}.items() if v})
    return render(request, "inspections.html",
                  {"rows": rows, "q": q, "status": status, "ents": ents, "f_ent": enterprise_id,
                   "f_type": check_type, "f_mode": check_mode, "f_concl": conclusion,
                   "d_from": date_from, "d_to": date_to,
                   "p": p, "pages": pages, "total": total, "qs": qs,
                   "CHECK_TYPES": CHECK_TYPES, "CHECK_MODES": CHECK_MODES,
                   "CONCLUSIONS": CONCLUSIONS}, user)


def _draft_payload(conn, ins_id: int):
    """草稿内容加载（登记页/现场登记页共用）：(ins, 检查项快照, 问题)；非草稿或不存在返回 (None,None,None)"""
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins or ins["status"] != "draft":
        return None, None, None
    its = [dict(r) for r in conn.execute(
        "SELECT * FROM inspection_items WHERE inspection_id=? ORDER BY sort_order", (ins_id,))]
    ins_items = [{**it, "code": it["item_code"], "name": it["item_name"], "content": it["item_content"],
                  "basis": it["legal_basis"]} for it in its]
    prs = [dict(r) for r in conn.execute("SELECT * FROM problems WHERE inspection_id=? ORDER BY seq", (ins_id,))]
    ins_probs = [{"item_id": p["item_id"], "description": p["description"], "basis": p["legal_basis"],
                  "requirement": p["requirement"], "deadline": p["deadline"], "responsible": p["responsible"],
                  "to_msa": bool(p["to_msa"])} for p in prs]
    return ins, ins_items, ins_probs


@router.get("/inspections/new", response_class=HTMLResponse)
def ins_new(request: Request, edit: int = 0):
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    ents = conn.execute("SELECT * FROM enterprises ORDER BY name").fetchall()
    tpls = conn.execute("SELECT * FROM check_templates WHERE active=1 ORDER BY id").fetchall()
    tpl_items = {}
    for t in tpls:
        tpl_items[t["id"]] = [dict(r) for r in conn.execute(
            "SELECT ci.* FROM template_items ti JOIN check_items ci ON ci.id=ti.item_id"
            " WHERE ti.template_id=? ORDER BY ti.sort_order", (t["id"],))]
    # 直接传 Python 对象，由模板 |tojson 输出（Jinja2 会转义 < > & '）；
    # 不再 json.dumps + |safe，避免 </script> 逃逸造成存储型 XSS（审计 P0-2）
    ins = ins_items = ins_probs = None
    if edit:
        ins, ins_items, ins_probs = _draft_payload(conn, edit)
        if not ins:
            conn.close()
            return HTMLResponse("只有草稿状态的检查记录可以编辑", status_code=400)
    all_items = [dict(r) for r in conn.execute("SELECT * FROM check_items WHERE active=1 ORDER BY code")]
    recents = conn.execute("SELECT id, code, check_date, check_type FROM inspections"
                           " WHERE status<>'draft' ORDER BY id DESC LIMIT 50").fetchall()
    plan_items = conn.execute("SELECT pi.id, pi.check_type, pi.period, pi.count_plan, p.title"
                              " FROM plan_items pi JOIN plans p ON p.id=pi.plan_id"
                              " WHERE p.status='issued' ORDER BY p.id DESC, pi.id").fetchall()
    gov_names = [r["real_name"] for r in conn.execute(
        "SELECT real_name FROM users WHERE role LIKE 'gov%' AND active=1 ORDER BY real_name")]
    conn.close()
    return render(request, "inspection_new.html",
                  {"ents": ents, "tpls": tpls, "tpl_items": tpl_items, "all_items": all_items,
                   "recents": recents, "plan_items": plan_items, "gov_names": gov_names,
                   "CHECK_TYPES": CHECK_TYPES, "CHECK_MODES": CHECK_MODES,
                   "ins": ins, "ins_items": ins_items, "ins_probs": ins_probs}, user)


def _save_uploads(files, owner_type, owner_id, username, conn):
    """附件保存：分块流式落盘、边写边判大小，不合格的返回具体原因（审计 P2-4）。

    返回 (saved, rejected)；rejected 为 [(文件名, 原因)]，调用方需把原因回显给用户，
    不再像原来那样静默丢弃。
    """
    from config import UPLOAD_DIR
    saved, rejected = [], []
    limit = MAX_UPLOAD_MB * 1024 * 1024
    chunk_size = 1024 * 1024
    for f in files:
        if not f or not f.filename:
            continue
        name = os.path.basename(f.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXT:
            rejected.append((name, "文件类型不在允许范围"))
            continue
        stored = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOAD_DIR, stored)
        size, sha, failed, reason = 0, hashlib.sha256(), False, ""
        try:
            with open(dest, "wb") as fp:
                while True:
                    chunk = f.file.read(chunk_size)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        failed, reason = True, f"超过单件 {MAX_UPLOAD_MB}MB 上限"
                        break
                    sha.update(chunk)
                    fp.write(chunk)
        except OSError:
            failed, reason = True, "写入失败"
        if not failed and size == 0:
            failed, reason = True, "空文件"
        if failed:
            try:
                os.remove(dest)
            except OSError:
                pass
            rejected.append((name, reason))
            continue
        conn.execute("INSERT INTO attachments(owner_type,owner_id,filename,stored_name,sha256,size,uploaded_by,uploaded_at)"
                     " VALUES(?,?,?,?,?,?,?,?)",
                     (owner_type, owner_id, name, stored, sha.hexdigest(), size, username,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        saved.append(name)
    return saved, rejected


@router.post("/inspections/save")
async def ins_save(request: Request,
                   ins_id: int = Form(0), csrf: str = Form(""),
                   enterprise_id: int = Form(...), template_id: int = Form(0),
                   parent_id: int = Form(0), plan_item_id: int = Form(0), check_type: str = Form(...),
                   check_mode: str = Form("现场检查"), check_date: str = Form(...), location: str = Form(""),
                   inspectors: str = Form(""), deadline: str = Form(""), conclusion: str = Form(""),
                   conclusion_note: str = Form(""),
                   items_json: str = Form("[]"), problems_json: str = Form("[]"), next: str = Form(""),
                   files: list[UploadFile] = File(default=[])):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    # 服务端校验：JSON 可解析、枚举合法、问题必填项齐全（审计 P2-2 / P2-3）
    try:
        items = json.loads(items_json)
        problems = json.loads(problems_json)
    except (ValueError, TypeError):
        return HTMLResponse("提交的数据格式不正确，请返回刷新后重试", status_code=400)
    if not isinstance(items, list) or not isinstance(problems, list):
        return HTMLResponse("提交的数据格式不正确", status_code=400)
    if check_type not in CHECK_TYPES or check_mode not in CHECK_MODES:
        return HTMLResponse("检查类型或检查方式不合法", status_code=400)
    if conclusion not in CONCLUSIONS:
        return HTMLResponse("检查结论不合法", status_code=400)
    for it in items:
        if it.get("result") not in (RESULT_OK, RESULT_NG, RESULT_NA, RESULT_UNCHECKED):
            return HTMLResponse("逐项检查结果只能为 符合/不符合/不适用/未检查", status_code=400)
    for p in problems:
        if not str(p.get("description", "")).strip() or not str(p.get("requirement", "")).strip():
            return HTMLResponse("问题的描述与整改要求均不能为空", status_code=400)
    conn = get_db()
    # 纵深防御：必填项与引用完整性不依赖前端（绕过浏览器直发请求也进不了库）
    if not str(check_date).strip():
        conn.close(); return HTMLResponse("检查日期不能为空", status_code=400)
    if not str(inspectors).strip():
        conn.close(); return HTMLResponse("检查人员不能为空", status_code=400)
    if not conn.execute("SELECT 1 FROM enterprises WHERE id=?", (enterprise_id,)).fetchone():
        conn.close(); return HTMLResponse("被检查企业不存在，请返回刷新后重新选择", status_code=400)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ins = None

    if ins_id:  # 草稿编辑
        ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
        if not ins or ins["status"] != "draft":
            conn.close(); return HTMLResponse("只有草稿状态的检查记录可以编辑", status_code=400)
        # 改动留痕：先抓修改前快照（审计 P1-7）
        before_snap = json.dumps({
            "enterprise_id": ins["enterprise_id"], "template_id": ins["template_id"],
            "check_type": ins["check_type"], "check_mode": ins["check_mode"], "check_date": ins["check_date"],
            "location": ins["location"], "inspectors": ins["inspectors"], "conclusion": ins["conclusion"],
            "conclusion_note": ins["conclusion_note"], "deadline": ins["deadline"],
            "items": [{k: r[k] for k in ("item_code", "result", "finding")}
                      for r in conn.execute("SELECT item_code,result,finding FROM inspection_items"
                                            " WHERE inspection_id=? ORDER BY sort_order", (ins_id,))],
            "problems": [{k: r[k] for k in ("description", "requirement", "deadline")}
                         for r in conn.execute("SELECT description,requirement,deadline FROM problems"
                                               " WHERE inspection_id=? ORDER BY seq", (ins_id,))],
        }, ensure_ascii=False)
        conn.execute("UPDATE inspections SET enterprise_id=?,template_id=?,parent_id=?,plan_item_id=?,"
                     "check_type=?,check_mode=?,"
                     "check_date=?,"
                     "location=?,inspectors=?,conclusion=?,conclusion_note=?,deadline=? WHERE id=?",
                     (enterprise_id, template_id, parent_id or 0, plan_item_id or 0, check_type, check_mode,
                      check_date, location,
                      inspectors, conclusion, conclusion_note, deadline, ins_id))
        conn.execute("DELETE FROM inspection_items WHERE inspection_id=?", (ins_id,))
        conn.execute("DELETE FROM problems WHERE inspection_id=?", (ins_id,))
    else:
        today = datetime.now().strftime("%Y%m%d")
        cur = None
        for _ in range(30):   # 编号撞号（UNIQUE）时重取流水，抗并发登记
            code = alloc_ins_code(conn, today)
            try:
                cur = conn.execute(
                    "INSERT INTO inspections(code,enterprise_id,template_id,parent_id,plan_item_id,check_type,check_mode,"
                    "check_date,location,"
                    "inspectors,conclusion,conclusion_note,status,deadline,created_by,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'draft',?,?,?)",
                    (code, enterprise_id, template_id, parent_id or 0, plan_item_id or 0, check_type, check_mode,
                     check_date, location,
                     inspectors, conclusion, conclusion_note, deadline, user["username"], now))
                break
            except sqlite3.IntegrityError:
                continue
        if cur is None:
            conn.close(); return HTMLResponse("生成检查编号失败，请稍后重试", status_code=500)
        ins_id = cur.lastrowid

    for i, it in enumerate(items):
        conn.execute("INSERT INTO inspection_items(inspection_id,item_code,category,item_name,item_content,"
                     "legal_basis,method,criteria,is_key,is_veto,score,result,finding,sort_order)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ins_id, it.get("code", ""), it.get("category", ""), it.get("name", ""),
                      it.get("content", ""), it.get("basis", ""), it.get("method", ""), it.get("criteria", ""),
                      it.get("is_key", 0), it.get("is_veto", 0), it.get("score", 0),
                      it.get("result", ""), it.get("finding", ""), i))
    for i, p in enumerate(problems, 1):
        conn.execute("INSERT INTO problems(inspection_id,seq,item_id,description,legal_basis,requirement,"
                     "deadline,responsible,status,to_msa,created_at) VALUES(?,?,?,?,?,?,?,?,'pending',?,?)",
                     (ins_id, i, p.get("item_id"), p.get("description", ""), p.get("basis", ""),
                      p.get("requirement", ""), p.get("deadline", deadline), p.get("responsible", ""),
                      1 if p.get("to_msa") else 0, now))
    saved, rejected = _save_uploads(files, "inspection", ins_id, user["username"], conn)
    warn = "" if not rejected else "；".join(f"{n}（{r}）" for n, r in rejected)
    if ins is not None:
        after_snap = json.dumps({
            "enterprise_id": enterprise_id, "template_id": template_id, "check_type": check_type,
            "check_mode": check_mode, "check_date": check_date, "location": location,
            "inspectors": inspectors, "conclusion": conclusion, "conclusion_note": conclusion_note,
            "deadline": deadline,
            "items": [{k: it.get(k) for k in ("code", "result", "finding")} for it in items],
            "problems": [{k: p.get(k) for k in ("description", "requirement", "deadline")} for p in problems],
        }, ensure_ascii=False)
        audit(conn, user["username"], "修改检查记录(草稿)", "inspection", ins_id, ins["code"],
              before=before_snap, after=after_snap)
        conn.commit(); conn.close()
        msg = "草稿已更新" + (f"；以下附件未保存：{warn}" if warn else "")
        return RedirectResponse(f"/inspections/{ins_id}?msg={msg}", status_code=302)
    audit(conn, user["username"], "登记检查记录", "inspection", ins_id,
          f"{code} 检查项{len(items)}项 问题{len(problems)}项 附件{len(saved)}件"
          + (f" 未通过：{warn}" if warn else ""))
    conn.commit(); conn.close()
    msg = "登记成功，可在详情页下发整改通知" + (f"；以下附件未保存：{warn}" if warn else "")
    if next == "new":   # 连录：保存后直接进入下一家登记
        return RedirectResponse(f"/inspections/new?msg=已保存 {code}，可继续登记下一家", status_code=302)
    return RedirectResponse(f"/inspections/{ins_id}?msg={msg}", status_code=302)


@router.post("/inspections/{ins_id}/delete")
def ins_delete(request: Request, ins_id: int, csrf: str = Form("")):
    """删除草稿检查记录（仅草稿可删，含级联数据与附件文件）"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    from config import UPLOAD_DIR
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] != "draft":
        conn.close(); return HTMLResponse("只有草稿状态的检查记录可以删除（已下发的记录请走更正留痕流程）", status_code=400)
    for a in conn.execute("SELECT * FROM attachments WHERE owner_type='inspection' AND owner_id=?", (ins_id,)):
        try:
            os.remove(os.path.join(UPLOAD_DIR, a["stored_name"]))
        except OSError:
            pass
    conn.execute("DELETE FROM attachments WHERE owner_type='inspection' AND owner_id=?", (ins_id,))
    conn.execute("DELETE FROM inspection_items WHERE inspection_id=?", (ins_id,))
    conn.execute("DELETE FROM problems WHERE inspection_id=?", (ins_id,))
    conn.execute("DELETE FROM inspections WHERE id=?", (ins_id,))
    audit(conn, user["username"], "删除检查记录(草稿)", "inspection", ins_id, ins["code"])
    conn.commit(); conn.close()
    return RedirectResponse("/inspections?msg=草稿已删除", status_code=302)


@router.post("/inspections/{ins_id}/reopen")
def ins_reopen(request: Request, ins_id: int, csrf: str = Form(""), reason: str = Form(...)):
    """更正留痕：解除已归档记录的锁定，全程留痕"""
    user, err = require(request, ("gov_admin", "sysadmin"))
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if not reason.strip():
        return HTMLResponse("必须填写更正理由", status_code=400)
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] != "archived":
        conn.close(); return HTMLResponse("仅已归档记录需要更正留痕", status_code=400)
    conn.execute("UPDATE inspections SET status='closed' WHERE id=?", (ins_id,))
    audit(conn, user["username"], "更正留痕-解除归档锁定", "inspection", ins_id, f"{ins['code']} 理由：{reason}")
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{ins_id}?msg=已解除归档锁定（更正留痕已记录），更正后请重新打包归档", status_code=302)


@router.get("/inspections/{ins_id}", response_class=HTMLResponse)
def ins_detail(request: Request, ins_id: int):
    user, err = require(request)
    if err: return err
    conn = get_db()
    ins = conn.execute("SELECT i.*, e.name ent_name, e.credit_code, e.license_no FROM inspections i"
                       " LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE i.id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if user["role"] not in GOV_ROLES + ("sysadmin",) and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    # 草稿未下发，企业端不可见（与列表口径一致，审计 P1-5）
    if user["role"] == "enterprise" and ins["status"] == "draft":
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    items = conn.execute("SELECT * FROM inspection_items WHERE inspection_id=? ORDER BY sort_order", (ins_id,)).fetchall()
    problems = conn.execute("SELECT * FROM problems WHERE inspection_id=? ORDER BY seq", (ins_id,)).fetchall()
    # 反馈/复核/附件批量取回，避免每问题 3~4 次查询（N+1 优化）
    pids = [p["id"] for p in problems]
    fbs, rvs, atts_all = {}, {}, {}
    if pids:
        marks = ",".join("?" * len(pids))
        for f in conn.execute(f"SELECT * FROM feedbacks WHERE problem_id IN ({marks}) ORDER BY round", pids):
            fbs.setdefault(f["problem_id"], []).append(f)
        for r in conn.execute(f"SELECT * FROM reviews WHERE problem_id IN ({marks}) ORDER BY reviewed_at", pids):
            rvs.setdefault(r["problem_id"], []).append(r)
        for a in conn.execute(f"SELECT * FROM attachments WHERE owner_type='problem' AND owner_id IN ({marks})", pids):
            atts_all.setdefault(("problem", a["owner_id"]), []).append(a)
        fids = [f["id"] for lst in fbs.values() for f in lst]
        if fids:
            marks2 = ",".join("?" * len(fids))
            for a in conn.execute(f"SELECT * FROM attachments WHERE owner_type='feedback' AND owner_id IN ({marks2})", fids):
                atts_all.setdefault(("feedback", a["owner_id"]), []).append(a)
    probs = []
    for p in problems:
        d = dict(p)
        d["seq_label"] = f"P{p['seq']}"
        d["feedbacks"] = fbs.get(p["id"], [])
        d["reviews"] = rvs.get(p["id"], [])
        # 整改前后对比：检查现场照片=整改前；企业反馈照片=整改后（复核直观）
        d["atts_before"] = list(atts_all.get(("problem", p["id"]), []))
        _after = []
        for f in d["feedbacks"]:
            _after += atts_all.get(("feedback", f["id"]), [])
        d["atts_after"] = _after
        d["atts"] = d["atts_before"] + _after
        probs.append(d)
    ins_atts = conn.execute("SELECT * FROM attachments WHERE owner_type='inspection' AND owner_id=?", (ins_id,)).fetchall()
    corrections = conn.execute("SELECT * FROM audit_logs WHERE action='更正留痕-解除归档锁定' AND entity='inspection'"
                               " AND entity_id=? ORDER BY id DESC", (str(ins_id),)).fetchall()
    # 复查关联（审计 P2-10）：本记录复查的原记录 + 本记录的复查记录
    parent = None
    if ins["parent_id"]:
        parent = conn.execute("SELECT id, code, check_date, check_type, status FROM inspections WHERE id=?",
                              (ins["parent_id"],)).fetchone()
    children = conn.execute("SELECT id, code, check_date, check_type, status FROM inspections"
                            " WHERE parent_id=? ORDER BY id DESC", (ins_id,)).fetchall()
    signs = {s["sign_type"]: s for s in
             conn.execute("SELECT * FROM signatures WHERE inspection_id=?", (ins_id,)).fetchall()}
    is_gov = user["role"] in GOV_ROLES
    conn.close()
    return render(request, "inspection_detail.html",
                  {"ins": ins, "items": items, "probs": probs, "ins_atts": ins_atts, "is_gov": is_gov,
                   "is_admin": user["role"] == "gov_admin", "corrections": corrections,
                   "parent": parent, "children": children, "signs": signs,
                   "today": date.today().isoformat()}, user)


@router.get("/inspections/{ins_id}/print", response_class=HTMLResponse)
def ins_print(request: Request, ins_id: int):
    """A4 打印视图（政府与被检查企业均可查看打印）：清版式检查表，签字栏带手写签名"""
    user, err = require(request)
    if err: return err
    conn = get_db()
    ins = conn.execute("SELECT i.*, e.name ent_name, e.credit_code, e.license_no FROM inspections i"
                       " LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE i.id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if user["role"] not in GOV_ROLES + ("sysadmin",) and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    if user["role"] == "enterprise" and ins["status"] == "draft":
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM inspection_items WHERE inspection_id=? ORDER BY sort_order", (ins_id,))]
    probs = [dict(r) for r in conn.execute("SELECT * FROM problems WHERE inspection_id=? ORDER BY seq", (ins_id,))]
    signs = {s["sign_type"]: s for s in
             conn.execute("SELECT * FROM signatures WHERE inspection_id=?", (ins_id,)).fetchall()}
    audit(conn, user["username"], "打印检查表", "inspection", ins_id, ins["code"])
    conn.commit(); conn.close()
    ins_d = dict(ins)
    ins_d["status_cn"] = REC_STATUS_CN.get(ins["status"], ins["status"])
    return render(request, "inspection_print.html",
                  {"ins": ins_d, "items": items, "probs": probs, "signs": signs, "org": ORG_NAME}, user)


@router.post("/inspections/{ins_id}/issue")
def ins_issue(request: Request, ins_id: int, csrf: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] == "archived":
        conn.close(); return HTMLResponse("该检查记录已归档锁定，不能修改。", status_code=403)
    nprob = conn.execute("SELECT COUNT(*) c FROM problems WHERE inspection_id=?", (ins_id,)).fetchone()["c"]
    new_status = "closed" if nprob == 0 else "issued"
    conn.execute("UPDATE inspections SET status=?, issued_at=? WHERE id=?",
                 (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ins_id))
    if new_status == "closed":
        conn.execute("UPDATE inspections SET closed_at=? WHERE id=?",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ins_id))
    audit(conn, user["username"], "下发检查记录", "inspection", ins_id,
          f"{ins['code']} → {REC_STATUS_CN[new_status]}")
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{ins_id}?msg=已下发，企业可查看并反馈整改", status_code=302)


@router.post("/inspections/{ins_id}/close")
def ins_close(request: Request, ins_id: int, csrf: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] == "archived":
        conn.close(); return HTMLResponse("该检查记录已归档锁定，不能修改。", status_code=403)
    conn.execute("UPDATE inspections SET status='closed', closed_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ins_id))
    audit(conn, user["username"], "闭环检查记录", "inspection", ins_id, ins["code"])
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{ins_id}?msg=已闭环", status_code=302)


# ---------------- 企业整改反馈 ----------------
@router.post("/problems/{pid}/feedback")
async def prob_feedback(request: Request, pid: int, reason: str = Form(""), measure: str = Form(...),
                        completion: str = Form(""), done_date: str = Form(""), csrf: str = Form(""),
                        files: list[UploadFile] = File(default=[])):
    user, err = require(request, ("enterprise",) + GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    prob = conn.execute("SELECT p.*, i.enterprise_id, i.code ins_code, i.status ins_status FROM problems p"
                        " JOIN inspections i ON i.id=p.inspection_id WHERE p.id=?", (pid,)).fetchone()
    if not prob:
        conn.close(); return HTMLResponse("问题不存在", status_code=404)
    if prob["ins_status"] == "archived":
        conn.close()
        return HTMLResponse("该检查记录已归档锁定，不能修改。如需更正请管理员发起“更正留痕”。<p><a href='/inspections/"
                            + str(prob["inspection_id"]) + "'>返回</a></p>", status_code=403)
    # 记录必须已下发，企业才能整改反馈：草稿阶段的“整改”没有程序意义（审计 P1-5）
    if prob["ins_status"] not in ("issued", "review"):
        conn.close()
        return HTMLResponse("该检查记录尚未下发，不能提交整改反馈。<p><a href='/inspections/"
                            + str(prob["inspection_id"]) + "'>返回</a></p>", status_code=403)
    if user["role"] == "enterprise" and prob["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权操作", status_code=403)
    # P1-8 定夺：允许代录时全程标注“政府代企业录入”；关闭开关则必须企业自行提交
    if user["role"] != "enterprise" and not ALLOW_GOV_ENT_FEEDBACK:
        conn.close()
        return HTMLResponse("当前配置不允许代企业录入整改反馈，请通知企业登录后自行提交", status_code=403)
    rnd = conn.execute("SELECT COALESCE(MAX(round),0)+1 r FROM feedbacks WHERE problem_id=?", (pid,)).fetchone()["r"]
    cur = conn.execute("INSERT INTO feedbacks(problem_id,round,reason,measure,completion,done_date,submitter,submitted_at)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (pid, rnd, reason, measure, completion, done_date, user["username"],
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    saved, rejected = _save_uploads(files, "feedback", cur.lastrowid, user["username"], conn)
    conn.execute("UPDATE problems SET status='submitted' WHERE id=?", (pid,))
    # 全部问题已提交 → 记录转待复核
    ins_id = prob["inspection_id"]
    left = conn.execute("SELECT COUNT(*) c FROM problems WHERE inspection_id=? AND status NOT IN ('submitted','passed')",
                        (ins_id,)).fetchone()["c"]
    if left == 0:
        conn.execute("UPDATE inspections SET status='review' WHERE id=? AND status<>'archived'", (ins_id,))
    audit(conn, user["username"], "整改反馈", "problem", pid,
          f"{prob['ins_code']} 第{prob['seq']}项问题 第{rnd}轮反馈 附件{len(saved)}件"
          + ("（政府代企业录入）" if user["role"] != "enterprise" else ""))
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{ins_id}?msg=整改反馈已提交，等待复核", status_code=302)


# ---------------- 政府复核 ----------------
@router.post("/problems/{pid}/ext")
def prob_ext(request: Request, pid: int, ext_deadline: str = Form(...), ext_reason: str = Form(""),
             csrf: str = Form("")):
    """整改延期申请：企业提出、政府审批；批准后新期限生效并全程留痕"""
    user, err = require(request)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    prob = conn.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    if not prob:
        conn.close(); return HTMLResponse("问题不存在", status_code=404)
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (prob["inspection_id"],)).fetchone()
    if user["role"] == "enterprise" and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权操作", status_code=403)
    if ins["status"] == "archived":
        conn.close(); return HTMLResponse("已归档锁定，不能申请延期", status_code=403)
    if not ext_deadline or (prob["deadline"] and ext_deadline <= prob["deadline"]):
        conn.close(); return HTMLResponse("新期限须晚于原整改期限", status_code=400)
    conn.execute("UPDATE problems SET ext_deadline=?, ext_reason=?, ext_status='pending' WHERE id=?",
                 (ext_deadline, ext_reason, pid))
    audit(conn, user["username"], "提交整改延期申请", "problem", pid,
          f"申请延至 {ext_deadline}：{ext_reason[:60]}")
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{prob['inspection_id']}?msg=延期申请已提交，等待监管人员审批",
                           status_code=302)


@router.post("/problems/{pid}/ext/handle")
def prob_ext_handle(request: Request, pid: int, action: str = Form(...), csrf: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if action not in ("approve", "reject"):
        return HTMLResponse("操作不合法", status_code=400)
    conn = get_db()
    prob = conn.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    if not prob:
        conn.close(); return HTMLResponse("问题不存在", status_code=404)
    if prob["ext_status"] != "pending":
        conn.close(); return HTMLResponse("没有待审批的延期申请", status_code=400)
    if action == "approve":
        conn.execute("UPDATE problems SET ext_status='approved', deadline=ext_deadline WHERE id=?", (pid,))
        msg = f"已批准延期，新期限 {prob['ext_deadline']} 生效"
    else:
        conn.execute("UPDATE problems SET ext_status='rejected' WHERE id=?", (pid,))
        msg = "已驳回延期申请"
    audit(conn, user["username"], "审批整改延期", "problem", pid,
          f"{'批准' if action == 'approve' else '驳回'}（申请延至 {prob['ext_deadline']}）")
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{prob['inspection_id']}?msg={msg}", status_code=302)


@router.post("/problems/{pid}/review")
def prob_review(request: Request, pid: int, result: str = Form(...), opinion: str = Form(""),
                recheck_date: str = Form(""), recheck_note: str = Form(""), csrf: str = Form("")):
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    prob = conn.execute("SELECT p.*, i.status ins_status FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                        " WHERE p.id=?", (pid,)).fetchone()
    if not prob:
        conn.close(); return HTMLResponse("问题不存在", status_code=404)
    if prob["ins_status"] == "archived":
        conn.close()
        return HTMLResponse("该检查记录已归档锁定，不能修改。如需更正请管理员发起“更正留痕”。", status_code=403)
    if result not in ("pass", "reject"):
        conn.close(); return HTMLResponse("复核结论只能为 通过 / 退回", status_code=400)
    fid = conn.execute("SELECT id FROM feedbacks WHERE problem_id=? ORDER BY round DESC LIMIT 1", (pid,)).fetchone()
    conn.execute("INSERT INTO reviews(problem_id,feedback_id,result,opinion,recheck_date,recheck_note,reviewer,reviewed_at)"
                 " VALUES(?,?,?,?,?,?,?,?)",
                 (pid, fid["id"] if fid else None, result, opinion, recheck_date, recheck_note,
                  user["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    new_status = "passed" if result == "pass" else "returned"
    conn.execute("UPDATE problems SET status=? WHERE id=?", (new_status, pid))
    ins_id = prob["inspection_id"]
    if result == "pass":
        left = conn.execute("SELECT COUNT(*) c FROM problems WHERE inspection_id=? AND status<>'passed'",
                            (ins_id,)).fetchone()["c"]
        if left == 0:
            conn.execute("UPDATE inspections SET status='closed', closed_at=? WHERE id=?",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ins_id))
    else:
        conn.execute("UPDATE inspections SET status='issued' WHERE id=? AND status<>'archived'", (ins_id,))
    audit(conn, user["username"], "复核整改", "problem", pid,
          f"{'通过' if result == 'pass' else '退回'}：{opinion[:50]}")
    conn.commit(); conn.close()
    msg = "复核通过" if result == "pass" else "已退回企业重新整改"
    return RedirectResponse(f"/inspections/{ins_id}?msg={msg}", status_code=302)


# ---------------- 打包下载 ----------------
@router.get("/inspections/{ins_id}/download")
def ins_download(request: Request, ins_id: int):
    """只读下载：不改变记录状态；已落盘的归档包直接复用（审计 P1-1 / P1-2）。"""
    user, err = require(request)
    if err: return err
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if user["role"] not in GOV_ROLES and user["role"] != "sysadmin" and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权下载", status_code=403)
    zip_bytes, zip_name, _sha, _sz, _cnt = zipgen.archive_and_download(conn, [ins_id], user["username"])
    conn.commit(); conn.close()
    return Response(zip_bytes, media_type="application/zip", headers=dl_header(zip_name))


@router.post("/inspections/{ins_id}/archive")
def ins_archive(request: Request, ins_id: int, csrf: str = Form("")):
    """显式归档：生成归档包、落盘保存并锁定记录（政府角色）。
    状态变更只在 POST 下发生，GET 下载不再锁档（审计 P1-2）。"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] == "archived":
        conn.close(); return RedirectResponse(f"/inspections/{ins_id}?msg=该记录已归档锁定", status_code=302)
    zip_bytes, zip_name, _sha, _sz, _cnt = zipgen.archive_and_download(
        conn, [ins_id], user["username"], archive=True)
    conn.commit(); conn.close()
    return Response(zip_bytes, media_type="application/zip", headers=dl_header(zip_name))


@router.post("/archives/batch")
async def archive_batch(request: Request, ids: str = Form(...), csrf: str = Form("")):
    """批量归档：每条一个子包 + 总目录，整包落盘；已闭环记录一并锁定（审计 P1-1）。"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return HTMLResponse("未选择检查记录", status_code=400)
    conn = get_db()
    exist = {r["id"] for r in conn.execute("SELECT id FROM inspections")}
    id_list = [i for i in id_list if i in exist]
    if not id_list:
        conn.close(); return HTMLResponse("选中的检查记录不存在", status_code=404)
    zip_bytes, zip_name, _sha, _sz, _cnt = zipgen.archive_and_download(
        conn, id_list, user["username"], archive=True)
    conn.commit(); conn.close()
    return Response(zip_bytes, media_type="application/zip", headers=dl_header(zip_name))


@router.get("/inspections/{ins_id}/doc/{kind}")
def ins_doc(request: Request, ins_id: int, kind: str):
    """单份文书 PDF：record / notice / feedback / review"""
    user, err = require(request)
    if err: return err
    conn = get_db()
    ins = conn.execute("SELECT i.*, e.name ent_name, e.credit_code, e.license_no FROM inspections i"
                       " LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE i.id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if user["role"] not in GOV_ROLES + ("sysadmin",) and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    from config import REC_STATUS_CN as SCN
    info = {"code": ins["code"], "ent_name": ins["ent_name"], "credit_code": ins["credit_code"] or "",
            "license_no": ins["license_no"] or "", "check_date": ins["check_date"], "check_type": ins["check_type"],
            "check_mode": ins["check_mode"], "location": ins["location"], "inspectors": ins["inspectors"],
            "conclusion": ins["conclusion"], "conclusion_note": ins["conclusion_note"],
            "deadline": ins["deadline"], "status_cn": SCN.get(ins["status"], ins["status"])}
    items = [dict(r) for r in conn.execute("SELECT * FROM inspection_items WHERE inspection_id=? ORDER BY sort_order", (ins_id,))]
    problems = conn.execute("SELECT * FROM problems WHERE inspection_id=? ORDER BY seq", (ins_id,)).fetchall()
    signs = _sig_map(conn, ins_id)
    buf = io.BytesIO()
    fname = f"{ins['code']}.pdf"
    if kind == "record":
        pdfgen.record_pdf(info, items, buf, signs=signs); fname = f"{ins['code']}-现场检查记录表.pdf"
    elif kind == "notice":
        rows = [{**dict(p), "seq_label": f"P{p['seq']}"} for p in problems]
        pdfgen.notice_pdf(info, rows, buf, signs=signs); fname = f"{ins['code']}-问题清单及整改要求.pdf"
    elif kind == "feedback":
        rows = []
        for p in problems:
            f = conn.execute("SELECT * FROM feedbacks WHERE problem_id=? ORDER BY round DESC LIMIT 1", (p["id"],)).fetchone()
            rows.append({"seq_label": f"P{p['seq']}", "description": p["description"],
                         "reason": f["reason"] if f else "（未反馈）", "measure": f["measure"] if f else "（未反馈）",
                         "completion": f["completion"] if f else "", "done_date": f["done_date"] if f else "",
                         "submitter": f["submitter"] if f else "",
                         "att_names": ""})
        pdfgen.feedback_pdf(info, rows, buf, signs=signs); fname = f"{ins['code']}-整改情况报告.pdf"
    elif kind == "review":
        rows = []
        for p in problems:
            for r in conn.execute("SELECT * FROM reviews WHERE problem_id=? ORDER BY reviewed_at", (p["id"],)):
                rows.append({"seq_label": f"P{p['seq']}", "summary": (r["opinion"] or "")[:60],
                             "result_cn": "通过" if r["result"] == "pass" else "退回", "opinion": r["opinion"],
                             "recheck_date": r["recheck_date"], "recheck_note": r["recheck_note"],
                             "reviewer": r["reviewer"]})
        pdfgen.review_pdf(info, rows, buf); fname = f"{ins['code']}-复核意见与复查记录.pdf"
    else:
        conn.close(); return HTMLResponse("文书类型错误", status_code=400)
    audit(conn, user["username"], "下载文书PDF", "inspection", ins_id, f"{ins['code']} {kind}")
    conn.commit(); conn.close()
    return Response(buf.getvalue(), media_type="application/pdf", headers=dl_header(fname))


@router.get("/attachments/{att_id}")
def att_download(request: Request, att_id: int, inline: int = 0):
    """附件下载；inline=1 时图片类按内嵌预览返回（不带 attachment 头）"""
    user, err = require(request)
    if err: return err
    from config import UPLOAD_DIR
    conn = get_db()
    a = conn.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
    if not a:
        conn.close(); return HTMLResponse("附件不存在", status_code=404)
    if user["role"] == "enterprise":
        # 企业只能下载本企业记录的附件
        ok = False
        if a["owner_type"] == "inspection":
            ok = conn.execute("SELECT 1 FROM inspections WHERE id=? AND enterprise_id=?",
                              (a["owner_id"], user["enterprise_id"])).fetchone()
        elif a["owner_type"] == "problem":
            ok = conn.execute("SELECT 1 FROM problems p JOIN inspections i ON i.id=p.inspection_id"
                              " WHERE p.id=? AND i.enterprise_id=?", (a["owner_id"], user["enterprise_id"])).fetchone()
        elif a["owner_type"] == "feedback":
            ok = conn.execute("SELECT 1 FROM feedbacks f JOIN problems p ON p.id=f.problem_id"
                              " JOIN inspections i ON i.id=p.inspection_id"
                              " WHERE f.id=? AND i.enterprise_id=?", (a["owner_id"], user["enterprise_id"])).fetchone()
        if not ok:
            conn.close(); return HTMLResponse("无权下载", status_code=403)
    audit(conn, user["username"], "下载附件", a["owner_type"], a["owner_id"], a["filename"])
    conn.commit(); conn.close()
    path = os.path.join(UPLOAD_DIR, a["stored_name"])
    if not os.path.exists(path):
        return HTMLResponse("文件已丢失", status_code=404)
    with open(path, "rb") as fp:
        data = fp.read()
    if inline:   # 图片内嵌预览（详情页缩略图）；其余类型仍走下载
        ct = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"} \
            .get(os.path.splitext(a["filename"])[1].lower())
        if ct:
            return Response(data, media_type=ct)
    return Response(data, headers=dl_header(a["filename"]))


# ---------------- 现场检查登记（手机适配）与电子签字确认 ----------------
def _sig_map(conn, ins_id: int) -> dict:
    """返回 {sign_type: 签名图路径}，供文书签字栏嵌入"""
    from config import UPLOAD_DIR
    out = {}
    for s in conn.execute("SELECT * FROM signatures WHERE inspection_id=?", (ins_id,)).fetchall():
        p = os.path.join(UPLOAD_DIR, s["stored_name"])
        if os.path.exists(p):
            out[s["sign_type"]] = p
    return out


@router.get("/onsite", response_class=HTMLResponse)
def onsite_page(request: Request, edit: int = 0):
    """现场检查登记（手机适配）：检查过程中逐项点选结果、拍照上传、登记问题、手写签字确认"""
    user, err = require(request, GOV_ROLES)
    if err: return err
    conn = get_db()
    ins = ins_items = ins_probs = None
    signs = {}
    if edit:
        ins, ins_items, ins_probs = _draft_payload(conn, edit)
        if not ins:
            conn.close(); return HTMLResponse("只有草稿状态的检查记录可现场登记", status_code=400)
        for s in conn.execute("SELECT * FROM signatures WHERE inspection_id=?", (edit,)).fetchall():
            signs[s["sign_type"]] = s
    ents = conn.execute("SELECT id, name FROM enterprises ORDER BY name").fetchall()
    tpls = conn.execute("SELECT * FROM check_templates WHERE active=1 ORDER BY id").fetchall()
    tpl_items = {}
    for t in tpls:
        tpl_items[t["id"]] = [dict(r) for r in conn.execute(
            "SELECT ci.* FROM template_items ti JOIN check_items ci ON ci.id=ti.item_id"
            " WHERE ti.template_id=? ORDER BY ti.sort_order", (t["id"],))]
    all_items = [dict(r) for r in conn.execute("SELECT * FROM check_items WHERE active=1 ORDER BY code")]
    gov_names2 = [r["real_name"] for r in conn.execute(
        "SELECT real_name FROM users WHERE role LIKE 'gov%' AND active=1 ORDER BY real_name")]
    conn.close()
    return render(request, "onsite.html",
                  {"ins": ins, "ins_items": ins_items, "ins_probs": ins_probs, "signs": signs,
                   "ents": ents, "tpls": tpls, "tpl_items": tpl_items, "all_items": all_items,
                   "gov_names": gov_names2,
                   "CHECK_TYPES": CHECK_TYPES, "CHECK_MODES": CHECK_MODES}, user)


@router.post("/inspections/{ins_id}/sign")
async def ins_sign(request: Request, ins_id: int, sign_type: str = Form(...),
                   signer_name: str = Form(...), image: str = Form(""), csrf: str = Form("")):
    """电子签字确认：被检查企业/检查人员手写签名（触屏或鼠标），PNG 落盘并嵌入归档文书签字栏"""
    user, err = require(request, ("enterprise",) + GOV_ROLES)
    if err: return err
    if bad_csrf(user, csrf):
        return HTMLResponse("表单已过期，请返回刷新后重试", status_code=403)
    if sign_type not in ("ent", "insp"):
        return HTMLResponse("签字类型不合法", status_code=400)
    name = signer_name.strip()
    if not name:
        return HTMLResponse("请填写签字人姓名", status_code=400)
    if not image.startswith("data:image/png;base64,"):
        return HTMLResponse("签字图片数据无效", status_code=400)
    try:
        raw = base64.b64decode(image.split(",", 1)[1])
    except Exception:
        return HTMLResponse("签字图片数据无效", status_code=400)
    if not raw or len(raw) > 2 * 1024 * 1024:
        return HTMLResponse("签字图片为空或过大", status_code=400)
    conn = get_db()
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (ins_id,)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if ins["status"] == "archived":
        conn.close(); return HTMLResponse("已归档锁定，不能补签", status_code=403)
    if user["role"] == "enterprise":
        if ins["enterprise_id"] != user["enterprise_id"]:
            conn.close(); return HTMLResponse("无权操作", status_code=403)
        if sign_type != "ent":
            conn.close(); return HTMLResponse("企业用户只能签署企业签字栏", status_code=403)
    from config import UPLOAD_DIR
    stored = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as fp:
        fp.write(raw)
    old = conn.execute("SELECT * FROM signatures WHERE inspection_id=? AND sign_type=?",
                       (ins_id, sign_type)).fetchone()
    if old:
        try:
            os.remove(os.path.join(UPLOAD_DIR, old["stored_name"]))
        except OSError:
            pass
        conn.execute("DELETE FROM signatures WHERE inspection_id=? AND sign_type=?", (ins_id, sign_type))
    conn.execute("INSERT INTO signatures(inspection_id,sign_type,signer_name,stored_name,signed_at)"
                 " VALUES(?,?,?,?,?)",
                 (ins_id, sign_type, name, stored, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    audit(conn, user["username"], "签字确认", "inspection", ins_id,
          f"{ins['code']} {'被检查企业' if sign_type == 'ent' else '检查人员'}签字：{name}"
          + ("（检查人员现场代录）" if (user["role"] != "enterprise" and sign_type == "ent") else ""))
    conn.commit(); conn.close()
    return RedirectResponse(f"/inspections/{ins_id}?msg=签字已确认"
                            f"（{'被检查企业' if sign_type == 'ent' else '检查人员'}）", status_code=302)


@router.get("/signatures/{sid}")
def signature_image(request: Request, sid: int):
    """签名图片（访问权限与检查记录一致）"""
    user, err = require(request)
    if err: return err
    from config import UPLOAD_DIR
    conn = get_db()
    s = conn.execute("SELECT * FROM signatures WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close(); return HTMLResponse("签名不存在", status_code=404)
    ins = conn.execute("SELECT * FROM inspections WHERE id=?", (s["inspection_id"],)).fetchone()
    if not ins:
        conn.close(); return HTMLResponse("记录不存在", status_code=404)
    if user["role"] == "enterprise" and ins["enterprise_id"] != user["enterprise_id"]:
        conn.close(); return HTMLResponse("无权查看", status_code=403)
    conn.close()
    path = os.path.join(UPLOAD_DIR, s["stored_name"])
    if not os.path.exists(path):
        return HTMLResponse("签名文件已丢失", status_code=404)
    with open(path, "rb") as fp:
        return Response(fp.read(), media_type="image/png")


