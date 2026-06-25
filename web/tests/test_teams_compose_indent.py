"""#109 — Teams compose toolbar must include indent and outdent buttons.

Quill supports indent formatting natively via quill.format('indent', +1/-1).
"""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


def _toolbar_html() -> str:
    start = SRC.find("function _buildQuillEditor(")
    end = SRC.find("// Init Quill after DOM insertion", start)
    return SRC[start:end]


def _cmd_handler() -> str:
    start = SRC.find("// Toolbar button handlers")
    end = SRC.find("// Emoji picker", start)
    return SRC[start:end]


class TestComposeIndent:

    def test_toolbar_has_indent_button(self):
        """Toolbar HTML must include an indent button (data-cmd='indent')."""
        html = _toolbar_html()
        assert 'data-cmd="indent"' in html or "data-cmd='indent'" in html, (
            "Compose toolbar must have an indent button (#109)"
        )

    def test_toolbar_has_outdent_button(self):
        """Toolbar HTML must include an outdent button (data-cmd='outdent')."""
        html = _toolbar_html()
        assert 'data-cmd="outdent"' in html or "data-cmd='outdent'" in html, (
            "Compose toolbar must have an outdent button (#109)"
        )

    def test_handler_applies_indent(self):
        """Command handler must apply Quill indent (+1) for indent command."""
        handler = _cmd_handler()
        assert "indent" in handler and "+1" in handler or ("'indent', 1" in handler), (
            "Handler must call quill.format('indent', +1) for indent (#109)"
        )

    def test_handler_applies_outdent(self):
        """Command handler must apply Quill outdent (-1) for outdent command."""
        handler = _cmd_handler()
        assert "outdent" in handler and "-1" in handler or ("'indent', -1" in handler), (
            "Handler must call quill.format('indent', -1) for outdent (#109)"
        )
