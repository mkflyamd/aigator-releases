"""Map Graph/HTTP failures to the short codes the file tools report."""


def classify_status(status: int) -> str:
    if status == 423:
        return "locked"
    if status in (401, 403):
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 429:
        return "throttled"
    return "unknown"


def classify_graph_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if not status:
        status = getattr(getattr(exc, "response", None), "status_code", 0)
    return classify_status(int(status or 0))
