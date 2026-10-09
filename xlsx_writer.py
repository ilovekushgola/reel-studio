"""
xlsx_writer.py - dependency-free .xlsx writer (stdlib only).

Excel workbooks are a zip of XML parts. This writes one sheet with a bold
frozen header row, auto column widths and inline strings, plus a light
zebra striping so the file opens looking like a real report.

Usage:
    from xlsx_writer import write_xlsx
    write_xlsx("out.xlsx", columns=["a","b"], rows=[[1,2],[3,4]], sheet_name="Data")
"""
from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import escape

_CELL_REF = re.compile(r"^[A-Z]{1,3}$")


def _col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sheet_xml(columns, rows):
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    ]
    ncols = max(1, len(columns))
    # column widths
    widths = []
    for i, c in enumerate(columns):
        longest = len(str(c))
        for r in rows[:400]:
            if i < len(r) and r[i] is not None:
                longest = max(longest, len(str(r[i])))
        widths.append(min(60, max(10, longest + 2)))
    parts.append("<cols>")
    for i, w in enumerate(widths):
        parts.append(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>')
    parts.append("</cols>")

    parts.append("<sheetData>")
    # header
    parts.append('<row r="1">')
    for i, c in enumerate(columns):
        ref = f"{_col_letter(i)}1"
        parts.append(f'<c r="{ref}" s="1" t="inlineStr"><is><t xml:space="preserve">'
                     f"{escape(str(c))}</t></is></c>")
    parts.append("</row>")
    # body
    for ri, row in enumerate(rows, start=2):
        style = "3" if ri % 2 else "2"
        parts.append(f'<row r="{ri}">')
        for ci in range(ncols):
            v = row[ci] if ci < len(row) else None
            if v is None or v == "":
                continue
            ref = f"{_col_letter(ci)}{ri}"
            if _is_num(v):
                parts.append(f'<c r="{ref}" s="{style}"><v>{v}</v></c>')
            else:
                parts.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is>'
                             f'<t xml:space="preserve">{escape(str(v))}</t></is></c>')
        parts.append("</row>")
    parts.append("</sheetData>")
    parts.append(f'<autoFilter ref="A1:{_col_letter(ncols-1)}{len(rows)+1}"/>')
    parts.append('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>')
    parts.append("</worksheet>")
    return "".join(parts)


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF0F0F0F"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF4F4F5"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>
</cellXfs>
</styleSheet>"""


def write_xlsx(path: str, columns, rows, sheet_name: str = "Data") -> str:
    sheet_name = re.sub(r"[\[\]:*?/\\]", "-", str(sheet_name))[:31] or "Data"
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", _sheet_xml(list(columns), [list(r) for r in rows]))
    return path
