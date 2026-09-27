# -*- coding: utf-8 -*-
"""内联脚本语法检查：提取各模板 <script>（非 src），替换 Jinja 表达式后做 node --check。
开发期工具——防止手改模板 JS 引入语法错误。需要本机有 node。"""
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
ok = fail = 0
for fn in sorted(os.listdir(TPL)):
    if not fn.endswith(".html"):
        continue
    src = open(os.path.join(TPL, fn), encoding="utf-8").read()
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S):
        js = m.group(1)
        js = re.sub(r"\{\{.*?\}\}", "null", js, flags=re.S)      # Jinja 表达式 → null
        js = re.sub(r"\{%.*?%\}", "", js, flags=re.S)            # Jinja 语句 → 删除
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fp:
            fp.write(js)
            tmp = fp.name
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print(f"[JS语法错误] {fn}:\n{r.stderr[:500]}")
print(f"内联脚本语法检查：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
