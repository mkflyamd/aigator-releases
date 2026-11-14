"""Core pure helpers for agent handoff."""

import logging

import agent_handoff as ah

FAKE = "aigator-fake-api-key"


def test_redact_removes_active_key_exactly():
    out, n = ah.redact(f"export KEY={FAKE} then run", api_key=FAKE)
    assert FAKE not in out
    assert n == 1


def test_redact_token_shapes_derived_from_fake_key():
    shapes = [
        "Bearer " + FAKE,
        "sk-" + FAKE,
        "AKIA" + "AIGATORFAKEAPIKEY"[:16],
        "ghp_" + "aigatorfakeapikey" * 2,
        "xoxb-" + FAKE,
        "-----BEGIN RSA PRIVATE KEY-----\n" + FAKE + "\n-----END RSA PRIVATE KEY-----",
    ]
    for s in shapes:
        out, n = ah.redact(f"before {s} after")
        assert "[REDACTED]" in out, s
        assert n >= 1, s
        assert FAKE not in out and "AIGATORFAKEAPI" not in out, s


def test_redact_leaves_ordinary_code_alone():
    text = "def skip_this(task_runner): return 'sk-learn' + 'a' * 3  # task-runner-with-sk-learn"
    out, n = ah.redact(text)
    assert out == text and n == 0


def test_redact_short_active_key_is_ignored():
    out, n = ah.redact("password=abc", api_key="abc")
    assert out == "password=abc" and n == 0


def test_strip_ansi_removes_csi_osc_and_cr():
    raw = "\x1b[31mred\x1b[0m\r\n\x1b]0;title\x07ok\x1b[2K\rdone"
    assert ah.strip_ansi(raw) == "red\nok\ndone"


def test_fence_grows_past_backtick_runs():
    out = ah.fence("a ```` b")
    assert out.startswith("`````\n") and out.endswith("\n`````")
    assert ah.fence("plain").startswith("```\n")


def test_build_prompt_contains_rules_and_never_a_trailing_newline():
    p = ah.build_prompt("claude", "C:\\repo", "C:\\h\\x.txt", "fix the bug", "I changed foo")
    assert "Claude Code" in p and "C:\\h\\x.txt" in p
    assert "fix the bug" in p and "I changed foo" in p
    assert "untrusted historical data" in p
    assert "wait for my instruction" in p
    assert not p.endswith("\n")


def test_build_prompt_omits_empty_last_messages():
    p = ah.build_prompt("opencode-bare", "/r", "/h/x.txt")
    assert "last message" not in p


def test_is_gateway_routed():
    assert ah.is_gateway_routed("opencode-bare") and ah.is_gateway_routed("crush")
    assert not ah.is_gateway_routed("claude") and not ah.is_gateway_routed("codex")
    assert not ah.is_gateway_routed("terminal")


def test_log_event_has_fields_and_no_secrets(caplog):
    with caplog.at_level(logging.INFO, logger="agent_handoff"):
        ah.log_event(
            "launched", project_id="demo", source="claude", target="crush",
            source_kind="transcript", snapshot_bytes=120, redactions=2, gateway_routed=True,
        )
    line = caplog.records[-1].getMessage()
    assert line == (
        "agent_handoff stage=launched project=demo source=claude target=crush "
        "source_kind=transcript snapshot_bytes=120 redactions=2 gateway_routed=true"
    )
    assert FAKE not in line
