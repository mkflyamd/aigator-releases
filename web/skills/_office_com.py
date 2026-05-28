"""Shared COM helpers for Office skills (Excel, Word, PowerPoint).

Handles listing open files, identifying the active document, and
targeting a specific open file by name.
"""


def get_excel_app():
    """Get the running Excel COM application. Returns (app, error_msg)."""
    try:
        import win32com.client
        app = win32com.client.GetActiveObject("Excel.Application")
        if app.Workbooks.Count == 0:
            return None, "Excel is running but no workbooks are open."
        return app, None
    except Exception:
        return None, "Excel is not running. Open a workbook first, or provide a file path."


def get_excel_workbook(app, file_path="open"):
    """Get a workbook by name or the active one.

    file_path="open" → ActiveWorkbook
    file_path="open:Budget.xlsx" → specific workbook by name
    """
    if ":" in file_path and file_path.startswith("open:"):
        name = file_path.split(":", 1)[1].strip()
        for i in range(1, app.Workbooks.Count + 1):
            wb = app.Workbooks(i)
            if wb.Name.lower() == name.lower() or wb.FullName.lower().endswith(name.lower()):
                return wb, None
        names = [app.Workbooks(i + 1).Name for i in range(app.Workbooks.Count)]
        return None, f"Workbook '{name}' not found. Open workbooks: {', '.join(names)}"
    return app.ActiveWorkbook, None


def list_excel_workbooks(app):
    """List all open workbooks."""
    books = []
    for i in range(1, app.Workbooks.Count + 1):
        wb = app.Workbooks(i)
        books.append({"name": wb.Name, "path": wb.FullName, "active": wb.Name == app.ActiveWorkbook.Name})
    return books


def get_word_app():
    """Get the running Word COM application. Returns (app, error_msg)."""
    try:
        import win32com.client
        app = win32com.client.GetActiveObject("Word.Application")
        if app.Documents.Count == 0:
            return None, "Word is running but no documents are open."
        return app, None
    except Exception:
        return None, "Word is not running. Open a document first, or provide a file path."


def get_word_document(app, file_path="open"):
    """Get a document by name or the active one."""
    if ":" in file_path and file_path.startswith("open:"):
        name = file_path.split(":", 1)[1].strip()
        for i in range(1, app.Documents.Count + 1):
            doc = app.Documents(i)
            if doc.Name.lower() == name.lower() or doc.FullName.lower().endswith(name.lower()):
                return doc, None
        names = [app.Documents(i + 1).Name for i in range(app.Documents.Count)]
        return None, f"Document '{name}' not found. Open documents: {', '.join(names)}"
    return app.ActiveDocument, None


def list_word_documents(app):
    """List all open Word documents."""
    docs = []
    for i in range(1, app.Documents.Count + 1):
        doc = app.Documents(i)
        docs.append({"name": doc.Name, "path": doc.FullName, "active": doc.Name == app.ActiveDocument.Name})
    return docs


def get_ppt_app():
    """Get the running PowerPoint COM application. Returns (app, error_msg)."""
    try:
        import win32com.client
        app = win32com.client.GetActiveObject("PowerPoint.Application")
        if app.Presentations.Count == 0:
            return None, "PowerPoint is running but no presentations are open."
        return app, None
    except Exception:
        return None, "PowerPoint is not running. Open a presentation first, or provide a file path."


def get_ppt_presentation(app, file_path="open"):
    """Get a presentation by name or the active one."""
    if ":" in file_path and file_path.startswith("open:"):
        name = file_path.split(":", 1)[1].strip()
        for i in range(1, app.Presentations.Count + 1):
            pres = app.Presentations(i)
            if pres.Name.lower() == name.lower() or pres.FullName.lower().endswith(name.lower()):
                return pres, None
        names = [app.Presentations(i + 1).Name for i in range(app.Presentations.Count)]
        return None, f"Presentation '{name}' not found. Open presentations: {', '.join(names)}"
    return app.ActivePresentation, None


def list_ppt_presentations(app):
    """List all open PowerPoint presentations."""
    preses = []
    active_name = ""
    try:
        active_name = app.ActivePresentation.Name
    except Exception:
        pass
    for i in range(1, app.Presentations.Count + 1):
        pres = app.Presentations(i)
        preses.append({"name": pres.Name, "path": pres.FullName, "active": pres.Name == active_name})
    return preses


# ── Save & Verify ────────────────────────────────────────────────────────────

def save_com_document(target, app_type: str):
    """Save a COM document/workbook/presentation. Returns (ok, error_msg).

    For unsaved files (no path), returns an error suggesting Save As.
    """
    try:
        # Check if file has been saved before
        full_name = target.FullName
        is_unsaved = (
            (app_type == "word" and full_name == target.Name) or
            (app_type == "excel" and not target.Path) or
            (app_type == "ppt" and full_name == target.Name)
        )
        if is_unsaved:
            return False, (
                f"'{target.Name}' has never been saved to disk. "
                f"Please use File → Save As in the application first, "
                f"or provide a file path so I can save it for you."
            )
        target.Save()
        return True, None
    except Exception as e:
        return False, f"Save failed: {e}"


def get_file_info(target, app_type: str) -> dict:
    """Get file identification info from a COM target."""
    try:
        name = target.Name
        full_name = target.FullName
        is_unsaved = (
            (app_type == "word" and full_name == name) or
            (app_type == "excel" and not target.Path) or
            (app_type == "ppt" and full_name == name)
        )
        return {
            "file_name": name,
            "file_path": full_name if not is_unsaved else None,
            "saved_to_disk": not is_unsaved,
        }
    except Exception:
        return {"file_name": "unknown", "file_path": None, "saved_to_disk": False}


def verify_com_alive(app_type: str):
    """Quick check that the Office app COM connection is alive. Returns (alive, app_or_none)."""
    try:
        import win32com.client
        if app_type == "word":
            app = win32com.client.GetActiveObject("Word.Application")
            return app.Documents.Count > 0, app
        elif app_type == "excel":
            app = win32com.client.GetActiveObject("Excel.Application")
            return app.Workbooks.Count > 0, app
        elif app_type == "ppt":
            app = win32com.client.GetActiveObject("PowerPoint.Application")
            return app.Presentations.Count > 0, app
    except Exception:
        pass
    return False, None
