# -*- coding: utf-8 -*-
"""文档口径门禁：文档宣称的回归项数必须与 smoke_test 实际执行的断言数一致。

数字来源优先级：
1) smoke_last_run.txt（smoke_test.py 每次运行时写入的运行时断言数，含循环内多次执行）；
2) 文件不存在时现场跑一遍 smoke_test.py 并解析统计行。
用运行时数字而非 AST 调用点数：存在 `for kind in (...): check(...)` 这类循环断言
（1 个调用点 → 4 次执行），AST 口径会少数。
"""
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
COUNT_FILE = os.path.join(BASE, "smoke_last_run.txt")

if os.path.exists(COUNT_FILE):
    count = int(open(COUNT_FILE, encoding="utf-8").read().strip())
    print(f"smoke_test 运行时断言数（读取上次运行结果）：{count}")
else:
    print("smoke_last_run.txt 不存在，现场运行 smoke_test.py 取数……")
    r = subprocess.run([sys.executable, os.path.join(BASE, "smoke_test.py")],
                       capture_output=True, text=True)
    m = re.search(r"=== \d+/(\d+) 通过 ===", r.stdout)
    if not m:
        print("无法从 smoke_test 输出取得断言数：\n", r.stdout[-500:], r.stderr[-500:])
        sys.exit(1)
    count = int(m.group(1))
    print(f"smoke_test 运行时断言数：{count}")

pattern = re.compile(r"(\d+)\s*项(?:全流程)?用例|(\d+)\s*项(?:全绿|回归)|smoke_test\.py`?\s*(\d+)\s*项")
bad = []
for fn in sorted(os.listdir(BASE)):
    if not fn.endswith(".md"):
        continue
    text = open(os.path.join(BASE, fn), encoding="utf-8").read()
    for m in pattern.finditer(text):
        num = int(next(g for g in m.groups() if g))
        line = text[:m.start()].count("\n") + 1
        if num != count:
            bad.append(f"  {fn}:{line}  写 {num} 项，实际 {count} 项  «{m.group(0)[:40]}»")
        else:
            print(f"  ✓ {fn}:{line}  {num} 项 对齐")

if bad:
    print("\n[文档口径不一致]：")
    print("\n".join(bad))
    sys.exit(1)
print("\n文档口径检查通过")
