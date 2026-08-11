"""Minimal plugin commands runtime (decision #11, 2026-08-07 milestone,
Increment 2): frontmatter+body parsing, $ARGUMENTS/positional substitution,
discovery during install, and the bare `/command args` detection seam used
by routes/chat.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from marketplace import commands as m


def test_parse_command_md_extracts_frontmatter_description_and_body():
    text = "---\ndescription: Say hello\n---\nHello, $ARGUMENTS!"
    fm, body = m._parse_command_md(text)
    assert fm == {"description": "Say hello"}
    assert body == "Hello, $ARGUMENTS!"


def test_parse_command_md_no_frontmatter_treats_whole_text_as_body():
    text = "Just do the thing with $1."
    fm, body = m._parse_command_md(text)
    assert fm == {}
    assert body == text


def test_expand_command_substitutes_arguments():
    body = "Summarize this: $ARGUMENTS"
    assert m.expand_command(body, "the quarterly report") == "Summarize this: the quarterly report"


def test_expand_command_substitutes_positional_args():
    body = "Rename $1 to $2"
    assert m.expand_command(body, "old.txt new.txt") == "Rename old.txt to new.txt"


def test_expand_command_missing_positional_becomes_empty_string():
    body = "From $1 to $2 via $3"
    assert m.expand_command(body, "a b") == "From a to b via "


def test_expand_command_both_arguments_and_positional_in_same_body():
    body = "Full: [$ARGUMENTS] first=[$1]"
    assert m.expand_command(body, "x y") == "Full: [x y] first=[x]"


def test_discover_command_files_finds_commands_dir(tmp_path):
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "commands").mkdir(parents=True)
    (plugin_dir / "commands" / "a.md").write_text("A", encoding="utf-8")
    (plugin_dir / "commands" / "b.md").write_text("B", encoding="utf-8")
    (plugin_dir / "skills" / "x").mkdir(parents=True)
    (plugin_dir / "skills" / "x" / "SKILL.md").write_text("not a command", encoding="utf-8")

    found = m.discover_command_files(plugin_dir)
    assert [p.name for p in found] == ["a.md", "b.md"]


def test_discover_command_files_no_commands_dir_returns_empty(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    assert m.discover_command_files(plugin_dir) == []


def test_register_plugin_commands_populates_registry(tmp_path):
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "commands").mkdir(parents=True)
    (plugin_dir / "commands" / "greet.md").write_text(
        "---\ndescription: Greets\n---\nHi $1!", encoding="utf-8"
    )
    try:
        command_ids = m.register_plugin_commands("my-plugin", plugin_dir)
        assert command_ids == ["greet"]
        assert m.COMMAND_REGISTRY["greet"]["plugin_id"] == "my-plugin"
        assert m.COMMAND_REGISTRY["greet"]["body"] == "Hi $1!"
        assert m.COMMAND_REGISTRY["greet"]["description"] == "Greets"
    finally:
        m.COMMAND_REGISTRY.pop("greet", None)


def test_deregister_plugin_commands_removes_from_registry():
    m.COMMAND_REGISTRY["temp-cmd"] = {"body": "x", "description": "", "plugin_id": "p"}
    m.deregister_plugin_commands(["temp-cmd"])
    assert "temp-cmd" not in m.COMMAND_REGISTRY


def test_deregister_plugin_commands_handles_empty_list_and_none():
    m.deregister_plugin_commands([])
    m.deregister_plugin_commands(None)  # must not raise


def test_try_expand_command_expands_registered_command():
    m.COMMAND_REGISTRY["ship-it"] = {"body": "Ship $1 now.", "description": "", "plugin_id": "p"}
    try:
        result = m.try_expand_command("/ship-it release-42")
        assert result == "Ship release-42 now."
    finally:
        m.COMMAND_REGISTRY.pop("ship-it", None)


def test_try_expand_command_returns_none_for_unregistered_command():
    assert m.try_expand_command("/not-a-registered-command hello") is None


def test_try_expand_command_returns_none_for_plugin_capability_syntax():
    """The /plugin:capability syntax (routes.chat.parse_slash_command) must
    never be touched by try_expand_command — even if a command happens to be
    registered under the same leading name."""
    m.COMMAND_REGISTRY["rocm-toolkit"] = {"body": "should not fire", "description": "", "plugin_id": "p"}
    try:
        result = m.try_expand_command("/rocm-toolkit:gpu-doctor diagnose device 0")
        assert result is None
    finally:
        m.COMMAND_REGISTRY.pop("rocm-toolkit", None)


def test_try_expand_command_returns_none_for_plain_text():
    assert m.try_expand_command("why is my GPU slow?") is None


def test_expand_command_argument_text_with_literal_dollar_digits_untouched():
    """Finding #2 (2026-08-07 milestone adversarial review): the previous
    implementation substituted $ARGUMENTS first and then re-ran the
    positional regex over the RESULT, so a literal $150 typed by the user
    as part of their own argument text got misinterpreted as a positional
    placeholder and corrupted. A single-pass substitution over the original
    template must leave the user's typed text completely unchanged."""
    body = "Process refund: $ARGUMENTS"
    result = m.expand_command(body, "$150 for order 42")
    assert result == "Process refund: $150 for order 42"


def test_expand_command_positional_arg_value_containing_dollar_sign_untouched():
    """Same finding, positional case: the substituted argument value itself
    (not just $ARGUMENTS) must never be re-scanned for further $N matches."""
    body = "Value: $1"
    result = m.expand_command(body, "$1")
    assert result == "Value: $1"


def test_expand_command_literal_dollar_amount_in_template_with_no_args_becomes_empty():
    """Documented known limitation (fix #2, see expand_command's docstring):
    a literal $<digits> written directly in the command TEMPLATE (not in
    the user's typed argument text) with no corresponding positional
    argument typed is treated as an unmatched positional placeholder and
    removed, mirroring the existing 'missing positional -> empty string'
    rule. This is a deliberate choice, not an oversight — Claude Code's own
    command templates have no escape syntax for a literal $digits, and this
    minimal runtime doesn't invent one (decision #11a)."""
    body = "Refund amount is $100 exactly."
    result = m.expand_command(body, "")
    assert result == "Refund amount is  exactly."


def test_register_plugin_commands_skips_name_colliding_with_existing_skill_id(tmp_path, monkeypatch):
    """Finding #4 (2026-08-07 milestone adversarial review): a plugin command
    whose name collides with an existing shared.SKILL_PROMPTS skill id must
    NOT be registered — otherwise try_expand_command() would intercept ANY
    message matching that name (including the model's own bare-/skillname
    auto-activation, routes.chat._SKILL_REQUEST_RE) and silently rewrite it
    into an unrelated command template, hijacking skill activation."""
    import shared
    monkeypatch.setitem(shared.SKILL_PROMPTS, "rocm-basics", "existing skill prompt text")

    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "commands").mkdir(parents=True)
    (plugin_dir / "commands" / "rocm-basics.md").write_text(
        "---\ndescription: Should not register\n---\nShould not fire.", encoding="utf-8"
    )

    command_ids = m.register_plugin_commands("some-plugin", plugin_dir)
    assert command_ids == []
    assert "rocm-basics" not in m.COMMAND_REGISTRY
    assert m.try_expand_command("/rocm-basics") is None


def test_load_installed_plugin_commands_rebuilds_registry_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import importlib
    import marketplace.installer as installer_mod
    importlib.reload(installer_mod)

    plugin_dir = tmp_path / "cache" / "claude-plugins-official" / "amd-skills" / "1.0"
    (plugin_dir / "commands").mkdir(parents=True)
    (plugin_dir / "commands" / "greet.md").write_text("Hi $1!", encoding="utf-8")
    installer_mod.save_installed([{
        "id": "amd-skills",
        "version": "1.0",
        "source": "claude-plugins-official",
        "command_ids": ["greet"],
    }])

    try:
        m.load_installed_plugin_commands()
        assert "greet" in m.COMMAND_REGISTRY
        assert m.COMMAND_REGISTRY["greet"]["plugin_id"] == "amd-skills"
    finally:
        m.COMMAND_REGISTRY.pop("greet", None)
