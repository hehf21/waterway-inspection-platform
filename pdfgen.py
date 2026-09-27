# -*- coding: utf-8 -*-
"""PDF 文书生成：现场检查记录表 / 责令整改通知书 / 整改情况报告 / 复核意见"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"

S_TITLE = ParagraphStyle("t", fontName=FONT, fontSize=16, leading=22, alignment=1, spaceAfter=4)
S_SUB = ParagraphStyle("s", fontName=FONT, fontSize=10, leading=14, alignment=1, spaceAfter=8)
S_H2 = ParagraphStyle("h2", fontName=FONT, fontSize=12, leading=18, spaceBefore=8, spaceAfter=4)
S_BODY = ParagraphStyle("b", fontName=FONT, fontSize=10, leading=16)
S_SMALL = ParagraphStyle("sm", fontName=FONT, fontSize=8.5, leading=12)
S_CELL = ParagraphStyle("c", fontName=FONT, fontSize=8.5, leading=11.5)

ORG = "平潭综合实验区交通与建设局"


def _p(text, style=S_CELL):
    return Paragraph(str(text).replace("\n", "<br/>") if text else "", style)


def _table(data, col_widths, header_rows=1):
    t = Table(data, colWidths=col_widths, repeatRows=header_rows)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.Color(.9, .93, .96)),
    ]))
    return t


def _doc(path):
    return SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=18 * mm, rightMargin=18 * mm,
                             topMargin=16 * mm, bottomMargin=16 * mm)


def _footer():
    return Spacer(1, 8 * mm)


def _sign_img(path, max_w=55 * mm, max_h=16 * mm):
    """手写签名图片：按比例缩放后放入签字栏（无文件/解码失败返回空，退回空白签字栏）"""
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(path)
        iw, ih = ir.getSize()
        scale = min(max_w / iw, max_h / ih)
        return Image(path, width=iw * scale, height=ih * scale)
    except Exception:
        return ""


def _sign_block(pairs, images=None):
    """签字栏：pairs=[('检查人员（签字）','企业负责人（签字）'), ...]
    images: {"left": 签名图路径, "right": 签名图路径} —— 有则在标签行上方插入手写签名。"""
    data, heights = [], []
    if images and (images.get("left") or images.get("right")):
        data.append([_sign_img(images["left"]) if images.get("left") else "",
                     _sign_img(images["right"]) if images.get("right") else ""])
        heights.append(18 * mm)
    data += [[_p(a, S_BODY), _p(b, S_BODY)] for a, b in pairs]
    heights += [14 * mm] * len(pairs)
    t = Table(data, colWidths=[87 * mm, 87 * mm], rowHeights=heights)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    return t


def _header(title, code):
    return [Paragraph(title, S_TITLE),
            Paragraph(f"{ORG}　　　检查（记录）编号：{code}", S_SUB)]


def record_pdf(info, items, out_path, signs=None):
    """01 现场检查记录表；signs={"ent": 企业签名图, "insp": 检查人员签名图}"""
    story = _header("水路运输企业现场检查记录表", info["code"])
    meta = [
        [_p("被检查企业"), _p(info["ent_name"]), _p("统一社会信用代码"), _p(info.get("credit_code", ""))],
        [_p("检查时间"), _p(info["check_date"]), _p("检查方式"), _p(info.get("check_mode", ""))],
        [_p("检查地点"), _p(info.get("location", "")), _p("检查类型"), _p(info["check_type"])],
        [_p("检查人员"), _p(info.get("inspectors", "")), _p("许可证号"), _p(info.get("license_no", ""))],
    ]
    story.append(_table(meta, [26 * mm, 61 * mm, 32 * mm, 55 * mm], header_rows=0))
    story.append(Spacer(1, 3 * mm))

    head = [_p("序号"), _p("检查项目"), _p("检查内容"), _p("检查依据"), _p("检查方法"), _p("检查结果"), _p("情况记录")]
    data = [head]
    for i, it in enumerate(items, 1):
        mark = "（重点）" if it.get("is_key") else ""
        data.append([_p(i), _p(it["item_name"] + mark), _p(it["item_content"]), _p(it["legal_basis"]),
                     _p(it.get("method", "")), _p(it.get("result", "")), _p(it.get("finding", ""))])
    story.append(_table(data, [9 * mm, 24 * mm, 48 * mm, 38 * mm, 15 * mm, 14 * mm, 26 * mm]))
    story.append(Spacer(1, 3 * mm))

    concl = [[_p("检查结论"), _p(info.get("conclusion", ""))],
             [_p("结论说明"), _p(info.get("conclusion_note", ""))]]
    story.append(_table(concl, [26 * mm, 148 * mm], header_rows=0))
    story.append(Spacer(1, 4 * mm))
    story.append(_p("本记录一式两份，一份交被检查企业，一份归档。被检查企业拒绝签字的，检查人员应将情况记录在案。", S_SMALL))
    story.append(_footer())
    story.append(_sign_block([("检查人员（签字）：　　　　　　　　", "企业负责人（签字）：　　　　　　　　"),
                              ("日期：　　年　　月　　日", "日期：　　年　　月　　日")],
                             images={"left": (signs or {}).get("insp"), "right": (signs or {}).get("ent")}))
    _doc(out_path).build(story)


def notice_pdf(info, problems, out_path, signs=None):
    """02 问题清单及整改要求（责令整改通知书样式）"""
    story = _header("水路运输企业检查问题清单及整改要求", info["code"])
    story.append(_p(f"被检查企业：{info['ent_name']}　　检查日期：{info['check_date']}　　整改期限：{info.get('deadline', '')}", S_BODY))
    story.append(Spacer(1, 3 * mm))
    if problems:
        head = [_p("问题编号"), _p("问题描述"), _p("违反的法律条款"), _p("整改要求"), _p("整改期限"), _p("责任人"), _p("备注")]
        data = [head]
        for p in problems:
            note = "移送海事部门" if p.get("to_msa") else ""
            data.append([_p(p["seq_label"]), _p(p["description"]), _p(p["legal_basis"]),
                         _p(p["requirement"]), _p(p["deadline"]), _p(p["responsible"]), _p(note)])
        story.append(_table(data, [15 * mm, 45 * mm, 34 * mm, 38 * mm, 17 * mm, 13 * mm, 12 * mm]))
    else:
        story.append(_p("本次检查未发现问题。", S_BODY))
    story.append(Spacer(1, 4 * mm))
    story.append(_p("请对照上述问题清单逐项落实整改，并在整改期限届满前通过本平台反馈整改情况并上传证明材料。"
                    "逾期未整改或整改不到位的，将依法依规处理。", S_SMALL))
    story.append(_footer())
    story.append(_sign_block([("检查人员（签字）：　　　　　　　　", "企业负责人（签收）：　　　　　　　　"),
                              ("日期：　　年　　月　　日", "日期：　　年　　月　　日")],
                             images={"left": (signs or {}).get("insp"), "right": (signs or {}).get("ent")}))
    _doc(out_path).build(story)


def feedback_pdf(info, rows, out_path, signs=None):
    """03 企业整改情况报告"""
    story = _header("水路运输企业检查整改情况报告", info["code"])
    story.append(_p(f"被检查企业：{info['ent_name']}　　整改期限：{info.get('deadline', '')}", S_BODY))
    story.append(Spacer(1, 3 * mm))
    if rows:
        head = [_p("问题编号"), _p("问题描述"), _p("原因分析与整改措施"), _p("完成情况"), _p("完成日期"), _p("附件")]
        data = [head]
        for r in rows:
            sub = r.get("submitter") or ""
            data.append([_p(r["seq_label"]), _p(r["description"]),
                         _p(f"问题认识/原因分析：{r.get('reason','')}\n整改措施：{r['measure']}"
                            + (f"\n提交人：{sub}" if sub else "")),
                         _p(r["completion"]), _p(r["done_date"]), _p(r["att_names"])])
        story.append(_table(data, [15 * mm, 38 * mm, 55 * mm, 30 * mm, 16 * mm, 20 * mm]))
    else:
        story.append(_p("本次检查未发现问题，无需整改。", S_BODY))
    story.append(_footer())
    story.append(_sign_block([("企业负责人（签字）：　　　　　　　　", "（企业盖章）"),
                              ("日期：　　年　　月　　日", "")],
                             images={"left": (signs or {}).get("ent")}))
    _doc(out_path).build(story)


def review_pdf(info, rows, out_path):
    """05 复核意见与复查记录"""
    story = _header("水路运输企业检查整改复核意见与复查记录", info["code"])
    story.append(_p(f"被检查企业：{info['ent_name']}　　复核方式：材料复核 / 现场复查", S_BODY))
    story.append(Spacer(1, 3 * mm))
    if rows:
        head = [_p("问题编号"), _p("整改情况摘要"), _p("复核结论"), _p("复核意见"), _p("复查日期"), _p("复查情况"), _p("复核人")]
        data = [head]
        for r in rows:
            data.append([_p(r["seq_label"]), _p(r["summary"]), _p(r["result_cn"]),
                         _p(r["opinion"]), _p(r["recheck_date"]), _p(r["recheck_note"]), _p(r["reviewer"])])
        story.append(_table(data, [15 * mm, 36 * mm, 16 * mm, 34 * mm, 17 * mm, 36 * mm, 20 * mm]))
    else:
        story.append(_p("无复核记录。", S_BODY))
    story.append(_footer())
    story.append(_sign_block([("复核人员（签字）：　　　　　　　　", "企业负责人（签字）：　　　　　　　　"),
                              ("日期：　　年　　月　　日", "日期：　　年　　月　　日")]))
    _doc(out_path).build(story)


def catalog_pdf(info, catalog, out_path):
    """06 归档目录（PDF 版，随 xlsx 同时提供）"""
    story = _header("检查记录归档目录", info["code"])
    story.append(_p(f"被检查企业：{info['ent_name']}　　检查日期：{info['check_date']}　"
                    f"　检查类型：{info['check_type']}　　归档状态：{info.get('status_cn', '')}", S_BODY))
    story.append(Spacer(1, 3 * mm))
    head = [_p("序号"), _p("文件名"), _p("类别"), _p("件数/大小"), _p("备注")]
    data = [head]
    for c in catalog:
        data.append([_p(c["no"]), _p(c["name"]), _p(c["kind"]), _p(c["size"]), _p(c["note"])])
    story.append(_table(data, [12 * mm, 68 * mm, 30 * mm, 28 * mm, 36 * mm]))
    story.append(_footer())
    story.append(_sign_block([("归档人（签字）：　　　　　　　　", "归档日期：　　年　　月　　日")]))
    _doc(out_path).build(story)
