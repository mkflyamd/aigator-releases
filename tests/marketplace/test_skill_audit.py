import logging

from marketplace import skill_audit as A


def test_extract_outbound_pulls_marker_lines_and_cleans_stderr():
    stderr = "warn\n" + A.MARKER + "api.example.com:443\nmore\n" + A.MARKER + "api.example.com:443\n"
    dests, cleaned = A.extract_outbound(stderr)
    assert dests == ["api.example.com:443"]
    assert cleaned == "warn\nmore\n"


def test_extract_outbound_caps_destinations():
    stderr = "".join(f"{A.MARKER}h{i}.example.com:443\n" for i in range(200))
    dests, _ = A.extract_outbound(stderr)
    assert len(dests) == A.MAX_DEST


def test_log_launch_and_outbound_lines(caplog):
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        A.log_launch("demo", "hook", True, ("a.example.com", "b.example.com"))
        A.log_outbound("demo", ["a.example.com:443"])
    text = caplog.text
    assert "skill-launch skill=demo kind=hook network=true declared_hosts=a.example.com,b.example.com" in text
    assert "skill-outbound skill=demo dest=a.example.com:443" in text


def test_log_values_cannot_inject_new_lines(caplog):
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        A.log_outbound("demo\nskill-launch skill=fake", ["x\ny:1"])
    assert "\nskill-launch skill=fake" not in caplog.text
