# -*- coding: utf-8 -*-
"""水路运输企业检查记录管理平台 — 全局配置"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SLYS_DATA", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archives")

DEFAULT_SECRET = "slys-dev-secret-change-in-production"


def _load_secret() -> str:
    """会话密钥：优先环境变量 SLYS_SECRET，其次 data\\secret.key（首次自动生成并持久化）。

    绝不再回退到内置默认值——默认值一旦生效，任何人都能自签管理员会话。
    """
    env = os.environ.get("SLYS_SECRET", "").strip()
    if env:
        if env == DEFAULT_SECRET or len(env) < 32:
            raise SystemExit("[安全] SLYS_SECRET 过短或仍是内置默认值，已拒绝启动（要求≥32位随机串）。")
        return env
    key_file = os.path.join(DATA_DIR, "secret.key")
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as fp:
                saved = fp.read().strip()
            if len(saved) >= 32:
                return saved
        import secrets as _secrets
        os.makedirs(DATA_DIR, exist_ok=True)
        generated = _secrets.token_urlsafe(48)
        with open(key_file, "w", encoding="utf-8") as fp:
            fp.write(generated)
        print("[安全] 已生成随机会话密钥并保存到 data\\secret.key（请随 data 目录一并备份，删除后所有会话失效）")
        return generated
    except OSError as exc:
        raise SystemExit("[安全] 无法生成会话密钥（%s）：请设置环境变量 SLYS_SECRET（≥32位随机串）。" % exc) from exc


SECRET_KEY = _load_secret()
SESSION_DAYS = 7
# 监听地址/端口可用环境变量覆盖（政务外网部署设 SLYS_HOST=0.0.0.0 即可，无需改源码）
HOST = os.environ.get("SLYS_HOST", "127.0.0.1")
PORT = int(os.environ.get("SLYS_PORT", "8098"))
MAX_UPLOAD_MB = 50
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".txt"}

APP_NAME = "水路运输企业检查记录管理平台"
ORG_NAME = os.environ.get("SLYS_ORG", "平潭综合实验区交通与建设局")   # 文书落款单位，可用环境变量覆盖

# —— 可选集成开关（不配置则相关能力自动降级，不影响主流程）——
WEBHOOK_URL = os.environ.get("SLYS_WEBHOOK_URL", "")          # 企业微信群机器人地址：每日逾期/临期提醒推送
PUSH_TIME = os.environ.get("SLYS_PUSH_TIME", "08:30")          # 每日推送时间 HH:MM
PUBLIC_RANDOM_NOTICE = os.environ.get("SLYS_PUBLIC_NOTICE", "1") == "1"   # 双随机结果公示页开关
ALLOW_GOV_ENT_FEEDBACK = os.environ.get("SLYS_ALLOW_GOV_FEEDBACK", "1") == "1"  # 是否允许政府代企业录整改反馈（代录全程标注）

# 状态机
REC_DRAFT = "draft"          # 草稿
REC_ISSUED = "issued"        # 已下发（整改中）
REC_REVIEW = "review"        # 待复核
REC_CLOSED = "closed"        # 整改完成闭环
REC_ARCHIVED = "archived"    # 已归档

REC_STATUS_CN = {
    "draft": "草稿", "issued": "整改中", "review": "待复核",
    "closed": "已闭环", "archived": "已归档",
}

PROB_PENDING = "pending"      # 待整改
PROB_SUBMITTED = "submitted"  # 已反馈待复核
PROB_PASSED = "passed"        # 复核通过
PROB_RETURNED = "returned"    # 复核退回（重新整改）

PROB_STATUS_CN = {
    "pending": "待整改", "submitted": "待复核",
    "passed": "复核通过", "returned": "已退回",
}

RESULT_OK = "符合"
RESULT_NG = "不符合"
RESULT_NA = "不适用"
RESULT_UNCHECKED = "未检查"   # 显式“本次未查”（不计入符合率，打印表标注）

CHECK_TYPES = ["日常检查", "专项检查", "双随机抽查", "复查", "投诉举报核查"]
CHECK_MODES = ["现场检查", "书面检查", "网络检查"]

ROLES = {
    "gov_admin": "政府管理员",
    "gov_staff": "政府检查员",
    "enterprise": "企业用户",
    "sysadmin": "系统管理员",
}
GOV_ROLES = ("gov_admin", "gov_staff")


def ensure_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, ARCHIVE_DIR):
        os.makedirs(d, exist_ok=True)
