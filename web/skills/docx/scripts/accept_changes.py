"""Accept all tracked changes in a DOCX file using LibreOffice.

Requires LibreOffice (soffice) to be installed.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Run directly or imported by the app: the shared office helpers live in skills/_scripts.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent / "_scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

from office.soffice import NOT_INSTALLED_MESSAGE, SofficeNotFound, run_basic_macro  # noqa: E402

MACRO_NAME = "AcceptAllTrackedChanges"

ACCEPT_CHANGES_MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
    Sub AcceptAllTrackedChanges()
        Dim document As Object
        Dim dispatcher As Object

        document = ThisComponent.CurrentController.Frame
        dispatcher = createUnoService("com.sun.star.frame.DispatchHelper")

        dispatcher.executeDispatch(document, ".uno:AcceptAllTrackedChanges", "", 0, Array())
        ThisComponent.store()
        ThisComponent.close(True)
    End Sub
</script:module>"""


def accept_changes(
    input_file: str,
    output_file: str,
) -> tuple[None, str]:
    input_path = Path(input_file)
    output_path = Path(output_file)

    if not input_path.exists():
        return None, f"Error: Input file not found: {input_file}"

    if not input_path.suffix.lower() == ".docx":
        return None, f"Error: Input file is not a DOCX file: {input_file}"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
    except Exception as e:
        return None, f"Error: Failed to copy input file to output location: {e}"

    try:
        result = run_basic_macro(
            ACCEPT_CHANGES_MACRO, MACRO_NAME, str(output_path), 30, "docx"
        )
    except SofficeNotFound:
        return None, f"Error: {NOT_INSTALLED_MESSAGE}"
    except subprocess.TimeoutExpired:
        return (
            None,
            f"Successfully accepted all tracked changes: {input_file} -> {output_file}",
        )
    except OSError as e:
        return None, f"Error: LibreOffice could not be started: {e}"

    if result.returncode != 0:
        return None, f"Error: LibreOffice failed: {result.stderr}"

    return (
        None,
        f"Successfully accepted all tracked changes: {input_file} -> {output_file}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Accept all tracked changes in a DOCX file"
    )
    parser.add_argument("input_file", help="Input DOCX file with tracked changes")
    parser.add_argument(
        "output_file", help="Output DOCX file (clean, no tracked changes)"
    )
    args = parser.parse_args()

    _, message = accept_changes(args.input_file, args.output_file)
    print(message)

    if "Error" in message:
        raise SystemExit(1)
