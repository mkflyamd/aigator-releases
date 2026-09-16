# macOS release build 35143715850

## Summary

Both macOS packages built successfully, but the packaged backend startup smoke test allowed only 60 seconds. PyInstaller's one-file backend took about 75 to 79 seconds to extract and reach FastAPI startup on the hosted macOS runners, so the workflow stopped polling immediately before the backend could serve `/health`.

The release matrix now gives macOS x64 and arm64 up to 180 seconds to start while retaining the 60-second limit for Windows and Linux. The polling loop also exits early if the backend process terminates.

## Verification

- `uv run pytest tests/test_desktop_packaging.py -q`: 14 passed.
- `uv lock --check`: passed.
- Release workflow YAML parsing and startup limits: passed.
- `git diff --check`: passed.
- `uv run pytest -q`: 1547 passed, 1 skipped, 6 unrelated failures. Five failures are existing source/test expectation mismatches; one requires an uninstalled Playwright Chromium binary.

## Full output

- [Failed release run](https://github.com/mkflyamd/aigator-releases/actions/runs/35143715850)
- [macOS arm64 job](https://github.com/mkflyamd/aigator-releases/actions/runs/35143715850/job/104954339386)
- [macOS x64 job](https://github.com/mkflyamd/aigator-releases/actions/runs/35143715850/job/104954339403)
