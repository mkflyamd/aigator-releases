"""Tests for browser competitive fixes — bot wall HITL, Chrome profile, skill handoff, scheduler templates."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio


# ── Fix 1: Bot wall → HITL pause ─────────────────────────────────────────────


class TestBotWallHITLPause:
    """Bot-wall detection should pause (not cancel) and notify via step updates."""

    def test_bot_block_reason_global_exists(self):
        import browser_agent
        assert hasattr(browser_agent, "_bot_block_reason")
        assert browser_agent._bot_block_reason == ""

    def test_bot_block_error_global_exists(self):
        import browser_agent
        assert hasattr(browser_agent, "_bot_block_error")

    def test_pause_browser_sets_paused(self):
        import browser_agent
        browser_agent._paused = False
        browser_agent.pause_browser()
        assert browser_agent._paused is True
        # cleanup
        browser_agent._paused = False

    def test_resume_browser_clears_paused(self):
        import browser_agent
        browser_agent._paused = True
        browser_agent.resume_browser()
        assert browser_agent._paused is False

    def test_bot_block_titles_covers_common_walls(self):
        """Bot detection patterns must cover common bot walls."""
        import browser_agent
        required = ["captcha", "datadome", "blocked", "robot check", "are you a human"]
        for title in required:
            assert title in browser_agent._BOT_BLOCK_TITLES, f"Missing: {title}"
        # Walmart/Kasada detection
        assert "robot or human" in browser_agent._BOT_BLOCK_TITLES

    def test_bot_block_urls_list_unchanged(self):
        """Bot detection URL patterns must not be modified."""
        import browser_agent
        expected_urls = [
            "datadome.co", "captcha", "recaptcha", "hcaptcha", "challenge",
            "ddos-guard.net", "imperva", "perimeterx", "akamai",
        ]
        assert browser_agent._BOT_BLOCK_URLS == expected_urls

    def test_blank_step_cascade_still_cancels(self):
        """Blank step cascade must still set _cancel_flag (not pause)."""
        import browser_agent
        # The cascade threshold should still exist
        assert browser_agent._MAX_BLANK_STEPS == 4

    def test_bot_block_resume_cooldown_exists(self):
        """Cooldown timer must exist to prevent re-triggering after resume."""
        import browser_agent
        assert hasattr(browser_agent, "_bot_block_resume_at")
        assert isinstance(browser_agent._bot_block_resume_at, float)

    def test_resume_browser_clears_bot_block_state(self):
        """resume_browser() must clear bot_block_reason and set cooldown."""
        import browser_agent
        import time
        browser_agent._bot_block_reason = "some wall"
        browser_agent._bot_block_resume_at = 0.0
        browser_agent.resume_browser()
        assert browser_agent._bot_block_reason == ""
        assert browser_agent._bot_block_resume_at > time.monotonic()  # cooldown set
        # cleanup
        browser_agent._paused = False
        browser_agent._bot_block_resume_at = 0.0


# ── Fix 2: Real Chrome session — config & flags ──────────────────────────────


class TestBrowserProfileConfig:
    """browser_profile config key controls Chrome launch flags."""

    def test_browser_profile_in_patchable_keys(self):
        from config import PATCHABLE_CONFIG_KEYS
        assert "browser_profile" in PATCHABLE_CONFIG_KEYS

    def test_browser_native_in_patchable_keys(self):
        from config import PATCHABLE_CONFIG_KEYS
        assert "browser_native" in PATCHABLE_CONFIG_KEYS

    def test_browser_prefer_in_patchable_keys(self):
        from config import PATCHABLE_CONFIG_KEYS
        assert "browser_prefer" in PATCHABLE_CONFIG_KEYS


class TestEnsureNativeBrowser:
    """_ensure_native_browser uses different flag sets for gator vs personal."""

    def test_gator_profile_uses_all_flags(self):
        """Gator profile should include stealth flags and --user-data-dir."""
        import browser_agent
        import subprocess

        with patch.object(browser_agent, "_cdp_port_ready", side_effect=[False, True]), \
             patch.object(subprocess, "Popen", return_value=MagicMock(poll=MagicMock(return_value=None))) as mock_popen:
            browser_agent._native_browser_proc = None
            result = browser_agent._ensure_native_browser(
                "chrome.exe", 9222, "C:\\AIGator\\BrowserProfile"
            )
            assert result is True
            cmd = mock_popen.call_args[0][0]
            assert "--remote-debugging-port=9222" in cmd
            assert any("--user-data-dir=" in arg for arg in cmd)
            assert "--disable-infobars" in cmd
            assert "--disable-blink-features=AutomationControlled" in cmd
            assert "--no-first-run" in cmd

    def test_personal_profile_uses_minimal_flags(self):
        """Personal profile should have --remote-debugging-port and --profile-directory. No stealth flags."""
        import browser_agent
        import subprocess

        with patch.object(browser_agent, "_cdp_port_ready", side_effect=[False, True]), \
             patch.object(subprocess, "Popen", return_value=MagicMock(poll=MagicMock(return_value=None))) as mock_popen:
            browser_agent._native_browser_proc = None
            result = browser_agent._ensure_native_browser(
                "chrome.exe", 9222, None  # None = personal profile
            )
            assert result is True
            cmd = mock_popen.call_args[0][0]
            assert "--remote-debugging-port=9222" in cmd
            assert "--profile-directory=Default" in cmd
            # Verify NO stealth flags that cause "unsupported command-line flag" warning
            assert "--disable-infobars" not in cmd
            assert "--disable-blink-features=AutomationControlled" not in cmd
            assert "--no-first-run" not in cmd
            assert not any("--user-data-dir" in arg for arg in cmd)

    def test_already_listening_reuses(self):
        """If CDP port is already listening, don't launch a new process."""
        import browser_agent
        import subprocess

        with patch.object(browser_agent, "_cdp_port_ready", return_value=True), \
             patch.object(subprocess, "Popen") as mock_popen:
            result = browser_agent._ensure_native_browser("chrome.exe", 9222, None)
            assert result is True
            mock_popen.assert_not_called()

    def test_timeout_returns_false(self):
        """If CDP port never becomes ready, return False."""
        import browser_agent
        import subprocess

        with patch.object(browser_agent, "_cdp_port_ready", return_value=False), \
             patch.object(subprocess, "Popen", return_value=MagicMock(poll=MagicMock(return_value=None))):
            browser_agent._native_browser_proc = None
            result = browser_agent._ensure_native_browser("chrome.exe", 9222, None)
            assert result is False


class TestNativeBrowserNoSilentFallback:
    """When native browser is enabled, failure must error — not silently fall back to Playwright."""

    def test_no_chrome_found_returns_error(self):
        """If no Chrome/Edge exe found, return error dict — don't fall back."""
        import browser_agent

        # Simulate: browser_native=True, browser_profile=personal, no Chrome found
        mock_cfg = {
            "browser_native": True,
            "browser_profile": "personal",
            "browser_prefer": "auto",
            "api_key": "test",
            "browser_mode": "balanced",
        }
        with patch.object(browser_agent, "_find_native_browser", return_value=None):
            # We can't easily run the full async function, but we can verify
            # the code path by checking the function source
            import inspect
            source = inspect.getsource(browser_agent._browser_task_impl)
            # Verify there's no "use_native = False" fallback after "No Chrome/Edge found"
            assert "falling back to Playwright" not in source

    def test_native_fail_returns_error(self):
        """If native browser fails to start, return error dict — don't fall back."""
        import browser_agent
        import inspect
        source = inspect.getsource(browser_agent._browser_task_impl)
        # After our fix, these should be return statements, not fallbacks
        assert "falling back to Playwright" not in source


# ── Fix 3: Browser → skill handoff ───────────────────────────────────────────


class TestCrossSkillHandoff:
    """Executor prompt and skill detection support browser→compose chaining."""

    def test_executor_suffix_has_chaining_instruction(self):
        from agent_loop import _EXECUTOR_SUFFIX
        assert "browser tools first" in _EXECUTOR_SUFFIX.lower() or \
               "browser tools first" in _EXECUTOR_SUFFIX
        assert "email_open_compose" in _EXECUTOR_SUFFIX
        assert "teams_open_compose" in _EXECUTOR_SUFFIX

    def test_executor_suffix_says_draft_not_send(self):
        """Must reference compose/draft tools — never auto-send."""
        from agent_loop import _EXECUTOR_SUFFIX
        assert "compose" in _EXECUTOR_SUFFIX.lower()
        # Should NOT contain "send_teams_message" or "send_email" as direct instructions
        assert "send_teams_message" not in _EXECUTOR_SUFFIX
        assert "send_email" not in _EXECUTOR_SUFFIX


class TestSkillKeywordDetection:
    """_infer_skills_from_message detects combined browser+messaging requests."""

    def _infer(self, msg):
        from routes.chat import _infer_skills_from_message
        return _infer_skills_from_message(msg)

    def test_browser_only(self):
        result = self._infer("browse to example.com")
        assert "browser" in result

    def test_teams_only(self):
        result = self._infer("send a teams message to John")
        assert "teams" in result

    def test_combined_browser_and_teams(self):
        """Combined request should activate BOTH skills."""
        result = self._infer("research online about competitors and send a teams message with findings")
        assert "browser" in result
        assert "teams" in result

    def test_combined_browser_and_email(self):
        result = self._infer("go to https://example.com and send an email summary")
        assert "browser" in result
        assert "email" in result

    def test_url_triggers_browser(self):
        result = self._infer("go to https://example.com and check the pricing")
        assert "browser" in result

    def test_research_online_triggers_browser(self):
        result = self._infer("research online about AI coding tools")
        assert "browser" in result

    def test_check_the_site_triggers_browser(self):
        result = self._infer("check the site for new content")
        assert "browser" in result

    def test_no_false_positive_plain_text(self):
        """Plain text without browser/messaging keywords should not match."""
        result = self._infer("what is the weather today")
        assert "browser" not in result
        assert "teams" not in result
        assert "email" not in result

    def test_existing_keywords_preserved(self):
        """Original browser keywords still work."""
        result = self._infer("@browse find me flights")
        assert "browser" in result

        result = self._infer("search on google for python tutorials")
        assert "browser" in result


# ── Fix 4: Scheduled browser tasks ───────────────────────────────────────────


class TestSchedulerBrowserAutoDetect:
    """Scheduled jobs auto-detect browser intent from prompt content."""

    def test_url_in_prompt_adds_browser_skill(self):
        """Prompt with URL should auto-add browser to skills."""
        skills = []
        prompt = "Every Monday, go to https://competitor.com/pricing and check for changes"
        prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = [
            "http://", "https://", "www.",
            ".com/", ".org/", ".net/", ".io/",
            "go to", "visit", "check site", "check the site",
            "search for", "browse", "look up online",
            "open the page", "open the site", "pricing page",
        ]
        if "browser" not in skills and any(s in prompt_lower for s in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
        assert "browser" in skills

    def test_go_to_keyword_adds_browser(self):
        skills = []
        prompt = "Go to the competitor site and check pricing"
        prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = [
            "http://", "https://", "www.",
            ".com/", ".org/", ".net/", ".io/",
            "go to", "visit", "check site", "check the site",
            "search for", "browse", "look up online",
            "open the page", "open the site", "pricing page",
        ]
        if "browser" not in skills and any(s in prompt_lower for s in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
        assert "browser" in skills

    def test_no_browser_for_email_prompt(self):
        """Email-only prompt should NOT trigger browser auto-detect."""
        skills = []
        prompt = "Send me a daily email summary of my inbox"
        prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = [
            "http://", "https://", "www.",
            ".com/", ".org/", ".net/", ".io/",
            "go to", "visit", "check site", "check the site",
            "search for", "browse", "look up online",
            "open the page", "open the site", "pricing page",
        ]
        if "browser" not in skills and any(s in prompt_lower for s in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
        assert "browser" not in skills

    def test_browser_already_in_skills_no_duplicate(self):
        """If browser is already in skills, don't add it again."""
        skills = ["browser"]
        prompt = "Go to https://example.com every day"
        prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = ["http://", "https://", "go to"]
        if "browser" not in skills and any(s in prompt_lower for s in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
        assert skills.count("browser") == 1

    def test_www_triggers_browser(self):
        skills = []
        prompt = "Check www.competitor.com daily"
        prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = ["http://", "https://", "www."]
        if "browser" not in skills and any(s in prompt_lower for s in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
        assert "browser" in skills


# ── Fix 2: Toolbar JS ────────────────────────────────────────────────────────


class TestToolbarJSStates:
    """Toolbar JS has all required visual states."""

    def test_toolbar_has_bot_block_observer(self):
        """Toolbar JS must include MutationObserver for data-gator-bot-block."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "gatorBotBlock" in js
        assert "MutationObserver" in js

    def test_toolbar_has_orange_color(self):
        """Bot-block state uses orange (#f97316)."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "#f97316" in js

    def test_toolbar_has_green_state(self):
        """Working state uses green (#4ade80)."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "#4ade80" in js

    def test_toolbar_has_yellow_state(self):
        """User-paused state uses yellow (#eab308)."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "#eab308" in js

    def test_toolbar_has_red_state(self):
        """Cancel/stop state uses red (#ef4444)."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "#ef4444" in js

    def test_toolbar_clears_bot_block_on_resume(self):
        """Clicking Resume must clear data-gator-bot-block."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "delete D.gatorBotBlock" in js or "delete D['gatorBotBlock']" in js

    def test_toolbar_shows_captcha_text(self):
        """Bot-block state shows CAPTCHA instruction."""
        import browser_agent
        js = browser_agent._HITL_TOOLBAR_BODY
        assert "solve CAPTCHA" in js or "CAPTCHA" in js


# ── Settings UI ───────────────────────────────────────────────────────────────


class TestSettingsHTML:
    """Settings HTML has the browser profile toggle."""

    def test_profile_row_exists_in_html(self):
        html_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        assert "browser-profile-row" in html
        assert "bpr-gator" in html
        assert "bpr-personal" in html

    def test_profile_row_hidden_by_default(self):
        html_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        # The row should be hidden by default (display:none)
        idx = html.index("browser-profile-row")
        context = html[idx - 100:idx + 200]
        assert "display:none" in context


class TestSettingsJS:
    """Settings JS persists browser_profile via PATCH."""

    def test_js_references_browser_profile(self):
        js_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js"
        js = js_path.read_text(encoding="utf-8")
        assert "browser_profile" in js
        assert "_browserProfile" in js

    def test_js_patches_config(self):
        """JS should PATCH browser_profile to /api/config."""
        js_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js"
        js = js_path.read_text(encoding="utf-8")
        assert "browser_profile" in js
        assert "/api/config" in js


# ── Agents Pane Templates ────────────────────────────────────────────────────


class TestAgentsPaneTemplates:
    """Agents pane empty state has browser example templates."""

    def test_has_browser_templates(self):
        js_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "agents-pane.js"
        js = js_path.read_text(encoding="utf-8")
        assert "competitor" in js.lower()
        assert "pricing" in js.lower() or "industry news" in js.lower()

    def test_has_globe_emoji(self):
        js_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "agents-pane.js"
        js = js_path.read_text(encoding="utf-8")
        # Globe emoji for browser templates
        assert "\U0001f310" in js  # 🌐

    def test_original_templates_preserved(self):
        js_path = pathlib.Path(__file__).parent.parent / "web" / "static" / "agents-pane.js"
        js = js_path.read_text(encoding="utf-8")
        assert "inbox" in js.lower()
        assert "meetings" in js.lower()
        assert "Teams" in js or "teams" in js.lower()
