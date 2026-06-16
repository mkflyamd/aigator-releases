import pytest
from mcp.normalizer import normalize, _find_placeholders

POSTGRES_JSON = """{
  "mcpServers": {
    "postgres": {
      "type": "http",
      "url": "https://mcp-platform.example.com/mcp/postgres/",
      "headers": {
        "X-Postgres-Host": "{pg_host}",
        "X-Postgres-Password": "{pg_password}",
        "X-Postgres-User": "readonly"
      }
    }
  }
}"""


def test_headers_extracted_from_json():
    result = normalize(POSTGRES_JSON)
    assert result.ok
    assert result.headers == {
        "X-Postgres-Host": "{pg_host}",
        "X-Postgres-Password": "{pg_password}",
        "X-Postgres-User": "readonly",
    }


def test_headers_absent_gives_empty_dict():
    result = normalize('{"mcpServers": {"x": {"url": "https://example.com/mcp"}}}')
    assert result.ok
    assert result.headers == {}


def test_find_placeholders_extracts_variable_names():
    d = {"X-Host": "{pg_host}", "X-Pass": "{pg_password}", "X-User": "readonly"}
    assert set(_find_placeholders(d)) == {"pg_host", "pg_password"}


def test_find_placeholders_empty_when_no_placeholders():
    assert _find_placeholders({"X-User": "alice"}) == []


def test_find_placeholders_works_on_env_values():
    d = {"MYSQL_HOST": "{db_host}", "MYSQL_PORT": "3306"}
    assert _find_placeholders(d) == ["db_host"]


def test_find_placeholders_no_duplicates():
    d = {"A": "{token}", "B": "prefix-{token}-suffix"}
    assert _find_placeholders(d) == ["token"]
