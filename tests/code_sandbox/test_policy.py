import pytest

from sandbox import policy as pol


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    path = tmp_path / "sandbox-policy.json"
    monkeypatch.setattr(pol, "policy_path", lambda: path)
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    return path


def test_missing_file_gives_defaults(policy_file):
    assert pol.load_policy() == pol.Policy("enabled", "ask", "ask", False)


def test_valid_file_is_parsed(policy_file):
    policy_file.write_text('{"code_runner": "disabled", "network": "deny", "filesystem": "strict", "require_sandbox": true}')
    assert pol.load_policy() == pol.Policy("disabled", "deny", "strict", True)


def test_partial_file_keeps_defaults_for_missing_keys(policy_file):
    policy_file.write_text('{"network": "deny"}')
    assert pol.load_policy() == pol.Policy("enabled", "deny", "ask", False)


@pytest.mark.parametrize("text", [
    "not json", "[]", '{"network": "allow"}', '{"filesystem": 1}',
    '{"require_sandbox": "yes"}', '{"code_runner": "on"}',
])
def test_invalid_file_fails_closed(policy_file, text):
    policy_file.write_text(text)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY
    assert pol.FAIL_CLOSED_POLICY == pol.Policy("enabled", "deny", "strict", True)


@pytest.mark.parametrize("text", [
    '{"network": ["deny"]}', '{"filesystem": {}}', '{"code_runner": ["enabled"]}',
    '{"network": null}', '{"code_runner": 1}', '{"require_sandbox": 1}',
    '{"require_sandbox": null}', '{"require_sandbox": []}',
    "",
])
def test_malformed_values_fail_closed(policy_file, text):
    policy_file.write_text(text)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


@pytest.mark.parametrize("text", [
    pytest.param("[" * 100000, id="deep-list"),
    pytest.param('{"a":' * 100000, id="deep-object"),
])
def test_deeply_nested_json_fails_closed(policy_file, text):
    policy_file.write_text(text)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


@pytest.mark.parametrize("text", [
    '{"requires_sandbox": false}', '{"network": "ask", "extra": 1}', '{"Network": "deny"}',
])
def test_unknown_keys_fail_closed(policy_file, text):
    policy_file.write_text(text)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


def test_parse_policy_raises_value_error_for_hostile_input():
    for text in ('{"network": ["deny"]}', "[" * 100000, '{"typo": 1}'):
        with pytest.raises(ValueError):
            pol.parse_policy(text)


def test_unreadable_path_fails_closed(policy_file):
    policy_file.mkdir()  # a directory where the file should be: stat works, read fails
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


def test_posix_writable_or_non_root_file_fails_closed(policy_file, monkeypatch):
    policy_file.write_text('{"network": "ask"}')
    monkeypatch.setattr(pol, "_is_posix", lambda: True)
    # Non-root: the file is not root-owned. Root (CI containers): the explicit
    # chmod makes it group/world-writable. On Windows os.stat already reports
    # 0o666. Every case must fail closed.
    policy_file.chmod(0o666)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


def test_owner_check_accepts_root_owned_0644():
    from types import SimpleNamespace
    assert pol._posix_owner_ok(SimpleNamespace(st_uid=0, st_mode=0o100644))
    assert not pol._posix_owner_ok(SimpleNamespace(st_uid=0, st_mode=0o100664))
    assert not pol._posix_owner_ok(SimpleNamespace(st_uid=501, st_mode=0o100644))


def test_cache_follows_mtime(policy_file):
    import os
    policy_file.write_text('{"network": "deny"}')
    assert pol.load_policy().network == "deny"
    policy_file.write_text('{"network": "ask", "filesystem": "strict"}')
    st = policy_file.stat()
    os.utime(policy_file, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert pol.load_policy() == pol.Policy("enabled", "ask", "strict", False)


def test_policy_paths_per_platform(monkeypatch):
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    assert pol.platform_policy_path("win32").parts[-2:] == ("AIGator", "sandbox-policy.json")
    assert pol.platform_policy_path("darwin").as_posix() == "/Library/Application Support/AIGator/sandbox-policy.json"
    assert pol.platform_policy_path("linux").as_posix() == "/etc/aigator/sandbox-policy.json"


def test_as_dict():
    assert pol.Policy().as_dict() == {
        "code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": False,
    }
