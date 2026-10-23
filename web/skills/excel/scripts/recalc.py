"""
Excel Formula Recalculation Script
Recalculates all formulas in an Excel file using LibreOffice
"""

import json
import subprocess
import sys
from pathlib import Path

# Run directly (python recalc.py) or imported by the app: either way the shared office helpers live in skills/_scripts.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent / "_scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

from office.soffice import (  # noqa: E402
    NOT_INSTALLED_MESSAGE,
    SofficeNotFound,
    find_soffice,
    run_basic_macro,
)
from openpyxl import load_workbook  # noqa: E402

MACRO_NAME = "RecalculateAndSave"

RECALCULATE_MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
    Sub RecalculateAndSave()
      ThisComponent.calculateAll()
      ThisComponent.store()
      ThisComponent.close(True)
    End Sub
</script:module>"""


def _libreoffice_failure(result):
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    tail = " ".join(line.strip() for line in detail[-3:])[:300]
    return (
        f"LibreOffice is installed but failed to run (exit code {result.returncode})"
        + (f": {tail}" if tail else "")
        + ". The file was saved and its formulas calculate when it is opened in Excel."
    )


def _formula_cell_counts(filename):
    """(formula cells, formula cells that carry a calculated value)."""
    formulas = load_workbook(filename, data_only=False)
    values = load_workbook(filename, data_only=True)
    total = computed = 0
    try:
        for ws in formulas.worksheets:
            ws_values = values[ws.title]
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        total += 1
                        if ws_values[cell.coordinate].value is not None:
                            computed += 1
    finally:
        formulas.close()
        values.close()
    return total, computed


def recalc(filename, timeout=30):
    if not Path(filename).exists():
        return {"error": f"File {filename} does not exist"}

    if not find_soffice():
        return {"error": NOT_INSTALLED_MESSAGE, "libreoffice_missing": True}

    try:
        result = run_basic_macro(RECALCULATE_MACRO, MACRO_NAME, filename, timeout, "recalc")
    except SofficeNotFound:
        return {"error": NOT_INSTALLED_MESSAGE, "libreoffice_missing": True}
    except subprocess.TimeoutExpired:
        return {"error": f"LibreOffice did not finish within {timeout} seconds, so formulas were not recalculated."}
    except OSError as e:
        return {"error": f"LibreOffice could not be started: {e}"}

    if result.returncode != 0:
        return {"error": _libreoffice_failure(result)}

    try:
        wb = load_workbook(filename, data_only=True)

        excel_errors = [
            "#VALUE!",
            "#DIV/0!",
            "#REF!",
            "#NAME?",
            "#NULL!",
            "#NUM!",
            "#N/A",
        ]
        error_details = {err: [] for err in excel_errors}
        total_errors = 0

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None and isinstance(cell.value, str):
                        for err in excel_errors:
                            if err in cell.value:
                                location = f"{sheet_name}!{cell.coordinate}"
                                error_details[err].append(location)
                                total_errors += 1
                                break

        wb.close()

        result = {
            "status": "success" if total_errors == 0 else "errors_found",
            "total_errors": total_errors,
            "error_summary": {},
        }

        for err_type, locations in error_details.items():
            if locations:
                result["error_summary"][err_type] = {
                    "count": len(locations),
                    "locations": locations[:20],
                }

        formula_count, computed = _formula_cell_counts(filename)
        if formula_count and not computed:
            return {"error": "LibreOffice ran but did not calculate any formulas, so the results could not be checked."}

        result["total_formulas"] = formula_count

        return result

    except Exception as e:
        return {"error": str(e)}


def main():
    if len(sys.argv) < 2:
        print("Usage: python recalc.py <excel_file> [timeout_seconds]")
        print("\nRecalculates all formulas in an Excel file using LibreOffice")
        print("\nReturns JSON with error details:")
        print("  - status: 'success' or 'errors_found'")
        print("  - total_errors: Total number of Excel errors found")
        print("  - total_formulas: Number of formulas in the file")
        print("  - error_summary: Breakdown by error type with locations")
        print("    - #VALUE!, #DIV/0!, #REF!, #NAME?, #NULL!, #NUM!, #N/A")
        sys.exit(1)

    filename = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    result = recalc(filename, timeout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
