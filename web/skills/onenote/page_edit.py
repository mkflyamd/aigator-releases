"""Pure helpers for reading and editing OneNote page content (no network)."""

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
