# -*- coding: utf-8 -*-
"""数据库维护工具（SQLite）——体检 / 备份轮转 / 测试数据清理 / 空间整理。

用法（在平台目录或任意目录执行，路径写死为平台 data 目录）：
    python db_maintenance.py check           # 完整性 + 孤儿数据 + 重复数据 + 容量体检
    python db_maintenance.py backup [--keep N]   # 热备份到 data\\backups\\ 并轮转（默认留 30 份）
    python db_maintenance.py clean-test [--apply]  # 清理演示/测试数据（默认 dry-run 只列不动）
    python db_maintenance.py vacuum          # VACUUM + ANALYZE（回收空间、刷新统计）
"""
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
P = os.path.dirname(os.path.abspath(__file__))   # 平台根目录（随脚本位置自适应）
DB = os.path.join(P, "data", "app.db")
UP = os.path.join(P, "data", "uploads")
BACKUP_DIR = os.path.join(P, "data", "backups")


def conn_ro():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    c.row_factory = sqlite3.Row
    return c


def q1(c, sql, a=()):
    return c.execute(sql, a).fetchone()[0]


# ---------------- 体检 ----------------
def do_check():
    c = conn_ro()
    print("【容量】")
    for f in ("app.db", "app.db-wal", "app.db-shm"):
        p = os.path.join(P, "data", f)
        if os.path.exists(p):
            print("  %-12s %10d 字节" % (f, os.path.getsize(p)))
    tables = [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("\n【行数】")
    for t in tables:
        print("  %-16s %s" % (t, q1(c, "SELECT COUNT(*) FROM %s" % t)))

    print("\n【完整性】")
    print("  integrity_check:", c.execute("PRAGMA integrity_check").fetchone()[0])
    print("  foreign_keys:", c.execute("PRAGMA foreign_keys").fetchone()[0],
          "（schema 未声明外键，孤儿数据以下方体检为准）")
    print("  journal_mode:", c.execute("PRAGMA journal_mode").fetchone()[0])

    print("\n【孤儿数据体检】")
    orphans = [
        ("检查记录→企业", "SELECT COUNT(*) FROM inspections i LEFT JOIN enterprises e ON e.id=i.enterprise_id WHERE e.id IS NULL"),
        ("逐项结果→检查记录", "SELECT COUNT(*) FROM inspection_items x LEFT JOIN inspections i ON i.id=x.inspection_id WHERE i.id IS NULL"),
        ("问题→检查记录", "SELECT COUNT(*) FROM problems p LEFT JOIN inspections i ON i.id=p.inspection_id WHERE i.id IS NULL"),
        ("反馈→问题", "SELECT COUNT(*) FROM feedbacks f LEFT JOIN problems p ON p.id=f.problem_id WHERE p.id IS NULL"),
        ("复核→问题", "SELECT COUNT(*) FROM reviews r LEFT JOIN problems p ON p.id=r.problem_id WHERE p.id IS NULL"),
        ("附件→所属对象", "SELECT COUNT(*) FROM attachments a WHERE NOT EXISTS("
                          " SELECT 1 FROM inspections i WHERE a.owner_type='inspection' AND i.id=a.owner_id)"
                          " AND NOT EXISTS(SELECT 1 FROM problems p WHERE a.owner_type='problem' AND p.id=a.owner_id)"
                          " AND NOT EXISTS(SELECT 1 FROM feedbacks f WHERE a.owner_type='feedback' AND f.id=a.owner_id)"),
        ("签名→检查记录", "SELECT COUNT(*) FROM signatures s LEFT JOIN inspections i ON i.id=s.inspection_id WHERE i.id IS NULL"),
        ("计划项→计划", "SELECT COUNT(*) FROM plan_items pi LEFT JOIN plans p ON p.id=pi.plan_id WHERE p.id IS NULL"),
        ("船舶→企业", "SELECT COUNT(*) FROM ships s LEFT JOIN enterprises e ON e.id=s.enterprise_id WHERE e.id IS NULL"),
        ("企业账号→企业", "SELECT COUNT(*) FROM users u LEFT JOIN enterprises e ON e.id=u.enterprise_id"
                          " WHERE u.role='enterprise' AND u.enterprise_id IS NOT NULL AND e.id IS NULL"),
        ("记录→计划项(悬空引用)", "SELECT COUNT(*) FROM inspections i LEFT JOIN plan_items pi ON pi.id=i.plan_item_id"
                                  " WHERE i.plan_item_id>0 AND pi.id IS NULL"),
        ("记录→父记录(悬空引用)", "SELECT COUNT(*) FROM inspections i LEFT JOIN inspections p ON p.id=i.parent_id"
                                  " WHERE i.parent_id>0 AND p.id IS NULL"),
    ]
    bad = 0
    for name, sql in orphans:
        n = q1(c, sql)
        bad += n
        print("  %-22s %s" % (name, ("OK" if n == 0 else "** %s 条" % n)))
    print("  小计孤儿/悬空：%s 条" % bad)

    print("\n【审计日志哈希链】")
    import hashlib
    rows = [dict(x) for x in c.execute("SELECT * FROM audit_logs ORDER BY id")]
    prev_hash = ""
    legacy = breaks = 0
    for r in rows:
        if not r.get("chain_hash"):
            legacy += 1
            prev_hash = ""
            continue
        payload = "|".join([r["username"], r["action"], r["entity"], str(r["entity_id"]),
                            r["detail"], r["before"], r["after"], r["ip"], r["created_at"]])
        if hashlib.sha256((prev_hash + "|" + payload).encode("utf-8")).hexdigest() != r["chain_hash"]:
            breaks += 1
        prev_hash = r["chain_hash"] or ""
    print(f"  已入链 {len(rows) - legacy} 条；未入链（历史留痕）{legacy} 条；链断点 {breaks} 条"
          + ("（有删改或并发写入异常，需人工核对）" if breaks else ""))

    print("\n【数据质量】")
    dup = q1(c, "SELECT COUNT(*) FROM enterprises a WHERE EXISTS("
                " SELECT 1 FROM enterprises b WHERE b.id<a.id AND (b.name=a.name OR (a.credit_code<>'' AND b.credit_code=a.credit_code)))")
    print("  重名/重信用代码企业：%s" % ("OK" if dup == 0 else "** %s 家" % dup))
    miss_hash = q1(c, "SELECT COUNT(*) FROM attachments WHERE sha256='' OR sha256 IS NULL")
    print("  无 SHA256 的附件：%s" % ("OK" if miss_hash == 0 else "** %s 件" % miss_hash))
    disk = set(os.listdir(UP)) if os.path.isdir(UP) else set()
    dbfiles = {r["stored_name"] for r in c.execute("SELECT stored_name FROM attachments")}
    dbfiles |= {r["stored_name"] for r in c.execute("SELECT stored_name FROM signatures")}
    print("  磁盘孤儿文件（无库记录）：%s" % (sorted(disk - dbfiles) or "OK"))
    print("  库记录缺失文件：%s" % (sorted(dbfiles - disk) or "OK"))
    c.close()


# ---------------- 备份轮转 ----------------
def do_backup(keep: int):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"app_{stamp}.db")
    src = sqlite3.connect(DB)
    dstc = sqlite3.connect(dst)
    src.backup(dstc)      # SQLite 热备份 API：在线一致拷贝，不锁库
    dstc.close(); src.close()
    size = os.path.getsize(dst)
    print(f"已备份：{dst}（{size} 字节）")
    olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("app_") and f.endswith(".db"))
    for f in olds[:-keep] if keep > 0 else []:
        os.remove(os.path.join(BACKUP_DIR, f))
        print("轮转删除：", f)
    print(f"当前备份 {min(len(olds), keep)} 份（保留上限 {keep}）")
    print("提示：附件/归档包/secret.key 需连同 data\\uploads、data\\archives、data\\secret.key 一起备份。")


# ---------------- 测试数据清理 ----------------
def do_clean(apply: bool):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    print("模式：%s\n" % ("实际清理" if apply else "预演（不动数据，加 --apply 执行）"))
    victims = [r["id"] for r in c.execute(
        "SELECT id FROM enterprises WHERE name LIKE '%测试%' OR name LIKE '%demo%'")]
    if victims:
        print("待清理演示企业 id=%s：" % victims)
        for r in c.execute("SELECT id,name,credit_code FROM enterprises WHERE id IN (%s)" % ",".join(map(str, victims))):
            print("   -", r["id"], r["name"], r["credit_code"])
        ins_ids = [r["id"] for r in c.execute(
            "SELECT id FROM inspections WHERE enterprise_id IN (%s)" % ",".join(map(str, victims)))]
        print("其名下检查记录 %s 条：%s" % (len(ins_ids), ins_ids))
        if apply:
            for iid in ins_ids:
                for att in c.execute("SELECT stored_name FROM attachments WHERE owner_type='inspection' AND owner_id=?", (iid,)):
                    try:
                        os.remove(os.path.join(UP, att["stored_name"]))
                    except OSError:
                        pass
                c.execute("DELETE FROM attachments WHERE owner_type='inspection' AND owner_id=?", (iid,))
                pids = [r["id"] for r in c.execute("SELECT id FROM problems WHERE inspection_id=?", (iid,))]
                for pid in pids:
                    for att in c.execute("SELECT stored_name FROM attachments WHERE owner_type='problem' AND owner_id=?", (pid,)):
                        try:
                            os.remove(os.path.join(UP, att["stored_name"]))
                        except OSError:
                            pass
                    c.execute("DELETE FROM attachments WHERE owner_type='problem' AND owner_id=?", (pid,))
                    fids = [r["id"] for r in c.execute("SELECT id FROM feedbacks WHERE problem_id=?", (pid,))]
                    for fid in fids:
                        for att in c.execute("SELECT stored_name FROM attachments WHERE owner_type='feedback' AND owner_id=?", (fid,)):
                            try:
                                os.remove(os.path.join(UP, att["stored_name"]))
                            except OSError:
                                pass
                        c.execute("DELETE FROM attachments WHERE owner_id=? AND owner_type='feedback'", (fid,))
                    c.execute("DELETE FROM feedbacks WHERE problem_id=?", (pid,))
                    c.execute("DELETE FROM reviews WHERE problem_id=?", (pid,))
                    c.execute("DELETE FROM problems WHERE id=?", (pid,))
                c.execute("DELETE FROM inspection_items WHERE inspection_id=?", (iid,))
                c.execute("DELETE FROM signatures WHERE inspection_id=?", (iid,))
                c.execute("DELETE FROM inspections WHERE id=?", (iid,))
            c.execute("DELETE FROM enterprises WHERE id IN (%s)" % ",".join(map(str, victims)))
            print("已删除演示企业及其全部记录")
    else:
        print("无演示企业（name LIKE '%测试%/%demo%'）")
    # 空壳附件（11/15 字节假文件等）
    tiny = [dict(r) for r in c.execute("SELECT id,filename,stored_name,size FROM attachments WHERE size<20")]
    if tiny:
        print("\n占位/假附件 %s 件：%s" % (len(tiny), [t["filename"] for t in tiny]))
        if apply:
            for t in tiny:
                try:
                    os.remove(os.path.join(UP, t["stored_name"]))
                except OSError:
                    pass
                c.execute("DELETE FROM attachments WHERE id=?", (t["id"],))
            print("已删除占位附件")
    else:
        print("\n无占位附件（size<20）")
    # 演示企业账号解绑/停用
    for r in c.execute("SELECT id,username,enterprise_id FROM users WHERE role='enterprise'"):
        ent = r["enterprise_id"]
        if ent in victims:
            if apply:
                c.execute("UPDATE users SET enterprise_id=NULL, active=0 WHERE id=?", (r["id"],))
            print("企业账号 %s 绑定演示企业 → %s" % (r["username"], "已解绑并停用" if apply else "将解绑并停用"))
    if apply:
        c.commit()
        print("\n清理完成。")
    else:
        print("\n预演结束。确认无误后加 --apply 执行。")
    c.close()


# ---------------- 空间整理 ----------------
def do_vacuum():
    c = sqlite3.connect(DB)
    before = os.path.getsize(DB)
    c.execute("ANALYZE")
    c.execute("VACUUM")
    c.close()
    after = os.path.getsize(DB)
    print("VACUUM 完成：%d → %d 字节（回收 %d）" % (before, after, before - after))


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    if cmd == "check":
        do_check()
    elif cmd == "backup":
        keep = 30
        if "--keep" in args:
            keep = int(args[args.index("--keep") + 1])
        do_backup(keep)
    elif cmd == "clean-test":
        do_clean("--apply" in args)
    elif cmd == "vacuum":
        do_vacuum()
    else:
        print(__doc__)
