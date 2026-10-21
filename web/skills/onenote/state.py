"""Session-scoped OneNote pinned pages."""

pinned_onenote_pages: dict[str, dict] = {}


def pin_site_text(site_id: str | None) -> str:
    return f", site_id: {site_id}" if site_id else ""
