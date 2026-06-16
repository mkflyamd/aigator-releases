"""XML helpers for rich docx creation using python-docx + lxml.

Covers features that python-docx lacks high-level APIs for:
footnotes, hyperlinks, page numbers, headers/footers, TOC, multi-column,
table formatting, and document styles.
"""

import os
import subprocess
from pathlib import Path

from proc_utils import no_window_kwargs
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsmap as _nsmap
from docx.shared import Inches, Pt, Emu, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

# Namespace URIs
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Path to bundled Anthropic scripts
SHARED_SCRIPTS = Path(__file__).parent.parent / "_scripts" / "office"
VALIDATE_SCRIPT = SHARED_SCRIPTS / "validate.py"


# ── Page Layout ──────────────────────────────────────────────────────────────

PAGE_SIZES = {
    "letter": (Inches(8.5), Inches(11)),
    "a4": (Emu(11906 * 635), Emu(16838 * 635)),  # 210mm x 297mm
}


def set_page_layout(section, page_size="letter", orientation="portrait", margins=None):
    """Configure page size, orientation, and margins."""
    width, height = PAGE_SIZES.get(page_size, PAGE_SIZES["letter"])

    if orientation == "landscape":
        section.page_width = height
        section.page_height = width
        section.orientation = 1  # WD_ORIENT.LANDSCAPE
    else:
        section.page_width = width
        section.page_height = height
        section.orientation = 0  # WD_ORIENT.PORTRAIT

    m = margins or {}
    section.top_margin = Inches(m.get("top", 1.0))
    section.bottom_margin = Inches(m.get("bottom", 1.0))
    section.left_margin = Inches(m.get("left", 1.0))
    section.right_margin = Inches(m.get("right", 1.0))


# ── Styles ───────────────────────────────────────────────────────────────────

def setup_styles(doc):
    """Set up professional default styles: Arial font, styled headings."""
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    heading_configs = [
        ("Heading 1", Pt(18), True),
        ("Heading 2", Pt(14), True),
        ("Heading 3", Pt(12), True),
    ]
    for name, size, bold in heading_configs:
        if name in doc.styles:
            s = doc.styles[name]
            s.font.name = "Arial"
            s.font.size = size
            s.font.bold = bold


# ── Headers & Footers ────────────────────────────────────────────────────────

def add_header(section, text):
    """Add a header with text to a section."""
    header = section.header
    header.is_linked_to_previous = False
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    p.text = text
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.style.font.size = Pt(9)
    p.style.font.color.rgb = RGBColor(0x80, 0x80, 0x80)


def add_footer(section, text=""):
    """Add a footer with text and page number.

    Use {{page}} in text to insert page number, e.g. "Page {{page}}".
    If text is empty, adds just centered page number.
    """
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if not text or text == "{{page}}":
        _add_page_number_run(p)
    elif "{{page}}" in text:
        parts = text.split("{{page}}")
        if parts[0]:
            run = p.add_run(parts[0])
            run.font.size = Pt(9)
        _add_page_number_run(p)
        if len(parts) > 1 and parts[1]:
            run = p.add_run(parts[1])
            run.font.size = Pt(9)
    else:
        run = p.add_run(text)
        run.font.size = Pt(9)


def _add_page_number_run(paragraph):
    """Insert a PAGE field code into a paragraph."""
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "18")  # 9pt
    rPr.append(sz)
    run.append(rPr)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run.append(fld_begin)
    paragraph._element.append(run)

    run2 = OxmlElement("w:r")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    run2.append(instr)
    paragraph._element.append(run2)

    run3 = OxmlElement("w:r")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run3.append(fld_end)
    paragraph._element.append(run3)


# ── Multi-Column ─────────────────────────────────────────────────────────────

def set_columns(section, count, space_inches=0.5):
    """Set the number of columns on a section."""
    if count <= 1:
        return
    sectPr = section._sectPr
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), str(count))
    cols.set(qn("w:space"), str(int(space_inches * 1440)))
    cols.set(qn("w:equalWidth"), "1")
    # Remove existing cols element if any
    for existing in sectPr.findall(qn("w:cols")):
        sectPr.remove(existing)
    sectPr.append(cols)


# ── Table of Contents ────────────────────────────────────────────────────────

def add_toc(doc):
    """Add a Table of Contents field code. Requires Word/LibreOffice to render."""
    p = doc.add_paragraph()
    run = p.add_run()

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._element.append(fld_begin)

    run2 = p.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    run2._element.append(instr)

    run3 = p.add_run()
    fld_separate = OxmlElement("w:fldChar")
    fld_separate.set(qn("w:fldCharType"), "separate")
    run3._element.append(fld_separate)

    run4 = p.add_run("(Table of contents — update in Word to populate)")
    run4.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    run4.font.italic = True

    run5 = p.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run5._element.append(fld_end)

    return p


# ── Hyperlinks ───────────────────────────────────────────────────────────────

def add_hyperlink(paragraph, url, text, color="0563C1"):
    """Add an external hyperlink to a paragraph."""
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)

    c = OxmlElement("w:color")
    c.set(qn("w:val"), color)
    rPr.append(c)

    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)

    run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)

    hyperlink.append(run)
    paragraph._element.append(hyperlink)


# ── Footnotes ────────────────────────────────────────────────────────────────

FOOTNOTES_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
FOOTNOTES_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"


def add_footnotes_part(doc, footnotes_data):
    """Create footnotes.xml and wire it into the document package.

    footnotes_data: list of {"id": int, "text": str}
    """
    from lxml import etree
    from docx.opc.part import Part
    from docx.opc.packuri import PackURI

    W = W_NS

    nsmap = {"w": W, "r": R_NS}
    root = etree.Element(f"{{{W}}}footnotes", nsmap=nsmap)

    # Separator footnote (required, id=-1)
    fn_sep = etree.SubElement(root, f"{{{W}}}footnote")
    fn_sep.set(f"{{{W}}}type", "separator")
    fn_sep.set(f"{{{W}}}id", "-1")
    p = etree.SubElement(fn_sep, f"{{{W}}}p")
    r = etree.SubElement(p, f"{{{W}}}r")
    etree.SubElement(r, f"{{{W}}}separator")

    # Continuation separator (required, id=0)
    fn_cont = etree.SubElement(root, f"{{{W}}}footnote")
    fn_cont.set(f"{{{W}}}type", "continuationSeparator")
    fn_cont.set(f"{{{W}}}id", "0")
    p = etree.SubElement(fn_cont, f"{{{W}}}p")
    r = etree.SubElement(p, f"{{{W}}}r")
    etree.SubElement(r, f"{{{W}}}continuationSeparator")

    # User footnotes
    for fn in footnotes_data:
        fn_elem = etree.SubElement(root, f"{{{W}}}footnote")
        fn_elem.set(f"{{{W}}}id", str(fn["id"]))

        p = etree.SubElement(fn_elem, f"{{{W}}}p")

        # Paragraph style
        pPr = etree.SubElement(p, f"{{{W}}}pPr")
        pStyle = etree.SubElement(pPr, f"{{{W}}}pStyle")
        pStyle.set(f"{{{W}}}val", "FootnoteText")

        # Reference mark (superscript number in footnote area)
        r1 = etree.SubElement(p, f"{{{W}}}r")
        rPr = etree.SubElement(r1, f"{{{W}}}rPr")
        rStyle = etree.SubElement(rPr, f"{{{W}}}rStyle")
        rStyle.set(f"{{{W}}}val", "FootnoteReference")
        etree.SubElement(r1, f"{{{W}}}footnoteRef")

        # Footnote text
        r2 = etree.SubElement(p, f"{{{W}}}r")
        t = etree.SubElement(r2, f"{{{W}}}t")
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = f" {fn['text']}"

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    partname = PackURI("/word/footnotes.xml")
    footnotes_part = Part(partname, FOOTNOTES_CONTENT_TYPE, xml_bytes, doc.part.package)
    doc.part.relate_to(footnotes_part, FOOTNOTES_REL_TYPE)


def add_footnote_ref(paragraph, footnote_id):
    """Add a superscript footnote reference in the document body."""
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "FootnoteReference")
    rPr.append(rStyle)
    run.append(rPr)

    ref = OxmlElement("w:footnoteReference")
    ref.set(qn("w:id"), str(footnote_id))
    run.append(ref)

    paragraph._element.append(run)


# ── Table Formatting ─────────────────────────────────────────────────────────

def format_table(table, header_shading="D9E2F3", border_color="BFBFBF"):
    """Apply professional formatting to a table: borders, header shading, auto-fit."""
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for row_idx, row in enumerate(table.rows):
        for cell in row.cells:
            # Borders
            tc = cell._element
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = OxmlElement("w:tcPr")
                tc.insert(0, tcPr)

            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                border = OxmlElement(f"w:{edge}")
                border.set(qn("w:val"), "single")
                border.set(qn("w:sz"), "4")
                border.set(qn("w:space"), "0")
                border.set(qn("w:color"), border_color)
                borders.append(border)
            # Remove existing borders
            for existing in tcPr.findall(qn("w:tcBorders")):
                tcPr.remove(existing)
            tcPr.append(borders)

            # Header row shading
            if row_idx == 0 and header_shading:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:val"), "clear")
                shading.set(qn("w:color"), "auto")
                shading.set(qn("w:fill"), header_shading)
                for existing in tcPr.findall(qn("w:shd")):
                    tcPr.remove(existing)
                tcPr.append(shading)

                # Bold header text
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.bold = True

            # Cell margins (padding) — OOXML uses start/end not left/right
            margins = OxmlElement("w:tcMar")
            for side, val in [("top", "60"), ("bottom", "60"), ("start", "80"), ("end", "80")]:
                m = OxmlElement(f"w:{side}")
                m.set(qn("w:w"), val)
                m.set(qn("w:type"), "dxa")
                margins.append(m)
            for existing in tcPr.findall(qn("w:tcMar")):
                tcPr.remove(existing)
            tcPr.append(margins)


# ── Run Formatting ───────────────────────────────────────────────────────────

def apply_run_format(run, bold=None, italic=None, underline=None,
                     color=None, size=None, font=None):
    """Apply inline formatting to a run."""
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if underline is not None:
        run.font.underline = underline
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if size:
        run.font.size = Pt(size)
    if font:
        run.font.name = font


# ── Validation ───────────────────────────────────────────────────────────────

def validate_docx(file_path):
    """Run Anthropic's validate.py on a document. Returns (ok, output)."""
    if not VALIDATE_SCRIPT.exists():
        return True, "Validation script not found, skipping"

    try:
        result = subprocess.run(
            ["python", str(VALIDATE_SCRIPT), str(file_path), "--auto-repair"],
            capture_output=True, text=True, timeout=30,
            cwd=str(VALIDATE_SCRIPT.parent),
            **no_window_kwargs(),
        )
        output = result.stdout + result.stderr
        ok = result.returncode == 0
        return ok, output.strip()
    except Exception as e:
        return True, f"Validation skipped: {e}"
