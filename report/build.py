"""Build report.docx (python-docx) and report.pdf (Word via docx2pdf) from report.md; print page count.
Usage: python report/build.py [--no-pdf]
"""
import re, sys
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = Path(__file__).resolve().parent
BODY_PT, CODE_PT, TAB_PT = 11, 7, 8.5   # tuned so the document is exactly 6 A4 pages
MARGIN_CM = 2.0
FONT = "Times New Roman"; CODE_FONT = "Consolas"

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for a in ("left_margin", "right_margin"):
    setattr(sec, a, Cm(MARGIN_CM))
for a in ("top_margin", "bottom_margin"):
    setattr(sec, a, Cm(1.8))

def setfont(run, name=FONT, size=None, bold=None, italic=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size: run.font.size = Pt(size)
    if bold is not None: run.bold = bold
    if italic is not None: run.italic = italic

st = doc.styles["Normal"]; st.font.name = FONT; st.font.size = Pt(BODY_PT)
st.paragraph_format.space_after = Pt(2); st.paragraph_format.space_before = Pt(0)
st.paragraph_format.line_spacing = 1.0

TOK = re.compile(r"(\*\*.+?\*\*|\*.+?\*|`.+?`)")
def add_inline(p, text, size=None):
    for part in TOK.split(text):
        if not part: continue
        if part.startswith("**"): r = p.add_run(part[2:-2]); setfont(r, size=size, bold=True)
        elif part.startswith("`"): r = p.add_run(part[1:-1]); setfont(r, CODE_FONT, (size or BODY_PT) - 1.2)
        elif part.startswith("*"): r = p.add_run(part[1:-1]); setfont(r, size=size, italic=True)
        else: r = p.add_run(part); setfont(r, size=size)

def shade(cell_or_p, fill):
    el = cell_or_p._tc if hasattr(cell_or_p, "_tc") else cell_or_p._p
    pr = el.get_or_add_tcPr() if hasattr(cell_or_p, "_tc") else el.get_or_add_pPr()
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), fill)
    pr.append(sh)

lines = (HERE / "report.md").read_text(encoding="utf-8").split("\n")
i = 0; first_h1 = True
while i < len(lines):
    ln = lines[i]
    if ln.startswith("```"):
        j = i + 1; buf = []
        while not lines[j].startswith("```"): buf.append(lines[j]); j += 1
        p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.0
        shade(p, "F2F2F2")
        for k, b in enumerate(buf):
            r = p.add_run(b + ("\n" if k < len(buf) - 1 else "")); setfont(r, CODE_FONT, CODE_PT)
        i = j + 1; continue
    if ln.startswith("# "):
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(ln[2:]); setfont(r, size=15, bold=True); p.paragraph_format.space_after = Pt(2)
        q = doc.add_paragraph(); q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = q.add_run("Database Term Project  |  SQLite + Python  |  Transfermarkt data"); setfont(r, size=9, italic=True)
    elif ln.startswith("## "):
        p = doc.add_paragraph(); r = p.add_run(ln[3:]); setfont(r, size=12.5, bold=True)
        p.paragraph_format.space_before = Pt(5); p.paragraph_format.space_after = Pt(2); p.paragraph_format.keep_with_next = True
    elif ln.startswith("### "):
        p = doc.add_paragraph(); r = p.add_run(ln[4:]); setfont(r, size=11, bold=True)
        p.paragraph_format.space_before = Pt(3); p.paragraph_format.space_after = Pt(1); p.paragraph_format.keep_with_next = True
    elif ln.startswith("!["):
        m = re.match(r"!\[w=([\d.]+) (.*)\]\((.*)\)", ln)
        w, cap, path = float(m[1]), m[2], m[3]
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(HERE / path), width=Cm((21.0 - 2 * MARGIN_CM) * w))
        c = doc.add_paragraph(); c.alignment = WD_ALIGN_PARAGRAPH.CENTER; add_inline(c, cap, 8.5)
    elif ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            if not re.match(r"^\|[\s\-|]+\|$", lines[i]):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
            i += 1
        t = doc.add_table(rows=len(rows), cols=len(rows[0])); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for ri, row in enumerate(rows):
            for ci, txt in enumerate(row):
                cell = t.cell(ri, ci); cp = cell.paragraphs[0]; cp.paragraph_format.space_after = Pt(0)
                add_inline(cp, ("**%s**" % txt) if ri == 0 else txt, TAB_PT)
                if ri == 0: shade(cell, "E7E6E6")
        sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(0)
        for r in sp.runs: pass
        sp.paragraph_format.line_spacing = Pt(3)
        continue
    elif ln.startswith("- "):
        p = doc.add_paragraph(style="List Bullet"); p.paragraph_format.space_after = Pt(1)
        add_inline(p, ln[2:])
    elif ln.strip():
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; add_inline(p, ln)
    i += 1

out = HERE / "report.docx"; doc.save(out); print("saved", out)
if "--no-pdf" not in sys.argv:
    from docx2pdf import convert
    convert(str(out), str(HERE / "report.pdf"))
    import fitz
    print("PDF pages:", fitz.open(str(HERE / "report.pdf")).page_count)
