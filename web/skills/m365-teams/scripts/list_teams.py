#!/usr/bin/env python3
"""List Teams the current user belongs to.

Usage:
    python3 list_teams.py
    python3 list_teams.py --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List your Teams")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get("/me/joinedTeams")
    teams = [{"id": t["id"], "name": t.get("displayName", ""),
              "description": t.get("description", "")}
             for t in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(teams), "teams": teams}, indent=2))
    else:
        if not teams:
            print("No teams found.")
            return
        print(f"Teams ({len(teams)}):\n")
        for t in teams:
            desc = f" - {t['description']}" if t["description"] else ""
            print(f"  {t['name']}{desc}")
            print(f"    ID: {t['id']}")


if __name__ == "__main__":
    main()
