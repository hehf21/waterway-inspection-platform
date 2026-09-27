# 参与贡献

感谢关注本项目！这是面向交通运输主管部门的监督检查记录管理系统，欢迎 Issue 与 PR。

## 提交前必过（一键）

```powershell
powershell -ExecutionPolicy Bypass -File deploy\release.ps1 -Push -Message "说明"
```

五道关全绿才允许推送：Python 语法 → **175 项回归** → 内联 JS 语法 → **文档口径门禁**（文档里的回归项数必须与实测一致）→ **敏感文件门禁**（`data/`、密钥、库文件不得入库）。CI 上会再跑一遍同样的门禁。

## 开发环境

```bash
pip install -r requirements.txt        # 运行依赖（已锁版本）
pip install playwright && playwright install chromium   # 仅 E2E 需要
python app.py                          # http://127.0.0.1:8098
```

## 代码结构约定

- `app.py` 只做装配（中间件/健康检查/异常兜底/路由注册）；**业务逻辑写进对应 `routes_*.py`**
- 路由模块统一 `from webcore import *` 取鉴权/渲染/常量；带下划线的内部函数按需显式导入
- 模板**不写内联事件处理器**（CSP 无 unsafe-inline）：用 `data-confirm` / `data-show` / `data-submit` / `data-*` + 事件委托（见 `templates/base.html` 与各页脚本）
- 模板渲染数据库文本一律经 `esc()`（JS 侧）或 Jinja 自动转义，禁止 `|safe`
- 改动涉及新表/新列 → 更新 `db.py` 的 SCHEMA **和**迁移列表（对已有库幂等生效）

## 门禁自检工具

| 命令 | 作用 |
|---|---|
| `python smoke_test.py` | 175 项全流程回归（隔离数据目录） |
| `python e2e_test.py` | Playwright 浏览器级闭环冒烟（自动起 :8099） |
| `python js_syntax_check.py` | 模板内联脚本语法（需 node） |
| `python check_docs.py` | 文档回归项数 == 实测断言数 |
| `python db_maintenance.py check` | 数据库体检（孤儿/重复/附件一致性） |

## Bug 反馈

请用 Issue 模板，附：复现步骤、期望/实际、`smoke_test.py` 是否全绿、浏览器与版本（前端问题请注明是否 Console 有 CSP 报错）。

## License

MIT。提交即表示同意以 MIT 协议贡献代码。
