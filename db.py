# -*- coding: utf-8 -*-
"""数据模型与初始化（SQLite）"""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime

from config import DB_PATH, UPLOAD_DIR, ensure_dirs
from seed_items import ITEMS, TEMPLATES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    real_name TEXT NOT NULL,
    role TEXT NOT NULL,                -- gov_admin / gov_staff / enterprise / sysadmin
    enterprise_id INTEGER,             -- enterprise 角色绑定的企业
    phone TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    must_change_pwd INTEGER DEFAULT 0, -- 1=首次登录强制改密
    session_rev INTEGER DEFAULT 0,     -- 会话版本：改密/重置后+1，旧会话全部失效（审计 P2-5）
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    credit_code TEXT DEFAULT '',       -- 统一社会信用代码
    license_no TEXT DEFAULT '',        -- 经营许可证号
    license_type TEXT DEFAULT '',      -- 经营类别：普通货物/危险货物/旅客/辅助业务
    legal_person TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    address TEXT DEFAULT '',
    scope TEXT DEFAULT '',             -- 核定经营范围
    remark TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enterprise_id INTEGER NOT NULL,
    name TEXT NOT NULL,                -- 船名
    ship_no TEXT DEFAULT '',           -- 船舶登记号/IMO
    ship_type TEXT DEFAULT '',         -- 船型/种类
    dwt TEXT DEFAULT '',               -- 载重吨
    gt TEXT DEFAULT '',                -- 总吨
    built_date TEXT DEFAULT '',        -- 建成日期
    license_no TEXT DEFAULT '',        -- 船舶营业运输证号
    cert_status TEXT DEFAULT '',       -- 证书情况
    remark TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS random_draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_type TEXT NOT NULL,           -- double=双随机（企业+检查员）/ single=仅随机抽企业
    ent_count INTEGER DEFAULT 0,       -- 抽取企业数
    insp_count INTEGER DEFAULT 0,      -- 选派检查员数
    exclude_days INTEGER DEFAULT 0,    -- 排除近N天已检查企业（0=不排除）
    seed TEXT DEFAULT '',              -- 随机种子：按种子可复现抽样过程，保证公正可审计
    ent_ids TEXT DEFAULT '',           -- 抽中企业id（逗号分隔）
    insp_ids TEXT DEFAULT '',          -- 选派检查员id（逗号分隔）
    detail TEXT DEFAULT '',            -- JSON 明细（企业/检查员/生成草稿id）
    note TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,               -- 如 2026年度水路运输企业监督检查计划
    year INTEGER DEFAULT 0,            -- 年度
    period TEXT DEFAULT '',            -- 全年/上半年/Q1/...
    status TEXT DEFAULT 'draft',       -- draft 草稿 / issued 已下达
    note TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    issued_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    enterprise_id INTEGER DEFAULT 0,   -- 指定企业；0=按适用范围描述
    ent_scope TEXT DEFAULT '',         -- 适用范围（如“全部危险货物运输企业”）
    check_type TEXT DEFAULT '',        -- 日常检查/专项检查/双随机抽查/...
    count_plan INTEGER DEFAULT 1,      -- 计划检查家次
    period TEXT DEFAULT '',            -- 计划时段（全年/Q1/3月/...）
    inspectors TEXT DEFAULT '',        -- 计划检查人员
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL,
    sign_type TEXT NOT NULL,           -- ent=被检查企业 / insp=检查人员
    signer_name TEXT NOT NULL,         -- 签字人姓名
    stored_name TEXT NOT NULL,         -- uploads 下手写签名 PNG
    signed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS check_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,                -- A01/B03...
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    legal_basis TEXT NOT NULL,
    method TEXT NOT NULL,
    criteria TEXT NOT NULL,
    is_key INTEGER DEFAULT 0,          -- 重点项
    is_veto INTEGER DEFAULT 0,         -- 否决项
    score INTEGER DEFAULT 3,
    scope TEXT DEFAULT '',
    note TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS check_item_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    code TEXT, category TEXT, name TEXT, content TEXT, legal_basis TEXT,
    method TEXT, criteria TEXT,
    is_key INTEGER DEFAULT 0, is_veto INTEGER DEFAULT 0, score INTEGER DEFAULT 3,
    scope TEXT DEFAULT '', note TEXT DEFAULT '', active INTEGER DEFAULT 1,
    changed_by TEXT, changed_at TEXT, change_note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS check_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    version INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1,
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_items (
    template_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    sort_order INTEGER DEFAULT 0,
    PRIMARY KEY (template_id, item_id)
);

CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,         -- 检查编号 JC-YYYYMMDD-XXX
    enterprise_id INTEGER NOT NULL,
    template_id INTEGER,
    parent_id INTEGER DEFAULT 0,       -- 复查关联的原检查记录id（审计 P2-10）
    plan_item_id INTEGER DEFAULT 0,    -- 关联的检查计划项id（0=未关联计划）
    check_type TEXT NOT NULL,          -- 日常检查/专项检查/双随机抽查/复查/投诉举报核查
    check_mode TEXT DEFAULT '现场检查',
    check_date TEXT NOT NULL,
    location TEXT DEFAULT '',
    inspectors TEXT DEFAULT '',        -- 检查人员（多人，逗号分隔）
    conclusion TEXT DEFAULT '',        -- 未发现问题/责发整改/移送线索
    conclusion_note TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',       -- draft/issued/review/closed/archived
    deadline TEXT DEFAULT '',          -- 整改期限
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    issued_at TEXT DEFAULT '',
    closed_at TEXT DEFAULT '',
    archived_at TEXT DEFAULT '',
    archive_file TEXT DEFAULT ''       -- 最近一次归档包文件名
);

CREATE TABLE IF NOT EXISTS inspection_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL,
    item_code TEXT, category TEXT, item_name TEXT, item_content TEXT,
    legal_basis TEXT, method TEXT, criteria TEXT,
    is_key INTEGER DEFAULT 0, is_veto INTEGER DEFAULT 0, score INTEGER DEFAULT 0,
    result TEXT DEFAULT '',            -- 符合/不符合/不适用
    finding TEXT DEFAULT '',           -- 情况描述
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL,
    seq INTEGER DEFAULT 1,             -- 问题序号 P1/P2...
    item_id INTEGER,                   -- 关联检查项（可空）
    description TEXT NOT NULL,         -- 问题描述
    legal_basis TEXT DEFAULT '',       -- 违反条款
    requirement TEXT DEFAULT '',       -- 整改要求
    deadline TEXT DEFAULT '',          -- 整改期限
    responsible TEXT DEFAULT '',       -- 责任人
    status TEXT DEFAULT 'pending',     -- pending/submitted/passed/returned
    to_msa INTEGER DEFAULT 0,          -- 是否移送海事
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL,
    round INTEGER DEFAULT 1,           -- 第几轮反馈
    reason TEXT DEFAULT '',            -- 问题认识/原因分析
    measure TEXT NOT NULL,             -- 整改措施
    completion TEXT DEFAULT '',        -- 完成情况
    done_date TEXT DEFAULT '',         -- 完成日期
    submitter TEXT DEFAULT '',
    submitted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL,          -- problem / feedback / inspection
    owner_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    sha256 TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    uploaded_by TEXT DEFAULT '',
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL,
    feedback_id INTEGER,
    result TEXT NOT NULL,              -- pass / reject
    opinion TEXT DEFAULT '',
    recheck_date TEXT DEFAULT '',
    recheck_note TEXT DEFAULT '',      -- 复查情况
    reviewer TEXT DEFAULT '',
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT DEFAULT '',
    entity_id TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    before TEXT DEFAULT '',
    after TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,               -- single / batch
    record_ids TEXT NOT NULL,
    file_name TEXT NOT NULL,
    sha256 TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    generated_by TEXT DEFAULT '',
    file_path TEXT DEFAULT '',         -- 归档包在 data\archives 下的落盘路径
    generated_at TEXT NOT NULL
);

-- ===== 常用查询索引（关联列/筛选列；对已有库幂等生效） =====
CREATE INDEX IF NOT EXISTS idx_inspections_ent ON inspections(enterprise_id);
CREATE INDEX IF NOT EXISTS idx_inspections_parent ON inspections(parent_id);
CREATE INDEX IF NOT EXISTS idx_inspections_plan ON inspections(plan_item_id);
CREATE INDEX IF NOT EXISTS idx_inspections_status ON inspections(status);
CREATE INDEX IF NOT EXISTS idx_inspections_date ON inspections(check_date);
CREATE INDEX IF NOT EXISTS idx_inspection_items_ins ON inspection_items(inspection_id);
CREATE INDEX IF NOT EXISTS idx_problems_ins ON problems(inspection_id);
CREATE INDEX IF NOT EXISTS idx_problems_status ON problems(status);
CREATE INDEX IF NOT EXISTS idx_feedbacks_problem ON feedbacks(problem_id);
CREATE INDEX IF NOT EXISTS idx_reviews_problem ON reviews(problem_id);
CREATE INDEX IF NOT EXISTS idx_attachments_owner ON attachments(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON plan_items(plan_id);
CREATE INDEX IF NOT EXISTS idx_signatures_ins ON signatures(inspection_id);
CREATE INDEX IF NOT EXISTS idx_ships_ent ON ships(enterprise_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
"""


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")   # 并发写排队等待，而非直接报 database is locked
    conn.execute("PRAGMA journal_mode=WAL")    # 写不阻塞读，多用户并发更顺（备份时连同 -wal/-shm 一起拷）
    return conn


def audit(conn, username, action, entity="", entity_id="", detail="", before="", after="", ip=""):
    """写操作日志并生成防篡改哈希链：本条 hash = sha256(上一条 hash + 本条内容)，
    校验时按 id 顺序重算即可发现任何删改（司法级留痕）。"""
    import hashlib
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prev = conn.execute("SELECT chain_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = (prev["chain_hash"] or "") if prev else ""
    payload = "|".join([username, action, entity, str(entity_id), detail, before, after, ip, ts])
    chain = hashlib.sha256((prev_hash + "|" + payload).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs(username,action,entity,entity_id,detail,before,after,ip,created_at,chain_hash)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (username, action, entity, str(entity_id), detail, before, after, ip, ts, chain))


# 法条摘要（悬停可见）：依据条款的简要说明，仅供工作参考，以法规原文为准
LEGAL_NOTES = {
    "A01": "《规定》第17条：经营许可证有效期5年；届满前30日申请换证（条例第17条同口径）。",
    "A02": "《条例》第14条：投入运营的船舶应持有效的船舶营业运输证，并随船携带备查。",
    "A03": "《条例》第13条：船舶须持有效的船舶登记证书和船舶检验证书。",
    "A05": "《规定》第8条：按经营规模配备海务、机务专职管理人员，资历符合要求。",
    "A07": "《规定》第21条：禁止出租、出借、伪造、变造许可证和船舶营业运输证（条例第37条对应罚则）。",
    "B01": "《安全生产法》第4条、第21条：建立健全全员安全生产责任制并考核落实。",
    "B02": "《安全生产法》第5条、第21条：主要负责人履行七项职责。",
    "B03": "《安全生产法》第24条、第25条：设安全管理机构或配备专职安全管理人员。",
    "B05": "《安全生产法》第23条：安全生产费用按规定提取和使用。",
    "B06": "《安全生产法》第21条第（三）项、第28条：教育培训计划、持证上岗、档案记录。",
    "C01": "《安全生产法》第4条、第21条第（五）项、第41条：安全风险分级管控。",
    "C02": "《安全生产法》第41条：隐患排查治理制度并落实到日常检查。",
    "C03": "《安全生产法》第41条：隐患排查治理台账如实记录、及时报告。",
    "C05": "《安全生产法》第21条第（六）项、第81条：应急预案与属地政府预案衔接。",
    "C06": "《安全生产法》第81条：定期组织应急演练并评估改进。",
    "D02": "《条例》第18条：按核定载客定额/载重量载运，不得超载（处罚属海事：条例第38条）。",
    "D04": "《条例》第19条、第39条：客运船舶投保承运人责任保险或取得财务担保。",
    "D13": "《条例》第24条、《规定》第35条：按规定报送月度、年度统计信息。",
    "D15": "《安全生产法》第36条：安全设备经常性维护、保养、检测并记录。",
    "E05": "《条例》第42条、《规定》第45条/第49条：取得许可后持续具备经营条件。",
    "E06": "《规定》第20条、第25条（条例第33条）：不得超范围经营、擅自改装船舶等。",
}


def init_db():
    """建库并注入种子数据（幂等）"""
    ensure_dirs()
    fresh = not os.path.exists(DB_PATH)
    conn = get_db()
    conn.executescript(SCHEMA)
    # 轻量迁移：给已有表补缺失列（SCHEMA 为 IF NOT EXISTS，不会自动加列）
    for table, col, decl in [
        ("feedbacks", "reason", "TEXT DEFAULT ''"),
        ("users", "must_change_pwd", "INTEGER DEFAULT 0"),
        ("users", "session_rev", "INTEGER DEFAULT 0"),
        ("inspections", "parent_id", "INTEGER DEFAULT 0"),
        ("inspections", "plan_item_id", "INTEGER DEFAULT 0"),
        ("archive_logs", "file_path", "TEXT DEFAULT ''"),
        ("audit_logs", "chain_hash", "TEXT DEFAULT ''"),
        ("problems", "ext_deadline", "TEXT DEFAULT ''"),
        ("problems", "ext_reason", "TEXT DEFAULT ''"),
        ("problems", "ext_status", "TEXT DEFAULT ''"),
        ("check_items", "legal_note", "TEXT DEFAULT ''"),
        ("check_item_history", "legal_note", "TEXT DEFAULT ''"),
    ]:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            # 存量库首次补出 must_change_pwd 列时，强制所有既有账号改密：
            # 否则补列取默认值 0，出厂弱口令将永久可用（审计 P0-1）。
            if table == "users" and col == "must_change_pwd":
                conn.execute("UPDATE users SET must_change_pwd=1")
                print("[安全] 检测到旧版用户表：已为全部存量账号置“首次登录必须改密”标记。")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if conn.execute("SELECT COUNT(*) c FROM check_items").fetchone()["c"] == 0:
        for it in ITEMS:
            conn.execute(
                "INSERT INTO check_items(code,category,name,content,legal_basis,method,criteria,"
                "is_key,is_veto,score,scope,note,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (it[0], it[1], it[2], it[3], it[4], it[5], it[6], it[7], it[8], it[9], it[10], it[11], now))

    # 法条摘要补齐（只填空不覆盖人工修订；存量库同样生效）
    for _code, _note in LEGAL_NOTES.items():
        conn.execute("UPDATE check_items SET legal_note=? WHERE code=? AND (legal_note IS NULL OR legal_note='')",
                     (_note, _code))

    if conn.execute("SELECT COUNT(*) c FROM check_templates").fetchone()["c"] == 0:
        for name, desc, codes in TEMPLATES:
            cur = conn.execute(
                "INSERT INTO check_templates(name,description,version,active,created_by,created_at)"
                " VALUES(?,?,1,1,'系统预置',?)", (name, desc, now))
            tid = cur.lastrowid
            for i, code in enumerate(codes):
                row = conn.execute("SELECT id FROM check_items WHERE code=?", (code,)).fetchone()
                if row:
                    conn.execute("INSERT INTO template_items(template_id,item_id,sort_order) VALUES(?,?,?)",
                                 (tid, row["id"], i))

    if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        users = [
            ("admin", "admin@123", "系统管理员", "sysadmin", None),
            ("gov", "gov@123", "张监管", "gov_admin", None),
            ("inspector", "insp@123", "李检查员", "gov_staff", None),
        ]
        for un, pw, rn, role, eid in users:
            salt = secrets.token_hex(8)
            conn.execute(
                "INSERT INTO users(username,password_hash,salt,real_name,role,enterprise_id,phone,active,must_change_pwd,created_at)"
                " VALUES(?,?,?,?,?,?,?,1,1,?)",
                (un, hash_password(pw, salt), salt, rn, role, eid, "", now))

    conn.commit()
    conn.close()
    return fresh


if __name__ == "__main__":
    fresh = init_db()
    print("数据库初始化完成：" + DB_PATH + ("（新建）" if fresh else "（已存在，幂等校验通过）"))
