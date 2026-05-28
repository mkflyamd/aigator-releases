"""AI Gator dedicated endpoints -- Office document generation (PPTX, Excel, DOCX)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class AigatorPptxRequest(BaseModel):
    file_path: str = "open"
    slide_number: int
    update_type: str  # "title" | "body" | "shape"
    new_text: str
    shape_index: int = 0


class AigatorExcelRequest(BaseModel):
    file_path: str
    cell: str
    value: str
    sheet_name: str = ""


class AigatorExcelCreateRequest(BaseModel):
    file_path: str
    sheets: list = []
    author: str = ""


class AigatorPptxCreateRequest(BaseModel):
    file_path: str
    slides: list = []
    author: str = ""


class AigatorDocxUpdateRequest(BaseModel):
    file_path: str = "open"
    action: str  # "find_replace" | "append" | "insert_after"
    find_text: str = ""
    replace_text: str = ""
    content_type: str = "paragraph"
    text: str = ""


class AigatorDocxCreateRequest(BaseModel):
    file_path: str
    title: str = ""
    content: list = []
    author: str = ""
    page_size: str = "letter"
    orientation: str = "portrait"
    margins: dict = None
    header_text: str = ""
    footer_text: str = ""
    columns: int = 1
    footnotes: list = None


# ── Aigator routes ───────────────────────────────────────────────────────────


@router.post("/api/aigator/update-pptx")
async def aigator_update_pptx(req: AigatorPptxRequest):
    from skills.ppt.tools import _tool_update_pptx
    result = _tool_update_pptx(req.slide_number, req.update_type, req.new_text,
                                req.file_path, req.shape_index)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to update PowerPoint"))
    return result


@router.post("/api/aigator/update-excel")
async def aigator_update_excel(req: AigatorExcelRequest):
    from skills.excel.tools import _tool_update_excel
    result = _tool_update_excel(req.file_path, req.cell, req.value, req.sheet_name)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to update Excel"))
    return result


@router.post("/api/aigator/create-excel")
async def aigator_create_excel(req: AigatorExcelCreateRequest):
    from skills.excel.tools import _tool_create_excel
    result = _tool_create_excel(req.file_path, req.sheets, req.author)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to create Excel workbook"))
    return result


@router.post("/api/aigator/create-pptx")
async def aigator_create_pptx(req: AigatorPptxCreateRequest):
    from skills.ppt.tools import _tool_create_pptx
    result = _tool_create_pptx(req.file_path, req.slides, req.author)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to create PowerPoint"))
    return result


@router.post("/api/aigator/update-docx")
async def aigator_update_docx(req: AigatorDocxUpdateRequest):
    from skills.docx.tools import _tool_update_docx
    result = _tool_update_docx(req.file_path, req.action, req.find_text,
                                req.replace_text, req.content_type, req.text)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to update Word document"))
    return result


@router.post("/api/aigator/create-docx")
async def aigator_create_docx(req: AigatorDocxCreateRequest):
    from skills.docx.tools import _tool_create_docx
    result = _tool_create_docx(req.file_path, req.content, req.title, req.author,
                                req.page_size, req.orientation, req.margins,
                                req.header_text, req.footer_text, req.columns, req.footnotes)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to create Word document"))
    return result
