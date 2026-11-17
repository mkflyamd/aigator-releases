#!/usr/bin/env python3
"""Copy the Gator Usage SharePoint list into the aigator_usage MySQL table.

Run by an admin on a machine where AI Gator is signed in and the MySQL host is reachable.
Needs: pip install pymysql cryptography

    python tools/sync_usage_to_mysql.py --dry-run
    python tools/sync_usage_to_mysql.py --create-table
    python tools/sync_usage_to_mysql.py

Environment:
    AIGATOR_USAGE_SITE_ID, AIGATOR_USAGE_LIST_ID   SharePoint site and list (or --site / --list)
    AIGATOR_USAGE_DB_PASSWORD                      password of the MySQL user (never a flag)
    AIGATOR_USAGE_DB_HOST / _PORT / _USER / _NAME  default atldbmyd-028-005 / 3306 / aigator_usage_user_rw / aigator_usage

Safe to re-run: a row already in MySQL for the same (email, report_date) is left untouched.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

TABLE = "usage_daily"
PAGE_SIZE = 200
INSERT_CHUNK = 500
_TEXT = (("OS", "os", 32), ("AppVersion", "app_version", 32), ("InstallId", "install_id", 64))
_NUMBERS = (
    ("Messages", "messages"), ("ToolRuns", "tool_runs"), ("InputTokens", "input_tokens"),
    ("OutputTokens", "output_tokens"), ("Conversations", "conversations"),
    ("BackgroundTasks", "background_tasks"), ("ToolErrors", "tool_errors"),
    ("McpToolRuns", "mcp_tool_runs"), ("LlmErrors", "llm_errors"), ("Failovers", "failovers"),
    ("Drafts", "drafts"), ("AvgTurnMs", "avg_turn_ms"),
)
COLUMNS = (
    "email", "report_date",
    *(column for _, column, _ in _TEXT),
    *(column for _, column in _NUMBERS),
    "details",
)

SCHEMA = (
    f"CREATE TABLE IF NOT EXISTS {TABLE} (\n"
    "  email VARCHAR(255) NOT NULL,\n"
    "  report_date DATE NOT NULL,\n"
    + "".join(f"  {column} VARCHAR({size}) NOT NULL DEFAULT '',\n" for _, column, size in _TEXT)
    + "".join(f"  {column} BIGINT NOT NULL DEFAULT 0,\n" for _, column in _NUMBERS)
    + "  details JSON NOT NULL,\n"
    "  PRIMARY KEY (email, report_date)\n"
    ") DEFAULT CHARSET=utf8mb4"
)
INSERT = (
    f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))}) "
    "ON DUPLICATE KEY UPDATE email = email"
)


def _number(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _details(value) -> str:
    try:
        return json.dumps(json.loads(value or "{}"), separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return "{}"


def _creator(item: dict) -> dict:
    return (item.get("createdBy") or {}).get("user") or {}


def creator_addresses(gc, user: dict, cache: dict) -> set[str]:
    """Every address the item's creator signs in or receives mail with, as SharePoint stamped it."""
    key = user.get("id") or user.get("email") or ""
    if key not in cache:
        found = {str(user.get("email") or "").lower()} - {""}
        if user.get("id"):
            try:
                profile = gc.get(f"/users/{user['id']}", {"$select": "userPrincipalName,mail,proxyAddresses"})
            except Exception:
                profile = {}
            found |= {str(profile.get(name) or "").lower() for name in ("userPrincipalName", "mail")} - {""}
            found |= {
                address[5:].lower() for address in profile.get("proxyAddresses") or [] if address.lower().startswith("smtp:")
            }
        cache[key] = found
    return cache[key]


def row_from_item(item: dict, creator_emails: set[str]) -> tuple | None:
    """Map one SharePoint list item to a table row.

    None if the Title is not 'email|YYYY-MM-DD' or its email is not one of the creator's own
    addresses (a writer must not be able to report as someone else).
    """
    fields = item.get("fields") or {}
    email, _, day = str(fields.get("Title") or "").rpartition("|")
    if "@" not in email or email.strip().lower() not in creator_emails:
        return None
    try:
        report_date = date.fromisoformat(day)
    except ValueError:
        return None
    return (
        email.lower(),
        report_date,
        *(str(fields.get(name) or "")[:size] for name, _, size in _TEXT),
        *(_number(fields.get(name)) for name, _ in _NUMBERS),
        _details(fields.get("Details")),
    )


def fetch_rows(gc, site: str, list_id: str) -> tuple[list[tuple], int]:
    """Return (rows, skipped) for every list item, following Graph paging."""
    rows, skipped, creators = [], 0, {}
    page = gc.get(f"/sites/{site}/lists/{list_id}/items", {"$expand": "fields", "$top": str(PAGE_SIZE)})
    while True:
        for item in page.get("value", []):
            row = row_from_item(item, creator_addresses(gc, _creator(item), creators))
            if row is None:
                skipped += 1
            else:
                rows.append(row)
        next_link = page.get("@odata.nextLink")
        if not next_link:
            return rows, skipped
        page = gc.get_absolute(next_link)


def _graph_client():
    from skills._m365.helpers import GraphClient

    return GraphClient()


def _connect(args):
    import pymysql

    return pymysql.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=os.environ["AIGATOR_USAGE_DB_PASSWORD"],
        database=args.db_name,
        charset="utf8mb4",
        connect_timeout=15,
    )


def _count(cursor) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE}")
    return cursor.fetchone()[0]


def load(connection, rows: list[tuple], create_table: bool) -> tuple[int, int]:
    """Insert rows not already present. Returns (rows before, rows after)."""
    cursor = connection.cursor()
    if create_table:
        cursor.execute(SCHEMA)
    before = _count(cursor)
    for start in range(0, len(rows), INSERT_CHUNK):
        cursor.executemany(INSERT, rows[start : start + INSERT_CHUNK])
    connection.commit()
    return before, _count(cursor)


def _parse(argv) -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--site", default=env("AIGATOR_USAGE_SITE_ID", ""))
    parser.add_argument("--list", dest="list_id", default=env("AIGATOR_USAGE_LIST_ID", ""))
    parser.add_argument("--db-host", default=env("AIGATOR_USAGE_DB_HOST", "atldbmyd-028-005"))
    parser.add_argument("--db-port", type=int, default=int(env("AIGATOR_USAGE_DB_PORT", "3306")))
    parser.add_argument("--db-user", default=env("AIGATOR_USAGE_DB_USER", "aigator_usage_user_rw"))
    parser.add_argument("--db-name", default=env("AIGATOR_USAGE_DB_NAME", "aigator_usage"))
    parser.add_argument("--dry-run", action="store_true", help="read the list and report; do not touch MySQL")
    parser.add_argument("--create-table", action="store_true", help="run CREATE TABLE IF NOT EXISTS first (needs CREATE rights)")
    parser.add_argument("--print-schema", action="store_true", help="print the CREATE TABLE statement and exit")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)
    if args.print_schema:
        print(SCHEMA + ";")
        return 0
    if not (args.site and args.list_id):
        print("Set --site and --list (or AIGATOR_USAGE_SITE_ID and AIGATOR_USAGE_LIST_ID).", file=sys.stderr)
        return 2
    if not args.dry_run and not os.environ.get("AIGATOR_USAGE_DB_PASSWORD"):
        print("Set AIGATOR_USAGE_DB_PASSWORD in your environment.", file=sys.stderr)
        return 2

    rows, skipped = fetch_rows(_graph_client(), args.site, args.list_id)
    users = {row[0] for row in rows}
    days = sorted({row[1] for row in rows})
    span = f"{days[0]} to {days[-1]}" if days else "no days"
    print(f"Read {len(rows)} rows ({len(users)} users, {span}); skipped {skipped} without an email|date Title matching the creator.")
    if args.dry_run:
        return 0

    connection = _connect(args)
    try:
        before, after = load(connection, rows, args.create_table)
    finally:
        connection.close()
    print(f"MySQL {args.db_name}.{TABLE}: {before} -> {after} rows ({after - before} new).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
