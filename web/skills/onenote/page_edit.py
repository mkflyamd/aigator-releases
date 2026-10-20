"""Pure helpers for reading and editing OneNote page content (no network)."""

import html as _html

from bs4 import BeautifulSoup

MAX_ELEMENT_HTML = 100_000
MAX_PREVIOUS_HTML = 20_000
DEFAULT_LIMIT = 100
MAX_LIMIT = 200
_TEXT_LEN = 80
_LISTED_TAGS = {
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "ol", "ul", "table", "img", "object", "div",
}


def _soup(page_html: str) -> BeautifulSoup:
    return BeautifulSoup(page_html, "lxml")


def _is_listed(el) -> bool:
    if el.name not in _LISTED_TAGS or not el.get("id"):
        return False
    if any(parent.name == "table" for parent in el.parents):
        return False
    if el.name == "div" and not any(parent.name == "div" for parent in el.parents):
        return False
    return True


def _table_shape(table) -> tuple[int, int]:
    rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
    cols = max(
        (len(r.find_all(["td", "th"], recursive=False)) for r in rows), default=0
    )
    return len(rows), cols


def outline(page_html: str, offset: int = 0, limit: int = DEFAULT_LIMIT) -> dict:
    offset = max(0, int(offset))
    limit = min(max(1, int(limit)), MAX_LIMIT)
    items = []
    for el in _soup(page_html).find_all(True):
        if not _is_listed(el):
            continue
        item = {
            "id": el["id"],
            "tag": el.name,
            "text": el.get_text(" ", strip=True)[:_TEXT_LEN],
        }
        if el.name == "table":
            item["rows"], item["cols"] = _table_shape(el)
        items.append(item)
    end = offset + limit
    return {
        "elements": items[offset:end],
        "total": len(items),
        "next_offset": end if end < len(items) else None,
    }


def element_html(page_html: str, element_id: str) -> str | None:
    el = _soup(page_html).find(attrs={"id": element_id})
    if el is None:
        return None
    for tag in [el, *el.find_all(True)]:
        tag.attrs.pop("id", None)
    return str(el)


_SIG_TEXT_LEN = 200
_DIFF_WINDOW = 8


def _signature_of(root, require_id: bool) -> list[tuple[str, str, str]]:
    """(id, tag, text) of each editable block, in page order. Text has all
    whitespace removed so Graph re-wrapping runs in spans does not matter."""
    sig = []
    for el in root.find_all(True):
        if el.name not in _LISTED_TAGS or el.name == "div":
            continue
        if require_id and not el.get("id"):
            continue
        if any(parent.name == "table" for parent in el.parents):
            continue
        text = "".join("".join(el.stripped_strings).split())[:_SIG_TEXT_LEN]
        if el.name == "p" and not text:
            continue
        sig.append((el.get("id", ""), el.name, text))
    return sig


def signature(page_html: str) -> list[tuple[str, str]]:
    return [(tag, text) for _, tag, text in _signature_of(_soup(page_html), True)]


def expected_signature(
    page_html: str, markup: str, action: str, target: str, position: str = ""
) -> list[tuple[str, str]] | None:
    """What signature(page) should be after the edit, or None when the result
    cannot be predicted (append/prepend onto an element)."""
    before = _signature_of(_soup(page_html), True)
    new = [(tag, text) for _, tag, text in _signature_of(_soup(markup), False)]
    plain = [(tag, text) for _, tag, text in before]
    if target == "body":
        return new + plain if action == "prepend" else None
    if action not in ("replace", "insert"):
        return None
    el = _soup(page_html).find(attrs={"id": target})
    if el is None:
        return None
    ids = {target} | {d["id"] for d in el.find_all(True) if d.get("id")}
    span = [i for i, (sid, _, _) in enumerate(before) if sid in ids]
    if not span:
        return None
    first, last = span[0], span[-1] + 1
    if action == "replace":
        return plain[:first] + new + plain[last:]
    cut = first if (position or "after") == "before" else last
    return plain[:cut] + new + plain[cut:]


def compare_signatures(expected: list, actual: list) -> dict | None:
    """None when they match; otherwise the differing stretch of each."""
    if expected == actual:
        return None
    head = 0
    while head < min(len(expected), len(actual)) and expected[head] == actual[head]:
        head += 1
    tail = 0
    while (
        tail < min(len(expected), len(actual)) - head
        and expected[-1 - tail] == actual[-1 - tail]
    ):
        tail += 1

    def window(sig):
        return [f"{t}: {x[:40]}" for t, x in sig[max(0, head - 1) : len(sig) - tail]][
            :_DIFF_WINDOW
        ]

    return {"expected": window(expected), "actual": window(actual)}


ACTIONS = ("append", "prepend", "insert", "replace")
_POSITIONS = ("before", "after")


class EditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _escape_text(text: str) -> str:
    return _html.escape(text, quote=False).replace("\n", "<br/>")


def build_patch_ops(
    content: str,
    html: bool = False,
    action: str = "append",
    target: str = "body",
    position: str = "",
) -> list[dict]:
    if action not in ACTIONS:
        raise EditError("invalid_action", f"action must be one of {', '.join(ACTIONS)}.")
    if position and position not in _POSITIONS:
        raise EditError("invalid_position", "position must be 'before' or 'after'.")

    if target == "title":
        if action != "replace":
            raise EditError("title_requires_replace", "The title can only be replaced.")
        if not content.strip():
            raise EditError("content_required", "The title cannot be empty.")
        title = _html.escape(" ".join(content.split()), quote=False)
        return [{"target": "title", "action": "replace", "content": title}]

    if target == "body":
        if action == "replace":
            raise EditError(
                "replace_body_not_allowed",
                "Replacing the body would erase the whole page. Replace a specific element, or append.",
            )
        if action == "insert":
            raise EditError("insert_needs_element", "insert needs an element id as the target.")
        if action == "append":
            if not content.strip():
                raise EditError("content_required", "append needs non-empty content.")
            body = content if html else _escape_text(content)
            return [{"target": "body", "action": "append", "content": f"<div>{body}</div>"}]

    if content == "":
        if action != "replace":
            raise EditError("content_required", f"{action} needs non-empty content.")
        markup = "<p></p>"
    else:
        markup = content if html else f"<p>{_escape_text(content)}</p>"
    op = {"target": target, "action": action, "content": markup}
    if action == "insert":
        op["position"] = position or "after"
    elif position:
        op["position"] = position
    return [op]
