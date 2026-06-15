"""Shared constants for Gator Chat skill tool definitions."""

FILE_PATH_DESC = (
    "Full path to file, or 'open' for the active document via COM, "
    "or 'open:filename' to target a specific open file by name"
)

FILE_PATH_DESC_DOCX = FILE_PATH_DESC.replace("file", ".docx file").replace("document", "Word document")
FILE_PATH_DESC_XLSX = FILE_PATH_DESC.replace("file", ".xlsx file").replace("document", "Excel workbook")
FILE_PATH_DESC_PPTX = FILE_PATH_DESC.replace("file", ".pptx file").replace("document", "PowerPoint presentation")
