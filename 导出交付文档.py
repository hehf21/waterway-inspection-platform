# -*- coding: utf-8 -*-
"""导出交付文档：检查内容清单 Word / 检查项目库 Excel 到 交付文档 目录"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ.setdefault("SLYS_DATA", os.path.join(BASE, "data"))

import exportgen
from db import get_db, init_db

OUT = os.path.join(BASE, "交付文档")
os.makedirs(OUT, exist_ok=True)

init_db()   # 保证旧库结构就绪（幂等，含轻量迁移）
conn = get_db()
items = [dict(r) for r in conn.execute("SELECT * FROM check_items WHERE active=1 ORDER BY code")]
conn.close()

docx_path = os.path.join(OUT, "检查内容清单.docx")
xlsx_path = os.path.join(OUT, "检查项目库.xlsx")
with open(docx_path, "wb") as f:
    f.write(exportgen.items_docx(items, "水路运输企业检查内容清单（51项·法规条款版）",
                                "编制：平潭综合实验区交通与建设局　"
                                "用于逐条核对检查依据条款；标注“移送海事”的事项属海事管理处罚范围（条例第38条）。"))
with open(xlsx_path, "wb") as f:
    f.write(exportgen.items_xlsx(items))
print(f"已导出：{docx_path}")
print(f"已导出：{xlsx_path}")
print(f"检查项数：{len(items)}")
