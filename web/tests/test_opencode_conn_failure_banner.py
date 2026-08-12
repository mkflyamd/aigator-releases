"""Manual recovery UX for "Failed to send prompt / Unable to connect" — the
OpenCode TUI's own text when it can't reach models.dev or the LLM gateway.

This is printed as TERMINAL OUTPUT (the TUI's own error display), never
surfaced to Gator as an HTTP error, so detection has to watch what OpenCode
actually prints. A dismissible banner (same pattern as the existing MCP-failure
banner) offers a manual "Restart" action rather than auto-restarting — the
session may still be perfectly usable for anything that doesn't need the
network, so silently killing it would be a worse surprise than the error.
"""
import pathlib
import re

JS = (pathlib.Path(__file__).resolve().parent.parent / "static" / "tp-opencode-terminal.js").read_text(encoding="utf-8")
CSS = (pathlib.Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(encoding="utf-8")


class TestConnFailureDetection:
    def test_pattern_matches_known_opencode_error_text(self):
        idx = JS.find("_OC_CONN_FAIL_PATTERN")
        assert idx != -1, "a connection-failure detection pattern must exist"
        region = JS[idx:idx + 300]
        m = re.search(r"_OC_CONN_FAIL_PATTERN\s*=\s*(/.*?/[a-z]*);", region, re.DOTALL)
        assert m, "could not locate the regex literal"
        pattern = m.group(1)
        # Compile the JS regex body as a Python regex (same syntax for this pattern).
        body, flags = pattern[1:pattern.rfind("/")], pattern[pattern.rfind("/") + 1:]
        py_flags = re.IGNORECASE if "i" in flags else 0
        compiled = re.compile(body, py_flags)
        assert compiled.search("Failed to send prompt"), \
            "must match OpenCode's real 'Failed to send prompt' TUI text"
        assert compiled.search("Unable to connect. Is the computer able to access the url?"), \
            "must match OpenCode's real 'Unable to connect...' TUI text"
        assert not compiled.search("BadRequest: reasoning_effort"), \
            "must not fire on unrelated errors (e.g. the reasoning_effort bug, fixed separately)"

    def test_scan_uses_a_rolling_buffer(self):
        assert "_ocScanForConnFailure" in JS, "a scan function must exist"
        idx = JS.find("function _ocScanForConnFailure")
        assert idx != -1
        body = JS[idx:idx + 400]
        assert "_recentOutput" in body, \
            "must accumulate a rolling buffer, not just test the latest chunk " \
            "(a matched phrase can straddle two PTY output writes)"
        assert ".slice(-" in body, "the rolling buffer must be capped, not grow unbounded"

    def test_scan_is_wired_into_output_handler(self):
        idx = JS.find("msg.type === 'output'")
        assert idx != -1
        region = JS[idx:idx + 300]
        assert "_ocScanForConnFailure(sess, msg.data)" in region, \
            "every output chunk must be scanned for the connection-failure signature"


class TestConnFailureBanner:
    def _banner_region(self) -> str:
        idx = JS.find("function _ocShowConnBanner")
        assert idx != -1, "_ocShowConnBanner must exist"
        end = JS.find("\nfunction ", idx + 1)
        return JS[idx:end if end != -1 else idx + 3000]

    def test_banner_is_dismissible_not_auto_restart(self):
        region = self._banner_region()
        assert "oc-mcp-banner-dismiss" in region, \
            "must be dismissible — this is manual recovery, not an auto-restart"
        assert "banner.remove()" in region

    def test_banner_has_manual_restart_action(self):
        region = self._banner_region()
        assert "oc-mcp-banner-restart" in region
        assert "/api/opencode/restart" in region, \
            "restart action must hit the real force-restart endpoint"
        assert "_ocRestartSession" in region, \
            "restart action must also redo the client-side attach, not just the server"

    def test_banner_guards_against_duplicates(self):
        region = self._banner_region()
        assert "querySelector('.oc-conn-banner')" in region, \
            "must not stack multiple banners for the same repeated failure text"

    def test_banner_css_exists_and_is_distinct_from_mcp_banner(self):
        assert ".oc-conn-banner" in CSS, "connection-failure banner must have its own CSS"
        # Distinct (redder) palette from the amber MCP banner so severity reads differently.
        # The shared structural rule is ".oc-mcp-banner, .oc-conn-banner {" — anchor past it
        # to the standalone ".oc-conn-banner {" override block that carries the red palette.
        shared_selector = ".oc-mcp-banner, .oc-conn-banner {"
        shared_end = CSS.find(shared_selector)
        assert shared_end != -1, "must extend the shared banner structure, not duplicate it"
        idx = CSS.find(".oc-conn-banner {", shared_end + len(shared_selector))
        assert idx != -1, "a standalone .oc-conn-banner override block must exist"
        block = CSS[idx:idx + 200]
        assert "127, 29, 29" in block or "#7f1d1d" in block.lower(), \
            "connection-failure banner should use a distinct (red) palette from the MCP banner"
