import shutil
import subprocess
import sys


def main() -> int:
    powershell = shutil.which("pwsh")
    if not powershell:
        return 0
    check_module = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            "if (Get-Module -ListAvailable PSScriptAnalyzer) { exit 0 } else { exit 2 }",
        ]
    )
    if check_module.returncode == 2:
        return 0
    if check_module.returncode:
        return check_module.returncode
    paths = ",".join(f"'{filename.replace("'", "''")}'" for filename in sys.argv[1:])
    command = (
        "$issues = Invoke-ScriptAnalyzer -Path @(" + paths + ") -Severity Error; "
        "$issues | Format-Table -AutoSize; if ($issues) { exit 1 }"
    )
    return subprocess.run([powershell, "-NoProfile", "-Command", command]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
