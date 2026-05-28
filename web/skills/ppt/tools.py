"""PowerPoint skill -- 4 tools."""

import os

SKILL_ID = "ppt"
SKILL_ALIASES = ["ppt_skill"]

# ── Layout name mapping (python-pptx built-in layout indices) ────────────────
LAYOUT_MAP = {
    "title_slide": 0,
    "title_content": 1,
    "section": 2,
    "two_content": 3,
    "comparison": 4,
    "title_only": 5,
    "blank": 6,
}

TOOL_DEFS = [
    {
        "name": "get_pptx_info",
        "description": "Get structural info about a PowerPoint presentation: slide count, slide titles, layouts, and dimensions. Use this first to understand a presentation before reading or editing. Use file_path='open' for the currently open PowerPoint via COM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .pptx file, or 'open' for the active presentation via COM, or 'open:Deck.pptx' for a specific open presentation"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "read_pptx",
        "description": "Read text content from PowerPoint slides. Returns slide titles, body text, shape text, and speaker notes. Use file_path='open' for COM, or provide a full file path. Optionally read a single slide by number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .pptx file, or 'open' for the active presentation via COM, or 'open:Deck.pptx' for a specific open presentation"},
                "slide_number": {"type": "integer", "description": "1-based slide number to read. Omit to read all slides."},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "create_pptx",
        "description": "Create a new PowerPoint presentation from scratch. Provide an array of slide definitions with layout, title, content (bullets or text), and optional notes/images. Call ONCE with all slides.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path where the .pptx file will be saved"},
                "slides": {
                    "type": "array",
                    "description": "Array of slide definitions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "layout": {"type": "string", "enum": ["title_slide", "title_content", "section", "blank", "two_content", "comparison", "title_only"], "description": "Slide layout. Defaults to 'title_content'.", "default": "title_content"},
                            "title": {"type": "string", "description": "Slide title"},
                            "subtitle": {"type": "string", "description": "Subtitle (for title_slide layout only)"},
                            "content": {
                                "description": "Slide body content. Array of strings for bullet points, or a single string for one paragraph.",
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "notes": {"type": "string", "description": "Speaker notes for this slide"},
                            "image": {
                                "type": "object",
                                "description": "Optional image to add to the slide.",
                                "properties": {
                                    "path": {"type": "string", "description": "Full path to image file"},
                                    "left": {"type": "number", "description": "Left position in inches. Default 1.", "default": 1},
                                    "top": {"type": "number", "description": "Top position in inches. Default 2.", "default": 2},
                                    "width": {"type": "number", "description": "Width in inches. Default 5.", "default": 5},
                                },
                                "required": ["path"],
                            },
                        },
                    },
                },
                "author": {"type": "string", "description": "Presentation author metadata. Optional.", "default": ""},
            },
            "required": ["file_path", "slides"],
        },
    },
    {
        "name": "update_pptx",
        "description": "Update PowerPoint slides. Supports single slide updates or batch mode for multiple slides in one call. ALWAYS use batch mode when updating more than one slide. Use file_path='open' for COM, or provide a full file path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .pptx file, or 'open' for the active presentation via COM, or 'open:Deck.pptx' for a specific open presentation. Defaults to 'open'.", "default": "open"},
                "slide_number": {"type": "integer", "description": "1-based slide number to update (for single operation)"},
                "update_type": {"type": "string", "enum": ["title", "body", "shape", "batch"], "description": "What to update. Use 'batch' to update multiple slides in one call."},
                "new_text": {"type": "string", "description": "New text content to set (for single operation)"},
                "shape_index": {"type": "integer", "description": "0-based shape index when update_type is 'shape'. Defaults to 0.", "default": 0},
                "operations": {
                    "type": "array",
                    "description": "For batch mode: array of slide updates.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slide_number": {"type": "integer"},
                            "update_type": {"type": "string", "enum": ["title", "body", "shape"]},
                            "new_text": {"type": "string"},
                            "shape_index": {"type": "integer", "default": 0},
                        },
                        "required": ["slide_number", "update_type", "new_text"],
                    },
                },
            },
            "required": ["update_type"],
        },
    },
]

TOOL_STATUS = {
    "get_pptx_info": "\U0001f4ca Inspecting PowerPoint...",
    "read_pptx":     "\U0001f4ca Reading PowerPoint...",
    "create_pptx":   "\U0001f4ca Creating PowerPoint...",
    "update_pptx":   "\U0001f4ca Updating PowerPoint...",
}


# ── Tool Handlers ────────────────────────────────────────────────────────────

def _tool_get_pptx_info(file_path: str) -> dict:
    try:
        if file_path.startswith("open"):
            from skills._office_com import get_ppt_app, get_ppt_presentation
            ppt, err = get_ppt_app()
            if err:
                return {"error": err}
            pres, err = get_ppt_presentation(ppt, file_path)
            if err:
                return {"error": err}
            slides_info = []
            for i in range(1, pres.Slides.Count + 1):
                slide = pres.Slides(i)
                title = ""
                try:
                    title = slide.Shapes.Title.TextFrame.TextRange.Text
                except Exception:
                    pass
                layout = slide.Layout
                slides_info.append({"number": i, "title": title, "layout_id": layout})
            return {
                "ok": True, "file": pres.FullName,
                "slide_count": pres.Slides.Count,
                "width": pres.PageSetup.SlideWidth,
                "height": pres.PageSetup.SlideHeight,
                "slides": slides_info,
            }
        else:
            from pptx import Presentation
            from pptx.util import Emu
            prs = Presentation(file_path)
            slides_info = []
            for idx, slide in enumerate(prs.slides, 1):
                title = slide.shapes.title.text if slide.shapes.title else ""
                layout = slide.slide_layout.name
                slides_info.append({"number": idx, "title": title, "layout": layout})
            return {
                "ok": True, "file": file_path,
                "slide_count": len(prs.slides),
                "width_inches": round(prs.slide_width / Emu(914400), 2),
                "height_inches": round(prs.slide_height / Emu(914400), 2),
                "slides": slides_info,
            }
    except Exception as e:
        return {"error": str(e)}


def _tool_read_pptx(file_path: str, slide_number: int = None) -> dict:
    try:
        if file_path.startswith("open"):
            from skills._office_com import get_ppt_app, get_ppt_presentation
            ppt, err = get_ppt_app()
            if err:
                return {"error": err}
            pres, err = get_ppt_presentation(ppt, file_path)
            if err:
                return {"error": err}
            slides_data = []
            start = slide_number or 1
            end = slide_number or pres.Slides.Count
            for i in range(start, end + 1):
                slide = pres.Slides(i)
                title = ""
                try:
                    title = slide.Shapes.Title.TextFrame.TextRange.Text
                except Exception:
                    pass
                content = []
                for j in range(1, slide.Shapes.Count + 1):
                    shape = slide.Shapes(j)
                    if shape.HasTextFrame:
                        text = shape.TextFrame.TextRange.Text.strip()
                        if text and text != title:
                            content.append(text)
                notes = ""
                try:
                    notes = slide.NotesPage.Shapes(2).TextFrame.TextRange.Text.strip()
                except Exception:
                    pass
                slides_data.append({"number": i, "title": title, "content": content, "notes": notes})
            return {"ok": True, "file": pres.FullName, "slides": slides_data}
        else:
            from pptx import Presentation
            prs = Presentation(file_path)
            slides_data = []
            for idx, slide in enumerate(prs.slides, 1):
                if slide_number and idx != slide_number:
                    continue
                title = slide.shapes.title.text if slide.shapes.title else ""
                content = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        text = shape.text_frame.text.strip()
                        if text and text != title:
                            content.append(text)
                notes = ""
                if slide.has_notes_slide:
                    notes_tf = slide.notes_slide.notes_text_frame
                    if notes_tf:
                        notes = notes_tf.text.strip()
                slides_data.append({"number": idx, "title": title, "content": content, "notes": notes})
            return {"ok": True, "file": file_path, "slides": slides_data}
    except Exception as e:
        return {"error": str(e)}


def _tool_create_pptx(file_path: str, slides: list, author: str = "") -> dict:
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        prs = Presentation()

        if author:
            prs.core_properties.author = author

        for slide_def in slides:
            layout_name = slide_def.get("layout", "title_content")
            layout_idx = LAYOUT_MAP.get(layout_name, 1)

            try:
                layout = prs.slide_layouts[layout_idx]
            except IndexError:
                layout = prs.slide_layouts[1]  # fallback to title+content

            slide = prs.slides.add_slide(layout)

            # Title
            title_text = slide_def.get("title", "")
            if title_text and slide.shapes.title:
                slide.shapes.title.text = title_text

            # Subtitle (title_slide only)
            subtitle_text = slide_def.get("subtitle", "")
            if subtitle_text and layout_name == "title_slide":
                for ph in slide.placeholders:
                    if ph.placeholder_format.idx == 1:
                        ph.text = subtitle_text
                        break

            # Content (bullets or text)
            content = slide_def.get("content")
            if content and layout_name not in ("blank", "title_only"):
                body_ph = None
                for ph in slide.placeholders:
                    if ph.placeholder_format.idx not in (0, ):  # skip title
                        body_ph = ph
                        break

                if body_ph and body_ph.has_text_frame:
                    tf = body_ph.text_frame
                    tf.clear()
                    items = content if isinstance(content, list) else [content]
                    for i, item in enumerate(items):
                        if i == 0:
                            p = tf.paragraphs[0]
                        else:
                            p = tf.add_paragraph()
                        p.text = item
                        p.font.size = Pt(18)

            # Speaker notes
            notes_text = slide_def.get("notes", "")
            if notes_text:
                notes_slide = slide.notes_slide
                notes_slide.notes_text_frame.text = notes_text

            # Image
            image_def = slide_def.get("image")
            if image_def and os.path.exists(image_def.get("path", "")):
                left = Inches(image_def.get("left", 1))
                top = Inches(image_def.get("top", 2))
                width = Inches(image_def.get("width", 5))
                slide.shapes.add_picture(image_def["path"], left, top, width=width)

        prs.save(file_path)
        return {
            "ok": True,
            "message": f"Created {file_path} — {len(slides)} slide(s)",
            "file_path": file_path,
            "slide_count": len(slides),
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_update_pptx(update_type: str, slide_number: int = None, new_text: str = "",
                       file_path: str = "open", shape_index: int = 0,
                       operations: list = None) -> dict:
    try:
        if update_type == "batch":
            if not operations:
                return {"error": "operations array is required for batch mode"}
            results = []
            for i, op in enumerate(operations):
                r = _tool_update_pptx(
                    file_path=file_path,
                    slide_number=op.get("slide_number"),
                    update_type=op.get("update_type", "title"),
                    new_text=op.get("new_text", ""),
                    shape_index=op.get("shape_index", 0),
                )
                results.append({"op": i + 1, **r})
                if r.get("error"):
                    break
            succeeded = sum(1 for r in results if r.get("ok"))
            return {"ok": True, "message": f"Batch: {succeeded}/{len(operations)} slides updated", "results": results}

        if not slide_number:
            return {"error": "slide_number is required"}

        if file_path.startswith("open"):
            from skills._office_com import get_ppt_app, get_ppt_presentation, save_com_document, get_file_info
            ppt, err = get_ppt_app()
            if err:
                return {"error": err}
            pres, err = get_ppt_presentation(ppt, file_path)
            if err:
                return {"error": err}
            finfo = get_file_info(pres, "ppt")
            slide = pres.Slides(slide_number)
            if update_type == "title":
                slide.Shapes.Title.TextFrame.TextRange.Text = new_text
            else:
                shape = slide.Shapes(shape_index + 1)
                shape.TextFrame.TextRange.Text = new_text
            save_com_document(pres, "ppt")
            return {"ok": True, **finfo, "message": f"Slide {slide_number} updated in {finfo['file_name']}"}
        else:
            from pptx import Presentation
            prs = Presentation(file_path)
            slide = prs.slides[slide_number - 1]
            if update_type == "title" and slide.shapes.title:
                slide.shapes.title.text = new_text
            elif update_type == "body":
                for ph in slide.placeholders:
                    if ph.placeholder_format.idx != 0:
                        ph.text = new_text
                        break
            elif update_type == "shape":
                slide.shapes[shape_index].text_frame.text = new_text
            prs.save(file_path)
            return {"ok": True, "message": f"Saved {file_path}"}
    except Exception as e:
        return {"error": str(e)}


TOOL_HANDLERS = {
    "get_pptx_info": _tool_get_pptx_info,
    "read_pptx":     _tool_read_pptx,
    "create_pptx":   _tool_create_pptx,
    "update_pptx":   _tool_update_pptx,
}
