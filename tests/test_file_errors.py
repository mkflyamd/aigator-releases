import pytest

from skills._files.errors import classify_graph_error, classify_status


@pytest.mark.parametrize(
    "status,code",
    [(423, "locked"), (401, "forbidden"), (403, "forbidden"), (404, "not_found"),
     (429, "throttled"), (500, "unknown"), (0, "unknown")],
)
def test_classify_status(status, code):
    assert classify_status(status) == code


def test_classify_graph_error_reads_status_code_attribute():
    class GraphLike(Exception):
        status_code = 423

    assert classify_graph_error(GraphLike("Graph API 423: locked")) == "locked"


def test_classify_graph_error_reads_httpx_response():
    class Resp:
        status_code = 404

    class HttpxLike(Exception):
        response = Resp()

    assert classify_graph_error(HttpxLike("x")) == "not_found"


def test_classify_graph_error_plain_exception_is_unknown():
    assert classify_graph_error(RuntimeError("boom")) == "unknown"
